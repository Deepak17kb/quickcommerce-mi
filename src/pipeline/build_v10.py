"""
build_v10.py
============
FIXES vs v9:
 1. Restores all 21,949 Blinkit products. The 2,923 rows v8 deleted as "duplicates"
    were distinct Master Product IDs with DIFFERENT prices - real separate catalog
    listings. Uniqueness key is now (snapshot_id, store_id, product_id); a
    listing_seq column disambiguates same-product listings inside a store.
 2. 30-day snapshot grid for ALL FOUR platforms (30 days x 2 slots = 60 snapshots),
    so cross-platform time-series actually lines up.
 3. Blinkit real baseline (2026-07-10) stays REAL and untouched; its 30-day panel
    is SYNTHETIC and labelled, because the source's other 4 dates were themselves
    backfilled, not observed.
 4. unit_price / mrp never fabricated on real rows.
"""
import numpy as np, pandas as pd
from pathlib import Path

RNG = np.random.default_rng(20260915)
OUT = Path("/mnt/user-data/outputs")
SCR = Path("/tmp/claude-0/-home-claude/3798d455-625a-503b-bf70-c7237fb22bb7/scratchpad")

OBS_COLS = ['snapshot_id','observed_at','snapshot_date','snapshot_time','hour','day_of_week',
            'platform','store_id','store_name','area','pincode','city','product_id',
            'canonical_product_key','listing_seq','product_name','brand','category','subcategory',
            'pack_size','pack_unit','mrp','selling_price','discount_percent','unit_price',
            'stock_status','in_stock','is_bestseller','is_sponsored','delivery_eta_min',
            'delivery_eta_max','delivery_fee','minimum_order_value','offer_type','offer_value',
            'coupon_required','buy_quantity','get_quantity','notes']
PROV = ['source','price_provenance','enrichment_provenance','data_status','is_real_observation']
ALL_COLS = OBS_COLS + PROV

PERSONAS = {
    'Blinkit':         dict(platform='Blinkit',          file='Blinkit',         pairs=1200,
        gap= 0.000, promo_rate=0.52, da=2.0, db=5.0, dmax=0.33, eta=(8,15),
        fees=[0,0,0,15,20,25], movs=[99,99,149], offer=0.31, bs=0.11, sp=0.08, oos=0.060),
    'Instamart':       dict(platform='Swiggy Instamart', file='Instamart',       pairs=1200,
        gap=-0.015, promo_rate=0.58, da=2.0, db=5.0, dmax=0.35, eta=(8,16),
        fees=[0,0,0,15,20,25], movs=[99,99,149], offer=0.34, bs=0.11, sp=0.09, oos=0.065),
    'FlipkartMinutes': dict(platform='Flipkart Minutes', file='FlipkartMinutes', pairs=900,
        gap=-0.060, promo_rate=0.72, da=2.0, db=4.0, dmax=0.42, eta=(10,22),
        fees=[0,0,0,0,19,29], movs=[0,49,99], offer=0.45, bs=0.09, sp=0.14, oos=0.085),
    'BigBasket':       dict(platform='BigBasket',        file='BigBasket',       pairs=1100,
        gap=-0.005, promo_rate=0.46, da=2.0, db=6.0, dmax=0.28, eta=(12,28),
        fees=[0,25,30,35,40], movs=[199,199,249], offer=0.28, bs=0.12, sp=0.07, oos=0.055),
}
OFFERS = np.array(['FLAT_OFF','PERCENT_OFF','BUY_X_GET_Y','COMBO_DEAL','BANK_OFFER'])
OFFER_W = np.array([0.26,0.34,0.16,0.12,0.12])
FRESH = {'Fruits & Vegetables','Dairy, Bread & Eggs','Meat, Fish & Eggs','Bakery','Fruits'}


def psych_vec(x):
    """vectorised snap to plausible Indian retail price endings"""
    x = np.asarray(x, dtype=float)
    out = np.empty_like(x)
    m1 = x < 20
    m2 = (x >= 20) & (x < 100)
    m3 = (x >= 100) & (x < 500)
    m4 = x >= 500
    out[m1] = np.round(x[m1], 1)
    v = np.floor(x[m2]); v = np.where(np.isin(v % 10, [0, 1]), v - 1, v)
    out[m2] = v
    out[m3] = np.round(x[m3] / 10.0) * 10 - 1
    out[m4] = np.round(x[m4] / 50.0) * 50 - 1
    return np.maximum(out, 1.0)


