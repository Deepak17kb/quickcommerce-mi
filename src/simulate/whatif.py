"""
whatif.py — deliverable 11, SIMULATE: competitive-positioning what-ifs. SYNTHETIC.

    python -m src.simulate.whatif

Runs a fixed set of named scenarios through src/simulate/engine.py and saves them through the output contract as
model 'simulate_whatif'. Every number is "under the fitted, generated dynamics"; outputs are price rank,
cheapest-of-4 share, availability and ETA only. Never demand, orders, GMV or revenue.

VALIDATION FIRST
  Before any what-if, the engine is run with no scenario and compared with what the data actually show:
  cheapest-of-4 shares (CLAUDE.md s.6 regression table) and the test period's OOS share path.
  A simulator that cannot reproduce the status quo has nothing to say about changes to it.

SCENARIOS
  P1  Blinkit -3% on every common-panel SKU       static (competitors frozen) vs strategic (fitted response)
  P2  Blinkit -5% on Snacks & Munchies only
  P3  Swiggy Instamart -3% everywhere            (a follower moves: the leader does not respond)
  S1  Blinkit promo depth +10 points on Snacks & Munchies -> stock-outs and ETA
  S2  one Blinkit store hit by a +2 sd demand surge for a day (2 snapshots) -> stock-outs and ETA
"""
import json

import numpy as np
import pandas as pd

import src.load as L
from src.model_output import save_model_outputs
from src.simulate.engine import PLATFORMS, PriceWorld, StockWorld

N_SIMS = 30
HORIZON = 12
TRUTH_CHEAPEST = {'Blinkit': 0.175, 'Swiggy Instamart': 0.246, 'Flipkart Minutes': 0.566, 'BigBasket': 0.180}


def band(a):
    """mean and 90% band over simulations of a per-simulation quantity."""
    a = np.asarray(a)
    return {'mean': float(a.mean()), 'p05': float(np.quantile(a, 0.05)), 'p95': float(np.quantile(a, 0.95))}


def price_scenarios(W: PriceWorld):
    K = W.n_keys
    snack = (W.key_category == 'Snacks & Munchies').to_numpy()
    base = W.simulate({}, horizon=HORIZON, n_sims=N_SIMS, seed=11)
    out = {'validation_cheapest_share': {p: {'simulated': band(base['cheapest_share'][:, :, j].mean(1)),
                                             'observed_in_data': TRUTH_CHEAPEST[p]} for j, p in enumerate(PLATFORMS)}}
    scen = {
        'P1_blinkit_minus3_all': {'Blinkit': np.full(K, -0.03)},
        'P2_blinkit_minus5_snacks': {'Blinkit': np.where(snack, -0.05, 0.0)},
        'P3_instamart_minus3_all': {'Swiggy Instamart': np.full(K, -0.03)},
    }
    rows = []
    for name, cut in scen.items():
        for respond in (False, True):
            r = W.simulate(cut, horizon=HORIZON, n_sims=N_SIMS, respond=respond, seed=11)
            for j, p in enumerate(PLATFORMS):
                b0 = base['cheapest_share'][:, :, j].mean(1)
                b1 = r['cheapest_share'][:, :, j].mean(1)
                rows.append({'scenario': name, 'view': 'strategic (fitted response)' if respond else 'static (no response)',
                             'platform': p, 'cheapest_share_base': float(b0.mean()), 'cheapest_share': band(b1),
                             'change_pp': band(100 * (b1 - b0)), 'mean_rank': float(r['mean_rank'][:, :, j].mean()),
                             'mean_rank_base': float(base['mean_rank'][:, :, j].mean()),
                             'final_price_move_pct': float(100 * r['final_mean_move'][:, j].mean())})
        print(f"  {name} done")
    # response over time for P1 strategic, for the figure
    r = W.simulate(scen['P1_blinkit_minus3_all'], horizon=HORIZON, n_sims=N_SIMS, respond=True, seed=11)
    s = W.simulate(scen['P1_blinkit_minus3_all'], horizon=HORIZON, n_sims=N_SIMS, respond=False, seed=11)
    path = {'strategic': r['cheapest_share'][:, :, 0].mean(0).tolist(), 'static': s['cheapest_share'][:, :, 0].mean(0).tolist(),
            'base': base['cheapest_share'][:, :, 0].mean(0).tolist()}
    return out, pd.DataFrame(rows), path


