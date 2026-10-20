"""
restock_objective.py — OPTIMIZE extension: a richer restock objective. SYNTHETIC.

    python -m src.optimize.restock_objective   # -> outputs/models/optimize_restock_objective/

WHY
  Deliverable 12b minimises out-of-stock listing-snapshots: every listing counts the same. But in positioning terms a
  stock-out only costs something when that listing would have won: been in stock AND the cheapest of the four. A listing
  on a product where its platform is never cheapest loses no cheapest-available win by running out. So:

  J1  out-of-stock listing-snapshots                      (12b's objective)
  J2  cheapest-available wins lost to stock-outs           wins if everything stayed in stock minus wins achieved, summed
                                                           over products, snapshots and platforms (each platform's stores
                                                           restock their own listings, so each platform's wins count)
  J3  store ETA minutes from stock-outs                     store OOS share x deliverable 5's fitted store-OOS term (state
                                                           space, 19 min per 100%; planted 8). Reported, not optimised.

THE WEIGHTED INDEX
  score_i = (expected OOS snapshots saved, the 12b index) x [ alpha + (1 - alpha) x w_i / mean(w) ]
  w_i = P(listing i's platform is cheapest-of-4 on its product) / (number of that platform's listings of the product in
  the store universe), from the status-quo price world. alpha = 1 is 12b's index; alpha = 0 is fully win-weighted. The
  sweep over alpha traces the trade-off between J1 and J2 (a Pareto frontier), rather than picking one weight.
  Benchmarks: none, random, longest-out-first, and a clairvoyant win-weighted oracle (true outage lengths).

EVALUATION
  Common-panel listings (products on all four platforms, so a winner exists), stock world from the last val snapshot,
  capacity 1% of each store's listings per snapshot, 12 snapshots. Price simulation i is paired with stock simulation i
  (the worlds are independent); every policy shares the same random streams.

CLAIM SCOPE
  Positioning and availability under the fitted, generated dynamics. A "lost win" is a lost cheapest-available position,
  not a lost sale: no demand exists here.
"""
import json

import numpy as np
import pandas as pd

from src.model_output import save_model_outputs
from src.optimize.restock_priority import _per_store_top, policy_longest_out, policy_random, priority_scores
from src.simulate.engine import PLATFORMS, PriceWorld, StockWorld
from src.simulate.unavailable import availability, common_panel_state, shares, winners

NAME = 'optimize_restock_objective'
N_SIMS = 24                        # lost wins are a small count per simulation: 24 paired runs for tight bands
HORIZON = 12
SEED = 41
CAPACITY = 0.01
ALPHAS = (1.0, 0.75, 0.5, 0.25, 0.0)


def weighted_policy(w, alpha, oracle=False):
    wn = w / max(w.mean(), 1e-12)

    def pol(state, rng, cap):
        base = priority_scores(state)
        if oracle:
            h_left = state['horizon'] - state['t']
            base = np.where(state['in_stock'] == 0, np.minimum(state['hidden_remaining'], h_left).astype(float), base)
        return _per_store_top(state['st'], base * (alpha + (1 - alpha) * wn), cap,
                              np.ones(len(state['in_stock']), bool), state.get('active'))
    pol.oracle = oracle
    return pol


