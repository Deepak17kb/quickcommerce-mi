"""
listing.py — the product x store chain, in seven explicit stages:

    Observe -> Applicability -> Prediction record -> Price grid -> Simulation -> Optimization -> Explanation

    python -m src.chain.listing --demo                      # gallery: 6 "cut" listings + 3 where Blinkit is cheapest
    python -m src.chain.listing --product "frooti" --store BLK-BBSR-008

WHY THIS EXISTS
  Deliverables 2-13 were built and tested one by one. This runs the whole loop on ONE listing, so every layer has to
  agree with the next: one listing -> which models apply -> their saved predictions -> the prices Blinkit can actually
  post -> a simulation that is checked before it is used -> the smallest rupee cut -> an explanation where every
  statement carries a label. The record on disk has exactly these seven keys, in this order.

PROVENANCE (never blurred)
  REAL       the 2026-07-10 Blinkit row of the SAME product in the SAME store (context only: one snapshot has no history
             to predict from), its REAL anomaly score, and the stores where the product is a REAL assortment gap.
  SYNTHETIC  the listing's generated panel, every other prediction, every simulation and the optimisation.
  METHOD     the assumptions, stated in full in the record.

THE STAGES
  1 Observe            the Blinkit listing at the decision snapshot (the last test snapshot that still has a next one,
                       so every prediction sits next to what happened), the three competitors' prices, the REAL row.
  2 Applicability      models 1-10, each: applies or not, and why, checked against the saved outputs. 7 applies in
                       stock, 8 out of stock; 10 cannot apply to a product the store already lists; and so on.
  3 Prediction record  the saved predictions of every applicable model joined on observation_key.
  4 Price grid         the listing's grid (step, remainder) inferred from its OWN past prices only; the ladder is
                       every grid point from a 30% raise down to a 30% cut.
  5 Simulation         FIRST the baseline check: the status quo from the last validation snapshot over the 11 test
                       snapshots must cover the observed competitor prices and the observed cheapest share. Then every
                       rung for 12 snapshots, with competitors responding (deliverable 9, bootstrap draws) or not
                       (static). Stock-outs and ETA move only if the move goes through the discount: a promo cut
                       deepens it, a raise withdraws it (deliverables 7, 8, 5).
                       Cross-check: the chain's own stock projection against deliverable 7's saved forecast.
  6 Optimization       one target (mean cheapest-of-4 share over 12 snapshots, ties counting), two directions: below it
                       at the current price, the smallest cut that reaches it; at or above it, the largest RAISE that
                       keeps it (price headroom). Both views, with the promo cost or withdrawal gain. No recommendation
                       when the baseline check failed.
  7 Explanation        labelled claims, stage by stage, built only from stages 1-6 (the analyst's explain_listing).
"""
import argparse
import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

import src.features.stock_clock as SC
import src.load as L
from src import provenance
from src.model_output import MODELS_DIR, save_model_outputs
from src.models import price_response as PR
from src.simulate.engine import PLATFORMS, PriceWorld, StockWorld

NAME = 'listing_chain'
CHAIN_DIR = MODELS_DIR / NAME / 'chains'
PANEL = ['platform', 'store_id', 'product_id']
HORIZON = 12
N_SIMS = 400
N_STOCK = 4000
TARGET = 0.5
MAX_CUT = 0.30
MAX_RAISE = 0.30
SEED = 20260924
REAL_DATE = '2026-07-10'
ASSUMPTIONS = [
    'Blinkit posts the candidate price and holds it for the next 12 snapshots (6 days).',
    'Competitors respond to Blinkit\'s latent price with the fitted response of deliverable 9 (strategic view), or '
    'ignore the move (static view). Parameter uncertainty enters through the bootstrap draws.',
    'Cheapest-of-4 is decided per snapshot on the mean price of each platform\'s listings of the product; ties count.',
    'A list-price move leaves the discount unchanged. A move through the discount holds MRP, so a cut deepens the promo '
    'and a raise withdraws it: depth -> 1 - (1 - d0) x new price / current, clipped to [0, 0.6]. A listing with no '
    'promo can only raise its list price.',
    'Stock-outs and ETA move only through discount depth (deliverables 7, 8, 5); store demand pressure starts at its '
    'observed index and follows the fitted AR(1).',
    'Everything is under the fitted, generated dynamics. No demand, orders or revenue exist, so nothing here is about '
    'sales or profit.',
]


def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')[:80]


# =========================================================================== data
@lru_cache(maxsize=1)
def panel_rows():
    ml = SC.attach(L.load_ml())
    s = ml[ml.data_status == 'SYNTHETIC'].copy()
    s['_ts'] = pd.to_datetime(s.observed_at.astype(str), format='mixed')
    s = s.sort_values(PANEL + ['_ts'], kind='stable')
    s['pos'] = s.groupby(PANEL, sort=False).cumcount()
    real = ml[ml.data_status == 'REAL']
    return s, real


@lru_cache(maxsize=1)
def worlds():
    return PriceWorld.load(), StockWorld.load()


def candidates():
    """Blinkit common-panel listings whose product is on all four platforms and has a REAL row in the same store."""
    s, real = panel_rows()
    c = s[s.in_common_panel == 1]
    n_plat = c.groupby('canonical_product_key').platform.nunique()
    keys = set(n_plat[n_plat == 4].index)
    blk = c[(c.platform == 'Blinkit') & c.canonical_product_key.isin(keys)]
    lst = blk[['canonical_product_key', 'product_id', 'store_id', 'product_name', 'category']].drop_duplicates()
    r = real[['canonical_product_key', 'store_id']].drop_duplicates()
    return lst.merge(r, on=['canonical_product_key', 'store_id']).reset_index(drop=True)


def find_listing(product: str | None = None, store: str | None = None):
    """Best candidate for a free-text product and a store. Every query word must be in the name; among those, the
    name with the fewest extra words wins ("sugar" -> "... Sugar (5 kg)", not "Sugar Free Sweet Lassi" first by row)."""
    from src.analyst.kb import tokenize
    cand = candidates()
    if store:
        m = re.search(r'(\d{3})', store)
        if m:
            cand = cand[cand.store_id.str.endswith(m.group(1))]
    if product:
        q = set(tokenize(product))
        toks = cand.product_name.map(lambda n: set(tokenize(n)))
        cand = cand.assign(_extra=toks.map(len) - toks.map(lambda t: len(q & t)))[toks.map(lambda t: q <= t)]
        cand = cand.sort_values('_extra', kind='stable').drop(columns='_extra')
    if cand.empty:
        return None
    return cand.iloc[0].to_dict()


# =========================================================================== 1 observe
def observe(lst):
    s, real = panel_rows()
    key, store, pid = lst['canonical_product_key'], lst['store_id'], lst['product_id']
    rows = s[s.canonical_product_key == key]
    me = rows[(rows.platform == 'Blinkit') & (rows.product_id == pid) & (rows.store_id == store)].sort_values('pos')
    t_star = int(me.pos.max()) - 1                  # last snapshot that still has a next one
    now = me[me.pos == t_star].iloc[0]
    comp = rows[rows.pos == t_star].groupby('platform').selling_price.mean()
    promo = now.mrp_source == 'simulated_discounted'
    r = real[(real.canonical_product_key == key) & (real.store_id == store)]
    real_row = None
    if len(r):
        x = r.iloc[0]
        real_row = {'provenance': 'REAL', 'date': REAL_DATE, 'observation_key': x.observation_key,
                    'product_name': x.product_name, 'store_id': x.store_id, 'selling_price': float(x.selling_price),
                    'mrp': float(x.mrp), 'stock_status': x.stock_status, 'eta_min': int(x.delivery_eta_min),
                    'eta_max': int(x.delivery_eta_max), 'store_name': x.store_name,
                    # price and stock are verified against the source; that the row belongs to THIS store is not
                    'store_label': provenance.store_label_status()['status']}
    return {
        'listing': {'product_name': lst['product_name'], 'pack_size': now.pack_size, 'category': now.category,
                    'brand': now.brand, 'store_id': store, 'store_name': now.store_name, 'area': now.area,
                    'canonical_product_key': key, 'product_id': pid},
        'decision_snapshot': {'provenance': 'SYNTHETIC', 'observation_key': now.observation_key,
                              'observed_at': str(now.observed_at), 'pos': t_star, 'split': now.split,
                              'selling_price': float(now.selling_price), 'mrp': float(now.mrp),
                              'discount_pct': float(now.discount_percent), 'promo_listing': bool(promo),
                              'in_stock': int(now.in_stock), 'instock_run_length': float(now.instock_run_length),
                              'clock_censored': int(now.instock_clock_censored),
                              'eta_min': int(now.delivery_eta_min), 'hour': int(now.hour),
                              'store_pressure_index': None if pd.isna(now.store_pressure_index) else float(now.store_pressure_index),
                              'competitor_prices': {p: round(float(comp.get(p, np.nan)), 2) for p in PLATFORMS},
                              'cheapest_now': bool(now.selling_price <= comp.min() + 1e-9)},
        'real_observation': real_row,
        '_rows': me, '_t_star': t_star,
    }


