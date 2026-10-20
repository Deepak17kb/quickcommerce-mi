"""
restock_priority.py — deliverable 12b, OPTIMIZE: which listings to restock first, under a capacity limit. SYNTHETIC.

    python -m src.optimize.restock_priority

WHAT THIS MAY AND MAY NOT CLAIM
  "Under the fitted, generated stock dynamics, this ranking cuts expected out-of-stock listing-snapshots by X% versus
  the alternatives." Not lost sales, not revenue, not the real cost of a stock-out: there is no demand data.

THE DECISION
  Each snapshot, each store may act on CAPACITY of its listings:
    an out-of-stock listing  -> expedited restock (back in stock now)
    an in-stock listing      -> pre-emptive top-up (its in-stock clock resets to 1, so its rising hazard resets)
  A policy sees only what an operator could: stock state, time out so far, the in-stock clock, category, platform.

THE PRIORITY INDEX (expected out-of-stock snapshots saved within the remaining horizon)
  out of stock, out for a:   E[min(D - a, H_left) | D >= a]         restock time, deliverable 8
  in stock, clock r:         [P(out within H_left | r) - P(out within H_left | 1)] x E[min(D, H_left / 2)]
                                                                     hazard, deliverable 7; spell length, deliverable 8
POLICIES COMPARED (same random streams)
  none, random, longest_out_first (a sensible operator rule), priority_index (the model)
"""
import numpy as np
import pandas as pd
from scipy.stats import nbinom

from src.model_output import save_model_outputs
from src.simulate.engine import StockWorld

NAME = 'optimize_restock_priority'
CAPACITY = 0.01
HORIZON = 12
N_SIMS = 20
SEED = 5


def _per_store_top(st, score, cap_share, eligible, active=None):
    """Top-scoring eligible listings per store, capacity = cap_share of the store's listings (at least 1).
    active: listings the operator can see; inactive ones are simulated (so random streams stay paired across
    scenarios) but never acted on and not counted in the store's capacity."""
    stores = st.store_id.to_numpy()
    if active is not None:
        eligible = eligible & active
    counted = pd.Series(stores[active] if active is not None else stores).value_counts()
    df = pd.DataFrame({'s': stores, 'score': np.where(eligible, score, -np.inf), 'i': np.arange(len(st))})
    cap = (pd.Series(stores).map(counted).fillna(0) * cap_share).clip(lower=1).astype(int).to_numpy()
    df['cap'] = cap
    df = df[np.isfinite(df.score)].sort_values(['s', 'score'], ascending=[True, False])
    df['rk'] = df.groupby('s').cumcount()
    return df[df.rk < df.cap].i.to_numpy()


def policy_random(state, rng, cap):
    ins = state['in_stock']
    return _per_store_top(state['st'], rng.random(len(ins)), cap, ins == 0, state.get('active'))


def policy_longest_out(state, rng, cap):
    ins = state['in_stock']
    return _per_store_top(state['st'], state['elapsed'] + 1e-6 * rng.random(len(ins)), cap, ins == 0, state.get('active'))


