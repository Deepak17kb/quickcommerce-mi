"""
store_adds.py — SIMULATE extension: a Blinkit store adds the products its peers list. REAL + SYNTHETIC, labelled per part.

    python -m src.simulate.store_adds         # -> outputs/models/simulate_store_adds/ (SYNTHETIC parts B, C)
                                              #    outputs/models/simulate_store_adds_real/ (REAL part A)

THE SCENARIO
  Store s adds its top-N assortment gaps (deliverable 10: products similar REAL stores list and s was not seen listing),
  N = 10, 25, 50. Three questions, three provenances:

  A  REAL        assortment shape. Does the store's category mix move towards its peers' (the other seven REAL stores)?
                 Measured as the total-variation distance between the store's category shares and the peer median, before
                 and after. And the REAL price level of the additions: their median price in the stores that list them.
                 A gap is "not seen in this store's listing", not "not stocked" (docs/ASSORTMENT_GAPS_v1.md).

  B  SYNTHETIC   price position of the additions. For added products that are in the four-platform common panel, the
                 share of snapshots Blinkit is cheapest-of-4 on them under the status-quo price world (deliverable 9),
                 against the store's current common-panel products.

  C  SYNTHETIC   operations. More listings compete for the same restock effort. The store's generated listings (the stock
                 world, deliverables 7, 8) get the added products as fresh in-stock listings of their categories, and
                 the priority index (12b) runs with a FIXED number of actions per snapshot (what 2% of today's listings
                 is) versus capacity that grows with the assortment. The added listings are simulated in every run and
                 are only invisible to the operator in the "before" run, so all random streams stay paired. Measured: out-of-stock exposure of the EXISTING
                 listings (the dilution cost), of the new ones, and the store OOS share -> ETA with deliverable 5's
                 store-OOS term, shown at the planted (8), state-space (19) and naive (56) values.

  The generated store has ~300 listings, a sample of the REAL store's 1,300-7,000; adding 50 products to it is a far
  bigger relative change than to the real store. Part C therefore reports per added listing as well as totals.

CLAIM SCOPE
  Part A is REAL (2026-07-10 snapshot). B and C are SYNTHETIC: positioning and availability under the fitted, generated
  dynamics. No demand exists, so nothing here says an addition would sell, earn or attract anyone.
"""
import json

import numpy as np
import pandas as pd

import src.load as L
from src.model_output import MODELS_DIR, save_model_outputs
from src.optimize.restock_priority import policy_priority
from src.simulate.engine import PLATFORMS, PriceWorld, StockWorld

NAME = 'simulate_store_adds'
NAME_REAL = 'simulate_store_adds_real'
NS = (10, 25, 50)
N_SIMS = 16
HORIZON = 12
SEED = 31
CAPACITY = 0.02                    # 2%: ~6 actions per snapshot, fine enough that capacity can scale
ETA_TERMS = {'planted': 8.0, 'naive': 56.0}
REAL_DATE = '2026-07-10'


# =========================================================================== A: REAL assortment shape
def tv_distance(a: pd.Series, b: pd.Series) -> float:
    idx = a.index.union(b.index)
    return float(0.5 * (a.reindex(idx, fill_value=0) - b.reindex(idx, fill_value=0)).abs().sum())


def real_part(real, gaps, store, n):
    mine = real[real.store_id == store]
    keys = set(mine.canonical_product_key)
    mix = mine.drop_duplicates('canonical_product_key').category.value_counts(normalize=True)
    peers = [real[real.store_id == p].drop_duplicates('canonical_product_key').category.value_counts(normalize=True)
             for p in sorted(real.store_id.unique()) if p != store]
    peer = pd.concat(peers, axis=1).fillna(0).median(axis=1)
    peer = peer / peer.sum()
    add = gaps[(gaps.store_id == store) & (gaps['rank'] <= n)]
    add = add[~add.canonical_product_key.isin(keys)]
    counts = mine.drop_duplicates('canonical_product_key').category.value_counts()
    after = counts.add(add.category.value_counts(), fill_value=0)
    after = after / after.sum()
    px = (real[real.canonical_product_key.isin(add.canonical_product_key)]
          .groupby('canonical_product_key').selling_price.median())
    under = (peer - mix.reindex(peer.index, fill_value=0))
    filled = add.category.map(lambda c: under.get(c, 0) > 0).mean() if len(add) else 0.0
    return {'provenance': 'REAL', 'products_now': int(len(keys)), 'added': int(len(add)),
            'tv_distance_to_peer_mix_before': round(tv_distance(mix, peer), 4),
            'tv_distance_to_peer_mix_after': round(tv_distance(after, peer), 4),
            'share_of_additions_in_under_represented_categories': round(float(filled), 3),
            'added_by_category': add.category.value_counts().to_dict(),
            'median_real_price_of_additions': float(px.median()) if len(px) else None,
            'median_real_price_now': float(mine.selling_price.median())}