def stock_scenarios(W: StockWorld, st: pd.DataFrame):
    ml = L.load_ml()
    act = ml[ml.split == 'test'].groupby('observed_at').in_stock.mean().rsub(1).sort_index().to_numpy()[:HORIZON]
    base = W.simulate(st, horizon=HORIZON, n_sims=N_SIMS, seed=7)
    val = {'simulated_oos_path': base['oos_share_path'].mean(0).tolist(), 'actual_test_oos_path': act.tolist(),
           'mean_abs_gap_pp': float(100 * np.abs(base['oos_share_path'].mean(0) - act).mean())}
    rows = []
    snack_blk = ((st.category == 'Snacks & Munchies') & (st.platform == 'Blinkit')).to_numpy()
    dd = np.where(snack_blk, 0.10, 0.0)
    s1 = W.simulate(st, horizon=HORIZON, n_sims=N_SIMS, seed=7, depth_delta=dd)
    b_seg = base['per_listing_oos_rate'][snack_blk].mean(); s_seg = s1['per_listing_oos_rate'][snack_blk].mean()
    eta = W.eta_shift(0.10, s_seg - b_seg)
    rows.append({'scenario': 'S1_blinkit_snacks_promo_plus10pp', 'segment': 'Blinkit x Snacks & Munchies',
                 'listings': int(snack_blk.sum()), 'oos_rate_base': float(b_seg), 'oos_rate': float(s_seg),
                 'oos_change_pp': float(100 * (s_seg - b_seg)), 'availability_change_pp': float(-100 * (s_seg - b_seg)),
                 'eta_change_minutes_on_promoted_listings': eta['from_discount_depth'],
                 'eta_note': 'listing-level discount term (3.88 min per 100% depth, deliverable 5)'})
    blk_stores = st[st.platform == 'Blinkit'].store_id.value_counts()
    store = blk_stores.index[0]
    s2 = W.simulate(st, horizon=HORIZON, n_sims=N_SIMS, seed=7, pressure_shock={store: (2.0, 2)})
    m = (st.store_id == store).to_numpy()
    s_rate = s2['per_listing_oos_rate'][m].mean(); b_rate = base['per_listing_oos_rate'][m].mean()
    eta2 = W.eta_shift(0.0, s_rate - b_rate)
    rows.append({'scenario': 'S2_demand_surge_one_blinkit_store', 'segment': f'store {store} (+2 sd for 2 snapshots)',
                 'listings': int(m.sum()), 'oos_rate_base': float(b_rate), 'oos_rate': float(s_rate),
                 'oos_change_pp': float(100 * (s_rate - b_rate)), 'availability_change_pp': float(-100 * (s_rate - b_rate)),
                 'eta_change_minutes_via_oos_share': eta2['from_store_oos_share'],
                 'eta_direct_demand_minutes': 'about +1.4 per sd while the surge lasts (b_demand, deliverable 5 state-space)',
                 'eta_note': eta2['note']})
    return val, pd.DataFrame(rows)