def priority_scores(state):
    """Expected out-of-stock snapshots saved within the remaining horizon, per listing (the priority index)."""
    W, st = state['world'], state['st']
    ins, clock, el = state['in_stock'], state['clock'], state['elapsed']
    h_left = state['horizon'] - state['t']
    mu = W.restock_mu(st); m = np.maximum(mu - 1, 1e-6); n = W.n_rst; p = n / (n + m)
    # out of stock: E[min(D - a, h_left) | D >= a] = sum_{s=1..h_left} P(D >= a + s) / P(D >= a)
    a = np.maximum(el, 1)
    sf_a = nbinom.sf(a - 2, n, p)
    save_oos = sum(nbinom.sf(a + s - 2, n, p) for s in range(1, h_left + 1)) / np.maximum(sf_a, 1e-12)
    # in stock: drop in P(out within h_left) from resetting the clock, times the expected capped spell
    c, pl = W._codes(st)
    e = np.exp(W.a_haz[c] + W.b_haz[pl] + 0.5 * W.g_eve + np.log1p(W.d_promo * state['depth']))
    def p_out(r):
        return 1 - np.exp(-e * ((r + h_left - 1) ** W.k - (r - 1) ** W.k))
    spell = sum(nbinom.sf(s - 2, n, p) for s in range(1, max(h_left // 2, 1) + 1))    # E[min(D, h/2)]
    save_in = (p_out(clock) - p_out(np.ones_like(clock))) * spell
    return np.where(ins == 0, save_oos, save_in)


def policy_priority(state, rng, cap):
    return _per_store_top(state['st'], priority_scores(state), cap, np.ones(len(state['in_stock']), bool),
                          state.get('active'))


def main():
    W = StockWorld.load(); st = W.initial_state()
    policies = {'none': (None, 0.0), 'random': (policy_random, CAPACITY),
                'longest_out_first': (policy_longest_out, CAPACITY), 'priority_index': (policy_priority, CAPACITY)}
    res = {}
    for name, (pol, cap) in policies.items():
        r = W.simulate(st, horizon=HORIZON, n_sims=N_SIMS, seed=SEED, policy=pol, capacity_share=cap)
        per_sim = r['oos_share_path'].mean(1) * len(st) * HORIZON          # OOS listing-snapshots per simulation
        res[name] = {'oos_listing_snapshots': per_sim, 'actions': r['actions'], 'oos_path': r['oos_share_path'].mean(0),
                     'per_listing': r['per_listing_oos_rate']}
        print(f"  {name:<18} OOS listing-snapshots {per_sim.mean():,.0f}  actions {r['actions'].mean():,.0f}")
    base = res['none']['oos_listing_snapshots']
    rows = []
    for name, r in res.items():
        saved = base - r['oos_listing_snapshots']
        act = r['actions'].mean()
        rows.append({'policy': name, 'oos_listing_snapshots': float(r['oos_listing_snapshots'].mean()),
                     'reduction_vs_none_pct': float(100 * saved.mean() / base.mean()),
                     'reduction_p05': float(100 * np.quantile(saved / base, 0.05)),
                     'reduction_p95': float(100 * np.quantile(saved / base, 0.95)),
                     'actions': float(act), 'oos_snapshots_saved_per_action': float(saved.mean() / act) if act else None})
    tab = pd.DataFrame(rows)
    print(tab.round(3).to_string())
    pi, lo = tab.set_index('policy').loc['priority_index'], tab.set_index('policy').loc['longest_out_first']
    # today's ranked list (snapshot 0), for operators: the top of the priority index per store
    state0 = {'in_stock': st.in_stock.to_numpy(), 'clock': st.clock.to_numpy(),
              'elapsed': np.where(st.in_stock == 0, np.maximum(st.oos_elapsed, 1), 0).astype(float),
              'st': st, 'world': W, 'depth': st.depth.to_numpy(), 't': 0, 'horizon': HORIZON}
    pick = policy_priority(state0, np.random.default_rng(0), CAPACITY)
    todo = st.iloc[pick][['observation_key', 'platform', 'store_id', 'category', 'in_stock', 'clock', 'oos_elapsed']].copy()
    todo['action'] = np.where(todo.in_stock == 0, 'expedite restock', 'pre-emptive top-up')
    todo['data_status'] = 'SYNTHETIC'
    todo['prediction'] = 1.0
    metrics = {
        'claim_limit': ('SYNTHETIC. Reduction in expected out-of-stock listing-snapshots under the fitted, generated stock '
                        'dynamics (deliverables 7 and 8). Not lost sales, revenue or real stock-out cost.'),
        'capacity_share_per_store_per_snapshot': CAPACITY, 'horizon': HORIZON, 'n_sims': N_SIMS,
        'policies': tab.to_dict(orient='records'),
        'priority_vs_longest_out_first_extra_reduction_pp': float(pi.reduction_vs_none_pct - lo.reduction_vs_none_pct),
        'oos_paths': {k: v['oos_path'].tolist() for k, v in res.items()},
        'todays_actions': {'rows': int(len(todo)), 'by_action': todo.action.value_counts().to_dict()},
    }
    save_model_outputs(NAME, todo, params={'capacity': CAPACITY, 'horizon': HORIZON, 'n_sims': N_SIMS,
                                           'engine': 'src/simulate/engine.py (stock world)'},
                       metrics=metrics, training_data=st.assign(data_status='SYNTHETIC', snapshot_date=''),
                       split={'initial_state': 'last val snapshot', 'uses': 'stockout_survival + restock_interval outputs'},
                       target='restock action (priority index)', notes='Deliverable 12b. SYNTHETIC ONLY. Never revenue.')
    _figure(res, tab)


def _figure(res, tab):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from src.model_output import MODELS_DIR
    fig, ax = plt.subplots(1, 2, figsize=(14, 4.8))
    fig.suptitle('Deliverable 12b · OPTIMIZE restock priority  —  SYNTHETIC; OOS exposure, never revenue',
                 fontsize=12, x=0.01, ha='left')
    cols = {'none': '#6e7781', 'random': '#bc4c00', 'longest_out_first': '#8250df', 'priority_index': '#0969da'}
    a = ax[0]
    for k, v in res.items():
        a.plot(np.arange(1, HORIZON + 1), v['oos_path'], 'o-', ms=3.5, color=cols[k], lw=2 if k == 'priority_index' else 1.2, label=k)
    a.set_xlabel('snapshot'); a.set_ylabel('share of listings out of stock'); a.legend(frameon=False, fontsize=8.5)
    a.set_title(f'A · OOS share, capacity {CAPACITY:.0%} of each store per snapshot', fontsize=10, loc='left')
    a = ax[1]
    t = tab[tab.policy != 'none']
    a.bar(t.policy, t.reduction_vs_none_pct, color=[cols[p] for p in t.policy],
          yerr=[t.reduction_vs_none_pct - t.reduction_p05, t.reduction_p95 - t.reduction_vs_none_pct], capsize=4)
    a.set_ylabel('reduction in OOS listing-snapshots vs no action (%)')
    a.set_title('B · same capacity, different ranking', fontsize=10, loc='left')
    for a in ax:
        a.spines[['top', 'right']].set_visible(False); a.grid(color='#d0d7de', lw=0.5, alpha=0.6); a.set_axisbelow(True)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    d = MODELS_DIR / NAME / 'figures'; d.mkdir(exist_ok=True)
    fig.savefig(d / 'restock_priority.png', dpi=130); plt.close(fig)


if __name__ == '__main__':
    main()