# =========================================================================== B: SYNTHETIC price position
def position_part(blk_share_by_key, keys_in_panel, real, gaps, store, n):
    mine = set(real[real.store_id == store].canonical_product_key)
    add = gaps[(gaps.store_id == store) & (gaps['rank'] <= n)].canonical_product_key
    add_in = [k for k in add if k in keys_in_panel]
    now_in = [k for k in mine if k in keys_in_panel]
    f = lambda ks: float(np.nanmean([blk_share_by_key[keys_in_panel[k]] for k in ks])) if ks else None
    return {'provenance': 'SYNTHETIC', 'additions_in_four_platform_panel': len(add_in),
            'current_products_in_panel': len(now_in),
            'blinkit_cheapest_of_4_share_additions': f(add_in), 'blinkit_cheapest_of_4_share_current': f(now_in)}


# =========================================================================== C: SYNTHETIC operations
def new_listings(st_store, gaps_store, depth_by_cat):
    tmpl = st_store.iloc[0]
    rows = []
    for _, g in gaps_store.iterrows():
        rows.append({'observation_key': f"ADDED | {tmpl.store_id} | {g.canonical_product_key}", 'platform': 'Blinkit',
                     'store_id': tmpl.store_id, 'category': g.category, 'in_stock': 1, 'clock': 1.0,
                     'clock_censored': 0, 'oos_elapsed': 0.0, 'depth': float(depth_by_cat.get(g.category, 0.0)),
                     'next_evening': float(tmpl.next_evening)})
    return pd.DataFrame(rows)


def ops_part(W, st_store, add_df, n_existing):
    k_actions = max(int(round(n_existing * CAPACITY)), 1)              # today's restock effort, actions per snapshot
    both = pd.concat([st_store, add_df], ignore_index=True)
    n_all = len(both)
    existing_only = np.arange(n_all) < n_existing

    def run(k, active):
        # the added listings are simulated in EVERY run, so all random streams stay paired; in the "before" run they
        # are inactive: the operator neither sees nor counts them. k actions exactly: int(n_active * share) == k
        share = (k + 0.5) / int(active.sum())
        r = W.simulate(both, horizon=HORIZON, n_sims=N_SIMS, seed=SEED, policy=policy_priority,
                       capacity_share=share, return_states=True, active=active)
        return 1 - r['in_stock_path']                                    # (sim, t, listing) out of stock
    all_on = np.ones(n_all, bool)
    before = run(k_actions, existing_only)
    fixed = run(k_actions, all_on)                                       # same number of actions, more listings
    k_scaled = max(int(round(n_all * CAPACITY)), 1)
    scaled = run(k_scaled, all_on)                                       # capacity grows with the assortment
    ex = slice(0, n_existing)

    def exposure(o, sl):
        return o[:, :, sl].sum((1, 2))                                   # OOS listing-snapshots per simulation
    e0, e_fix, e_sc = exposure(before, ex), exposure(fixed, ex), exposure(scaled, ex)
    new_fix = exposure(fixed, slice(n_existing, None))
    share0 = before[:, :, :n_existing].mean((1, 2)); share_fix = fixed.mean((1, 2))
    b_ss = W.eta.get('b_store_oos_state_space') or 0.0
    terms = {**ETA_TERMS, 'state_space': b_ss}
    d_share = float((share_fix - share0).mean())
    return {'provenance': 'SYNTHETIC', 'restock_actions_per_snapshot': k_actions, 'scaled_actions': k_scaled,
            'existing_listings': n_existing, 'added_listings': int(len(add_df)),
            'existing_oos_listing_snapshots_before': round(float(e0.mean()), 2),
            'existing_oos_change_pct_fixed_capacity': round(float(100 * (e_fix - e0).mean() / e0.mean()), 2),
            'existing_oos_change_pct_scaled_capacity': round(float(100 * (e_sc - e0).mean() / e0.mean()), 2),
            'dilution_band_90_pct': [round(float(100 * np.quantile((e_fix - e0) / e0, q)), 2) for q in (0.05, 0.95)],
            'new_listing_oos_rate': round(float(new_fix.mean() / (len(add_df) * HORIZON)), 4) if len(add_df) else None,
            'existing_oos_rate_before': round(float(e0.mean() / (n_existing * HORIZON)), 4),
            'store_oos_share_change_pp': round(100 * d_share, 3),
            'eta_minutes': {k: round(v * d_share, 3) for k, v in terms.items()}}