def make_grid():
    """30 days x 2 slots (09:00 / 18:00) = 60 snapshots, 2026-09-15 -> 2026-10-14"""
    rows = []
    start = pd.Timestamp('2026-09-15')
    for d in range(30):
        day = start + pd.Timedelta(days=d)
        for si, t in [(1, '09:00'), (2, '18:00')]:
            rows.append(dict(
                snapshot_id=f"D{d+1:02d}_S{si}", day_number=d + 1,
                snapshot_date=day.strftime('%Y-%m-%d'), snapshot_time=t,
                hour=int(t[:2]), day_of_week=day.day_name(),
                planned_at=f"{day.strftime('%Y-%m-%d')} {t}"))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- real Blinkit
def build_real_blinkit():
    """All 21,949 products at the real 2026-07-10 observation."""
    v7 = pd.read_excel(SCR / 'Blinkit_REAL_v7.xlsx', sheet_name='OBSERVATIONS')
    ml = pd.read_excel(SCR / 'blinkit_ml_dataset.xlsx', sheet_name='ML_READY')
    ml = ml[ml.snapshot_date == '2026-07-10']

    b = v7.copy()
    b['listing_seq'] = b.groupby(['store_id', 'canonical_product_key']).cumcount() + 1

    # the 4 product ids that never made it into the v7 build: identity only, no prices
    missing = sorted(set(ml['Master Product ID']) - set(b.product_id))
    if missing:
        mm = ml[ml['Master Product ID'].isin(missing)]
        add = pd.DataFrame(index=range(len(mm)), columns=b.columns)
        add['product_id'] = mm['Master Product ID'].values
        add['canonical_product_key'] = mm['canonical_product_key'].values
        add['product_name'] = mm['Product Name Clean'].values
        add['pack_size'] = mm['Size'].values
        add['category'] = mm['Category Clean'].values
        add['store_id'] = mm['store_id'].values
        add['store_name'] = mm['store_name'].values
        add['area'] = mm['area'].values
        add['pincode'] = mm['pin'].values
        add['city'] = mm['city'].values
        add['platform'] = 'Blinkit'
        add['snapshot_id'] = 'BASELINE_2026-07-10'
        add['observed_at'] = '2026-07-10'
        add['snapshot_date'] = '2026-07-10'
        add['day_of_week'] = 'Friday'
        add['listing_seq'] = 1
        # MRP and stock status are identical on all 5 source dates -> untouched source
        # values. Selling price carries the backfill jitter, so it stays NULL.
        add['mrp'] = pd.to_numeric(mm['MRP'].values, errors='coerce')
        add['stock_status'] = mm['Stock Status'].values
        add['in_stock'] = (mm['Stock Status'].values == 'Available').astype(int)
        add['notes'] = ('Unnamed listing in source catalog. MRP and stock_status recovered '
                        '(stable across all source dates); product_name, pack_size and '
                        'selling_price absent from the cleaned source, left NULL not invented')
        b = pd.concat([b, add], ignore_index=True)

    # concat with the identity-only rows makes numeric columns object; coerce back
    for c in ['mrp','selling_price','discount_percent','unit_price','delivery_eta_min',
              'delivery_eta_max','in_stock','pincode']:
        b[c] = pd.to_numeric(b[c], errors='coerce')

    # ---- cleaning rules (same as v8, applied on the full restored set) ----
    bad = (b['selling_price'] > b['mrp']).fillna(False)
    b.loc[bad, 'mrp'] = np.nan
    b.loc[bad, 'discount_percent'] = np.nan

    mrp_a, sp_a = b['mrp'].to_numpy(float), b['selling_price'].to_numpy(float)
    with np.errstate(invalid='ignore', divide='ignore'):
        b['discount_percent'] = np.where(np.isfinite(mrp_a) & np.isfinite(sp_a) & (mrp_a > 0),
                                         np.round((mrp_a - sp_a) / mrp_a * 100, 2), np.nan)

    qty = pd.to_numeric(b['pack_size'].astype(str).str.split().str[0],
                        errors='coerce').to_numpy(float)
    has_unit = b['pack_unit'].notna().to_numpy()
    with np.errstate(invalid='ignore', divide='ignore'):
        b['unit_price'] = np.where(np.isfinite(sp_a) & np.isfinite(qty) & (qty > 0) & has_unit,
                                   np.round(sp_a / np.where(qty > 0, qty, 1), 2), np.nan)

    b['is_bestseller'] = np.nan          # never captured in the real snapshot
    b['is_sponsored'] = np.nan
    b['notes'] = b['notes'].fillna('Real observed snapshot 2026-07-10; time-of-day not recorded')

    b['source'] = 'Blinkit_Master_FINAL_Clean_v2 (real catalog snapshot)'
    b['price_provenance'] = 'observed'
    b['enrichment_provenance'] = 'not_captured'
    b['data_status'] = 'REAL'
    b['is_real_observation'] = 1

    for c in ALL_COLS:
        if c not in b.columns:
            b[c] = np.nan
    print(f"  REAL Blinkit: {len(b):,} rows, {b.product_id.nunique():,} product ids, "
          f"{int(b.listing_seq.max())} max listings per product per store")
    return b[ALL_COLS], missing


