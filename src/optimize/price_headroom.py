"""
price_headroom.py — OPTIMIZE extension: how far can Blinkit RAISE a category's prices? SYNTHETIC.

    python -m src.simulate.grid                # once (the price side comes from the what-if grid, cuts and raises)
    python -m src.optimize.price_headroom      # -> outputs/models/optimize_price_headroom/

THE QUESTION
  Deliverable 12a asks for the smallest cut that reaches a cheapest-of-4 target. The mirror question: the largest raise
  that costs Blinkit at most a given loss of cheapest-of-4 share (its price headroom), per category, with competitors
  responding (followers follow Blinkit up, deliverable 9) and without.

THREE THINGS IT MEASURES
  headroom      the largest raise in 1-10% whose median paired share change stays within a loss budget, for budgets
                of 1, 2 and 5 pp together (a trade-off curve, not one tuned threshold), common random numbers
  asymmetry     share lost by raising x% / share gained by cutting x%. A linear response would make this 1; the
                cheapest-of-4 minimum and the price grids need not.
  withdrawal    a raise taken by withdrawing an existing promo (MRP held) makes the discount shallower, and in the fitted
                hazard (deliverable 7) a shallower discount lowers the stock-out risk: the mirror of the promo frontier.
                Depth -> max(0, 1 - (1 - d0)(1 + x)); listings with no promo can only raise the list price (no change).
                Joined as AVAILABLE-AND-CHEAPEST share = share cheapest x share in stock (the worlds are independent).

CLAIM SCOPE
  Positioning and availability under the fitted, generated dynamics. A raise is NOT framed as more money: no demand,
  orders, revenue or margin exist here, so nothing says a raise pays. "Headroom" means only "costs little cheapest-of-4
  share in the generator".
"""
import json

import numpy as np
import pandas as pd

from src.model_output import load_model_outputs, save_model_outputs
from src.simulate.engine import StockWorld
from src.simulate.grid import CUTS, RAISES, load_grid

NAME = 'optimize_price_headroom'
N_SIMS = 10
HORIZON = 12
SEED = 7                                       # same seed as the promo frontier: the two are directly comparable
LOSS_BUDGETS_PP = (1.0, 2.0, 5.0)


def cells(grid, direction, view):
    return {(c['group'], c['cut_pct']): c for c in grid['cells']
            if c['mover'] == 'Blinkit' and c['view'] == view and c.get('direction', 'cut') == direction}


