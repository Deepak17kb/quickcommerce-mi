"""
price_cut.py — deliverable 12a, OPTIMIZE: the smallest Blinkit price cut that reaches a target cheapest-of-4 share.
SYNTHETIC.

    python -m src.optimize.price_cut

WHAT THIS MAY AND MAY NOT CLAIM
  "Under the fitted, generated dynamics, the smallest uniform cut that makes Blinkit cheapest-of-4 on at least TARGET
  of a category's common-panel SKUs, averaged over the next 12 snapshots, is c." A positioning answer. It is not a
  profit- or revenue-optimal price: there is no demand or cost data, so the cost of the cut cannot be weighed.

METHOD
  For every category with at least MIN_KEYS common-panel SKUs, bisection over the cut c in [0, MAX_CUT] on the
  simulation engine (src/simulate/engine.py). All categories are searched in one pass: products of different
  categories never interact, so each simulation serves every category's bisection at once. Common random numbers
  keep the share monotone in c. Two views:
    static      competitors do not react (what a one-off price comparison would suggest)
    strategic   competitors respond with the fitted leader/follower response (deliverable 9)
  The gap between the two is the price of ignoring the response.
"""

import numpy as np
import pandas as pd

from src.model_output import load_model_outputs, save_model_outputs
from src.simulate.engine import PriceWorld

NAME = 'optimize_price_cut'
TARGET = 0.40
MAX_CUT = 0.25
MIN_KEYS = 30
N_ITER = 9
N_SIMS = 12
HORIZON = 12
SEED = 21


def per_category_share(W, cut_by_key, respond, cat_arr, cats):
    """Blinkit cheapest-of-4 share per category, averaged over horizon and simulations."""
    out = np.zeros(len(cats))
    res = W.simulate({'Blinkit': -cut_by_key}, horizon=HORIZON, n_sims=N_SIMS, respond=respond, seed=SEED,
                     param_uncertainty=False)
    flag = res['cheapest_by_key'][0]                 # Blinkit: share of snapshots x sims it is cheapest, per key
    for i, c in enumerate(cats):
        out[i] = np.nanmean(flag[cat_arr == c])
    return out


def main():
    W = PriceWorld.load()
    cat_arr = W.key_category.to_numpy()
    counts = pd.Series(cat_arr).value_counts()
    cats = sorted(counts[counts >= MIN_KEYS].index)
    base = per_category_share(W, np.zeros(W.n_keys), True, cat_arr, cats)
    print('base Blinkit cheapest share by category:', dict(zip(cats, base.round(3))))
    results = {}
    for respond in (False, True):
        lo, hi = np.zeros(len(cats)), np.full(len(cats), MAX_CUT)
        top = per_category_share(W, np.full(W.n_keys, MAX_CUT), respond, cat_arr, cats)
        reachable = top >= TARGET
        for it in range(N_ITER):
            mid = (lo + hi) / 2
            cut = np.zeros(W.n_keys)
            for i, c in enumerate(cats):
                cut[cat_arr == c] = mid[i]
            sh = per_category_share(W, cut, respond, cat_arr, cats)
            ok = sh >= TARGET
            hi = np.where(ok, mid, hi); lo = np.where(ok, lo, mid)
            print(f"  {'strategic' if respond else 'static'} iter {it + 1}/{N_ITER}")
        results['strategic' if respond else 'static'] = {'min_cut': np.where(reachable, hi, np.nan), 'share_at_max': top}
    rows = []
    for i, c in enumerate(cats):
        s_, g_ = results['static']['min_cut'][i], results['strategic']['min_cut'][i]
        rows.append({'category': c, 'common_panel_skus': int(counts[c]), 'blinkit_cheapest_share_now': float(base[i]),
                     'target': TARGET, 'min_cut_static_pct': None if np.isnan(s_) else float(100 * s_),
                     'min_cut_strategic_pct': None if np.isnan(g_) else float(100 * g_),
                     'strategic_over_static': None if (np.isnan(s_) or np.isnan(g_) or s_ == 0) else float(g_ / s_),
                     'already_at_target': bool(base[i] >= TARGET),
                     'reachable_within_max_cut_strategic': bool(not np.isnan(g_))})
    tab = pd.DataFrame(rows).sort_values('min_cut_strategic_pct')
    print(tab.round(3).to_string())
    ratio = tab.strategic_over_static.dropna()
    metrics = {
        'claim_limit': ('SYNTHETIC. The smallest cut that reaches a cheapest-share target under the fitted, generated '
                        'dynamics. A positioning answer, not a profit- or revenue-optimal price (no demand or cost data).'),
        'target_cheapest_share': TARGET, 'max_cut_searched': MAX_CUT, 'horizon_snapshots': HORIZON,
        'by_category': tab.to_dict(orient='records'),
        'median_strategic_over_static': float(ratio.median()) if len(ratio) else None,
        'headline': (f"Ignoring competitor response understates the cut needed: median {ratio.median():.2f}x "
                     f"deeper once followers react (fitted response, deliverable 9)." if len(ratio) else None),
    }
    anchors = load_model_outputs('price_response')['predictions']
    anchors = anchors[anchors.platform == 'Swiggy Instamart'].observation_key.iloc[0]
    pred = tab.assign(observation_key=anchors, data_status='SYNTHETIC',
                      prediction=tab.min_cut_strategic_pct.astype(float))
    save_model_outputs(NAME, pred, params={'target': TARGET, 'max_cut': MAX_CUT, 'bisection_iters': N_ITER,
                                           'n_sims': N_SIMS, 'engine': 'src/simulate/engine.py (price world)'},
                       metrics=metrics, training_data=pred.assign(snapshot_date=''),
                       split={'uses': 'fitted price_response outputs'}, target='minimum Blinkit price cut per category',
                       notes='Deliverable 12a. SYNTHETIC ONLY. Positioning optimum, never profit.')
    _figure(tab)
    print(metrics['headline'])


def _figure(tab):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from src.model_output import MODELS_DIR
    t = tab.dropna(subset=['min_cut_strategic_pct']).sort_values('min_cut_strategic_pct')
    fig, a = plt.subplots(figsize=(10, 0.36 * len(t) + 1.8))
    y = np.arange(len(t))
    a.barh(y + 0.2, t.min_cut_static_pct, 0.4, color='#bc4c00', label='static (competitors frozen)')
    a.barh(y - 0.2, t.min_cut_strategic_pct, 0.4, color='#0969da', label='strategic (fitted response)')
    a.set_yticks(y); a.set_yticklabels(t.category, fontsize=8.5)
    a.set_xlabel(f'smallest Blinkit price cut (%) to be cheapest-of-4 on {TARGET:.0%} of SKUs')
    a.set_title('Deliverable 12a · OPTIMIZE price cut  —  SYNTHETIC; a positioning answer, not a profit optimum',
                fontsize=10.5, loc='left')
    a.legend(frameon=False, fontsize=8.5); a.spines[['top', 'right']].set_visible(False)
    a.grid(axis='x', color='#d0d7de', lw=0.5)
    fig.tight_layout()
    d = MODELS_DIR / NAME / 'figures'; d.mkdir(exist_ok=True)
    fig.savefig(d / 'price_cut.png', dpi=130); plt.close(fig)


if __name__ == '__main__':
    main()