def main():
    real = L.real_only(L.load_raw())
    gaps = pd.read_parquet(MODELS_DIR / 'assortment_gaps' / 'predictions.parquet')
    stores = sorted(gaps.store_id.unique())
    # B: per-key Blinkit cheapest-of-4 share, status quo
    PW = PriceWorld.load()
    blk_share = PW.simulate({}, horizon=HORIZON, n_sims=N_SIMS, seed=SEED)['cheapest_by_key'][0]
    keys_in_panel = {k: i for i, k in enumerate(PW.keys)}
    # C: stock world
    W = StockWorld.load(); st = W.initial_state()
    blk = st[st.platform == 'Blinkit']
    depth_by_cat = blk.groupby('category').depth.mean().to_dict()
    out, rows = [], []
    for s in stores:
        st_s = blk[blk.store_id == s].reset_index(drop=True)
        for n in NS:
            a = real_part(real, gaps, s, n)
            b = position_part(blk_share, keys_in_panel, real, gaps, s, n)
            add = gaps[(gaps.store_id == s) & (gaps['rank'] <= n)]
            add = add[add.category.isin(W.cats)]
            c = ops_part(W, st_s, new_listings(st_s, add, depth_by_cat), len(st_s))
            out.append({'store_id': s, 'n': n, 'real': a, 'position': b, 'operations': c})
            rows.append({'store_id': s, 'n': n, 'tv_before': a['tv_distance_to_peer_mix_before'],
                         'tv_after': a['tv_distance_to_peer_mix_after'],
                         'share_additions': b['blinkit_cheapest_of_4_share_additions'],
                         'share_current': b['blinkit_cheapest_of_4_share_current'],
                         'dilution_pct': c['existing_oos_change_pct_fixed_capacity'],
                         'scaled_pct': c['existing_oos_change_pct_scaled_capacity'],
                         'eta_state_space': c['eta_minutes']['state_space']})
            print(f"  {s} +{n}: TV {a['tv_distance_to_peer_mix_before']:.3f}->{a['tv_distance_to_peer_mix_after']:.3f}  "
                  f"dilution {c['existing_oos_change_pct_fixed_capacity']:+.1f}%  scaled {c['existing_oos_change_pct_scaled_capacity']:+.1f}%")
    tab = pd.DataFrame(rows)
    at50 = tab[tab.n == 50]
    # ---- REAL part A, saved as its own REAL-ONLY output (one provenance per model output)
    real_metrics = {
        'claim_limit': ('REAL, from the 2026-07-10 Blinkit snapshot. A gap means "not seen in the store listing", not '
                        '"not stocked". Assortment shape and price level only; nothing about demand or sales.'),
        'adds': list(NS),
        'stores_moving_closer_to_peer_mix_at_50': int((at50.tv_after < at50.tv_before).sum()),
        'median_tv_distance_before_at_50': float(at50.tv_before.median()),
        'median_tv_distance_after_at_50': float(at50.tv_after.median()),
        'by_store': [{'store_id': o['store_id'], 'n': o['n'], **o['real']} for o in out]}
    real_pred = gaps[['observation_key', 'store_id', 'rank', 'canonical_product_key', 'category']].assign(
        data_status='REAL', prediction=gaps['rank'])
    save_model_outputs(NAME_REAL, real_pred, params={'adds': list(NS), 'peer': 'median category mix of the other 7 stores'},
                       metrics=real_metrics, training_data=real.assign(snapshot_date=REAL_DATE)[['observation_key', 'data_status', 'snapshot_date']],
                       split={'uses': 'REAL snapshot + assortment_gaps (REAL)'},
                       target='category-mix distance to peers when a store adds its gaps',
                       notes='SIMULATE extension, store adds products, part A. REAL ONLY.')
    # ---- SYNTHETIC parts B, C
    metrics = {
        'claim_limit': ('SYNTHETIC: price position (B) and restock dilution (C) of adding the REAL assortment gaps of a store, '
                        'under the fitted, generated dynamics. The REAL assortment part is simulate_store_adds_real. '
                        'Nothing about demand, sales or revenue.'),
        'n_sims': N_SIMS, 'horizon': HORIZON, 'capacity_share_today': CAPACITY, 'adds': list(NS),
        'summary_at_50': {
            'median_existing_oos_change_pct_fixed_capacity': float(at50.dilution_pct.median()),
            'median_existing_oos_change_pct_scaled_capacity': float(at50.scaled_pct.median()),
            'median_blinkit_share_additions': float(at50.share_additions.median()),
            'median_blinkit_share_current': float(at50.share_current.median()),
            'median_eta_minutes_state_space': float(at50.eta_state_space.median())},
        'by_store': [{'store_id': o['store_id'], 'n': o['n'], 'position': o['position'], 'operations': o['operations']}
                     for o in out],
    }
    anchor = W.initial_state().observation_key.iloc[0]
    pred = tab.drop(columns=['tv_before', 'tv_after']).assign(observation_key=anchor, data_status='SYNTHETIC',
                                                               prediction=tab.dilution_pct)
    save_model_outputs(NAME, pred, params={'adds': list(NS), 'n_sims': N_SIMS, 'horizon': HORIZON, 'seed': SEED,
                                           'capacity_share_today': CAPACITY},
                       metrics=metrics, training_data=pred, split={'uses': 'assortment_gaps + price and stock worlds'},
                       target='price position and restock dilution when a store adds its gaps',
                       notes='SIMULATE extension: store adds products, parts B-C. SYNTHETIC ONLY.')
    print(json.dumps(real_metrics | {'by_store': None}, indent=1))
    print(json.dumps(metrics['summary_at_50'], indent=1))


if __name__ == '__main__':
    main()
