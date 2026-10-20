"""
collection.py — how much REAL data would be enough? A power analysis for the panel nobody has collected yet.

    python -m src.planner.collection

WHY
  Every dynamic result in this project rests on a generated panel, because the only REAL data is one snapshot. A real
  panel has to be logged by hand (the owner's QuickComm Price Logger holds a 128-product watchlist and, when this was
  written, 0 observations). Before anyone spends evenings on four apps, this answers: for each quantity the project
  cares about, how many days and how many products does a panel need before the estimate is worth having?

HOW
  The SYNTHETIC common panel (2,000 products on all four platforms, 60 snapshots, 09:00 and 18:00 for 30 days) has
  the shape a real panel would have. A DESIGN is (days, products, snapshots per day). For each design the panel is
  cut down to it many times: a random run of consecutive days and a random set of products, every platform's listing
  of each. Each cut is estimated with the plain estimator a first analysis would use, and compared with what the full
  panel gives. A design IDENTIFIES a quantity when at least 90% of its cuts land within the stated tolerance.

THE QUANTITIES
  price_gap        Flipkart Minutes' median price gap to the other three platforms, in percent
  cheapest_share   how often Flipkart Minutes is the cheapest of the four, in percent
  oos_rate         share of Blinkit listings out of stock, in percent
  restock_mean     mean length of a completed out-of-stock spell, in snapshots
  hazard_ratio     stock-out hazard after 5-10 snapshots in stock over the hazard after 1-2: is it duration-dependent?
  response_beta    Swiggy Instamart's naive response to Blinkit's last price move
  evening_eta      Blinkit's evening ETA minus its morning ETA, in minutes
  The last four need both daily snapshots; a once-a-day design cannot estimate them at all and is reported so.

WHAT IT CAN CLAIM  (read this before using a number)
  SYNTHETIC-DERIVED. The answer is "what a panel of this shape resolves IF the real market is about as noisy as the
  generator". Two parts of that noise are calibrated to the REAL snapshot (stock-out level per category, price-ending
  grid); the rest is assumption (docs/GENERATOR_v15_PARAMETERS.md). So this is a planning prior, not a guarantee: log
  a short pilot, then re-run the same cuts on the pilot's own variance. Hours of effort use an assumed logging speed.
  One REAL fact widens the stock-out answer: records of the same product are out of stock together far more often
  than chance (real_store_label_audit), which the generator does not plant.
"""
import json

import numpy as np
import pandas as pd

import src.load as L
from src.diagnostics import completed_oos_spells, run_length_hazard
from src.model_output import MODELS_DIR, save_model_outputs

NAME = 'collection_planner'
PLATFORMS = ['Blinkit', 'Swiggy Instamart', 'Flipkart Minutes', 'BigBasket']
BLK, INS, FKM = 0, 1, 2
DAYS = (1, 2, 3, 5, 7, 10, 14, 21, 30)
SKUS = (10, 25, 50, 128, 250, 500, 1000)
WATCHLIST_SKUS = 128                  # products on the owner's price logger watchlist
PER_DAY = (2, 1)                      # both scheduled snapshots, or the morning one only
REPS = 200
SEED = 20261013
IDENTIFIED_SHARE = 0.90               # share of cuts that must land within tolerance
SECONDS_PER_OBSERVATION = 20          # ASSUMPTION: one product on one app, typed into the logger form
MIN_SPELLS = 5

# name -> (tolerance, unit, needs both daily snapshots, planted value or None, what transfers to the real market)
QUANTITIES = {
    'price_gap': (1.0, 'percentage points', False, -6.0,
                  'The price-ending grid is REAL-calibrated; the size and spread of cross-platform gaps is assumed.'),
    'cheapest_share': (3.0, 'percentage points', False, None,
                       'Depends on how often prices tie, which the REAL-calibrated grid sets, and on assumed gaps.'),
    'oos_rate': (1.0, 'percentage points', False, None,
                 'The stock-out LEVEL is REAL-calibrated per category. How long a stock-out lasts is assumed, and real '
                 'stock-outs cluster by product (REAL), so the real answer needs more products than this says.'),
    'restock_mean': (0.2, 'snapshots', True, None, 'Assumed dynamics. A short panel cannot see long spells at all.'),
    'hazard_ratio': (1.5, 'ratio', True, None, 'Assumed dynamics (planted Weibull shape 2).'),
    'response_beta': (0.05, 'coefficient', True, 0.45,
                      'Assumed dynamics. The naive estimate is about half the planted value on rounded prices.'),
    'evening_eta': (0.5, 'minutes', True, 3.5, 'Assumed. Not estimable from one snapshot a day, whatever the size.'),
}