# =========================================================================== 2 applicability
_PRED_CACHE = {}


def _preds(model):
    if model not in _PRED_CACHE:
        p = MODELS_DIR / model / 'predictions.parquet'
        _PRED_CACHE[model] = pd.read_parquet(p) if p.exists() else None
    return _PRED_CACHE[model]


def _pred(model, key, cols):
    d = _preds(model)
    if d is None:
        return None
    d = d[d.observation_key == key]
    return None if d.empty else d.iloc[0][[c for c in cols if c in d.columns]].to_dict()


# deliverable -> saved output that holds its per-observation prediction
SAVED = {'2_next_price': 'price_forecast_lgbm', '3_direction': 'price_direction', '4_stock_next': 'stockout_classifier',
         '5_eta_next': 'eta_forecast', '7_time_to_stockout': 'stockout_survival', '8_restock': 'restock_interval'}


def applicability(obs):
    """Stage 2: which of models 1-10 apply to THIS listing, and why. Checked against the saved outputs, never assumed."""
    d = obs['decision_snapshot']
    ok, in_stock = d['observation_key'], d['in_stock'] == 1
    real = obs['real_observation']
    out = {}
    out['1_product_matcher'] = {
        'applies': False, 'provenance': 'METHOD',
        'why': 'the generated panel carries the cross-platform key, and the REAL row is joined on canonical_product_key '
               '+ store_id; the matcher\'s real-name-variation tier is not measurable yet (no human labels)'}
    for k in ('2_next_price', '3_direction', '4_stock_next', '5_eta_next'):
        has = _pred(SAVED[k], ok, ['observation_key']) is not None
        out[k] = {'applies': has, 'model': SAVED[k], 'provenance': 'SYNTHETIC',
                  'why': 'a saved test-split prediction exists for the decision snapshot' if has
                  else 'no saved test-split prediction for the decision snapshot'}
    has_r = real is not None and _pred('anomaly_real', real['observation_key'], ['observation_key']) is not None
    has_t = _pred('anomaly_temporal', ok, ['observation_key']) is not None
    out['6_anomaly'] = {'applies': has_r or has_t, 'models': ['anomaly_real', 'anomaly_temporal'],
                        'provenance': 'REAL + SYNTHETIC',
                        'why': ('the REAL detector scores the REAL 2026-07-10 row' if has_r else 'no REAL row scored')
                        + '; ' + ('the temporal detector scores the decision snapshot' if has_t
                                  else 'the temporal detector did not score the decision snapshot')}
    k7, k8 = '7_time_to_stockout', '8_restock'
    has7 = in_stock and _pred(SAVED[k7], ok, ['observation_key']) is not None
    has8 = (not in_stock) and _pred(SAVED[k8], ok, ['observation_key']) is not None
    out[k7] = {'applies': has7, 'model': SAVED[k7], 'provenance': 'SYNTHETIC',
               'why': 'in stock now, so the time to the next stock-out is the question' if has7 else
               ('out of stock now: the time to stock-out does not apply' if not in_stock
                else 'no saved prediction for the decision snapshot')}
    out[k8] = {'applies': has8, 'model': SAVED[k8], 'provenance': 'SYNTHETIC',
               'why': 'out of stock now, so the time until it is back is the question' if has8 else
               ('in stock now: restock time applies only to an outage' if in_stock
                else 'no saved prediction for the decision snapshot')}
    out['9_competitor_response'] = {
        'applies': True, 'model': 'price_response', 'provenance': 'SYNTHETIC',
        'why': 'Blinkit is the fitted leader and this product is on all four platforms, so the fitted follower '
               'response says how competitors move after a Blinkit price change'}
    gaps = _preds('assortment_gaps')
    elsewhere = [] if gaps is None else sorted(
        gaps[gaps.canonical_product_key == obs['listing']['canonical_product_key']].store_id.unique().tolist())
    out['10_assortment_gap'] = {
        'applies': False, 'model': 'assortment_gaps', 'provenance': 'REAL',
        'why': 'the product is in this store\'s REAL 2026-07-10 listing, so it cannot be a gap here',
        'recommended_as_gap_in': elsewhere}
    return out


# =========================================================================== 3 prediction record
def prediction_record(obs, app):
    """Stage 3: one row per applicable model, its prediction next to what actually happened. Skipped models say why."""
    ok = obs['decision_snapshot']['observation_key']
    rec = {}

    def skip(k):
        return {'applies': False, 'why': app[k]['why']}

    if app['2_next_price']['applies']:
        p = _pred(SAVED['2_next_price'], ok, ['prediction', 'actual_future_price', 'baseline_naive'])
        rec['2_next_price'] = {'provenance': 'SYNTHETIC', 'predicted': round(float(p['prediction']), 2),
                               'actual_next': float(p['actual_future_price']), 'naive': float(p['baseline_naive'])}
    else:
        rec['2_next_price'] = skip('2_next_price')
    if app['3_direction']['applies']:
        p = _pred(SAVED['3_direction'], ok, ['p_down', 'p_flat', 'p_up', 'prediction', 'actual_direction'])
        rec['3_direction'] = {'provenance': 'SYNTHETIC', 'p_down': round(float(p['p_down']), 3),
                              'p_flat': round(float(p['p_flat']), 3), 'p_up': round(float(p['p_up']), 3),
                              'predicted': p['prediction'], 'actual': p['actual_direction']}
    else:
        rec['3_direction'] = skip('3_direction')
    if app['4_stock_next']['applies']:
        p = _pred(SAVED['4_stock_next'], ok, ['prediction', 'p_stockout_next', 'actual_future_stock'])
        rec['4_stock_next'] = {'provenance': 'SYNTHETIC', 'p_in_stock_next': round(float(p['prediction']), 4),
                               'p_stockout_next': None if pd.isna(p.get('p_stockout_next'))
                               else round(float(p['p_stockout_next']), 4),
                               'actual_in_stock_next': int(p['actual_future_stock'])}
    else:
        rec['4_stock_next'] = skip('4_stock_next')
    if app['5_eta_next']['applies']:
        p = _pred(SAVED['5_eta_next'], ok, ['prediction', 'lower_90', 'upper_90', 'promise_eta_90', 'actual_future_eta'])
        rec['5_eta_next'] = {'provenance': 'SYNTHETIC', 'predicted_min': round(float(p['prediction']), 2),
                             'interval_90': [round(float(p['lower_90']), 2), round(float(p['upper_90']), 2)],
                             'promise_min': float(p['promise_eta_90']), 'actual_next_min': float(p['actual_future_eta'])}
    else:
        rec['5_eta_next'] = skip('5_eta_next')
    if app['6_anomaly']['applies']:
        a = {}
        real = obs['real_observation']
        if real is not None:
            r = _pred('anomaly_real', real['observation_key'], ['prediction', 'flag_unusual', 'reason'])
            if r:
                a['real_row'] = {'provenance': 'REAL', 'score': round(float(r['prediction']), 3),
                                 'flag_unusual': bool(r['flag_unusual']), 'reason': r['reason'] or 'none'}
        t = _pred('anomaly_temporal', ok, ['prediction', 'is_injected'])
        if t:
            a['decision_snapshot'] = {'provenance': 'SYNTHETIC', 'score': round(float(t['prediction']), 3),
                                      'threshold': 5, 'flagged': bool(t['prediction'] > 5),
                                      'is_injected_test_anomaly': bool(t['is_injected'])}
        a['meaning'] = 'a flag means unusual within its snapshot or history, never an error or a deal'
        rec['6_anomaly'] = a
    else:
        rec['6_anomaly'] = skip('6_anomaly')
    if app['7_time_to_stockout']['applies']:
        p = _pred(SAVED['7_time_to_stockout'], ok, ['p_oos_within_1', 'p_oos_within_2', 'p_oos_within_4', 'p_oos_within_6',
                                                    'actual_oos_within_1', 'clock_started_before_panel'])
        rec['7_time_to_stockout'] = {'provenance': 'SYNTHETIC',
                                     **{k: round(float(v), 4) for k, v in p.items() if k.startswith('p_')},
                                     'actual_oos_within_1': None if pd.isna(p.get('actual_oos_within_1'))
                                     else int(p['actual_oos_within_1']),
                                     'clock_started_before_panel': int(p['clock_started_before_panel'])}
    else:
        rec['7_time_to_stockout'] = skip('7_time_to_stockout')
    if app['8_restock']['applies']:
        p = _pred(SAVED['8_restock'], ok, ['p_back_within_1', 'p_back_within_2', 'p_back_within_4', 'back_by',
                                           'expected_remaining_snapshots'])
        rec['8_restock'] = {'provenance': 'SYNTHETIC', **{k: (round(float(v), 4) if isinstance(v, (float, np.floating))
                                                               else v) for k, v in p.items()}}
    else:
        rec['8_restock'] = skip('8_restock')
    m9 = json.loads((MODELS_DIR / 'price_response' / 'metrics.json').read_text(encoding='utf-8'))
    rec['9_competitor_response'] = {
        'provenance': 'SYNTHETIC',
        'followers': {r['follower']: {'beta': round(r['corrected_beta'], 3), 'lag_snapshots': r['lag'],
                                      'ci': [round(v, 3) for v in r['corrected_ci']]} for r in m9['response_recovery']}}
    rec['10_assortment_gap'] = skip('10_assortment_gap')
    return rec


