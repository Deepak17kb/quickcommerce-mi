"""
store_coverage.py — deliverable 12c, store coverage gaps. REAL data only.

    python -m src.coverage.store_coverage

Two questions, two model outputs (docs/MODEL_OUTPUT_CONTRACT.md):

  outputs/models/store_category_coverage/   which categories each store covers vs is sparse in
  outputs/models/store_coverage_geography/  where in Bhubaneswar a platform is far from its own
                                            nearest store while a competitor is close

SCOPE LIMIT — READ BEFORE USING THE CATEGORY OUTPUT.
Only the 8 Blinkit stores have a REAL carry matrix (which products a store actually lists). The
other 22 stores exist in this dataset with REAL names, addresses and coordinates, but every row
of theirs is SYNTHETIC and their assortment was generated (docs/PROJECT_PLAN.md, deliverable 10).
Category coverage is therefore computed for 8 stores, not 30. Geography uses all 30 stores,
because the coordinates are real public-web observations (STORES*.csv, last_verified 2026-07-10).

The geography output measures distance to a LISTED store. It is not demand, population or
service-area coverage: the 30 stores are the stores in this dataset, not a verified census of
every dark store in Bhubaneswar, and no population data exists here to weight a gap by.
"""
import numpy as np
import pandas as pd

import src.load as L
from src.model_output import save_model_outputs

EARTH_KM = 6371.0088

# category coverage_index bands (observed / expected under the store's own breadth)
SPARSE_BELOW = 0.60
STRONG_ABOVE = 1.40
SMALL_CATEGORY_BELOW = 20        # chain-carried keys below this: too few to band confidently

# geography
GRID_STEP_DEG = 0.004            # ~440 m
GRID_PAD_DEG = 0.010
IN_CITY_KM = 5.0                 # a cell is analysed only if some store is within this
FAR_KM = 3.0                     # a platform is "far" from a cell beyond this
COMPETITOR_CLOSE_KM = 1.5        # ... and the gap is "relative" if a rival is within this
NEIGHBOUR_KM = 2.0               # radius for the per-store competitor count


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle km. Broadcasts, so (n,1) against (1,m) gives the full distance matrix."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lon2) - np.radians(lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_KM * np.arcsin(np.sqrt(a))


# --------------------------------------------------------------------------- category coverage
def category_coverage(real: pd.DataFrame, catalog: pd.DataFrame):
    """One row per REAL Blinkit store x catalog category."""
    known = real[real.canonical_product_key.isin(catalog.canonical_product_key)]
    dropped = real.canonical_product_key.nunique() - known.canonical_product_key.nunique()

    key_cat = catalog.set_index('canonical_product_key').category
    carried = (known[['store_id', 'canonical_product_key']].drop_duplicates()
               .assign(category=lambda d: d.canonical_product_key.map(key_cat)))

    catalog_universe = catalog.groupby('category').canonical_product_key.nunique()
    chain_universe = carried.groupby('category').canonical_product_key.nunique()
    store_total = carried.groupby('store_id').canonical_product_key.nunique()
    chain_total = carried.canonical_product_key.nunique()

    stores = sorted(carried.store_id.unique())
    cats = sorted(chain_universe.index)
    observed = (carried.groupby(['store_id', 'category']).canonical_product_key.nunique()
                .reindex(pd.MultiIndex.from_product([stores, cats],
                                                    names=['store_id', 'category']), fill_value=0))

    df = observed.rename('store_carried').reset_index()
    df['store_total_carried'] = df.store_id.map(store_total)
    df['chain_carried_in_category'] = df.category.map(chain_universe)
    df['catalog_products_in_category'] = df.category.map(catalog_universe)
    # what this store would carry in this category if its breadth were spread evenly
    df['expected_under_store_breadth'] = (df.chain_carried_in_category
                                          * df.store_total_carried / chain_total)
    df['coverage_vs_chain'] = df.store_carried / df.chain_carried_in_category
    df['coverage_index'] = df.store_carried / df.expected_under_store_breadth
    df['small_category'] = df.chain_carried_in_category < SMALL_CATEGORY_BELOW
    df['coverage_status'] = np.select(
        [df.store_carried.eq(0), df.coverage_index < SPARSE_BELOW, df.coverage_index > STRONG_ABOVE],
        ['missing', 'sparse', 'strong'], default='covered')
    df.loc[df.small_category & df.coverage_status.ne('missing'), 'coverage_status'] = 'small_category'
    return df.round(6), {'keys_dropped_not_in_catalog': int(dropped),
                         'chain_total_carried': int(chain_total)}