# ---------------------------------------------------------------- synthetic
def build_synth(name, cfg, grid, catalog, stores, ref):
    cat = catalog[catalog.canonical_product_key.isin(ref.index)].copy()
    cat['ref_price'] = cat.canonical_product_key.map(ref)
    cat = cat[cat.ref_price.notna() & (cat.ref_price > 0)].reset_index(drop=True)

    P = cfg['pairs']
    pi = RNG.choice(len(cat), size=P, replace=False) if P <= len(cat) \
        else RNG.choice(len(cat), size=P, replace=True)
    sids = stores.store_id.to_numpy()
    si = RNG.integers(0, len(sids), size=P)

    # per-pair persistent attributes (stable across the 60 snapshots)
    lvl   = np.clip(RNG.normal(1 + cfg['gap'], 0.045, P), 0.78, 1.22)
    promo = RNG.random(P) < cfg['promo_rate']
    depth = RNG.beta(cfg['da'], cfg['db'], P) * cfg['dmax']
    bs    = RNG.random(P) < cfg['bs']
    spon  = RNG.random(P) < cfg['sp']
    offon = RNG.random(P) < cfg['offer']
    otyp  = RNG.choice(OFFERS, size=P, p=OFFER_W)

    base   = cat.ref_price.to_numpy()[pi]
    isfresh = np.isin(cat.category.to_numpy()[pi], list(FRESH))
    qty    = pd.to_numeric(cat.pack_qty, errors='coerce').to_numpy()[pi]
    punit  = cat.pack_unit.to_numpy()[pi]

    S = len(grid)
    N = P * S
    wave = np.repeat(RNG.normal(0, 0.012, S), P)          # per-snapshot promo wave
    hour = np.repeat(grid.hour.to_numpy(), P)
    T = lambda a: np.tile(a, S)                            # per-pair -> full panel

    # ---- price: anchor SELLING price, derive MRP upward ----
    sp_raw = T(base) * T(lvl) * (1 + wave) * RNG.normal(1.0, 0.018, N)
    sell = psych_vec(np.maximum(sp_raw, 1.0))

    dep = np.clip(T(depth) * RNG.uniform(0.75, 1.15, N), 0.02, 0.60)
    mrp = np.where(T(promo), psych_vec(sell / (1 - dep)), sell)
    bad = mrp <= sell
    mrp = np.where(bad & T(promo), np.round(sell * (1 + np.maximum(dep, 0.05)), 2), mrp)
    mrp = np.maximum(mrp, sell)
    disc = np.where(mrp > 0, np.round((mrp - sell) / mrp * 100, 2), np.nan)

    # ---- unit price ----
    q = T(qty)
    valid_u = np.isfinite(q) & (q > 0) & (T(punit) != None) & (pd.notna(T(punit)))
    unit = np.where(valid_u, np.round(sell / np.where(q > 0, q, 1), 2), np.nan)

    # ---- stock ----
    p_oos = np.minimum(cfg['oos'] * np.where(T(isfresh), 1.9, 1.0)
                       * np.where(hour == 18, 1.35, 1.0), 0.45)
    instock = (RNG.random(N) >= p_oos).astype(int)

    # ---- eta (hour aware) ----
    lo, hi = cfg['eta']
    bump = np.where(hour == 18, 4, 0)
    eta_lo = RNG.integers(lo, lo + 4, N) + bump
    eta_hi = eta_lo + RNG.integers(4, 11, N)

    # ---- offers ----
    show = T(offon) & (instock == 1)
    ot = np.where(show, T(otyp), 'NO_OFFER')
    oval = np.full(N, np.nan); bq = np.full(N, np.nan); gq = np.full(N, np.nan)
    coup = np.zeros(N)
    for t, vals in [('FLAT_OFF', [10,20,25,30,50,75,100]),
                    ('PERCENT_OFF', [5,10,15,20,25,30]),
                    ('COMBO_DEAL', [15,25,40,60]),
                    ('BANK_OFFER', [10,50,75,100])]:
        m = ot == t
        if m.any():
            oval[m] = RNG.choice(vals, size=int(m.sum()))
            coup[m] = (RNG.random(int(m.sum())) < (0.35 if t == 'FLAT_OFF' else
                       0.30 if t == 'PERCENT_OFF' else 0.0)).astype(float)
            if t == 'BANK_OFFER':
                coup[m] = 1.0
    mb = ot == 'BUY_X_GET_Y'
    if mb.any():
        bq[mb] = RNG.choice([1,2,2,3], size=int(mb.sum())); gq[mb] = 1.0

    st = stores.set_index('store_id')
    sid_f = T(sids[si])
    df = pd.DataFrame({
        'snapshot_id':   np.repeat(grid.snapshot_id.to_numpy(), P),
        'observed_at':   np.repeat(grid.planned_at.to_numpy(), P),
        'snapshot_date': np.repeat(grid.snapshot_date.to_numpy(), P),
        'snapshot_time': np.repeat(grid.snapshot_time.to_numpy(), P),
        'hour': hour,
        'day_of_week':   np.repeat(grid.day_of_week.to_numpy(), P),
        'platform': cfg['platform'],
        'store_id': sid_f,
        'store_name': st.store_name.reindex(sid_f).to_numpy(),
        'area':       st.area.reindex(sid_f).to_numpy(),
        'pincode':    st['pin'].reindex(sid_f).to_numpy(),
        'city':       st.city.reindex(sid_f).to_numpy(),
        'product_id': T(np.array([f"{cfg['file'][:3].upper()}-{i+1:06d}" for i in range(P)])),
        'canonical_product_key': T(cat.canonical_product_key.to_numpy()[pi]),
        'listing_seq': 1,
        'product_name': T(cat.product_name.to_numpy()[pi]),
        'brand':        T(cat.brand.to_numpy()[pi]),
        'category':     T(cat.category.to_numpy()[pi]),
        'subcategory':  T(cat.subcategory.to_numpy()[pi]),
        'pack_size':    T(cat.pack_size.to_numpy()[pi]),
        'pack_unit':    T(punit),
        'mrp': mrp, 'selling_price': sell, 'discount_percent': disc, 'unit_price': unit,
        'stock_status': np.where(instock == 1, 'Available', 'Out of Stock'),
        'in_stock': instock,
        'is_bestseller': np.where(instock == 1, T(bs).astype(int), 0),
        'is_sponsored': T(spon).astype(int),
        'delivery_eta_min': eta_lo, 'delivery_eta_max': eta_hi,
        'delivery_fee': RNG.choice(cfg['fees'], N).astype(float),
        'minimum_order_value': RNG.choice(cfg['movs'], N).astype(float),
        'offer_type': ot, 'offer_value': oval, 'coupon_required': coup,
        'buy_quantity': bq, 'get_quantity': gq,
        'notes': 'SYNTHETIC ROW - generated for pipeline/demo use, not a real observation',
        'source': 'SIMULATED_GENERATOR_v10',
        'price_provenance': 'simulated_from_blinkit_median_reference',
        'enrichment_provenance': 'simulated',
        'data_status': 'SYNTHETIC', 'is_real_observation': 0,
    })
    df = df.drop_duplicates(subset=['snapshot_id','store_id','product_id'], keep='first')
    print(f"  {name:<16} {len(df):>7,} rows | {df.snapshot_id.nunique()} snapshots | "
          f"{df.store_id.nunique()} stores | {df.canonical_product_key.nunique():,} products")
    return df[ALL_COLS]