# =========================================================================== price simulator
def _grid_round(P, step, rem):
    out = np.round((P - rem) / step) * step + rem
    return np.where(out < 1, np.maximum(np.round(P), 1), out)


class ProductSim:
    """Latent-price simulator for ONE product (its four platforms' listings), started from observed prices."""

    def __init__(self, obs):
        PW, _ = worlds()
        self.PW = PW
        s, _ = panel_rows()
        key = obs['listing']['canonical_product_key']
        kidx = PW.keys.index(key)
        pan = PW.pan[PW.pan.k == kidx].reset_index(drop=True)
        self.pan = pan
        me = pan[(pan.platform == 'Blinkit') & (pan.store_id == obs['listing']['store_id'])
                 & (pan.product_id == obs['listing']['product_id'])]
        if me.empty:
            raise ValueError('listing is not in the common-panel price world')
        self.lead = int(me.index[0])
        rows = s[s.canonical_product_key == key]
        self.obs_price = rows.pivot_table(index=['platform', 'store_id', 'product_id'], columns='pos',
                                          values='selling_price')
        self.plat = pan.platform.to_numpy()
        self.lag = np.array([PR.PLANTED['lag'].get(p, 1) for p in self.plat])

    def observed(self, t):
        idx = pd.MultiIndex.from_frame(self.pan[PANEL])
        return self.obs_price.reindex(idx)[t].to_numpy(float)

    def platform_price(self, prices):
        """(sims, panels) -> (sims, 4) mean price per platform."""
        out = np.full((prices.shape[0], 4), np.nan)
        for j, p in enumerate(PLATFORMS):
            m = self.plat == p
            if m.any():
                out[:, j] = prices[:, m].mean(1)
        return out

    def run(self, start_t, horizon, post_price=None, respond=True, n_sims=N_SIMS, seed=SEED):
        """post_price None = status quo (Blinkit follows its own fitted AR). Returns prices (sims, horizon, 4)."""
        rng = np.random.default_rng(seed)
        pan, n = self.pan, len(self.pan)
        level = pan.level.to_numpy()
        step, rem = pan.step.to_numpy(), pan.rem.to_numpy()
        p_now = self.observed(start_t)
        p_prev = self.observed(start_t - 1)
        y0 = np.log(p_now / level)
        yl_prev = np.log(p_prev[self.lead] / level[self.lead])
        boot = self.PW.boot
        draws = boot.iloc[rng.integers(len(boot), size=n_sims)].to_dict('records') if len(boot) else [self.PW.theta] * n_sims
        rho = np.array([[d[f'rho[{p}]'] for p in self.plat] for d in draws])
        sig = np.array([[d[f'sigma[{p}]'] for p in self.plat] for d in draws])
        beta = np.array([[d.get(f'beta[{p}]', 0.0) for p in self.plat] for d in draws])
        y = np.tile(y0, (n_sims, 1))
        lead_hist = [np.full(n_sims, yl_prev), y[:, self.lead].copy()]         # t-1, t  (status-quo leader path)
        post_x = None if post_price is None else np.log(post_price / level[self.lead])
        prices = np.zeros((n_sims, horizon, n))
        is_lead = np.arange(n) == self.lead
        for h in range(horizon):
            eps = rng.standard_normal((n_sims, n))
            yl_sq = rho[:, self.lead] * lead_hist[-1] + sig[:, self.lead] * eps[:, self.lead]
            lead_hist.append(yl_sq)
            # what each follower sees of the leader at its lag
            ref = np.zeros((n_sims, n))
            for i in range(n):
                if is_lead[i]:
                    continue
                sq = lead_hist[-1 - self.lag[i]]                              # status-quo leader at t+h+1-lag
                if post_price is not None and respond:
                    # the price is posted at t+1; a follower at t+h+1 sees the leader at t+h+1-lag, which is the
                    # posted price once h >= lag and the pre-decision history before that
                    ref[:, i] = post_x if h - self.lag[i] >= 0 else sq
                else:
                    ref[:, i] = sq
            y_new = rho * y + beta * (ref - y) + sig * eps
            y_new[:, self.lead] = yl_sq
            y = y_new
            w = np.stack([rng.normal(0, self.PW.wave_sd[p], n_sims) for p in self.plat], 1)
            pr = _grid_round(level * np.exp(y + w), step, rem)
            if post_price is not None:
                pr[:, self.lead] = post_price
            prices[:, h] = pr
        return prices

    def summarise(self, prices):
        pp = np.stack([self.platform_price(prices[:, h]) for h in range(prices.shape[1])], 1)   # (sims, h, 4)
        blk = pp[:, :, 0]
        others = np.nanmin(pp[:, :, 1:], 2)
        cheapest = blk <= others + 1e-9
        share = cheapest.mean(1)
        return {'mean_cheapest_share': float(share.mean()),
                'band_90': [float(np.quantile(share, 0.05)), float(np.quantile(share, 0.95))],
                'p_cheapest_next': float(cheapest[:, 0].mean()),
                'p_cheapest_by_snapshot': cheapest.mean(0).round(4).tolist(),
                'competitor_median_price_end': {p: float(np.nanmedian(pp[:, -1, j])) for j, p in enumerate(PLATFORMS) if j},
                'competitor_median_path': {p: np.nanmedian(pp[:, :, j], 0).round(2).tolist() for j, p in enumerate(PLATFORMS) if j}}