def main():
    PW = PriceWorld.load()
    W = StockWorld.load()
    st = common_panel_state(W)
    kidx = pd.Series(np.arange(PW.n_keys), index=PW.keys)
    st['k'] = st.canonical_product_key.map(kidx)
    st = st[st.k.notna()].reset_index(drop=True)
    st['k'] = st.k.astype(int)
    K = PW.n_keys
    pidx = st.platform.map({p: i for i, p in enumerate(PLATFORMS)}).to_numpy()
    g = pidx * K + st.k.to_numpy()

    pr = PW.simulate({}, horizon=HORIZON, n_sims=N_SIMS, seed=SEED, return_prices=True)
    price = pr['platform_prices']
    n_same = pd.Series(g).map(pd.Series(g).value_counts()).to_numpy()
    w = pr['cheapest_by_key'][pidx, st.k.to_numpy()] / n_same
    w = np.nan_to_num(w)

    wp, ok = winners(price, np.ones((N_SIMS, HORIZON, 4, K), bool))
    wins_all_in = (wp & ok[:, None]).sum((1, 2, 3))                     # per sim: wins if nothing ever ran out
    stores = st.store_id.to_numpy()
    b_ss = W.eta.get('b_store_oos_state_space') or 0.0

    def evaluate(pol, cap):
        r = W.simulate(st, horizon=HORIZON, n_sims=N_SIMS, seed=SEED, policy=pol, capacity_share=cap,
                       return_states=True)
        S = r['in_stock_path']
        av = availability(S, g, 4 * K).reshape(N_SIMS, HORIZON, 4, K)
        win, _ = winners(price, av)
        wins = (win & ok[:, None]).sum((1, 2, 3))
        oos = (1 - S).sum((1, 2)).astype(float)
        store_share = pd.DataFrame((1 - S).mean(1).T).groupby(stores).mean().to_numpy()   # (store, sim)
        return {'J1_oos': oos, 'J2_lost_wins': (wins_all_in - wins).astype(float),
                'J3_eta_min': b_ss * store_share.mean(0), 'actions': r['actions']}

    policies = {'none': (None, 0.0), 'random': (policy_random, CAPACITY), 'longest_out_first': (policy_longest_out, CAPACITY)}
    for a in ALPHAS:
        policies[f'index_alpha_{a:g}'] = (weighted_policy(w, a), CAPACITY)
    policies['oracle_win_weighted'] = (weighted_policy(w, 0.0, oracle=True), CAPACITY)
    res = {}
    for name, (pol, cap) in policies.items():
        res[name] = evaluate(pol, cap)
        print(f"  {name:<22} J1 {res[name]['J1_oos'].mean():8.1f}  J2 {res[name]['J2_lost_wins'].mean():8.1f}  "
              f"J3 {res[name]['J3_eta_min'].mean():.3f} min")
    base = res['none']
    rows = []
    for name, r in res.items():
        rel = {}
        for j in ('J1_oos', 'J2_lost_wins'):
            d = 100 * (base[j] - r[j]) / base[j]                             # paired reduction, per simulation
            rel[j] = (float(d.mean()), float(np.quantile(d, 0.05)), float(np.quantile(d, 0.95)))
        rows.append({'policy': name, 'J1_oos_listing_snapshots': float(r['J1_oos'].mean()),
                     'J2_lost_cheapest_available_wins': float(r['J2_lost_wins'].mean()),
                     'J3_store_eta_minutes': float(r['J3_eta_min'].mean()),
                     'J1_reduction_pct': rel['J1_oos'][0], 'J1_reduction_band': list(rel['J1_oos'][1:]),
                     'J2_reduction_pct': rel['J2_lost_wins'][0], 'J2_reduction_band': list(rel['J2_lost_wins'][1:]),
                     'actions': float(r['actions'].mean())})
    tab = pd.DataFrame(rows)
    print(tab.round(2).to_string())
    t = tab.set_index('policy')
    plain, full = t.loc['index_alpha_1'], t.loc['index_alpha_0']
    frontier = [{'alpha': a, 'J1_reduction_pct': float(t.loc[f'index_alpha_{a:g}'].J1_reduction_pct),
                 'J2_reduction_pct': float(t.loc[f'index_alpha_{a:g}'].J2_reduction_pct)} for a in ALPHAS]
    # paired differences against the plain index (alpha = 1), per alpha: what win-weighting gains on J2, costs on J1
    paired = {}
    for a in ALPHAS[1:]:
        r = res[f'index_alpha_{a:g}']
        g2 = 100 * (res['index_alpha_1']['J2_lost_wins'] - r['J2_lost_wins']) / base['J2_lost_wins']
        c1 = 100 * (r['J1_oos'] - res['index_alpha_1']['J1_oos']) / base['J1_oos']
        def ci_mean(x):
            # 90% confidence interval of the MEAN paired difference (t quantile, n - 1 degrees of freedom). The band
            # next to it is the spread of single 12-snapshot windows: a different, much wider quantity
            from scipy.stats import t as tdist
            h = tdist.ppf(0.95, len(x) - 1) * x.std(ddof=1) / np.sqrt(len(x))
            return [float(x.mean() - h), float(x.mean() + h)]
        paired[f'{a:g}'] = {'J2_gain_pp': float(g2.mean()), 'J2_gain_band_90': [float(np.quantile(g2, 0.05)),
                                                                              float(np.quantile(g2, 0.95))],
                            'J2_gain_mean_ci90': ci_mean(g2), 'J1_cost_mean_ci90': ci_mean(c1),
                            'J2_gain_positive_in_share_of_sims': float((g2 > 0).mean()),
                            'J1_cost_pp': float(c1.mean()), 'J1_cost_band_90': [float(np.quantile(c1, 0.05)),
                                                                                float(np.quantile(c1, 0.95))]}
    # the alpha with the largest J2 reduction among those not beaten on both objectives by another alpha
    fr = pd.DataFrame(frontier)
    dominated = [any((o.J1_reduction_pct >= r.J1_reduction_pct) and (o.J2_reduction_pct > r.J2_reduction_pct)
                     for _, o in fr.iterrows() if o.alpha != r.alpha) for _, r in fr.iterrows()]
    metrics = {
        'claim_limit': ('SYNTHETIC. Out-of-stock exposure and lost cheapest-available-of-4 positions under the fitted, '
                        'generated dynamics. A lost win is a lost price position, never a lost sale.'),
        'n_sims': N_SIMS, 'horizon': HORIZON, 'capacity_share': CAPACITY, 'listings': int(len(st)),
        'wins_if_always_in_stock_per_sim': float(wins_all_in.mean()),
        'lost_wins_with_no_action': float(base['J2_lost_wins'].mean()),
        'eta_term_min_per_100pct_oos': {'state_space': b_ss, 'planted': 8.0},
        'weights': {'share_of_listings_with_zero_win_weight': float((w == 0).mean()),
                    'weight_p50': float(np.median(w)), 'weight_p90': float(np.quantile(w, 0.9))},
        'policies': tab.to_dict(orient='records'),
        'frontier_alpha': frontier,
        'paired_vs_plain_index': paired,
        'dominated_alphas': [float(a) for a, d in zip(fr.alpha, dominated) if d],
        'win_weighted_share_of_oracle_J2': float(full.J2_reduction_pct / t.loc['oracle_win_weighted'].J2_reduction_pct),
    }
    anchor = st.observation_key.iloc[0]
    pred = tab.assign(observation_key=anchor, data_status='SYNTHETIC', prediction=tab.J2_reduction_pct)
    per_sim = pd.DataFrame({f'{name}__{j}': r[j] for name, r in res.items() for j in ('J1_oos', 'J2_lost_wins')})
    mdir = save_model_outputs(NAME, pred, params={'n_sims': N_SIMS, 'horizon': HORIZON, 'seed': SEED, 'capacity': CAPACITY,
                                           'alphas': list(ALPHAS),
                                           'score': 'index x [alpha + (1 - alpha) w / mean(w)]'},
                       metrics=metrics, training_data=pred, split={'initial_state': 'last val snapshot'},
                       target='out-of-stock exposure and lost cheapest-available wins by restock policy',
                       notes='OPTIMIZE extension: richer restock objective. SYNTHETIC ONLY.')
    per_sim.to_csv(mdir / 'per_simulation.csv', index_label='simulation')
    print(json.dumps({k: metrics[k] for k in ('frontier_alpha', 'paired_vs_plain_index', 'dominated_alphas',
                                              'win_weighted_share_of_oracle_J2', 'weights')}, indent=1))


if __name__ == '__main__':
    main()