# --------------------------------------------------------------------------- the panel as arrays
def load_arrays() -> dict:
    raw = L.load_raw()
    c = raw[(raw.data_status == 'SYNTHETIC') & (raw.in_common_panel == 1)].copy()
    assert c.data_status.eq('SYNTHETIC').all()
    c['_ts'] = pd.to_datetime(c.observed_at.astype(str), format='mixed')
    c = c.sort_values(['platform', 'canonical_product_key', '_ts'])
    keys = np.sort(c.canonical_product_key.unique())
    times = np.sort(c._ts.unique())
    K, T = len(keys), len(times)
    out = {'keys': keys, 'times': times, 'first_observation_key': str(c.observation_key.iloc[0]),
           'evening': pd.DatetimeIndex(times).hour.to_numpy() >= 15}
    for name, col in (('price', 'selling_price'), ('stock', 'in_stock'), ('eta', 'delivery_eta_min')):
        mats = []
        for p in PLATFORMS:
            g = c[c.platform == p]
            assert len(g) == K * T and (g.canonical_product_key.to_numpy().reshape(K, T)[:, 0] == keys).all()
            mats.append(g[col].to_numpy(float).reshape(K, T))
        out[name] = np.stack(mats)                                   # (platform, product, snapshot)
    return out


# --------------------------------------------------------------------------- estimators on one cut
def estimate(P: np.ndarray, S: np.ndarray, E: np.ndarray, evening: np.ndarray, both_snapshots: bool) -> dict:
    """Every quantity on one cut. P, S, E are (platform, product, snapshot). NaN = cannot be estimated from this cut."""
    others = (P.sum(0) - P[FKM]) / 3.0
    out = {'price_gap': float(100 * np.median(P[FKM] / others - 1)),
           'cheapest_share': float(100 * (P[FKM] <= P.min(0)).mean()),
           'oos_rate': float(100 * (1 - S[BLK].mean())),
           'restock_mean': np.nan, 'hazard_ratio': np.nan, 'response_beta': np.nan, 'evening_eta': np.nan}
    T = P.shape[2]
    if not both_snapshots:
        return out
    ins = S.reshape(-1, T).astype(int)
    if T >= 3:
        lengths, _ = completed_oos_spells(ins)
        if len(lengths) >= MIN_SPELLS:
            out['restock_mean'] = float(lengths.mean())
        x = np.log(P) - np.log(P.mean(2, keepdims=True))
        y = x[INS][:, 1:].ravel()
        X = np.c_[np.ones(len(y)), x[INS][:, :-1].ravel(), x[BLK][:, :-1].ravel()]
        if np.linalg.matrix_rank(X) == 3:
            out['response_beta'] = float(np.linalg.lstsq(X, y, rcond=None)[0][2])
    if T >= 7:
        with np.errstate(invalid='ignore', divide='ignore'):
            h, n = run_length_hazard(ins, max_run=10)
        short, long_ = slice(0, 2), slice(4, 10)
        if n[short].sum() > 0 and n[long_].sum() >= 50:
            hs = np.nansum(h[short] * n[short]) / n[short].sum()
            hl = np.nansum(np.where(n[long_] > 0, h[long_], 0) * n[long_]) / n[long_].sum()
            if hs > 0:
                out['hazard_ratio'] = float(hl / hs)
    if evening.any() and (~evening).any():
        out['evening_eta'] = float(E[BLK][:, evening].mean() - E[BLK][:, ~evening].mean())
    return out