# --------------------------------------------------------------------------- geography
def store_geography(stores: pd.DataFrame) -> pd.DataFrame:
    """Per store: nearest own-platform store, nearest competitor store, competitors within 2 km."""
    lat, lon = stores.latitude.to_numpy(), stores.longitude.to_numpy()
    d = haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
    same = stores.platform.to_numpy()[:, None] == stores.platform.to_numpy()[None, :]
    self_ = np.eye(len(stores), dtype=bool)

    own = np.where(same & ~self_, d, np.inf)
    rival = np.where(~same, d, np.inf)
    out = stores[['store_id', 'platform', 'store_name', 'area', 'pin',
                  'latitude', 'longitude']].copy()
    out['km_to_nearest_own_platform_store'] = np.where(np.isinf(own.min(axis=1)), np.nan, own.min(axis=1))
    out['km_to_nearest_competitor_store'] = rival.min(axis=1)
    out['nearest_competitor_store_id'] = stores.store_id.to_numpy()[rival.argmin(axis=1)]
    out['competitor_stores_within_2km'] = (rival <= NEIGHBOUR_KM).sum(axis=1)
    return out.round(6)


def grid_gaps(stores: pd.DataFrame):
    """One row per analysed grid cell, with km to the nearest store of each platform."""
    lats = np.arange(stores.latitude.min() - GRID_PAD_DEG,
                     stores.latitude.max() + GRID_PAD_DEG + GRID_STEP_DEG, GRID_STEP_DEG)
    lons = np.arange(stores.longitude.min() - GRID_PAD_DEG,
                     stores.longitude.max() + GRID_PAD_DEG + GRID_STEP_DEG, GRID_STEP_DEG)
    glat, glon = (a.ravel() for a in np.meshgrid(lats, lons, indexing='ij'))

    d = haversine_km(glat[:, None], glon[:, None],
                     stores.latitude.to_numpy()[None, :], stores.longitude.to_numpy()[None, :])
    cell = pd.DataFrame({'grid_lat': glat.round(6), 'grid_lon': glon.round(6)})
    platforms = sorted(stores.platform.unique())
    cols = {}
    for p in platforms:
        m = (stores.platform == p).to_numpy()
        cols[p] = d[:, m].min(axis=1)
        cell[f'km_to_nearest_{_slug(p)}'] = cols[p].round(4)

    near = np.column_stack([cols[p] for p in platforms])
    cell['km_to_nearest_any_store'] = near.min(axis=1).round(4)
    cell['nearest_store_id'] = stores.store_id.to_numpy()[d.argmin(axis=1)]
    cell['nearest_store_area'] = stores.area.to_numpy()[d.argmin(axis=1)]

    cell = cell[cell.km_to_nearest_any_store <= IN_CITY_KM].reset_index(drop=True)
    near = near[(near.min(axis=1) <= IN_CITY_KM)]

    # a platform is in a relative gap here if it is far while some rival is close
    for i, p in enumerate(platforms):
        rival_min = np.delete(near, i, axis=1).min(axis=1)
        cell[f'gap_{_slug(p)}'] = (near[:, i] > FAR_KM) & (rival_min <= COMPETITOR_CLOSE_KM)
    cell['gap_all_platforms'] = cell.km_to_nearest_any_store > FAR_KM
    cell['platforms_in_relative_gap'] = cell[[f'gap_{_slug(p)}' for p in platforms]].sum(axis=1)
    return cell, platforms


