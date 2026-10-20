"""
restock_lab.py — OPTIMIZE extension: what restock capacity buys, and how close the priority index is to perfect.
SYNTHETIC.

    python -m src.optimize.restock_lab       # -> outputs/models/optimize_restock_lab/

TWO QUESTIONS
  1 The capacity curve. Each policy is run at 0.25% to 4% of each store's listings per snapshot. The marginal value of
    capacity (out-of-stock listing-snapshots saved per extra action) shows where more restock effort stops paying.
  2 The optimality gap. Two benchmarks bracket the priority index (deliverable 12b):
      index, restock only   the same index but no pre-emptive top-ups: isolates what top-ups add
      clairvoyant oracle    knows the TRUE remaining length of every outage (information no operator has) and ranks
                            outages by it, with the index for in-stock items. A benchmark for perfect outage
                            information under the same greedy ranking, not a proven optimum.
    The gap between the index and the oracle is roughly what better restock-time information would be worth.

CLAIM SCOPE: out-of-stock exposure under the fitted, generated stock dynamics (deliverables 7, 8). Not lost sales,
revenue or the real cost of a stock-out.
"""
import json

import numpy as np
import pandas as pd

from src.model_output import save_model_outputs
from src.optimize.restock_priority import (_per_store_top, policy_longest_out, policy_priority, policy_random,
                                          priority_scores)
from src.simulate.engine import StockWorld

NAME = 'optimize_restock_lab'
CAPACITIES = (0.0025, 0.005, 0.01, 0.02, 0.04)
N_SIMS = 8
HORIZON = 12
SEED = 5


def policy_restock_only(state, rng, cap):
    """The priority index, restricted to out-of-stock listings (no pre-emptive top-ups)."""
    return _per_store_top(state['st'], priority_scores(state), cap, state['in_stock'] == 0, state.get('active'))


def policy_oracle(state, rng, cap):
    """Clairvoyant benchmark: an outage's saving is its TRUE remaining length (capped at the horizon left); an in-stock
    listing keeps the index's expected saving. Both are in out-of-stock snapshots saved, so one ranking serves both."""
    ins = state['in_stock']
    h_left = state['horizon'] - state['t']
    score = np.where(ins == 0, np.minimum(state['hidden_remaining'], h_left).astype(float), priority_scores(state))
    return _per_store_top(state['st'], score, cap, np.ones(len(ins), bool), state.get('active'))


policy_oracle.oracle = True


def main():
    W = StockWorld.load(); st = W.initial_state()
    none = W.simulate(st, horizon=HORIZON, n_sims=N_SIMS, seed=SEED)
    base = none['oos_share_path'].mean(1) * len(st) * HORIZON
    policies = {'random': policy_random, 'longest_out_first': policy_longest_out,
                'index_restock_only': policy_restock_only, 'priority_index': policy_priority,
                'clairvoyant_oracle': policy_oracle}
    rows = []
    for cap in CAPACITIES:
        for name, pol in policies.items():
            r = W.simulate(st, horizon=HORIZON, n_sims=N_SIMS, seed=SEED, policy=pol, capacity_share=cap)
            per_sim = r['oos_share_path'].mean(1) * len(st) * HORIZON
            saved = base - per_sim
            rows.append({'capacity_pct': 100 * cap, 'policy': name, 'oos_listing_snapshots': float(per_sim.mean()),
                         'reduction_pct': float(100 * saved.mean() / base.mean()),
                         'reduction_p05': float(100 * np.quantile(saved / base, 0.05)),
                         'reduction_p95': float(100 * np.quantile(saved / base, 0.95)),
                         'actions': float(r['actions'].mean()),
                         'saved_per_action': float(saved.mean() / r['actions'].mean()) if r['actions'].mean() else None})
            print(f"  capacity {100 * cap:.2f}%  {name:<20} reduction {rows[-1]['reduction_pct']:.1f}%")
    tab = pd.DataFrame(rows)
    piv = tab.pivot(index='capacity_pct', columns='policy', values='reduction_pct')
    gap = (piv['clairvoyant_oracle'] - piv['priority_index'])
    share_of_oracle = piv['priority_index'] / piv['clairvoyant_oracle']
    topup = piv['priority_index'] - piv['index_restock_only']
    pi = tab[tab.policy == 'priority_index'].sort_values('capacity_pct')
    marginal = (pi.oos_listing_snapshots.diff().abs() / pi.actions.diff()).tolist()
    metrics = {
        'claim_limit': ('SYNTHETIC. Out-of-stock exposure under the fitted, generated stock dynamics. Not lost sales or '
                        'revenue; the oracle uses information no operator has and is a benchmark only.'),
        'baseline_oos_listing_snapshots': float(base.mean()), 'n_sims': N_SIMS, 'horizon': HORIZON,
        'reduction_pct_by_capacity': piv.round(2).to_dict(orient='index'),
        'index_share_of_oracle_by_capacity': share_of_oracle.round(4).to_dict(),
        'oracle_gap_pp_by_capacity': gap.round(2).to_dict(),
        'topup_contribution_pp_by_capacity': topup.round(2).to_dict(),
        'marginal_saved_per_extra_action_priority': dict(zip(pi.capacity_pct.tolist(), [None] + [round(m, 3) for m in marginal[1:]])),
        'rows': rows,
    }
    anchor = st.observation_key.iloc[0]
    pred = tab.assign(observation_key=anchor, data_status='SYNTHETIC', prediction=tab.reduction_pct)
    save_model_outputs(NAME, pred, params={'capacities': list(CAPACITIES), 'n_sims': N_SIMS, 'horizon': HORIZON,
                                           'policies': list(policies)},
                       metrics=metrics, training_data=pred, split={'initial_state': 'last val snapshot'},
                       target='reduction in out-of-stock listing-snapshots by policy and capacity',
                       notes='OPTIMIZE extension: capacity curve and optimality gap. SYNTHETIC ONLY.')
    print(piv.round(2).to_string())
    print(json.dumps({k: metrics[k] for k in ('index_share_of_oracle_by_capacity', 'topup_contribution_pp_by_capacity')}, indent=1))


if __name__ == '__main__':
    main()
