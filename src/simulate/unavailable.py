"""
unavailable.py — SIMULATE extension: what happens when a product becomes unavailable. SYNTHETIC.

    python -m src.simulate.unavailable        # -> outputs/models/simulate_unavailable/

THE MEASURE: CHEAPEST-AVAILABLE-OF-4
  A platform that is out of stock cannot be the cheapest option for a product. At each snapshot, for each product listed
  on all four platforms, the winner is the cheapest platform among those with at least one listing of it IN STOCK (ties
  count for every tied platform). The price world (deliverable 9) and the stock world (deliverables 7, 8) are
  independent in the fitted models, so simulation i of one is paired with simulation i of the other.

SCENARIOS (all paired with the no-outage run: common random numbers, and a separate stream for outage lengths)
  who inherits   each platform in turn loses every common-panel listing now; outage lengths are drawn from the fitted
                 restock distribution (deliverable 8). Which platform picks up the cheapest-available wins? 4 runs.
  by category    categories never interact, so the Blinkit run answers every category at once.
  duration       Blinkit outages lasting 0, 1, 2, 4, 8 snapshots after now versus the drawn length: what restoring
                 stock sooner is worth, in cheapest-available wins (the value of expediting, deliverable 12b's action).
                 0 is not "no outage": the listing comes back with a fresh in-stock clock, and under the fitted rising
                 hazard (deliverable 7) that is a small gain, the same effect as a pre-emptive top-up.
  store ETA      a whole category out in one Blinkit store raises the store's OOS share; deliverable 5's fitted store-OOS
                 term turns that into minutes. The term is confounded with latent demand: the naive estimate is
                 56 min per 100% OOS share, the state-space fix 19, the planted value 8 (docs/ETA_FORECAST_v1.md). The
                 minutes are shown for all three, not just the fitted one.

NEGATIVE CONTROL ON THE DATA: IS THERE SUBSTITUTION?
  If shoppers switched platforms when Blinkit is out, a competitor listing of the same product would run out faster
  while Blinkit is out. The generator planted no such link (its stock-outs are driven by each store's own latent
  pressure), so the simulator assumes none. The check: logistic regression of a competitor listing's next-snapshot
  stock-out on whether Blinkit's listings of the same product are out now, controlling for every driver of the fitted
  hazard: category, platform, in-stock clock, store pressure and whether the next snapshot is an evening one. Standard
  errors are clustered by product. It should find nothing. Real substitution cannot be measured here: there is no demand.
  History: the first specification left out the evening term and found a small NEGATIVE association (odds ratio 0.91).
  Blinkit is more often out at snapshots followed by a morning one, when every hazard is lower, so time of day
  confounded it. With the evening term (a known hazard driver that belonged in from the start) it vanishes; snapshot
  fixed effects agree. Both specifications are kept in the output.

CLAIM SCOPE
  Positioning and availability under the fitted, generated dynamics. Nothing about lost sales, switching shoppers or
  revenue.
"""
import json

import numpy as np
import pandas as pd

import src.features.stock_clock as SC
import src.load as L
from src.model_output import save_model_outputs
from src.simulate.engine import PLATFORMS, PriceWorld, StockWorld

NAME = 'simulate_unavailable'
N_SIMS = 16
HORIZON = 12
SEED = 23
LENGTHS = (0, 1, 2, 4, 8)          # snapshots out after now; 0 = restored before the next snapshot
ETA_TERMS = {'planted': 8.0, 'state_space': None, 'naive': 56.0}      # min per 100% store OOS share; state space read


def common_panel_state(W):
    """Stock state (last val snapshot) of every common-panel listing, with its product and platform index."""
    st = W.initial_state()
    ml = L.load_ml(with_targets=False)[['observation_key', 'canonical_product_key', 'in_common_panel']]
    st = st.merge(ml, on='observation_key', how='left')
    st = st[st.in_common_panel == 1].reset_index(drop=True)
    return st