def validate(sim, t_star):
    """Stage 5a, before any what-if: the status quo from the last validation snapshot over the test snapshots.

    Passes when (a) every platform has >= 70% of its observed prices inside the simulated 90% band, and (b) the observed
    Blinkit cheapest-of-4 share lies inside the simulated 2.5-97.5% range, ends included. (b) used to be a percentile test
    that failed whenever observed and simulated shares were all 0: a degenerate tie is agreement, not a miss.
    """
    start = t_star - 11
    horizon = t_star - start
    prices = sim.run(start, horizon, post_price=None, respond=True, seed=SEED + 1)
    pp = np.stack([sim.platform_price(prices[:, h]) for h in range(horizon)], 1)
    obs = np.stack([sim.platform_price(sim.observed(start + 1 + h)[None, :])[0] for h in range(horizon)], 0)  # (h, 4)
    lo, hi = np.nanquantile(pp, 0.05, axis=0), np.nanquantile(pp, 0.95, axis=0)
    inside = (obs >= lo - 1e-9) & (obs <= hi + 1e-9)
    cov = {p: float(inside[:, j].mean()) for j, p in enumerate(PLATFORMS)}
    obs_cheap = float((obs[:, 0] <= np.nanmin(obs[:, 1:], 1) + 1e-9).mean())
    sim_cheap = (pp[:, :, 0] <= np.nanmin(pp[:, :, 1:], 2) + 1e-9).mean(1)
    r_lo, r_hi = (float(v) for v in np.quantile(sim_cheap, [0.025, 0.975]))
    mid_rank = float((sim_cheap < obs_cheap - 1e-9).mean() + 0.5 * (np.abs(sim_cheap - obs_cheap) <= 1e-9).mean())
    prices_ok = all(v >= 0.7 for v in cov.values())
    share_ok = r_lo - 1e-9 <= obs_cheap <= r_hi + 1e-9
    return {'provenance': 'SYNTHETIC', 'start_pos': start, 'snapshots_checked': horizon,
            'coverage_of_observed_prices_by_90pct_band': cov, 'prices_ok': bool(prices_ok),
            'observed_blinkit_cheapest_share': obs_cheap,
            'simulated_share_95_range': [r_lo, r_hi], 'observed_share_mid_rank': mid_rank, 'share_ok': bool(share_ok),
            'passed': bool(prices_ok and share_ok),
            'rule': 'every platform >= 70% of observed prices inside the 90% band, and the observed cheapest share '
                    'inside the simulated 2.5-97.5% range (ends included)'}


# =========================================================================== 4 price grid
def price_grid(obs, sim):
    """Stage 4: the rupee prices Blinkit can actually post, read off this listing's own past prices.

    The grid (step, remainder) is inferred from the listing's prices up to and including the decision snapshot, so the
    ladder uses nothing from the future. Every grid point up to a 30% raise, the hold, and every grid point down to a
    30% cut (a Rs 1 grid is thinned to about 13 rungs each way; a grid coarser than 30% still gets one rung each way).
    """
    me = obs['_rows']
    past = me[me.pos <= obs['_t_star']].selling_price.to_numpy(float)
    step, rem = PR.infer_grid(past)
    world_step, world_rem = int(sim.pan.step[sim.lead]), int(sim.pan.rem[sim.lead])
    now = obs['decision_snapshot']['selling_price']
    floor, ceiling = now * (1 - MAX_CUT), now * (1 + MAX_RAISE)
    ups, p = [], now + step
    while p <= ceiling:
        ups.append(p)
        p += step
    downs, p = [], now - step
    while p >= max(floor, 1):
        downs.append(p)
        p -= step
    ups = ups or [now + step]                                                 # a grid coarser than 30%: one rung
    downs = downs or ([now - step] if now - step >= 1 else [])

    def thin(xs):                                                             # a Rs 1 grid: ~13 rungs each way
        if step > 1 or len(xs) <= 13:
            return xs
        return [xs[i] for i in np.unique(np.linspace(0, len(xs) - 1, 13).round().astype(int))]
    ups, downs = sorted(thin(ups), reverse=True), thin(downs)
    rungs = []
    for x in ups + [now] + downs:
        rungs.append({'price': float(x), 'kind': 'increase' if x > now else 'hold' if x == now else 'cut',
                      'cut_rs': round(now - x, 2), 'cut_pct': round(100 * (1 - x / now), 2),
                      'move_pct': round(100 * (x / now - 1), 2)})
    comp = (sim.pan.assign(grid=sim.pan.step.astype(int).astype(str) + '/' + sim.pan.rem.astype(int).astype(str))
            .groupby('platform').grid.agg(lambda g: sorted(set(g))).to_dict())
    return {'provenance': 'SYNTHETIC', 'step': int(step), 'remainder': int(rem),
            'inferred_from': f'{len(past)} past prices of this listing ({len(np.unique(past))} distinct), '
                             'up to and including the decision snapshot',
            'agrees_with_price_world_grid': bool((step, rem) == (world_step, world_rem)),
            'max_cut': MAX_CUT, 'floor_price': round(min([floor] + downs), 2), 'max_raise': MAX_RAISE,
            'ceiling_price': round(max(ceiling, max(ups)), 2),
            'competitor_grids_step_remainder': comp, 'rungs': rungs}


# =========================================================================== stock + ETA for this listing
def _expected_clock(W, row, depth):
    if not row['clock_censored']:
        return max(row['instock_run_length'], 1.0)
    st = pd.DataFrame({'category': [row['category']], 'platform': ['Blinkit']})
    c, p = W._codes(st)
    e = np.exp(W.a_haz[c] + W.b_haz[p] + 0.5 * W.g_eve + np.log1p(W.d_promo * depth))[0]
    ages = np.arange(0, 121, dtype=float)
    clock = ages + row['instock_run_length']
    w = np.exp(-e * (clock - 1) ** W.k)
    return float((w * clock).sum() / w.sum())


def stock_projection(obs, depth, horizon=HORIZON, n=N_STOCK, seed=SEED):
    _, W = worlds()
    d = obs['decision_snapshot']
    row = {'category': obs['listing']['category'], 'clock_censored': d['clock_censored'],
           'instock_run_length': d['instock_run_length']}
    st = pd.DataFrame({'category': [row['category']] * n, 'platform': ['Blinkit'] * n})
    rng = np.random.default_rng(seed)
    z = rng.standard_normal(n)
    ins = np.full(n, d['in_stock'])
    clock = np.full(n, _expected_clock(W, row, depth)) if d['in_stock'] else np.ones(n)
    mu = W.restock_mu(st.iloc[:1])[0]
    remaining = np.where(ins == 0, np.maximum(np.round(mu), 1), 0)
    D = np.full(n, d['store_pressure_index'] or 0.0)
    eve = float(d['hour'] == 9)                                             # the next snapshot after 09:00 is 18:00
    first_out = np.full(n, horizon + 1)
    out_count = np.zeros(n)
    for t in range(horizon):
        D = W.phi * D + np.sqrt(1 - W.phi ** 2) * rng.standard_normal(n)
        h = W.hazard(st, clock, np.full(n, eve), np.full(n, depth), np.clip(D, -4, 4), z)
        goes = (ins == 1) & (rng.random(n) < h)
        remaining = np.where(ins == 0, remaining - 1, remaining)
        back = (ins == 0) & (remaining <= 0)
        dur = W.draw_duration(rng, np.full(n, mu))
        remaining = np.where(goes, dur, remaining)
        new = np.where(ins == 1, ~goes, back).astype(int)
        clock = np.where((new == 1) & (ins == 1), clock + 1, np.where(new == 1, 1, clock))
        ins = new
        first_out = np.where((ins == 0) & (first_out > horizon), t + 1, first_out)
        out_count += (1 - ins)
        eve = 1 - eve
    return {'p_oos_within': {h: float((first_out <= h).mean()) for h in (1, 2, 4, 6, 12)},
            'expected_oos_snapshots_in_12': float(out_count.mean())}