def banner(kind, platform, n_real, n_syn, missing=None):
    L = [f'*** {platform} ***', '']
    if n_real:
        L += [f'REAL rows      : {n_real:,}   (data_status = REAL, is_real_observation = 1)']
    if n_syn:
        L += [f'SYNTHETIC rows : {n_syn:,}   (data_status = SYNTHETIC, is_real_observation = 0)']
    L += ['', 'FILTER BEFORE YOU MODEL:',
          "    real = df[df.data_status == 'REAL']",
          "    syn  = df[df.data_status == 'SYNTHETIC']", '']
    if kind == 'blinkit':
        L += [
            'THE REAL ROWS', '  One observed snapshot: 2026-07-10. All 21,949 catalog listings.',
            '  snapshot_time and hour are EMPTY because the source recorded the date only.',
            '  mrp is NULL on most rows because the source cleaning backfilled MRP = selling',
            '  price; only genuinely distinct MRPs were kept. Neither is invented.', '',
            'WHY THE 30-DAY PANEL IS SYNTHETIC',
            '  The source workbook carried 5 dated snapshots, but its own build notes mark',
            '  four of them (06-10, 06-17, 06-24, 07-01) as backfilled_modeled_for_pipeline_',
            '  testing: prices are jitter around the 07-10 price and stock status is identical',
            '  on every date (20,595 / 1,354, same SKUs). Only 2026-07-10 was ever observed.',
            '  So there is no real Blinkit history to restore - the panel is generated.', '']
        if missing:
            L += ['FOUR LISTINGS WITH IDENTITY ONLY',
                  '  ' + ', '.join(missing),
                  '  Present in the catalog index but absent from the cleaned price table.',
                  '  Names and categories kept; price/stock/ETA left NULL, not invented.', '']
    else:
        L += ['WHAT IS REAL IN THE SYNTHETIC ROWS',
              '  Store names, addresses, coordinates, pincodes, product names, brands,',
              '  categories and pack sizes are real.',
              '  Prices, MRP, discounts, stock, ETA, fees, offers and badges are generated.', '']
    L += ['SAFE USES        : pipeline tests, dashboards, demos, screenshots, schema checks',
          'NOT SAFE FOR     : production model training, real price claims, competitive calls', '',
          'TO REPLACE WITH REAL DATA',
          '  Clear the synthetic rows, log observations against SNAPSHOT_SCHEDULE, then set',
          "  data_status = 'REAL' and is_real_observation = 1. Schema already matches."]
    return pd.DataFrame({'READ_ME': L})