def availability(states, g, n_groups):
    """(sim, t, listing) in-stock -> (sim, t, group) any listing of the group in stock."""
    N, T, _ = states.shape
    out = np.zeros((N, T, n_groups), np.int16)
    for s in range(N):
        np.add.at(out[s], (slice(None), g), states[s])
    return out > 0


def winners(M, avail):
    """M (sim, platform, key, t) prices; avail (sim, t, platform, key). Returns (sim, platform, key, t) win flags for
    cheapest-available-of-4 and the mask of key-snapshots where all four list the product."""
    A = np.transpose(avail, (0, 2, 3, 1))                                # -> (sim, platform, key, t)
    listed = np.isfinite(M)
    ok = listed.all(1)                                                   # (sim, key, t)
    P = np.where(A & listed, M, np.inf)
    mn = P.min(1)
    win = (P <= mn[:, None] + 1e-9) & np.isfinite(P)
    return win, ok


def shares(win, ok, keys=None):
    """Mean cheapest-available share per (sim, platform) over key-snapshots where all four list the product."""
    if keys is not None:
        win, ok = win[:, :, keys], ok[:, keys]
    return (win & ok[:, None]).sum((2, 3)) / np.maximum(ok.sum((1, 2)), 1)[:, None]


def substitution_check():
    """Negative control on the SYNTHETIC panel: does a Blinkit outage of a product raise a competitor's stock-out risk?"""
    import statsmodels.formula.api as smf
    ml = SC.attach(L.load_ml())
    d = ml[(ml.data_status == 'SYNTHETIC') & (ml.in_common_panel == 1)].copy()
    d['_ts'] = pd.to_datetime(d.observed_at.astype(str), format='mixed')
    d = d.sort_values(['platform', 'store_id', 'product_id', '_ts'])
    d['next_in'] = d.groupby(['platform', 'store_id', 'product_id']).in_stock.shift(-1)
    blk = (d[d.platform == 'Blinkit'].groupby(['canonical_product_key', 'snapshot_id']).in_stock.mean()
           .rename('blinkit_in_share').reset_index())
    c = d[(d.platform != 'Blinkit') & (d.in_stock == 1) & d.next_in.notna()].merge(
        blk, on=['canonical_product_key', 'snapshot_id'], how='inner')
    c['event'] = (c.next_in == 0).astype(int)
    c['blinkit_out'] = (c.blinkit_in_share < 1).astype(int)
    c['clock'] = np.log1p(c.instock_run_length.fillna(1))
    c['pressure'] = c.store_pressure_index.clip(-4, 4).fillna(0)
    c['evening'] = c.next_snapshot_is_evening.fillna(0)
    f = 'event ~ blinkit_out + C(category) + C(platform) + clock + pressure + evening'
    f_first = 'event ~ blinkit_out + C(category) + C(platform) + clock + pressure'
    naive = smf.logit(f, data=c).fit(disp=0)
    # rows are repeated snapshots of the same products: cluster the standard errors by product
    groups = pd.factorize(c.canonical_product_key)[0]
    fit = smf.logit(f, data=c).fit(disp=0, cov_type='cluster', cov_kwds={'groups': groups})
    first = smf.logit(f_first, data=c).fit(disp=0, cov_type='cluster', cov_kwds={'groups': groups})
    b, se = float(fit.params['blinkit_out']), float(fit.bse['blinkit_out'])
    raw = c.groupby('blinkit_out').event.mean()
    lo, hi = float(np.exp(b - 1.96 * se)), float(np.exp(b + 1.96 * se))
    return {'provenance': 'SYNTHETIC', 'rows': int(len(c)), 'events': int(c.event.sum()),
            'rows_with_blinkit_out': int(c.blinkit_out.sum()),
            'raw_next_oos_rate': {'blinkit_in_stock': float(raw.get(0, np.nan)), 'blinkit_out': float(raw.get(1, np.nan))},
            'odds_ratio': float(np.exp(b)), 'odds_ratio_ci95_cluster_by_product': [lo, hi],
            'p_value_cluster_by_product': float(fit.pvalues['blinkit_out']),
            'p_value_naive_iid': float(naive.pvalues['blinkit_out']),
            'first_spec_without_evening': {'odds_ratio': float(np.exp(first.params['blinkit_out'])),
                                           'p_value_cluster': float(first.pvalues['blinkit_out']),
                                           'why_replaced': 'time of day confounds it: Blinkit is out more often before '
                                                           'a morning snapshot, when every hazard is lower'},
            'share_of_blinkit_out_rows_before_evening': float(c[c.blinkit_out == 1].evening.mean()),
            'share_of_blinkit_in_rows_before_evening': float(c[c.blinkit_out == 0].evening.mean()),
            # substitution would make competitors run out FASTER while Blinkit is out: an odds ratio above 1
            'verdict': ('no substitution effect: the odds ratio is not above 1, consistent with the generator, which '
                        'planted none' if lo <= 1.0 else
                        'competitors run out faster while Blinkit is out: investigate before assuming no substitution'),
            'meaning': 'real substitution cannot be measured here: there are no orders or shoppers in the data'}