# =========================================================================== 5 simulation
def simulation(obs, grid, sim):
    """Stage 5: baseline check FIRST, then every rung of the ladder in both views, then its stock/ETA effect when the
    move goes through the discount (a cut deepens the promo, a raise withdraws it)."""
    d = obs['decision_snapshot']
    val = validate(sim, obs['_t_star'])
    _, W = worlds()
    d0 = d['discount_pct'] / 100.0 if d['promo_listing'] else 0.0
    base_stock = stock_projection(obs, d0)
    status_quo = sim.summarise(sim.run(obs['_t_star'], HORIZON, post_price=None))
    ladder = []
    for g in grid['rungs']:
        p = g['price']
        row = dict(g)
        for view, resp in (('strategic', True), ('static', False)):
            row[view] = sim.summarise(sim.run(obs['_t_star'], HORIZON, post_price=p, respond=resp))
        new_depth = float(np.clip(1 - (1 - d0) * p / d['selling_price'], 0.0, 0.6)) if p != d['selling_price'] else d0
        promo = stock_projection(obs, new_depth) if abs(new_depth - d0) > 1e-9 else base_stock
        mode = 'deepen' if new_depth > d0 + 1e-9 else 'withdraw' if new_depth < d0 - 1e-9 else 'none'
        row['promo'] = {'mode': mode, 'depth_before': round(d0, 4), 'depth_after': round(new_depth, 4),
                        'p_oos_within_12': promo['p_oos_within'][12],
                        'extra_p_oos_within_12_pp': round(100 * (promo['p_oos_within'][12] - base_stock['p_oos_within'][12]), 2),
                        'expected_oos_snapshots_in_12': promo['expected_oos_snapshots_in_12'],
                        'eta_added_min': round(W.eta['b_discount'] * (new_depth - d0), 3)}
        ladder.append(row)
    s7 = obs.get('_p7') or {}
    xcheck = None
    if s7.get('provenance'):
        xcheck = {'model_7_p_oos_within_2': s7.get('p_oos_within_2'), 'chain_p_oos_within_2': base_stock['p_oos_within'][2],
                  'model_7_p_oos_within_6': s7.get('p_oos_within_6'), 'chain_p_oos_within_6': base_stock['p_oos_within'][6],
                  'note': 'two routes through the fitted stock models for the same listing: the saved dynamic forecast '
                          'of deliverable 7, and this chain\'s own projection at the current price'}
    return {'provenance': 'SYNTHETIC', 'horizon_snapshots': HORIZON, 'n_sims': N_SIMS, 'band': 90,
            'baseline_check': val, 'trusted': val['passed'], 'status_quo': status_quo, 'ladder': ladder,
            'current_stock_projection': base_stock, 'cross_check_stock': xcheck,
            'scenario_unavailable': unavailable_scenario(obs, sim)}


# =========================================================================== 5b the product-unavailable scenario
def unavailable_scenario(obs, sim, n=N_SIMS):
    """If THIS listing went out of stock now: how long (deliverable 8), what it costs in cheapest-available-of-4 wins over
    the next 12 snapshots, who picks them up, and what restoring it sooner is worth. Status-quo prices (deliverable 9)
    paired with the stock world (7, 8) started at the decision snapshot for all of the product's listings."""
    from src.optimize.restock_priority import priority_scores
    s, _ = panel_rows()
    _, W = worlds()
    L_ = obs['listing']
    rows = s[(s.canonical_product_key == L_['canonical_product_key']) & (s.pos == obs['_t_star'])]
    st = W.state_from_rows(rows)
    me = ((rows.platform == 'Blinkit') & (rows.store_id == L_['store_id'])
          & (rows.product_id == L_['product_id'])).to_numpy()
    plat = st.platform.to_numpy()
    prices = sim.run(obs['_t_star'], HORIZON, post_price=None, respond=True, n_sims=n, seed=SEED + 2)
    pp = np.stack([sim.platform_price(prices[:, h]) for h in range(HORIZON)], 1)       # (sims, h, 4)

    def run(outage):
        S = W.simulate(st, horizon=HORIZON, n_sims=n, seed=SEED + 3, outage=outage, return_states=True)['in_stock_path']
        av = np.zeros((n, HORIZON, 4), bool)
        av[:, :, 0] = S[:, :, me].max(2) > 0                            # Blinkit = THIS store's listing
        for j, pl in enumerate(PLATFORMS[1:], 1):
            m = plat == pl
            av[:, :, j] = S[:, :, m].max(2) > 0 if m.any() else False
        P = np.where(av, pp, np.inf)
        mn = P.min(2)
        win = (P <= mn[:, :, None] + 1e-9) & np.isfinite(P)
        return win.mean(1), S[:, :, me].mean((1, 2))                    # (sims, 4) share, (sims,) in-stock share

    base, base_in = run(None)
    runs = {'drawn': {'mask': me, 'length': None}, 'restored_now': {'mask': me, 'length': 0},
            'out_2_snapshots': {'mask': me, 'length': 2}}
    out = {}
    for k, o in runs.items():
        w, i_ = run(o)
        d = 100 * (w - base)
        out[k] = {'blinkit_change_pp': round(float(d[:, 0].mean()), 2),
                  'band_90_pp': [round(float(np.quantile(d[:, 0], 0.05)), 2), round(float(np.quantile(d[:, 0], 0.95)), 2)],
                  'inherits_pp': {pl: round(float(d[:, j].mean()), 2) for j, pl in enumerate(PLATFORMS) if j},
                  'listing_in_stock_share': round(float(i_.mean()), 4)}
    mu = float(W.restock_mu(st[me])[0])
    from scipy.stats import nbinom
    m_ = max(mu - 1, 1e-6); nn = W.n_rst; pr = nn / (nn + m_)
    # P(D <= h): back within h. String keys, so the record reads the same before and after a JSON round trip
    back = {str(h): round(float(nbinom.cdf(h - 1, nn, pr)), 4) for h in (1, 2, 4)}
    state = {'in_stock': np.zeros(1, int), 'clock': np.ones(1), 'elapsed': np.ones(1), 'st': st[me].reset_index(drop=True),
             'world': W, 'depth': st[me].depth.to_numpy(), 't': 0, 'horizon': HORIZON}
    return {'provenance': 'SYNTHETIC', 'n_sims': n, 'horizon_snapshots': HORIZON,
            'cheapest_available_share_now': round(float(base[:, 0].mean()), 4),
            'listing_in_stock_share_now': round(float(base_in.mean()), 4),
            'expected_spell_snapshots': round(mu, 3), 'p_back_within': back,
            'expedite_priority_index': round(float(priority_scores(state)[0]), 3),
            'scenarios': out,
            'meaning': ('drawn = an outage of the length the fitted restock model draws; restored_now = back before the '
                        'next snapshot (the value of expediting); cheapest-available = in stock and cheapest of the four')}


