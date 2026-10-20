"""
stockout_classifier.py — deliverable 4, next-snapshot stock state (`future_stock`). SYNTHETIC.

    python -m src.features.stock_clock        # once: builds the past-only stock-clock features
    python -m src.models.stockout_classifier

WHAT THIS MAY AND MAY NOT CLAIM
  Every row with a `future_stock` is SYNTHETIC (CLAUDE.md section 2). Results show the modelling pipeline
  recovers the v15.1 generator's planted stock dynamics (docs/GENERATOR_v15_PARAMETERS.md A, B).
  They say nothing about real availability, real depletion or real restocking. Never "category X
  sells out faster": the category hazard scales are calibrated to a real prevalence that cannot
  separate depletion from replenishment.

METHOD — two heads, because stock-state change is two different processes
  DEPLETION head   rows in stock at t     P(out of stock at t+1)   the hazard
  RESTOCK head     rows out of stock at t P(back in stock at t+1)  the repair rate
  Both are LightGBM binary classifiers. P(future in stock) is assembled from them, so the combined
  forecast is scored like any single classifier. Features: L.feature_columns (IDs and targets refused;
  `platform` and `store_id` are identifiers and stay out) + `category` as a categorical + the
  stock-clock table (src/features/stock_clock.py), whose key column is the in-stock run length,
  the clock a duration-dependent hazard runs on and that the ML layer did not have.

THE BAR
  Persistence ("tomorrow's stock = today's") is right ~94% of the time and is useless as a
  probability. The honest baseline is a lookup table of transition rates learned on train:
    markov           P(change | state)
    markov_category  P(change | state, category)      <- the bar: the model must beat it on log loss
  An ablation (same LightGBM, stock-clock features removed) measures what the new features bought.

PLANTED-PARAMETER RECOVERY (pipeline check, never a market finding)
  A  hazard rises with the in-stock clock: discrete Weibull, planted k = 2 (frailty biases estimates down)
  A  evening snapshot multiplies the hazard increment 1.4 / 0.7 = 2.0x vs morning (counterfactual flip)
  B  restock: mean OOS spell by platform, planted order Blinkit < Instamart < BigBasket < Flipkart
"""
import json

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

import src.features.stock_clock as SC
import src.load as L
from src.model_output import MODELS_DIR, save_model_outputs

TARGET = 'future_stock'
NAME = 'stockout_classifier'
CATEGORICAL = ['category']
PARAMS = {
    'objective': 'binary',
    'learning_rate': 0.03,
    'num_leaves': 63,
    'min_data_in_leaf': 200,
    'feature_fraction': 0.8,
    'bagging_fraction': 0.8,
    'bagging_freq': 1,
    'lambda_l2': 5.0,
    'cat_smooth': 50,
    'num_threads': 0,
    'verbose': -1,
    'seed': 20260923,
}
NUM_BOOST_ROUND = 4000
EARLY_STOPPING = 150
ALERT_BUDGETS = (0.01, 0.05, 0.10)
EPS = 1e-6

# planted values, docs/GENERATOR_v15_PARAMETERS.md (assumptions, not real)
PLANTED = {'weibull_k': 2.0, 'evening_vs_morning_m': 1.4 / 0.7,
           'restock_platform_order': ['Blinkit', 'Swiggy Instamart', 'BigBasket', 'Flipkart Minutes'],
           'restock_platform_multiplier': {'Blinkit': 0.85, 'Swiggy Instamart': 0.90,
                                           'BigBasket': 1.15, 'Flipkart Minutes': 1.25}}


# --------------------------------------------------------------------------- helpers
def _prep(d, feats):
    X = d[feats].copy()
    for c in CATEGORICAL:
        X[c] = pd.Categorical(X[c].astype(str), categories=CAT_LEVELS[c])
    return X