def main():
    PW = PriceWorld.load()
    W = StockWorld.load()
    st = common_panel_state(W)
    kidx = pd.Series(np.arange(PW.n_keys), index=PW.keys)
    st['k'] = st.canonical_product_key.map(kidx)
    st = st[st.k.notna()].reset_index(drop=True)
    st['k'] = st.k.astype(int)
    pidx = st.platform.map({p: i for i, p in enumerate(PLATFORMS)}).to_numpy()
    K = PW.n_keys
    g = pidx * K + st.k.to_numpy()
    cat_of_key = PW.key_category.to_numpy()
    cats = sorted(pd.Series(cat_of_key).value_counts().loc[lambda v: v >= 30].index)
    print(f'  common-panel listings {len(st):,}, products {K:,}')

    price = PW.simulate({}, horizon=HORIZON, n_sims=N_SIMS, seed=SEED, return_prices=True)['platform_prices']

    def run(outage=None):
        S = W.simulate(st, horizon=HORIZON, n_sims=N_SIMS, seed=SEED, outage=outage, return_states=True)['in_stock_path']
        av = availability(S, g, 4 * K).reshape(N_SIMS, HORIZON, 4, K)
        return winners(price, av), S

    (w0, ok), S0 = run()
    base = shares(w0, ok)
    # cheapest-of-4 ignoring stock, for reference: availability costs every platform some wins
    wp, _ = winners(price, np.ones((N_SIMS, HORIZON, 4, K), bool))
    price_only = shares(wp, ok)

    # ---- who inherits
    inherit, blk_cat = {}, None
    for j, p in enumerate(PLATFORMS):
        (w1, _), S1 = run({'mask': (st.platform == p).to_numpy(), 'length': None})
        sh = shares(w1, ok)
        d = 100 * (sh - base)                                                # paired, pp
        inherit[p] = {q: {'change_pp': [round(float(np.quantile(d[:, i], v)), 3) for v in (0.05, 0.5, 0.95)]}
                      for i, q in enumerate(PLATFORMS)}
        if p == 'Blinkit':
            blk_cat = {}
            for c in cats:
                keys = np.flatnonzero(cat_of_key == c)
                dc = 100 * (shares(w1, ok, keys) - shares(w0, ok, keys))
                blk_cat[c] = {'skus': int(len(keys)),
                              'blinkit_share_now_pp': round(float(100 * shares(w0, ok, keys)[:, 0].mean()), 3),
                              'blinkit_change_pp': round(float(np.median(dc[:, 0])), 3),
                              'inherits': {q: round(float(np.median(dc[:, i])), 3) for i, q in enumerate(PLATFORMS) if i}}
            outage_S = S1
        print(f'  outage {p}: own change {np.median(d[:, j]):+.2f} pp')

    # ---- duration: fixed outage lengths vs the drawn one (Blinkit, all common-panel listings)
    blk = (st.platform == 'Blinkit').to_numpy()
    dur = {}
    for L_ in LENGTHS:
        (w2, _), _ = run({'mask': blk, 'length': L_})
        dur[str(L_)] = round(float(np.median(100 * (shares(w2, ok) - base)[:, 0])), 3)
    drawn = inherit['Blinkit']['Blinkit']['change_pp'][1]
    mu = W.restock_mu(st[blk].iloc[:1])[0] if blk.any() else None

    # ---- store ETA: one category out in one Blinkit store
    stores = sorted(st[blk].store_id.unique())
    eta_rows = []
    b_ss = W.eta.get('b_store_oos_state_space')
    terms = {**ETA_TERMS, 'state_space': b_ss}
    for c in cats:
        m_c = blk & (st.category == c).to_numpy()
        if not m_c.any():
            continue
        oos_delta = []
        for s in stores:
            m = m_c & (st.store_id == s).to_numpy()
            if not m.any():
                continue
            in_store = (st.store_id == s).to_numpy()
            # the outage run of every Blinkit listing already contains this store-category outage (listings never
            # interact), so the store's extra OOS share comes from the category's listings alone
            extra = ((1 - outage_S[:, :, m]).sum(2) - (1 - S0[:, :, m]).sum(2)) / in_store.sum()
            oos_delta.append(float(extra.mean()))
        dm = float(np.mean(oos_delta)) if oos_delta else 0.0
        eta_rows.append({'category': c, 'mean_extra_store_oos_share': round(dm, 5),
                         'eta_minutes': {k: round(v * dm, 3) for k, v in terms.items() if v is not None}})

    sub = substitution_check()
    print(json.dumps(sub, indent=1))

    metrics = {
        'claim_limit': ('SYNTHETIC. Cheapest-available-of-4 share and availability under the fitted, generated '
                        'dynamics. Nothing about lost sales, shoppers switching or revenue.'),
        'n_sims': N_SIMS, 'horizon': HORIZON, 'listings': int(len(st)), 'products': int(K),
        'cheapest_of_4_ignoring_stock': {p: round(float(price_only[:, i].mean()), 4) for i, p in enumerate(PLATFORMS)},
        'cheapest_available_now': {p: round(float(base[:, i].mean()), 4) for i, p in enumerate(PLATFORMS)},
        'who_inherits': inherit,
        'blinkit_outage_by_category': blk_cat,
        'blinkit_outage_by_length_pp': {**dur, 'drawn_from_restock_model': drawn,
                                        'meaning': 'snapshots out after now; 0 = restored before the next snapshot'},
        'blinkit_mean_restock_snapshots_first_category': float(mu) if mu is not None else None,
        'store_category_outage_eta': {'terms_min_per_100pct_oos': terms, 'by_category': eta_rows,
                                      'note': 'the fitted state-space term is a partial de-confounding; planted is 8'},
        'substitution_check': sub,
    }
    rows = [{'outage_platform': p, 'platform': q, 'change_pp': v['change_pp'][1]}
            for p, d in inherit.items() for q, v in d.items()]
    anchor = st.observation_key.iloc[0]
    pred = pd.DataFrame(rows).assign(observation_key=anchor, data_status='SYNTHETIC',
                                     prediction=lambda t: t.change_pp)
    save_model_outputs(NAME, pred, params={'n_sims': N_SIMS, 'horizon': HORIZON, 'seed': SEED, 'lengths': list(LENGTHS),
                                           'measure': 'cheapest-available-of-4 (in stock and cheapest, ties count)'},
                       metrics=metrics, training_data=pred,
                       split={'initial_state': 'last val snapshot', 'uses': 'price_response + stock world'},
                       target='cheapest-available-of-4 share under outages',
                       notes='SIMULATE extension: product unavailable. SYNTHETIC ONLY.')
    print(json.dumps({k: metrics[k] for k in ('cheapest_of_4_ignoring_stock', 'cheapest_available_now',
                                               'blinkit_outage_by_length_pp')}, indent=1))
    print(json.dumps({p: {q: v['change_pp'][1] for q, v in d.items()} for p, d in inherit.items()}, indent=1))


if __name__ == '__main__':
    main()