# =========================================================================== 6 optimization
def optimization(obs, simres, target=TARGET):
    """Stage 6, one target, two directions. Below the target at the current price: the smallest rupee cut that reaches
    it. At or above it: the largest rupee RAISE that still meets it (the listing's price headroom). Both are judged on
    posted prices (the hold rung), not on the status quo, where Blinkit's own price keeps drifting."""
    now = obs['decision_snapshot']['selling_price']
    rungs = simres['ladder']
    hold = next(r for r in rungs if r['kind'] == 'hold')

    def best_raise(view):
        ok = [r for r in rungs if r['price'] >= now and r['move_pct'] <= 100 * MAX_RAISE + 1e-9
              and r[view]['mean_cheapest_share'] >= target]
        if not ok:
            return {'target_met_at_current_price': False}
        r = max(ok, key=lambda r: r['price'])
        return {'target_met_at_current_price': True, 'price': r['price'], 'raise_rs': round(r['price'] - now, 2),
                'raise_pct': r['move_pct'], 'mean_cheapest_share': r[view]['mean_cheapest_share'],
                'band_90': r[view]['band_90'], 'at_ceiling': r['price'] == max(x['price'] for x in rungs),
                'withdraw_mode': r['promo']['mode'],
                'withdraw_p_oos_within_12_change_pp': r['promo']['extra_p_oos_within_12_pp'],
                'withdraw_eta_change_min': r['promo']['eta_added_min']}

    def best(view):
        # a single-step rung beyond 30% (a grid coarser than the limit) is shown on the ladder but never recommended
        ok = [r for r in rungs if r['price'] <= now and r['cut_pct'] <= 100 * MAX_CUT + 1e-9
              and r[view]['mean_cheapest_share'] >= target]
        if not ok:
            return {'reachable_within_30pct': False}
        r = max(ok, key=lambda r: r['price'])
        return {'reachable_within_30pct': True, 'price': r['price'], 'cut_rs': r['cut_rs'], 'cut_pct': r['cut_pct'],
                'mean_cheapest_share': r[view]['mean_cheapest_share'], 'band_90': r[view]['band_90'],
                'promo_extra_p_oos_within_12_pp': r['promo']['extra_p_oos_within_12_pp'],
                'promo_eta_added_min': r['promo']['eta_added_min']}
    strat, stat = best('strategic'), best('static')
    r_strat, r_stat = best_raise('strategic'), best_raise('static')
    already = hold['strategic']['mean_cheapest_share'] >= target
    if not simres['trusted']:
        verdict = 'baseline check failed: the ladder is shown, but no move is recommended from it'
    elif already and r_strat['price'] > now:
        verdict = (f"no cut needed: holding at Rs {now:g} already meets the target, and a raise of up to Rs "
                   f"{r_strat['raise_rs']:g} still does with competitors responding"
                   + (f" (Rs {r_stat['raise_rs']:g} if they did not: ignoring the response understates the headroom)"
                      if r_stat.get('target_met_at_current_price') and r_stat['price'] < r_strat['price'] else ''))
    elif already:
        verdict = f"hold: Rs {now:g} meets the target, but no raise on the grid does"
    elif strat['reachable_within_30pct'] and stat['reachable_within_30pct'] and strat['price'] < stat['price']:
        verdict = (f"cut to the strategic optimum; competitor response makes the needed cut deeper than the static "
                   f"figure (Rs {strat['cut_rs']:g} vs Rs {stat['cut_rs']:g})")
    elif strat['reachable_within_30pct']:
        verdict = 'cut to the strategic optimum; the same rung meets the target whether or not competitors respond'
    else:
        verdict = 'the target is out of reach within a 30% cut once competitors respond'
    return {'provenance': 'SYNTHETIC', 'target': target, 'horizon_snapshots': HORIZON, 'max_cut': MAX_CUT,
            'max_raise': MAX_RAISE, 'direction': 'raise' if already else 'cut',
            'objective': f'mean cheapest-of-4 share >= {target:.0%} over the next {HORIZON} snapshots, ties counting '
                         'as cheapest: the smallest cut that reaches it, or the largest raise that keeps it',
            'hold_mean_cheapest_share': hold['strategic']['mean_cheapest_share'],
            'raise': {'strategic': r_strat, 'static': r_stat},
            'status_quo_mean_cheapest_share': simres['status_quo']['mean_cheapest_share'],
            'status_quo_band_90': simres['status_quo']['band_90'],
            'strategic': strat, 'static': stat, 'verdict': verdict,
            'if_unavailable': _if_unavailable(simres)}


def _if_unavailable(simres):
    u = simres.get('scenario_unavailable')
    if not u:
        return None
    gain = u['scenarios']['restored_now']['blinkit_change_pp'] - u['scenarios']['drawn']['blinkit_change_pp']
    return {'action': 'expedite restock' if gain > 0.5 else 'no urgency: it usually comes back on its own quickly',
            'cheapest_available_pp_recovered_by_expediting': round(gain, 2),
            'expedite_priority_index': u['expedite_priority_index'],
            'rule': 'expedite when restoring now recovers more than 0.5 pp of cheapest-available share over 12 snapshots'}


# =========================================================================== 7 explanation
def _span(a, b):
    return f'{a}' if a == b else f'{a}-{b}'