def _fit(train, val, feats, label):
    dtr = lgb.Dataset(_prep(train, feats), label=label(train), categorical_feature=CATEGORICAL,
                      free_raw_data=False)
    dva = lgb.Dataset(_prep(val, feats), label=label(val), reference=dtr,
                      categorical_feature=CATEGORICAL)
    b = lgb.train(PARAMS, dtr, NUM_BOOST_ROUND, valid_sets=[dva], valid_names=['val'],
                  callbacks=[lgb.early_stopping(EARLY_STOPPING, verbose=False),
                             lgb.log_evaluation(500)])
    return b


def _predict(b, d, feats):
    return b.predict(_prep(d, feats), num_iteration=b.best_iteration)


def _clip(p):
    return np.clip(np.asarray(p, float), EPS, 1 - EPS)


def event_metrics(y, p) -> dict:
    y, p = np.asarray(y, int), _clip(p)
    return {'log_loss': float(log_loss(y, p, labels=[0, 1])), 'brier': float(brier_score_loss(y, p)),
            'roc_auc': float(roc_auc_score(y, p)), 'pr_auc': float(average_precision_score(y, p)),
            'base_rate': float(y.mean()), 'n': int(len(y))}


def ece(y, p, bins=15) -> float:
    """Expected calibration error on quantile bins."""
    y, p = np.asarray(y, float), np.asarray(p, float)
    q = pd.qcut(p, bins, labels=False, duplicates='drop')
    t = pd.DataFrame({'y': y, 'p': p, 'q': q}).groupby('q').agg(y=('y', 'mean'), p=('p', 'mean'), n=('y', 'size'))
    return float((t.n * (t.y - t.p).abs()).sum() / t.n.sum())


def markov_tables(train):
    tr = train.assign(_chg=(train.in_stock != train[TARGET]).astype(int))
    by_state = tr.groupby('in_stock')._chg.mean()
    by_cat = tr.groupby(['in_stock', 'category'])._chg.agg(['sum', 'count'])
    # shrink small categories toward the state mean (50 pseudo-rows)
    prior = by_cat.index.get_level_values(0).map(by_state)
    by_cat['rate'] = (by_cat['sum'] + 50 * prior.values) / (by_cat['count'] + 50)
    return by_state, by_cat['rate']


def markov_predict(d, by_state, by_cat, use_category):
    if use_category:
        idx = pd.MultiIndex.from_arrays([d.in_stock.to_numpy(), d.category.to_numpy()])
        chg = pd.Series(by_cat.reindex(idx).to_numpy(), index=d.index)
        chg = chg.fillna(d.in_stock.map(by_state))
    else:
        chg = d.in_stock.map(by_state)
    return np.where(d.in_stock == 1, chg, np.nan), np.where(d.in_stock == 0, chg, np.nan)


def discrete_weibull(r, c, k):
    return 1 - np.exp(-c * (r ** k - (r - 1) ** k))


def fit_k(r, h, w):
    (c, k), cov = curve_fit(discrete_weibull, r, h, p0=[0.001, 1.5], sigma=1 / np.sqrt(w),
                            bounds=([1e-8, 0.2], [1.0, 6.0]), maxfev=20000)
    return float(c), float(k), float(np.sqrt(cov[1, 1]))


def capture_at_budget(y, score, budget):
    n = max(1, int(round(len(y) * budget)))
    top = np.argsort(-np.asarray(score))[:n]
    caught = float(np.asarray(y)[top].sum() / max(1, np.asarray(y).sum()))
    return {'budget': budget, 'alerts': n, 'capture': caught, 'lift': caught / budget,
            'precision': float(np.asarray(y)[top].mean())}