def main():
    grid = load_grid()
    if 'raises_pct' not in grid:
        raise SystemExit('the what-if grid has no raises: run python -m src.simulate.grid')
    groups = grid['groups']
    up = {v: cells(grid, 'raise', v) for v in ('strategic', 'static')}
    down = cells(grid, 'cut', 'strategic')

    # ---- stock side: raises taken by withdrawing promos
    W = StockWorld.load(); st = W.initial_state()
    blk = (st.platform == 'Blinkit').to_numpy()
    d0 = st.depth.to_numpy()
    on_promo = blk & (d0 > 0)
    oos = {}
    for x in [0] + RAISES:
        new = np.maximum(0.0, 1 - (1 - d0) * (1 + x / 100))
        dd = np.where(blk, new - d0, 0.0)
        r = W.simulate(st, horizon=HORIZON, n_sims=N_SIMS, seed=SEED, depth_delta=dd)
        ps = r['per_sim_listing_oos_rate']
        for g in groups:
            m = blk if g == 'All' else blk & (st.category == g).to_numpy()
            oos[(g, x)] = {'per_sim': ps[:, m].mean(1), 'depth_delta': float(dd[m].mean()),
                           'listings': int(m.sum()), 'on_promo': int((m & on_promo).sum())}
        print(f'  stock world at raise {x}% done')

    rows, summary = [], []
    for g in groups:
        o0 = oos[(g, 0)]
        base = up['strategic'][(g, RAISES[0])]['base']['Blinkit']
        for x in RAISES:
            cs, cf = up['strategic'][(g, x)], up['static'][(g, x)]
            o = oos[(g, x)]
            d_oos = 100 * (o['per_sim'] - o0['per_sim'])
            s_after = cs['share']['Blinkit']
            rows.append({'category': g, 'raise_pct': x, 'skus': cs['skus'], 'cheapest_share_now': base,
                         'cheapest_share_after': s_after,
                         'loss_pp_strategic': cs['change_pp']['Blinkit'][1],
                         'loss_pp_strategic_p05': cs['change_pp']['Blinkit'][0],
                         'loss_pp_strategic_p95': cs['change_pp']['Blinkit'][2],
                         'loss_pp_static': cf['change_pp']['Blinkit'][1],
                         'gain_pp_cut_same_size': down[(g, x)]['change_pp']['Blinkit'][1] if x in CUTS else None,
                         'oos_change_pp_withdraw': float(d_oos.mean()),
                         'oos_change_pp_withdraw_p05': float(np.quantile(d_oos, 0.05)),
                         'oos_change_pp_withdraw_p95': float(np.quantile(d_oos, 0.95)),
                         'eta_change_min_withdraw': float(W.eta['b_discount'] * o['depth_delta']),
                         'available_cheapest_withdraw': s_after * (1 - o['per_sim'].mean()),
                         'available_cheapest_list_price': s_after * (1 - o0['per_sim'].mean())})
        t = pd.DataFrame([r for r in rows if r['category'] == g])

        def headroom(col, budget):
            ok = t[t[col] >= -budget].raise_pct
            # the largest raise such that every smaller raise is also within budget (no jumping over a cliff)
            h = 0
            for x in RAISES:
                if x in set(ok):
                    h = x
                else:
                    break
            return h
        at5 = t[t.raise_pct == 5].iloc[0]
        at1 = t[t.raise_pct == 1].iloc[0]
        summary.append({
            'category': g, 'skus': int(t.skus.iloc[0]), 'blinkit_listings': o0['listings'],
            'blinkit_listings_on_promo': o0['on_promo'], 'cheapest_share_now': float(base),
            'headroom_pct_strategic': {f'{b:g}pp': headroom('loss_pp_strategic', b) for b in LOSS_BUDGETS_PP},
            'headroom_pct_static': {f'{b:g}pp': headroom('loss_pp_static', b) for b in LOSS_BUDGETS_PP},
            'loss_pp_at_1pct_strategic': float(at1.loss_pp_strategic), 'loss_pp_at_1pct_static': float(at1.loss_pp_static),
            'loss_pp_at_5pct_strategic': float(at5.loss_pp_strategic), 'loss_pp_at_5pct_static': float(at5.loss_pp_static),
            'gain_pp_cut_5pct_strategic': float(at5.gain_pp_cut_same_size),
            'loss_over_gain_at_5pct': (float(-at5.loss_pp_strategic / at5.gain_pp_cut_same_size)
                                       if at5.gain_pp_cut_same_size > 0 else None),
            'withdraw_oos_change_pp_at_5pct': float(at5.oos_change_pp_withdraw),
            'withdraw_eta_change_min_at_5pct': float(at5.eta_change_min_withdraw),
            'withdraw_beats_list_price_on_available_cheapest': bool(at5.available_cheapest_withdraw
                                                                    >= at5.available_cheapest_list_price)})
    tab = pd.DataFrame(rows)
    summ = pd.DataFrame(summary)
    cat = summ[summ.category != 'All']
    print(summ.round(3).to_string())
    gm = json.loads(json.dumps(load_model_outputs('simulate_grid')['metrics'], default=float))
    metrics = {
        'claim_limit': ('SYNTHETIC. Positioning and availability under the fitted, generated dynamics. Headroom means a '
                        'raise costs little cheapest-of-4 share in the generator; never that a raise earns more, since '
                        'no demand or revenue exists.'),
        'loss_budgets_pp': list(LOSS_BUDGETS_PP), 'n_sims': N_SIMS, 'horizon': HORIZON,
        'panel': summ[summ.category == 'All'].iloc[0].to_dict(),
        'by_category': cat.sort_values('loss_pp_at_5pct_strategic', ascending=False).to_dict(orient='records'),
        'categories_where_response_widens_headroom': {
            f'{b:g}pp': int(sum(r['headroom_pct_strategic'][f'{b:g}pp'] > r['headroom_pct_static'][f'{b:g}pp']
                                for r in summary if r['category'] != 'All')) for b in LOSS_BUDGETS_PP},
        'categories_with_any_headroom_strategic': {
            f'{b:g}pp': int(sum(r['headroom_pct_strategic'][f'{b:g}pp'] > 0 for r in summary if r['category'] != 'All'))
            for b in LOSS_BUDGETS_PP},
        'loss_pp_at_1pct_strategic_range': [float(cat.loss_pp_at_1pct_strategic.min()),
                                            float(cat.loss_pp_at_1pct_strategic.max())],
        'median_loss_over_gain_at_5pct': float(cat.loss_over_gain_at_5pct.median()),
        'raise_static_over_strategic_loss_median_panel': gm.get('raise_static_over_strategic_loss_median'),
        'follower_raise_max_view_gap_pp': gm.get('follower_raise_max_view_gap_pp'),
    }
    anchor = load_model_outputs('stockout_survival')['predictions'].observation_key.iloc[0]
    pred = tab.assign(observation_key=anchor, data_status='SYNTHETIC', prediction=tab.cheapest_share_after)
    mdir = save_model_outputs(NAME, pred, params={'n_sims': N_SIMS, 'horizon': HORIZON, 'seed': SEED,
                                                  'raises_pct': RAISES, 'loss_budgets_pp': list(LOSS_BUDGETS_PP),
                                                  'depth_rule': 'withdraw: depth -> max(0, 1 - (1 - d0)(1 + x))'},
                              metrics=metrics, training_data=pred, split={'uses': 'simulate_grid + stock world'},
                              target='Blinkit cheapest-of-4 share and availability after a raise, by category',
                              notes='OPTIMIZE extension: price headroom for raises. SYNTHETIC ONLY.')
    tab.to_csv(mdir / 'headroom.csv', index=False)
    print(json.dumps({k: v for k, v in metrics.items() if k != 'by_category'}, indent=1, default=str))


if __name__ == '__main__':
    main()