def explain(rec, source_file):
    """Stage 7: labelled claims, one stage after another, built only from stages 1-6 of the record."""
    O, A, P, G, S, Z = (rec[k] for k in STAGES[:6])
    L_, d = O['listing'], O['decision_snapshot']
    name = f"{L_['product_name']} ({L_['pack_size']}) at {L_['store_name']} ({L_['store_id']})"
    out = []

    def add(stage, prov, text, src=source_file, detail=None, date=None):
        c = {'stage': stage, 'provenance': prov, 'source_file': src, 'text': text}
        if detail:
            c['source_detail'] = detail
        if date:
            c['date'] = date
        out.append(c)

    # 1 observe
    ro = O.get('real_observation')
    if ro:
        add('1_observe', 'REAL',
            f"On 2026-07-10 (REAL), {name} was listed at Rs {ro['selling_price']:g} (MRP Rs {ro['mrp']:g}), "
            f"{ro['stock_status']}, ETA {_span(ro['eta_min'], ro['eta_max'])} min. Context only: no model uses it."
            + (' Its price and stock status are verified against the source; that it belongs to this store is not '
               '(store label unverified).' if ro.get('store_label', 'UNVERIFIED') != 'DEPARTS_FROM_RANDOM' else ''),
            src='data/raw (REAL rows)', detail=f"REAL row {ro['observation_key']}", date=ro['date'])
    others = ', '.join(f"{p} Rs {v:g}" for p, v in d['competitor_prices'].items() if p != 'Blinkit')
    add('1_observe', 'SYNTHETIC',
        f"Decision snapshot {d['observed_at']} (generated panel): Blinkit at Rs {d['selling_price']:g}, "
        f"{'in stock' if d['in_stock'] else 'out of stock'}, ETA {d['eta_min']} min; competitors {others}. "
        f"Blinkit is {'' if d['cheapest_now'] else 'not '}the cheapest of the four.", detail='decision snapshot')
    # 2 applicability
    yes = [k.split('_')[0] for k, v in A.items() if v['applies']]
    no = [f"{k.split('_')[0]} ({v['why']})" for k, v in A.items() if not v['applies']]
    add('2_applicability', 'SYNTHETIC',
        f"Models that apply to this listing: {', '.join(yes)}. Not applied: {'; '.join(no)}.", detail='applicability')
    gap_in = A['10_assortment_gap'].get('recommended_as_gap_in') or []
    if gap_in:
        add('2_applicability', 'REAL',
            f"In the REAL snapshot the product is a recommended assortment gap for {', '.join(gap_in)} "
            f"(not seen in those stores' listings, which is not the same as not stocked).",
            src='outputs/models/assortment_gaps/predictions.parquet', detail='assortment gaps', date=REAL_DATE)
    # 3 prediction record
    bits = []
    if P['2_next_price'].get('provenance'):
        x = P['2_next_price']
        bits.append(f"next price Rs {x['predicted']:g} (actual Rs {x['actual_next']:g})")
    if P['3_direction'].get('provenance'):
        x = P['3_direction']
        bits.append(f"direction {x['predicted']} (down {100 * x['p_down']:.1f}%, flat {100 * x['p_flat']:.1f}%, "
                    f"up {100 * x['p_up']:.1f}%; actual {x['actual']})")
    if P['4_stock_next'].get('provenance') and P['4_stock_next'].get('p_stockout_next') is not None:
        x = P['4_stock_next']
        bits.append(f"out of stock at the next snapshot {100 * x['p_stockout_next']:.1f}% "
                    f"(actual: {'in stock' if x['actual_in_stock_next'] else 'out of stock'})")
    if P['5_eta_next'].get('provenance'):
        x = P['5_eta_next']
        bits.append(f"next ETA {x['predicted_min']:g} min (90% interval {x['interval_90'][0]:g}-{x['interval_90'][1]:g}; "
                    f"actual {x['actual_next_min']:g})")
    if P['7_time_to_stockout'].get('provenance'):
        bits.append(f"out of stock within 6 snapshots {100 * P['7_time_to_stockout']['p_oos_within_6']:.1f}%")
    if P['8_restock'].get('provenance'):
        bits.append(f"back in stock within 2 snapshots {100 * P['8_restock']['p_back_within_2']:.1f}%")
    an = P['6_anomaly'].get('decision_snapshot')
    if an:
        bits.append(f"temporal anomaly score {an['score']:g} ({'flagged' if an['flagged'] else 'not flagged'})")
    fol = P['9_competitor_response']['followers']
    bits.append('competitor response ' + ', '.join(f"{k} beta {v['beta']:g} after {v['lag_snapshots']} snapshot(s)"
                                                    for k, v in fol.items()))
    add('3_prediction_record', 'SYNTHETIC', 'Prediction record: ' + '; '.join(bits) + '.', detail='prediction record')
    ar = P['6_anomaly'].get('real_row')
    if ar:
        add('3_prediction_record', 'REAL',
            f"The REAL anomaly detector {'flags' if ar['flag_unusual'] else 'does not flag'} the 2026-07-10 row "
            f"(score {ar['score']:g}). A flag means unusual within the snapshot, never an error or a deal.",
            src='outputs/models/anomaly_real/predictions.parquet', detail='REAL anomaly score', date=REAL_DATE)
    # 4 price grid
    add('4_price_grid', 'SYNTHETIC',
        f"Price grid: Rs {G['step']} steps ending in {G['remainder']}, inferred from {G['inferred_from']}. "
        f"Ladder: {G['n_increases']} increases up to Rs {G['ceiling_price']:g}, the hold at Rs {d['selling_price']:g} "
        f"and {G['n_cuts']} cuts down to Rs {G['floor_price']:g} ({100 * G['max_cut']:.0f}% each way, or a single grid "
        f"step where the grid is coarser than that).",
        detail='price grid')
    # 5 simulation
    v = S['baseline_check']
    cov = ', '.join(f"{p} {100 * c:.0f}%" for p, c in v['coverage_of_observed_prices_by_90pct_band'].items())
    add('5_simulation', 'SYNTHETIC',
        f"Baseline check before any what-if: the status quo replayed over the {v['snapshots_checked']} test snapshots put "
        f"{cov} of observed prices inside the 90% band; the observed cheapest share "
        f"{100 * v['observed_blinkit_cheapest_share']:.1f}% against a simulated range "
        f"{100 * v['simulated_share_95_range'][0]:.1f}-{100 * v['simulated_share_95_range'][1]:.1f}%. "
        f"{'Passed.' if v['passed'] else 'FAILED: treat everything below with caution.'}", detail='baseline check')
    sq = S['status_quo']
    hold = next(r for r in S['ladder'] if r['kind'] == 'hold')
    up = [r for r in S['ladder'] if r['kind'] == 'increase']
    up_txt = ''
    if up:
        u = min(up, key=lambda r: r['price'])
        up_txt = (f" Raising it to Rs {u['price']:g}: {100 * u['strategic']['mean_cheapest_share']:.1f}% with competitors "
                  f"reacting.")
    add('5_simulation', 'SYNTHETIC',
        f"Over the next {S['horizon_snapshots']} snapshots, if Blinkit keeps following its own fitted price process "
        f"(status quo), it is cheapest-of-4 in {100 * sq['mean_cheapest_share']:.1f}% of them (90% band "
        f"{100 * sq['band_90'][0]:.1f}-{100 * sq['band_90'][1]:.1f}%). Holding the price at Rs {hold['price']:g}: "
        f"{100 * hold['strategic']['mean_cheapest_share']:.1f}% with competitors reacting, "
        f"{100 * hold['static']['mean_cheapest_share']:.1f}% if they did not." + up_txt,
        detail='status quo, hold and increases')
    u = S.get('scenario_unavailable')
    if u:
        dr, rn = u['scenarios']['drawn'], u['scenarios']['restored_now']
        top = max(dr['inherits_pp'], key=dr['inherits_pp'].get)
        add('5_simulation', 'SYNTHETIC',
            f"If this listing went out of stock now: the fitted restock model expects a spell of "
            f"{u['expected_spell_snapshots']:g} snapshots (back within 2 snapshots {100 * u['p_back_within']['2']:.1f}%). "
            f"Over the next {u['horizon_snapshots']} snapshots Blinkit is in stock and cheapest in "
            f"{100 * u['cheapest_available_share_now']:.1f}% of them now; the outage changes that by "
            f"{dr['blinkit_change_pp']:+g} pp (90% band {dr['band_90_pp'][0]:+g} to {dr['band_90_pp'][1]:+g}); "
            + (f"{top} picks up the most ({dr['inherits_pp'][top]:+g} pp). " if dr['inherits_pp'][top] > 0.05 else
               "no competitor gains much, because Blinkit was rarely the cheapest available anyway. ")
            + f"Restored before the next snapshot, the change "
            f"is {rn['blinkit_change_pp']:+g} pp.", detail='product-unavailable scenario')
    x = S.get('cross_check_stock')
    if x:
        add('5_simulation', 'SYNTHETIC',
            f"Cross-check: deliverable 7's saved forecast gives out of stock within 6 snapshots "
            f"{100 * x['model_7_p_oos_within_6']:.1f}%; the chain's own projection gives "
            f"{100 * x['chain_p_oos_within_6']:.1f}%.", detail='cross-check between layers')
    # 6 optimization
    def opt_text(view, label):
        o = Z[view]
        if not o.get('reachable_within_30pct'):
            return f"{label}: not reachable within a {100 * Z['max_cut']:.0f}% cut"
        return (f"{label}: cut Rs {o['cut_rs']:g} to Rs {o['price']:g} ({o['cut_pct']:g}%), cheapest-of-4 share "
                f"{100 * o['mean_cheapest_share']:.1f}% (90% band {100 * o['band_90'][0]:.1f}-{100 * o['band_90'][1]:.1f}%)")
    s = Z['strategic']
    promo = (f" Run as a promo, that cut adds {s['promo_extra_p_oos_within_12_pp']:g} pp to the chance of a stock-out "
             f"within {Z['horizon_snapshots']} snapshots and {s['promo_eta_added_min']:g} min of ETA; as a list-price "
             f"cut, neither." if s.get('reachable_within_30pct') else '')
    if Z.get('direction') == 'raise':
        def raise_text(view, label):
            o = Z['raise'][view]
            if not o.get('target_met_at_current_price'):
                return f"{label}: the target is not met even at the current price"
            if o['raise_rs'] == 0:
                return f"{label}: no raise keeps it; hold"
            return (f"{label}: up to Rs {o['raise_rs']:g} (+{o['raise_pct']:g}%) to Rs {o['price']:g}, cheapest-of-4 "
                    f"share {100 * o['mean_cheapest_share']:.1f}%"
                    + (' (the top of the ladder)' if o['at_ceiling'] else ''))
        o = Z['raise']['strategic']
        wd = (f" Taken by withdrawing the promo, that raise changes the chance of a stock-out within "
              f"{Z['horizon_snapshots']} snapshots by {o['withdraw_p_oos_within_12_change_pp']:g} pp and ETA by "
              f"{o['withdraw_eta_change_min']:g} min." if o.get('withdraw_mode') == 'withdraw' else '')
        add('6_optimization', 'SYNTHETIC',
            f"Objective: keep Blinkit cheapest-of-4 in at least {100 * Z['target']:.0f}% of the next "
            f"{Z['horizon_snapshots']} snapshots. Holding at Rs {d['selling_price']:g} gives "
            f"{100 * Z['hold_mean_cheapest_share']:.1f}%, so the question is headroom. "
            f"{raise_text('strategic', 'With competitors reacting')}. {raise_text('static', 'If they did not react')}."
            f"{wd} Verdict: {Z['verdict']}.", detail='optimization')
    else:
        add('6_optimization', 'SYNTHETIC',
            f"Objective: the smallest cut that makes Blinkit cheapest-of-4 in at least {100 * Z['target']:.0f}% of the "
            f"next {Z['horizon_snapshots']} snapshots. {opt_text('strategic', 'With competitors reacting')}. "
            f"{opt_text('static', 'If they did not react')}.{promo} Verdict: {Z['verdict']}.", detail='optimization')
    iu = Z.get('if_unavailable')
    if iu:
        add('6_optimization', 'SYNTHETIC',
            f"If it goes out: {iu['action']}. Restoring it at once recovers "
            f"{iu['cheapest_available_pp_recovered_by_expediting']:+g} pp of cheapest-available share; its restock "
            f"priority index is {iu['expedite_priority_index']:g} expected out-of-stock snapshots saved "
            f"(deliverable 12b).", detail='if unavailable')
    # assumptions
    add('6_optimization', 'METHOD', 'Assumptions: ' + ' '.join(rec['assumptions'][:5]),
        src='src/chain/listing.py', detail='ASSUMPTIONS', date=rec.get('built'))
    return out


