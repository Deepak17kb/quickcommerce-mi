"""
promo_frontier.py — OPTIMIZE extension: the price-position vs availability frontier. SYNTHETIC.

    python -m src.simulate.grid              # once (the price side comes from the what-if grid)
    python -m src.optimize.promo_frontier    # -> outputs/models/optimize_promo_frontier/

THE TENSION THIS MAPS
  Blinkit can make a category cheaper in two ways:
    promo        the selling price falls, MRP stays: the discount deepens. In the fitted hazard (deliverable 7) discount
                 depth raises the stock-out hazard (promo effect d = 1.84), and in the ETA model (deliverable 5) it adds
                 delivery time (3.88 min per 100% depth).
    list price   the selling price and MRP fall together: same price move, discount unchanged, no hazard or ETA effect.
  Both buy the same cheapest-of-4 share (deliverable 9, via the grid). A listing that is out of stock cannot win the
  comparison, so the measure that joins them is AVAILABLE-AND-CHEAPEST share:
        share cheapest (price world) x share in stock (stock world)
  The two worlds are independent in the fitted models (price shocks and stock shocks share no random driver), so the
  product is the joint probability at category level.

  A promo cut of x on a listing with current depth d0 moves its depth to 1 - (1 - d0)(1 - x): the depth rises by
  x(1 - d0). One stock simulation per cut serves every category (listings interact only through store demand, which
  a discount does not move).

CLAIM SCOPE
  "Under the fitted, generated dynamics." The promo-hurts-availability link is a planted assumption of the generator
  (docs/GENERATOR_v15_PARAMETERS.md, E), so "cut list prices, not promos" is a statement about the generator. Never
  demand, never revenue: nobody here knows what the extra stock-outs or the cut cost in money.
"""
import json

import numpy as np
import pandas as pd

from src.model_output import load_model_outputs, save_model_outputs
from src.simulate.engine import StockWorld
from src.simulate.grid import CUTS, load_grid

NAME = 'optimize_promo_frontier'
N_SIMS = 10
HORIZON = 12
SEED = 7
OOS_BUDGET_PP = 1.0


def main():
    grid = load_grid()
    groups = [g for g in grid['groups'] if g != 'All']
    share = {(c['group'], c['cut_pct']): c for c in grid['cells']
             if c['mover'] == 'Blinkit' and c['view'] == 'strategic' and c.get('direction', 'cut') == 'cut'}
    W = StockWorld.load(); st = W.initial_state()
    blk = (st.platform == 'Blinkit').to_numpy()
    d0 = st.depth.to_numpy()
    oos = {}
    for x in [0] + CUTS:
        dd = np.where(blk, (x / 100) * (1 - d0), 0.0)
        r = W.simulate(st, horizon=HORIZON, n_sims=N_SIMS, seed=SEED, depth_delta=dd)
        ps = r['per_sim_listing_oos_rate']
        for g in groups:
            m = blk & (st.category == g).to_numpy()
            per_sim = ps[:, m].mean(1)
            oos[(g, x)] = {'mean': float(per_sim.mean()), 'per_sim': per_sim,
                           'depth_delta': float(dd[m].mean()), 'listings': int(m.sum())}
        print(f'  stock world at promo cut {x}% done')
    rows = []
    for g in groups:
        base_share = share[(g, CUTS[0])]['base']['Blinkit']
        o0 = oos[(g, 0)]
        for x in [0] + CUTS:
            s = base_share if x == 0 else share[(g, x)]['share']['Blinkit']
            o = oos[(g, x)]
            d_oos = 100 * (o['per_sim'] - o0['per_sim'])                       # paired, common random numbers
            rows.append({'category': g, 'cut_pct': x, 'blinkit_listings': o['listings'],
                         'cheapest_share': s,
                         'oos_rate_promo': o['mean'], 'oos_rate_list_price': o0['mean'],
                         'oos_added_pp': float(d_oos.mean()), 'oos_added_pp_p05': float(np.quantile(d_oos, 0.05)),
                         'oos_added_pp_p95': float(np.quantile(d_oos, 0.95)),
                         'available_cheapest_promo': s * (1 - o['mean']),
                         'available_cheapest_list_price': s * (1 - o0['mean']),
                         'eta_added_min_promo': float(W.eta['b_discount'] * o['depth_delta'])})
    tab = pd.DataFrame(rows)
    tab['promo_penalty_pp'] = 100 * (tab.available_cheapest_list_price - tab.available_cheapest_promo)
    summary = []
    for g, t in tab.groupby('category'):
        t = t.sort_values('cut_pct')
        gain = 100 * (t.cheapest_share - t.cheapest_share.iloc[0])
        within = t[t.oos_added_pp <= OOS_BUDGET_PP]
        at10 = t[t.cut_pct == CUTS[-1]].iloc[0]
        summary.append({
            'category': g, 'blinkit_listings': int(t.blinkit_listings.iloc[0]),
            'cheapest_share_now': float(t.cheapest_share.iloc[0]), 'oos_now': float(t.oos_rate_list_price.iloc[0]),
            'largest_promo_within_budget_pct': int(within.cut_pct.max()),
            'share_gain_at_10pct_pp': float(gain.iloc[-1]), 'oos_added_at_10pct_pp': float(at10.oos_added_pp),
            'oos_pp_per_share_pp_at_10pct': float(at10.oos_added_pp / gain.iloc[-1]) if gain.iloc[-1] > 0 else None,
            'promo_penalty_at_10pct_pp': float(at10.promo_penalty_pp),
            'available_cheapest_best_cut_promo': int(t.cut_pct.iloc[int(t.available_cheapest_promo.values.argmax())]),
            'eta_added_at_10pct_min': float(at10.eta_added_min_promo)})
    summ = pd.DataFrame(summary).sort_values('oos_pp_per_share_pp_at_10pct', ascending=False)
    print(summ.round(3).to_string())
    metrics = {
        'claim_limit': ('SYNTHETIC. Under the fitted, generated dynamics; the promo-to-stock-out link is a planted '
                        'generator assumption. Positioning and availability only, never demand or revenue.'),
        'oos_budget_pp': OOS_BUDGET_PP, 'n_sims': N_SIMS, 'horizon': HORIZON,
        'by_category': summ.to_dict(orient='records'),
        'categories_where_promo_breaks_budget_before_10pct': int((summ.largest_promo_within_budget_pct < CUTS[-1]).sum()),
        'available_cheapest_is_monotone_in_cut': bool((summ.available_cheapest_best_cut_promo == CUTS[-1]).all()),
    }
    anchor = load_model_outputs('stockout_survival')['predictions'].observation_key.iloc[0]
    pred = tab.assign(observation_key=anchor, data_status='SYNTHETIC', prediction=tab.available_cheapest_promo)
    mdir = save_model_outputs(NAME, pred, params={'n_sims': N_SIMS, 'horizon': HORIZON, 'seed': SEED, 'cuts_pct': CUTS,
                                                  'depth_rule': 'promo depth -> 1 - (1 - d0)(1 - x)'},
                              metrics=metrics, training_data=pred, split={'uses': 'simulate_grid + stock world'},
                              target='available-and-cheapest share by category and cut',
                              notes='OPTIMIZE extension: price-position vs availability frontier. SYNTHETIC ONLY.')
    tab.to_csv(mdir / 'frontier.csv', index=False)
    print(json.dumps({k: v for k, v in metrics.items() if k != 'by_category'}, indent=1))


if __name__ == '__main__':
    main()