def main():
    print('price world ...')
    PW = PriceWorld.load()
    val_p, price_rows, path = price_scenarios(PW)
    print(json.dumps(val_p, indent=1))
    print('stock world ...')
    SW = StockWorld.load(); st = SW.initial_state()
    val_s, stock_rows = stock_scenarios(SW, st)
    print(price_rows[price_rows.platform == 'Blinkit'][['scenario', 'view', 'cheapest_share_base']].assign(
        after=price_rows.cheapest_share.map(lambda d: round(d['mean'], 4))).to_string())
    print(stock_rows.to_string())

    # contract: one prediction row per (scenario, view, platform) anchored to a real observation key of the panel
    ml_keys = L.load_ml(with_targets=False)[['observation_key', 'data_status', 'platform', 'split']]
    anchors = ml_keys[(ml_keys.data_status == 'SYNTHETIC') & (ml_keys.split == 'test')].groupby('platform').observation_key.first()
    pred = price_rows.assign(observation_key=price_rows.platform.map(anchors), data_status='SYNTHETIC',
                             prediction=price_rows.cheapest_share.map(lambda d: d['mean']),
                             cheapest_share=price_rows.cheapest_share.map(json.dumps),
                             change_pp=price_rows.change_pp.map(json.dumps))
    metrics = {
        'claim_limit': ('SYNTHETIC. What-ifs under the fitted, generated dynamics: price rank, cheapest-of-4 share, '
                        'availability and ETA only. Never demand, orders, GMV or revenue; no order data exists.'),
        'validation': {'cheapest_share': val_p['validation_cheapest_share'], 'oos_path': val_s},
        'price_scenarios': price_rows.to_dict(orient='records'),
        'stock_scenarios': stock_rows.to_dict(orient='records'),
        'p1_blinkit_cheapest_share_path': path,
        'n_sims': N_SIMS, 'horizon_snapshots': HORIZON,
        'assumption': ('a platform\'s price move is a persistent shift of its latent price that others respond to via '
                       'the fitted response (deliverable 9); stock and ETA via deliverables 7, 8, 5'),
    }
    save_model_outputs('simulate_whatif', pred,
                       params={'engine': 'src/simulate/engine.py', 'n_sims': N_SIMS, 'horizon': HORIZON,
                               'inputs': ['price_response', 'stockout_survival', 'restock_interval', 'eta_forecast']},
                       metrics=metrics, training_data=ml_keys[ml_keys.split == 'train'].assign(snapshot_date=''),
                       split={'uses': 'fitted model outputs; initial stock state = last val snapshot'},
                       target='cheapest-of-4 share / availability / ETA under a scenario',
                       notes='Deliverable 11. SYNTHETIC ONLY. Positioning what-ifs, never demand.')
    _figure(path, price_rows, val_s)


def _figure(path, rows, val_s):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from src.model_output import MODELS_DIR
    ink, muted, grid = '#1f2328', '#6e7781', '#d0d7de'
    fig, ax = plt.subplots(1, 3, figsize=(16, 5))
    fig.suptitle('Deliverable 11 · SIMULATE  —  what-ifs under the fitted, generated dynamics (SYNTHETIC; never demand)',
                 fontsize=12, color=ink, x=0.01, ha='left')
    a = ax[0]
    h = np.arange(1, HORIZON + 1)
    a.plot(h, val_s['actual_test_oos_path'], 'o-', color=ink, label='actual test OOS share')
    a.plot(h, val_s['simulated_oos_path'], 's--', color='#0969da', label='engine, no scenario')
    a.set_xlabel('snapshot of the test period'); a.set_ylabel('share of listings out of stock')
    a.set_title('A · validation: the engine reproduces the status quo', fontsize=10, loc='left'); a.legend(frameon=False, fontsize=8.5)
    a = ax[1]
    a.plot(h, path['base'], color=muted, label='no change')
    a.plot(h, path['static'], 's--', color='#bc4c00', label='Blinkit −3%, competitors frozen')
    a.plot(h, path['strategic'], 'o-', color='#0969da', label='Blinkit −3%, fitted competitor response')
    a.set_xlabel('snapshots after the move'); a.set_ylabel('Blinkit cheapest-of-4 share')
    a.set_title('B · the static view overstates the gain', fontsize=10, loc='left'); a.legend(frameon=False, fontsize=8.5)
    a = ax[2]
    sub = rows[rows.platform.isin(['Blinkit', 'Swiggy Instamart'])]
    lab = sub.scenario.str.split('_').str[0] + ' ' + sub.platform.str.split().str[0] + '\n' + sub.view.str.split().str[0]
    vals = sub.change_pp.map(lambda d: d['mean'])
    a.barh(lab, vals, color=np.where(sub.view.str.startswith('static'), '#bc4c00', '#0969da'))
    a.axvline(0, color=grid)
    a.set_xlabel('change in cheapest-of-4 share (pp)'); a.tick_params(axis='y', labelsize=7.5)
    a.set_title('C · every price scenario, static vs strategic', fontsize=10, loc='left')
    for a in ax:
        a.spines[['top', 'right']].set_visible(False); a.grid(color=grid, lw=0.5, alpha=0.6); a.set_axisbelow(True)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    d = MODELS_DIR / 'simulate_whatif' / 'figures'; d.mkdir(exist_ok=True)
    fig.savefig(d / 'simulate_whatif.png', dpi=130); plt.close(fig)


if __name__ == '__main__':
    main()