def main():
    print("=" * 78); print("BUILD v10"); print("=" * 78)
    grid = make_grid()
    print(f"Grid: {len(grid)} snapshots, {grid.snapshot_date.nunique()} days "
          f"({grid.snapshot_date.min()} -> {grid.snapshot_date.max()}), "
          f"slots {sorted(grid.snapshot_time.unique())}\n")

    real_b, missing = build_real_blinkit()

    # reference price per canonical product, from the REAL Blinkit observation
    ref = real_b.groupby('canonical_product_key').selling_price.median()
    catalog = pd.read_excel(OUT / 'Instamart_CLEAN_v8.xlsx', sheet_name='MASTER_CATALOG')

    print("\nSynthetic panels:")
    parts = {'Blinkit': [real_b]}
    for name, cfg in PERSONAS.items():
        stores = pd.read_excel(OUT / f"{cfg['file']}_CLEAN_v8.xlsx", sheet_name='STORES')
        syn = build_synth(name, cfg, grid, catalog, stores, ref)
        parts.setdefault(name, []).append(syn)

    print("\nWriting workbooks:")
    for name, cfg in PERSONAS.items():
        df = pd.concat(parts[name], ignore_index=True)
        stores = pd.read_excel(OUT / f"{cfg['file']}_CLEAN_v8.xlsx", sheet_name='STORES')
        n_real = int((df.data_status == 'REAL').sum())
        n_syn = int((df.data_status == 'SYNTHETIC').sum())
        out = OUT / f"{cfg['file']}_FINAL_v10.xlsx"
        with pd.ExcelWriter(out, engine='xlsxwriter') as w:
            banner('blinkit' if name == 'Blinkit' else 'other', cfg['platform'],
                   n_real, n_syn, missing).to_excel(w, sheet_name='_READ_ME_FIRST', index=False)
            df.to_excel(w, sheet_name='OBSERVATIONS', index=False)
            grid.to_excel(w, sheet_name='SNAPSHOT_SCHEDULE', index=False)
            catalog.to_excel(w, sheet_name='MASTER_CATALOG', index=False)
            stores.to_excel(w, sheet_name='STORES', index=False)
        print(f"  {out.name:<34} {len(df):>7,} rows  (REAL {n_real:,} / SYN {n_syn:,})")
        parts[name] = df

    allp = pd.concat(parts.values(), ignore_index=True)
    allp.to_csv(OUT / 'ALL_PLATFORMS_FINAL_v10.csv.gz', index=False, compression='gzip')
    print(f"  ALL_PLATFORMS_FINAL_v10.csv.gz     {len(allp):>7,} rows")

    summary = (allp.groupby(['platform', 'data_status'])
               .agg(rows=('selling_price', 'size'), products=('canonical_product_key', 'nunique'),
                    listings=('product_id', 'nunique'), stores=('store_id', 'nunique'),
                    snapshots=('snapshot_id', 'nunique'), days=('snapshot_date', 'nunique'),
                    median_price=('selling_price', 'median'),
                    pct_in_stock=('in_stock', lambda s: round(100 * s.mean(), 1)))
               .reset_index())
    with pd.ExcelWriter(OUT / 'ALL_PLATFORMS_FINAL_v10.xlsx', engine='xlsxwriter') as w:
        banner('other', 'MIXED REAL + SYNTHETIC DATASET',
               int((allp.data_status == 'REAL').sum()),
               int((allp.data_status == 'SYNTHETIC').sum())).to_excel(
            w, sheet_name='_READ_ME_FIRST', index=False)
        summary.to_excel(w, sheet_name='SUMMARY', index=False)
        allp.to_excel(w, sheet_name='ALL_OBSERVATIONS', index=False)

    print("\n" + "=" * 78); print("SUMMARY"); print("=" * 78)
    print(summary.to_string(index=False))

    print("\n" + "=" * 78); print("VALIDATION"); print("=" * 78)
    d = allp[allp.mrp.notna() & allp.selling_price.notna()]
    exp = ((d.mrp - d.selling_price) / d.mrp * 100).round(2)
    chk = [
        ("selling_price > mrp", int((allp.selling_price > allp.mrp).sum())),
        ("duplicate (snapshot, store, product_id)",
         int(allp.duplicated(['snapshot_id','store_id','product_id']).sum())),
        ("discount_percent mismatch", int((exp - d.discount_percent).abs().gt(0.02).sum())),
        ("unit_price set where pack_unit NULL",
         int(allp[allp.unit_price.notna()].pack_unit.isna().sum())),
        ("eta_max <= eta_min", int((allp.delivery_eta_max.notna() &
                                    (allp.delivery_eta_max <= allp.delivery_eta_min)).sum())),
        ("in_stock vs stock_status mismatch",
         int(((allp.stock_status == 'Available') != (allp.in_stock == 1)).sum())),
        ("synthetic row not labelled", int((allp[allp.source.astype(str).str.startswith('SIMULATED')]
                                            .data_status != 'SYNTHETIC').sum())),
        ("real row not labelled REAL", int((allp[~allp.source.astype(str).str.startswith('SIMULATED')]
                                            .data_status != 'REAL').sum())),
        ("Blinkit real listings != 21949",
         int(allp[(allp.platform=='Blinkit') & (allp.data_status=='REAL')].product_id.nunique() - 21949)),
    ]
    for l, v in chk:
        print(f"  {'PASS' if v == 0 else 'FAIL'}  {l:<44} {v}")

    print("\nFIELD COVERAGE (non-null %)")
    for f in ['observed_at','snapshot_time','hour','mrp','discount_percent','unit_price',
              'delivery_eta_min','delivery_eta_max','offer_type','is_bestseller']:
        r = allp[allp.data_status=='REAL'][f].notna().mean()*100
        s = allp[allp.data_status=='SYNTHETIC'][f].notna().mean()*100
        print(f"  {f:<20} REAL {r:6.1f}%   SYNTHETIC {s:6.1f}%")

    print("\nPRICE POSITIONING vs Blinkit real (synthetic)")
    for p in ['Swiggy Instamart','Flipkart Minutes','BigBasket','Blinkit']:
        sub = allp[(allp.platform == p) & (allp.data_status == 'SYNTHETIC')]
        if not len(sub): continue
        gap = (sub.selling_price / sub.canonical_product_key.map(ref) - 1) * 100
        print(f"  {p:<18} median {gap.median():+6.2f}%   promo {(sub.discount_percent>0).mean()*100:5.1f}%")


if __name__ == '__main__':
    main()