# --------------------------------------------------------------------------- main
def main():
    global CAT_LEVELS
    ml = SC.attach(L.load_ml())
    train, val, test = L.splits(ml, TARGET)
    for part, name in ((train, 'train'), (val, 'val'), (test, 'test')):
        assert part.data_status.eq('SYNTHETIC').all(), f"{name} unexpectedly contains REAL rows"
    CAT_LEVELS = {c: sorted(train[c].astype(str).unique()) for c in CATEGORICAL}

    base_feats = L.feature_columns(train)
    base_feats = [f for f in base_feats if f not in SC.NEW_COLUMNS]
    full_feats = L.check_feature_set(base_feats + SC.NEW_COLUMNS + CATEGORICAL)
    ablation_feats = L.check_feature_set(base_feats + CATEGORICAL)

    parts = {'train': train, 'val': val, 'test': test}
    dep = {k: v[v.in_stock == 1] for k, v in parts.items()}
    rst = {k: v[v.in_stock == 0] for k, v in parts.items()}
    y_dep = lambda d: (d[TARGET] == 0).astype(int)   # event = goes out of stock
    y_rst = lambda d: (d[TARGET] == 1).astype(int)   # event = comes back

    # ---- fit: full model and ablation, both heads
    heads = {}
    for tag, feats in (('full', full_feats), ('ablation', ablation_feats)):
        print(f"\n--- {tag}: depletion head ({len(dep['train']):,} rows)")
        bd = _fit(dep['train'], dep['val'], feats, y_dep)
        print(f"--- {tag}: restock head ({len(rst['train']):,} rows)")
        br = _fit(rst['train'], rst['val'], feats, y_rst)
        heads[tag] = (bd, br, feats)

    # ---- scoring on test
    by_state, by_cat = markov_tables(train)
    y_test = test[TARGET].astype(int).to_numpy()
    yd, yr = y_dep(dep['test']).to_numpy(), y_rst(rst['test']).to_numpy()

    def combined(p_dep, p_rst):
        """P(future in stock) for every test row from the two heads."""
        return np.where(test.in_stock == 1, 1 - p_dep, p_rst)

    preds, results = {}, {}
    for tag, (bd, br, feats) in heads.items():
        pd_ = np.full(len(test), np.nan); pr_ = np.full(len(test), np.nan)
        m1 = (test.in_stock == 1).to_numpy()
        pd_[m1] = _predict(bd, test[m1], feats); pr_[~m1] = _predict(br, test[~m1], feats)
        preds[tag] = (pd_, pr_)
    for tag, use_cat in (('markov', False), ('markov_category', True)):
        preds[tag] = markov_predict(test, by_state, by_cat, use_cat)

    m1 = (test.in_stock == 1).to_numpy()
    for tag, (pd_, pr_) in preds.items():
        pin = combined(pd_, pr_)
        results[tag] = {
            'overall': {'log_loss': float(log_loss(y_test, _clip(pin))),
                        'brier': float(brier_score_loss(y_test, pin)),
                        'roc_auc': float(roc_auc_score(y_test, pin)),
                        'accuracy_at_0.5': float(((pin >= 0.5) == y_test).mean()),
                        'ece': ece(y_test, pin)},
            'depletion': {**event_metrics(yd, pd_[m1]), 'ece': ece(yd, pd_[m1])},
            'restock': {**event_metrics(yr, pr_[~m1]), 'ece': ece(yr, pr_[~m1])},
        }
    results['persistence'] = {'overall': {
        'brier': float(brier_score_loss(y_test, test.in_stock.astype(float))),
        'accuracy_at_0.5': float((test.in_stock.to_numpy() == y_test).mean()),
        'log_loss': 'infinite (hard 0/1 probabilities)'}}

    bar = results['markov_category']
    full = results['full']
    beats = {h: full[h]['log_loss'] < bar[h]['log_loss'] for h in ('overall', 'depletion', 'restock')}
    skill = {h: 1 - full[h]['log_loss'] / bar[h]['log_loss'] for h in ('overall', 'depletion', 'restock')}
    ablation_gain = {h: 1 - full[h]['log_loss'] / results['ablation'][h]['log_loss']
                     for h in ('overall', 'depletion', 'restock')}
    verdict = ('USEFUL: beats the markov_category transition table on test log loss for the '
               'combined forecast and both heads.' if all(beats.values()) else
               f'NOT USEFUL on every head by the project bar: beats = {beats}. Report as such.')

    # ---- decision layer: a stock-out radar with a fixed alert budget
    p_full_dep, p_mc_dep = preds['full'][0][m1], preds['markov_category'][0][m1]
    radar = {'model': [capture_at_budget(yd, p_full_dep, b) for b in ALERT_BUDGETS],
             'markov_category': [capture_at_budget(yd, p_mc_dep, b) for b in ALERT_BUDGETS]}

    # ---- planted-parameter recovery (uncensored clocks only)
    td = test[m1].assign(p=p_full_dep, y=yd)
    unc = td[(td.instock_clock_censored == 0) & (td.instock_run_length <= 25)]
    curve = (unc.groupby('instock_run_length')
                .agg(empirical=('y', 'mean'), model=('p', 'mean'), n=('y', 'size')).reset_index())
    curve = curve[curve.n >= 200]
    r = curve.instock_run_length.to_numpy(float)
    c_e, k_e, se_e = fit_k(r, curve.empirical.to_numpy(), curve.n.to_numpy())
    c_m, k_m, se_m = fit_k(r, curve.model.to_numpy(), curve.n.to_numpy())

    bd, br, feats = heads['full']
    X = test[m1].copy()
    # hour and the schedule flag are locked together (09:00 -> next is 18:00); flip both, or the
    # counterfactual rows are ones the model never saw
    X_eve = X.assign(hour=9, next_snapshot_is_evening=1.0)
    X_mor = X.assign(hour=18, next_snapshot_is_evening=0.0)
    p_eve, p_mor = _predict(bd, X_eve, feats), _predict(bd, X_mor, feats)
    eve_ratio = float(p_eve.mean() / p_mor.mean())
    emp_eve = float(td[td.next_snapshot_is_evening == 1].y.mean() / td[td.next_snapshot_is_evening == 0].y.mean())

    # restock: model-implied mean OOS spell per platform from hazard by spell age
    tr_ = test[~m1].assign(p=preds['full'][1][~m1])
    spell = {}
    for plat, g in tr_.groupby('platform'):
        h = g.groupby('oos_run_length').p.mean().reindex(range(1, 31)).ffill().to_numpy()
        surv = np.concatenate([[1.0], np.cumprod(1 - h)[:-1]])
        spell[str(plat)] = {'model_implied_mean_spell': float(surv.sum()),
                            'observed_restock_rate': float(g[TARGET].mean()), 'n': int(len(g))}
    order = sorted(spell, key=lambda k: spell[k]['model_implied_mean_spell'])
    from scipy.stats import spearmanr
    rho = spearmanr([spell[p]['model_implied_mean_spell'] for p in PLANTED['restock_platform_order']],
                    [PLANTED['restock_platform_multiplier'][p] for p in PLANTED['restock_platform_order']]).statistic

    recovery = {
        'A_hazard_shape': {'planted_k': PLANTED['weibull_k'],
                           'k_hat_empirical': k_e, 'k_hat_empirical_se': se_e,
                           'k_hat_model': k_m, 'k_hat_model_se': se_m,
                           'h_run1_model': float(curve.model.iloc[0]),
                           'h_run_max_model': float(curve.model.iloc[-1]),
                           'max_run_used': int(r.max()),
                           'note': ('Uncensored clocks only. Unobserved product frailty (lognormal sd 0.25) '
                                    'and the category/platform scale mix bias pooled k downward, so k_hat '
                                    'below 2 but well above 1 is the expected recovery.')},
        'A_evening_multiplier': {'planted_m_ratio': PLANTED['evening_vs_morning_m'],
                                 'model_counterfactual_ratio': eve_ratio, 'empirical_ratio': emp_eve},
        'B_restock_by_platform': {'model_order_fast_to_slow': order,
                                  'planted_order_fast_to_slow': PLANTED['restock_platform_order'],
                                  'spearman_vs_planted_multiplier': float(rho), 'detail': spell},
    }

    # ---- what drives the hazard (mean |SHAP| on a test sample)
    samp = X.sample(min(20000, len(X)), random_state=0)
    contrib = bd.predict(_prep(samp, feats), num_iteration=bd.best_iteration, pred_contrib=True)
    shap = pd.Series(np.abs(contrib[:, :-1]).mean(0), index=feats).sort_values(ascending=False)

    metrics = {
        'verdict': verdict,
        'claim_limit': ('SYNTHETIC panel. These numbers show the pipeline recovers the v15.1 generator\'s '
                        'planted stock-out hazard and restock process. They are not findings about real '
                        'availability, depletion or restocking.'),
        'bar': 'markov_category (transition rate by current state x category, learned on train)',
        'test': results, 'beats_bar_on_log_loss': beats, 'log_loss_skill_vs_bar': skill,
        'log_loss_gain_from_stock_clock_features': ablation_gain,
        'stockout_radar': radar,
        'planted_parameter_recovery': recovery,
        'depletion_top_drivers_mean_abs_shap': {k: float(v) for k, v in shap.head(15).items()},
        'best_iteration': {'depletion': int(bd.best_iteration), 'restock': int(br.best_iteration)},
        'rows': {k: {'depletion': len(dep[k]), 'restock': len(rst[k])} for k in parts},
        'n_features': len(full_feats),
    }

    pd_full, pr_full = preds['full']
    pin = combined(pd_full, pr_full)
    out = pd.DataFrame({
        'observation_key': test.observation_key.to_numpy(),
        'data_status': test.data_status.to_numpy(),
        'platform': test.platform.to_numpy(),
        'store_id': test.store_id.to_numpy(),
        'category': test.category.to_numpy(),
        'snapshot_date': test.date.astype(str).to_numpy(),
        'hour': test.hour.to_numpy(),
        'in_stock_now': test.in_stock.to_numpy(),
        'instock_run_length': test.instock_run_length.to_numpy(),
        'prediction': pin,                               # P(in stock at t+1)
        'p_stockout_next': np.where(m1, pd_full, np.nan),
        'p_restock_next': np.where(~m1, pr_full, np.nan),
        'baseline_markov_category': combined(*preds['markov_category']),
        'actual_future_stock': y_test,
    })
    mdir = save_model_outputs(
        NAME, out,
        params={**PARAMS, 'num_boost_round': NUM_BOOST_ROUND, 'early_stopping': EARLY_STOPPING,
                'heads': {'depletion': 'rows in stock at t, event = OOS at t+1',
                          'restock': 'rows OOS at t, event = in stock at t+1'},
                'categorical': CATEGORICAL, 'extra_feature_table': 'data/ml/stock_clock.parquet',
                'library': f'lightgbm {lgb.__version__}'},
        metrics=metrics, training_data=train,
        split={'source': "pipeline 'split' column via src.load.splits", 'fit': 'train',
               'early_stopping_on': 'val', 'evaluated_on': 'test'},
        target=TARGET, feature_columns=full_feats,
        notes=('Deliverable 4. SYNTHETIC ONLY. Two-head hazard/restock classifier on the stock-clock '
               'features; scored against a category-aware Markov transition table and an ablation. '
               'Recovery of planted parameters is a pipeline check, not a market finding.'))
    bd.save_model(str(mdir / 'depletion_head.txt'), num_iteration=bd.best_iteration)
    br.save_model(str(mdir / 'restock_head.txt'), num_iteration=br.best_iteration)
    curve.to_csv(mdir / 'hazard_curve.csv', index=False)

    _figures(mdir, curve, c_e, k_e, c_m, k_m, yd, preds, m1, radar, shap)

    print('\n' + '=' * 72)
    for tag in ('persistence', 'markov', 'markov_category', 'ablation', 'full'):
        o = results[tag]['overall']
        print(f"{tag:>16}  logloss {o['log_loss'] if isinstance(o['log_loss'], str) else round(o['log_loss'], 4)}"
              f"  brier {o['brier']:.5f}")
    print(verdict)
    print(json.dumps({'skill': skill, 'ablation_gain': ablation_gain}, indent=1))
    print(json.dumps(recovery, indent=1, default=str))
    print(json.dumps(radar, indent=1))
    print(shap.head(10).round(4).to_string())