# =========================================================================== the chain
STAGES = ['1_observe', '2_applicability', '3_prediction_record', '4_price_grid', '5_simulation', '6_optimization',
          '7_explanation']


def chain_file(listing):
    return CHAIN_DIR / f"{slug(listing['product_name'] + '-' + listing['store_id'])}.json"


def run_chain(lst, target=TARGET, verbose=True):
    """Observe -> applicability -> prediction record -> price grid -> simulation -> optimization -> explanation."""
    obs = observe(lst)
    app = applicability(obs)
    preds = prediction_record(obs, app)
    obs['_p7'] = preds['7_time_to_stockout']
    sim = ProductSim(obs)
    grid = price_grid(obs, sim)
    grid['n_increases'] = sum(r['kind'] == 'increase' for r in grid['rungs'])
    grid['n_cuts'] = sum(r['kind'] == 'cut' for r in grid['rungs'])
    simres = simulation(obs, grid, sim)
    opt = optimization(obs, simres, target)
    if verbose:
        v = simres['baseline_check']
        print(f"  baseline {'PASS' if v['passed'] else 'FAIL'}  coverage "
              + ' '.join(f"{c:.2f}" for c in v['coverage_of_observed_prices_by_90pct_band'].values())
              + f"  share {v['observed_blinkit_cheapest_share']:.2f} in "
              f"[{v['simulated_share_95_range'][0]:.2f}, {v['simulated_share_95_range'][1]:.2f}]")
        for r in simres['ladder']:
            print(f"  {r['kind']:>8} Rs {r['price']:>7.0f}  strategic {r['strategic']['mean_cheapest_share']:.2f}  "
                  f"static {r['static']['mean_cheapest_share']:.2f}  promo {r['promo']['extra_p_oos_within_12_pp']:+.1f} pp OOS")
        print(f"  verdict: {opt['verdict']}")
    rec = {'claim_scope': 'SYNTHETIC except the REAL 2026-07-10 row (context only) and the REAL anomaly and '
                          'assortment-gap entries. Positioning and availability only.',
           'stages': STAGES,
           '1_observe': {'listing': obs['listing'], 'real_observation': obs['real_observation'],
                         'decision_snapshot': obs['decision_snapshot']},
           '2_applicability': app, '3_prediction_record': preds, '4_price_grid': grid, '5_simulation': simres,
           '6_optimization': opt, 'assumptions': ASSUMPTIONS, 'built': date.today().isoformat()}
    f = chain_file(obs['listing'])
    rel = f'outputs/models/{NAME}/chains/{f.name}'
    rec['7_explanation'] = explain(rec, rel)
    CHAIN_DIR.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rec, indent=1, default=str), encoding='utf-8')
    rec['_file'] = rel
    return rec


def pick_demo_and_gallery(n=6, n_cheapest=3):
    """In-stock listings where every applicable model has a prediction, one per category within each half:
    n where Blinkit is NOT cheapest now (the cut question) and n_cheapest where it is (the raise / headroom question)."""
    return (_pick(n, cheapest=False) + _pick(n_cheapest, cheapest=True)) if n_cheapest else _pick(n, cheapest=False)


def _pick(n, cheapest):
    cand = candidates()
    out, seen_cats = [], set()
    rng = np.random.default_rng(3)
    for i in rng.permutation(len(cand)):
        lst = cand.iloc[i].to_dict()
        try:
            obs = observe(lst)
        except Exception:
            continue
        d = obs['decision_snapshot']
        if d['cheapest_now'] != cheapest or d['in_stock'] != 1 or d['selling_price'] < 20:
            continue
        app = applicability(obs)
        if not all(app[k]['applies'] for k in ('2_next_price', '3_direction', '4_stock_next', '5_eta_next',
                                               '7_time_to_stockout')):
            continue
        if lst['category'] in seen_cats:
            continue
        seen_cats.add(lst['category'])
        out.append(lst)
        if len(out) >= n:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--demo', action='store_true')
    ap.add_argument('--product'); ap.add_argument('--store')
    ap.add_argument('--target', type=float, default=TARGET)
    a = ap.parse_args()
    lists = pick_demo_and_gallery() if a.demo else [find_listing(a.product, a.store)]
    if not lists or lists[0] is None:
        raise SystemExit('no matching listing (needs a Blinkit common-panel product with a REAL row in the same store)')
    recs = []
    for lst in lists:
        print(f"\n== {lst['product_name']} @ {lst['store_id']} ({lst['category']})")
        recs.append(run_chain(lst, target=a.target))
    if a.demo:                        # a gallery run replaces the gallery, but only once every chain has succeeded
        keep = {Path(r['_file']).name for r in recs}
        for old in CHAIN_DIR.glob('*.json'):
            if old.name not in keep:
                old.unlink()
    rows = []
    for r in recs:
        for g in r['5_simulation']['ladder']:
            rows.append({'observation_key': r['1_observe']['decision_snapshot']['observation_key'],
                         'data_status': 'SYNTHETIC', 'product_name': r['1_observe']['listing']['product_name'],
                         'store_id': r['1_observe']['listing']['store_id'], 'rung': g['kind'],
                         'price': g['price'], 'cut_pct': g['cut_pct'],
                         'prediction': g['strategic']['mean_cheapest_share'],
                         'static_share': g['static']['mean_cheapest_share'],
                         'promo_extra_oos_pp': g['promo']['extra_p_oos_within_12_pp']})
    pred = pd.DataFrame(rows)
    metrics = {'claim_limit': 'SYNTHETIC chain on generated listings; the REAL 2026-07-10 row of each listing is shown as '
                              'context only. Positioning and availability, never demand or revenue.',
               'stages': STAGES,
               'listings': [{'product': r['1_observe']['listing']['product_name'],
                             'store': r['1_observe']['listing']['store_id'], 'file': r['_file'],
                             'models_applied': [k for k, v in r['2_applicability'].items() if v['applies']],
                             'baseline_check_passed': r['5_simulation']['baseline_check']['passed'],
                             'status_quo_share': r['6_optimization']['status_quo_mean_cheapest_share'],
                             'optimum_strategic': r['6_optimization']['strategic'],
                             'optimum_static': r['6_optimization']['static'],
                             'direction': r['6_optimization']['direction'],
                             'hold_share': r['6_optimization']['hold_mean_cheapest_share'],
                             'raise_strategic': r['6_optimization']['raise']['strategic'],
                             'raise_static': r['6_optimization']['raise']['static'],
                             'verdict': r['6_optimization']['verdict'],
                             'cross_check_stock': r['5_simulation']['cross_check_stock']} for r in recs],
               'baseline_checks_passed': int(sum(r['5_simulation']['baseline_check']['passed'] for r in recs)),
               'n_listings': len(recs)}
    save_model_outputs(NAME, pred, params={'horizon': HORIZON, 'n_sims': N_SIMS, 'n_stock_paths': N_STOCK,
                                           'target': a.target, 'max_cut': MAX_CUT, 'assumptions': ASSUMPTIONS},
                       metrics=metrics, training_data=pred, split={'uses': 'saved outputs of 2-10 + fitted price/stock worlds'},
                       target='cheapest-of-4 share for one listing by posted price',
                       notes='Product x store chain: observe -> applicability -> prediction record -> price grid -> '
                             'simulation -> optimization -> explanation. SYNTHETIC, with REAL context rows.')
    print(json.dumps(metrics, indent=1, default=str))


if __name__ == '__main__':
    main()