def _slug(platform: str) -> str:
    return platform.lower().replace(' ', '_')


# --------------------------------------------------------------------------- save
def main():
    raw = L.load_raw()
    real = L.real_only(raw)
    catalog = L.load_catalog()
    stores = L.load_stores().sort_values('store_id').reset_index(drop=True)

    assert real.data_status.eq('REAL').all() and real.platform.nunique() == 1
    assert len(stores) == 30, f"expected the 30-store master, got {len(stores)}"

    # ---------------- category coverage (8 REAL-carry stores)
    cov, cov_notes = category_coverage(real, catalog)
    rep = (real.sort_values('observation_key').groupby('store_id').observation_key.first())
    cov_pred = cov.assign(
        observation_key=cov.store_id.map(rep),
        data_status='REAL',
        platform='Blinkit',
        snapshot_date='2026-07-10',
    )
    band = cov.coverage_status.value_counts().to_dict()
    worst = (cov[cov.coverage_status.isin(['missing', 'sparse'])]
             .sort_values(['coverage_index', 'chain_carried_in_category']))
    cov_metrics = {
        'scope': ('REAL carry matrix, 8 Blinkit stores, snapshot 2026-07-10. The other 22 stores '
                  'have no REAL assortment: every row of theirs is SYNTHETIC.'),
        'stores': int(cov.store_id.nunique()),
        'categories': int(cov.category.nunique()),
        'rows': len(cov),
        **cov_notes,
        'catalog_products': int(catalog.canonical_product_key.nunique()),
        'coverage_status_counts': band,
        'store_breadth': (cov.groupby('store_id').store_carried.sum()
                          .astype(int).to_dict()),
        'category_chain_universe': cov.drop_duplicates('category')
                                      .set_index('category').chain_carried_in_category
                                      .astype(int).sort_index().to_dict(),
        'largest_gaps': worst.head(25)[['store_id', 'category', 'store_carried',
                                        'expected_under_store_breadth', 'coverage_index',
                                        'coverage_status']].to_dict('records'),
        'categories_missing_in_every_store': sorted(
            cov.groupby('category').store_carried.max().pipe(lambda s: s[s.eq(0)]).index.tolist()),
    }
    save_model_outputs(
        'store_category_coverage', cov_pred,
        params={'sparse_below': SPARSE_BELOW, 'strong_above': STRONG_ABOVE,
                'small_category_below': SMALL_CATEGORY_BELOW,
                'coverage_index': 'store_carried / (chain_category_keys * store_breadth_share)',
                'carry_definition': 'distinct canonical_product_key observed in that store, REAL rows'},
        metrics=cov_metrics, training_data=real,
        split={'type': 'none — descriptive coverage measurement, no model fit',
               'measured_on': 'REAL Blinkit snapshot 2026-07-10'},
        target='category coverage per store (descriptive)',
        training_source='data/raw REAL Blinkit rows via src.load + data/reference/MASTER_CATALOG.parquet',
        notes=('Deliverable 12c, category half. REAL only. 8 Blinkit stores x 22 catalog categories; '
               'the other 22 stores of the 30-store master are excluded because their assortment is '
               'SYNTHETIC (docs/PROJECT_PLAN.md deliverable 10). coverage_index compares a store to '
               'its own breadth, so a small store is not called sparse merely for being small. '
               'observation_key is a REPRESENTATIVE REAL listing of that store (first by key), not a '
               'per-category observation: these rows are store x category aggregates. The 4 unnamed '
               'listings (CLAUDE.md 3.7) are not in MASTER_CATALOG and are excluded. Coverage is '
               'measured against what the 8 stores carry between them, not against any platform '
               'assortment claim.'))

    # ---------------- geography (all 30 REAL store locations)
    geo = store_geography(stores)
    cell, platforms = grid_gaps(stores)
    gap_cols = [f'gap_{_slug(p)}' for p in platforms]
    cell_pred = cell.assign(
        observation_key=('GEO_GRID | ' + cell.grid_lat.map('{:.6f}'.format)
                         + ' | ' + cell.grid_lon.map('{:.6f}'.format)),
        data_status='REAL',
    )
    cell_km = 111.32 * GRID_STEP_DEG * np.cos(np.radians(float(stores.latitude.mean())))
    by_area = (cell[cell[gap_cols].any(axis=1)].groupby('nearest_store_area')
               .size().sort_values(ascending=False))
    geo_metrics = {
        'scope': ('REAL store coordinates for all 30 stores (STORES*.csv, public_web_observation, '
                  'last_verified 2026-07-10). Distance to a LISTED store only — not demand, '
                  'population or a dark-store census.'),
        'stores': len(stores),
        'stores_by_platform': stores.platform.value_counts().sort_index().to_dict(),
        'grid': {'step_deg': GRID_STEP_DEG, 'approx_cell_km': round(cell_km, 3),
                 'cells_analysed': len(cell), 'in_city_km': IN_CITY_KM,
                 'far_km': FAR_KM, 'competitor_close_km': COMPETITOR_CLOSE_KM},
        'relative_gap_cells_by_platform': {p: int(cell[f'gap_{_slug(p)}'].sum()) for p in platforms},
        'relative_gap_share_by_platform': {p: round(float(cell[f'gap_{_slug(p)}'].mean()), 4)
                                           for p in platforms},
        'cells_no_platform_within_3km': int(cell.gap_all_platforms.sum()),
        'median_km_to_nearest_by_platform': {
            p: round(float(cell[f'km_to_nearest_{_slug(p)}'].median()), 3) for p in platforms},
        'gap_cells_by_nearest_store_area': by_area.head(20).astype(int).to_dict(),
        'most_isolated_stores': geo.sort_values('km_to_nearest_competitor_store', ascending=False)
                                   .head(5)[['store_id', 'platform', 'area',
                                             'km_to_nearest_competitor_store',
                                             'competitor_stores_within_2km']].to_dict('records'),
        'store_geography': geo.to_dict('records'),
    }
    save_model_outputs(
        'store_coverage_geography', cell_pred,
        params={'grid_step_deg': GRID_STEP_DEG, 'grid_pad_deg': GRID_PAD_DEG,
                'in_city_km': IN_CITY_KM, 'far_km': FAR_KM,
                'competitor_close_km': COMPETITOR_CLOSE_KM, 'neighbour_km': NEIGHBOUR_KM,
                'distance': 'haversine, earth radius 6371.0088 km',
                'relative_gap_rule': 'platform farther than far_km while another platform is within '
                                     'competitor_close_km'},
        metrics=geo_metrics, training_data=stores.assign(data_status='REAL'),
        split={'type': 'none — geometric measurement over real store coordinates'},
        target='coverage gap per grid cell (descriptive)',
        training_source='data/reference/STORES*.csv (30 real store locations)',
        notes=('Deliverable 12c, geographic half. REAL: every coordinate is a real observed store '
               'location, including the stores of the three platforms whose PRICE data is synthetic. '
               'observation_key is a GEO_GRID cell identifier, NOT joinable to data/ml — these rows '
               'are city grid cells, not listings. A gap means distance to the nearest listed store; '
               'it is not evidence of unserved demand, and the 30 stores are this dataset\'s stores, '
               'not a verified census. Population weighting is impossible here: no demand data '
               'exists (CLAUDE.md section 4).'))

    print(f"category coverage: {len(cov)} rows, {cov.store_id.nunique()} REAL-carry stores, "
          f"{cov.category.nunique()} categories -> {band}")
    print(f"geography: {len(cell)} cells (~{cell_km:.2f} km), gaps "
          f"{ {p: int(cell[f'gap_{_slug(p)}'].sum()) for p in platforms} }")
    print("saved outputs/models/store_category_coverage, outputs/models/store_coverage_geography")


if __name__ == '__main__':
    main()