def _figures(mdir, curve, c_e, k_e, c_m, k_m, yd, preds, m1, radar, shap):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from sklearn.metrics import precision_recall_curve

    ink, muted, grid = '#1f2328', '#6e7781', '#d0d7de'
    c_model, c_base, c_emp = '#0969da', '#bc4c00', '#1a7f37'
    fig, ax = plt.subplots(2, 2, figsize=(13, 9.5))
    fig.suptitle('Deliverable 4 · stock-out classifier  —  SYNTHETIC panel (pipeline check, not a market finding)',
                 fontsize=12.5, color=ink, x=0.01, ha='left')

    a = ax[0, 0]
    r = curve.instock_run_length.to_numpy(float); rr = np.linspace(1, r.max(), 200)
    a.scatter(r, curve.empirical, s=22, color=c_emp, label='observed stock-out rate', zorder=3)
    a.plot(r, curve.model, color=c_model, lw=2, label='model mean P(stock-out)')
    a.plot(rr, discrete_weibull(rr, c_m, k_m), color=c_model, lw=1, ls='--',
           label=f'discrete Weibull fit to model  k̂ = {k_m:.2f}')
    a.set_title(f'A · hazard rises with the in-stock clock   (planted k = 2.0, empirical k̂ = {k_e:.2f})',
                fontsize=10, loc='left')
    a.set_xlabel('consecutive in-stock snapshots (uncensored clocks)'); a.set_ylabel('P(out of stock next)')
    a.legend(frameon=False, fontsize=8.5)

    a = ax[0, 1]
    for tag, col, lab in (('full', c_model, 'model'), ('ablation', muted, 'model w/o stock clock'),
                          ('markov_category', c_base, 'markov × category')):
        p = preds[tag][0][m1]
        pr, rc, _ = precision_recall_curve(yd, p)
        a.plot(rc, pr, color=col, lw=2 if tag == 'full' else 1.4,
               label=f'{lab}  AP = {average_precision_score(yd, p):.3f}')
    a.axhline(yd.mean(), color=grid, lw=1, ls=':')
    a.set_title('B · depletion head, precision–recall on test', fontsize=10, loc='left')
    a.set_xlabel('recall (share of next-snapshot stock-outs caught)'); a.set_ylabel('precision')
    a.legend(frameon=False, fontsize=8.5)

    a = ax[1, 0]
    p = preds['full'][0][m1]
    q = pd.qcut(p, 20, labels=False, duplicates='drop')
    cal = pd.DataFrame({'y': yd, 'p': p, 'q': q}).groupby('q').mean()
    lim = max(cal.p.max(), cal.y.max()) * 1.05
    a.plot([0, lim], [0, lim], color=grid, lw=1)
    a.plot(cal.p, cal.y, 'o-', color=c_model, ms=4)
    a.set_title('C · calibration, depletion head (20 quantile bins)', fontsize=10, loc='left')
    a.set_xlabel('predicted P(stock-out)'); a.set_ylabel('observed rate')

    a = ax[1, 1]
    top = shap.head(12)[::-1]
    a.barh(top.index, top.values, color=[c_model if i in SC.NEW_COLUMNS else muted for i in top.index])
    a.set_title('D · what drives the hazard (mean |SHAP|; blue = new stock-clock features)',
                fontsize=10, loc='left')
    a.tick_params(axis='y', labelsize=8.5)

    for a in ax.flat:
        a.spines[['top', 'right']].set_visible(False)
        a.grid(color=grid, lw=0.5, alpha=0.6)
        a.set_axisbelow(True)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    (mdir / 'figures').mkdir(exist_ok=True)
    fig.savefig(mdir / 'figures' / 'stockout_classifier.png', dpi=130)
    plt.close(fig)


if __name__ == '__main__':
    main()