def cut(A: dict, days: int, skus: int, per_day: int, rng) -> dict:
    T = len(A['times'])
    start = int(rng.integers(0, T // 2 - days + 1))
    t = np.arange(2 * start, 2 * (start + days))
    if per_day == 1:
        t = t[~A['evening'][t]]
    k = rng.choice(len(A['keys']), size=skus, replace=False)
    ix = np.ix_(range(len(PLATFORMS)), k, t)
    return estimate(A['price'][ix], A['stock'][ix], A['eta'][ix], A['evening'][t], per_day == 2)


# --------------------------------------------------------------------------- the grid
def run_grid(A: dict, truth: dict, reps: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for per_day in PER_DAY:
        for days in DAYS:
            for skus in SKUS:
                est = pd.DataFrame([cut(A, days, skus, per_day, rng) for _ in range(reps)])
                for q, (tol, unit, needs_both, _, _) in QUANTITIES.items():
                    v = est[q].dropna()
                    ok = len(v) / reps
                    row = {'quantity': q, 'days': days, 'products': skus, 'snapshots_per_day': per_day,
                           'observations': days * per_day * len(PLATFORMS) * skus, 'cuts': reps,
                           'estimable_share': ok, 'estimable_by_design': not (needs_both and per_day == 1)}
                    if len(v) >= 0.5 * reps:
                        err = v - truth[q]
                        row.update(mean=float(v.mean()), bias=float(err.mean()), sd=float(v.std(ddof=1)),
                                   rmse=float(np.sqrt((err ** 2).mean())), p05=float(v.quantile(0.05)),
                                   p95=float(v.quantile(0.95)),
                                   half_width_90=float((v.quantile(0.95) - v.quantile(0.05)) / 2),
                                   within_tolerance_share=float((err.abs() <= tol).sum() / reps))
                    else:
                        row.update(mean=None, bias=None, sd=None, rmse=None, p05=None, p95=None, half_width_90=None,
                                   within_tolerance_share=0.0)
                    row['identified'] = bool(row['within_tolerance_share'] >= IDENTIFIED_SHARE)
                    rows.append(row)
    return pd.DataFrame(rows)


def smallest(grid: pd.DataFrame, q: str, products: int | None = None) -> dict | None:
    """The design that identifies q with the fewest observations (then the fewest days). A design counts only if every
    larger design with the same products and schedule identifies it too: one lucky cell is not a recommendation."""
    g = grid[grid.quantity == q]
    if products is not None:
        g = g[g.products == products]
    best = None
    for r in g[g.identified].sort_values(['observations', 'days']).itertuples():
        longer = g[(g.products == r.products) & (g.snapshots_per_day == r.snapshots_per_day) & (g.days >= r.days)]
        if longer.identified.all():
            best = r
            break
    if best is None:
        return None
    return {'days': int(best.days), 'products': int(best.products), 'snapshots_per_day': int(best.snapshots_per_day),
            'observations': int(best.observations), 'within_tolerance_share': float(best.within_tolerance_share),
            'hours_at_assumed_speed': round(best.observations * SECONDS_PER_OBSERVATION / 3600, 1)}


def same_product_clustering(A: dict) -> dict:
    """Does the generator make one product run out on several platforms at once? (REAL records of one product do.)"""
    out = A['stock'] == 0                                           # (platform, product, snapshot)
    n_out = out.sum(0)
    both = (n_out * (n_out - 1) / 2).sum()
    disc = (n_out * (len(PLATFORMS) - n_out)).sum()
    rate = float(out.mean())
    cond = float(2 * both / (2 * both + disc))
    return {'out_of_stock_rate': rate, 'p_other_platform_out_given_one_out': cond, 'lift_over_rate': cond / rate}


def run(save: bool = True, reps: int = REPS) -> dict:
    A = load_arrays()
    truth = estimate(A['price'], A['stock'], A['eta'], A['evening'], True)
    grid = run_grid(A, truth, reps, SEED)

    syn_cluster = same_product_clustering(A)
    real_cluster = None
    audit = MODELS_DIR / 'real_store_label_audit' / 'metrics.json'
    if audit.exists():
        s = json.loads(audit.read_text(encoding='utf-8'))['record_level_anatomy']['stock']
        real_cluster = {'out_of_stock_rate': s['out_of_stock_rate'],
                        'p_other_record_out_given_one_out': s['p_other_record_out_given_one_out'],
                        'lift_over_rate': s['lift_over_rate'], 'source': 'outputs/models/real_store_label_audit (REAL)'}

    quantities = {}
    for q, (tol, unit, needs_both, planted, transfer) in QUANTITIES.items():
        g = grid[grid.quantity == q]
        quantities[q] = {
            'full_panel_value': truth[q], 'planted_value': planted, 'tolerance': tol, 'unit': unit,
            'needs_both_daily_snapshots': needs_both,
            'smallest_identifying_design': smallest(grid, q),
            'smallest_with_the_watchlist': smallest(grid, q, WATCHLIST_SKUS),
            'identified_once_a_day': bool(g[(g.snapshots_per_day == 1)].identified.any()),
            'precision_with_the_watchlist_90pct_half_width': {
                int(r.days): (None if r.half_width_90 is None or pd.isna(r.half_width_90) else round(float(r.half_width_90), 3))
                for r in g[(g.products == WATCHLIST_SKUS) & (g.snapshots_per_day == 2)].itertuples()},
            'what_transfers_to_the_real_market': transfer}
    # bias a short window builds in, at the largest product count (so sampling noise is small)
    big = grid[(grid.products == max(SKUS)) & (grid.snapshots_per_day == 2)]
    short_bias = {q: {int(r.days): (None if r.bias is None or pd.isna(r.bias) else round(float(r.bias), 4))
                      for r in big[big.quantity == q].itertuples()}
                  for q in ('restock_mean', 'response_beta', 'hazard_ratio')}

    def menu(days, products, per_day):
        g = grid[(grid.days == days) & (grid.products == products) & (grid.snapshots_per_day == per_day)]
        obs = int(g.observations.iloc[0])
        return {'days': days, 'products': products, 'snapshots_per_day': per_day, 'observations': obs,
                'hours_at_assumed_speed': round(obs * SECONDS_PER_OBSERVATION / 3600, 1),
                'identifies': sorted(g.quantity[g.identified]),
                'does_not_identify': sorted(g.quantity[~g.identified])}

    plans = {'one_weekend_watchlist': menu(2, WATCHLIST_SKUS, 2), 'one_week_watchlist': menu(7, WATCHLIST_SKUS, 2),
             'two_weeks_watchlist': menu(14, WATCHLIST_SKUS, 2), 'full_month_watchlist': menu(30, WATCHLIST_SKUS, 2),
             'one_week_50_products': menu(7, 50, 2), 'two_weeks_morning_only_watchlist': menu(14, WATCHLIST_SKUS, 1),
             'two_weeks_25_products': menu(14, 25, 2), 'month_25_products_morning_only': menu(30, 25, 1)}
    never = sorted(q for q, v in quantities.items() if v['smallest_identifying_design'] is None)
    result = {
        'NOTE': 'SYNTHETIC-DERIVED planning prior: what a panel of each shape resolves if the real market is about as '
                'noisy as the generator. Not a market finding and not a guarantee.',
        'panel': {'products': int(len(A['keys'])), 'snapshots': int(len(A['times'])), 'platforms': PLATFORMS},
        'rule': f'a design identifies a quantity when at least {IDENTIFIED_SHARE:.0%} of {reps} random cuts land '
                'within its tolerance of the full-panel value, and every longer design of the same size does too',
        'assumed_seconds_per_observation': SECONDS_PER_OBSERVATION,
        'watchlist_products': WATCHLIST_SKUS,
        'quantities': quantities,
        'not_identified_by_any_design_tried': never,
        'bias_from_a_short_window_at_1000_products': short_bias,
        'plans': plans,
        'same_product_stock_clustering': {
            'SYNTHETIC_across_platforms': syn_cluster, 'REAL_across_records_of_one_name_pack': real_cluster,
            'reading': 'In the generated panel a product running out on one platform says almost nothing about the '
                       'others. In the REAL snapshot, records of the same product run out together. If that holds '
                       'across real platforms, extra platforms add less information about stock-outs than extra '
                       'products do, and the oos_rate sample sizes here are too optimistic.'},
    }
    show = {q: {'full_panel': round(v['full_panel_value'], 3), 'smallest': v['smallest_identifying_design'],
                'watchlist': v['smallest_with_the_watchlist']} for q, v in quantities.items()}
    print(json.dumps({'quantities': show, 'never_identified': never, 'plans': plans,
                      'short_window_bias': short_bias, 'clustering': {'synthetic': syn_cluster, 'real': real_cluster}},
                     indent=1, default=str))
    if not save:
        return result
    pred = grid.assign(observation_key=A['first_observation_key'], data_status='SYNTHETIC')
    training = pd.DataFrame({'data_status': ['SYNTHETIC'] * int(A['price'].size)})
    save_model_outputs(NAME, pred, {'days': DAYS, 'products': SKUS, 'snapshots_per_day': PER_DAY, 'cuts': reps,
                                    'seed': SEED, 'identified_share': IDENTIFIED_SHARE,
                                    'tolerances': {q: v[0] for q, v in QUANTITIES.items()},
                                    'seconds_per_observation_ASSUMED': SECONDS_PER_OBSERVATION},
                       result, training_data=training,
                       split={'fit': 'nothing (design study)', 'evaluated_on': 'random cuts of the SYNTHETIC common panel'},
                       target='precision of seven estimates as a function of panel size',
                       training_source='data/raw SYNTHETIC common-panel rows via src.load',
                       notes='Design study. Rows are (quantity, design) cells; observation_key is a placeholder (the '
                             'first common-panel row), as in simulate_grid. A planning prior, not a market finding.')
    return result


if __name__ == '__main__':
    run()
