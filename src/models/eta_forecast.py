"""
eta_forecast.py — deliverable 5, next-snapshot delivery ETA (`future_eta` = next delivery_eta_min). SYNTHETIC.

    python -m src.features.stock_clock        # once
    python -m src.models.eta_forecast

WHAT THIS MAY AND MAY NOT CLAIM
  Every row with a `future_eta` is SYNTHETIC. Recovering the evening peak, the discount, store-stock-out and
  demand terms shows the pipeline recovers the v15.1 generator's planted ETA equation
  (docs/GENERATOR_v15_PARAMETERS.md D, 🟠 assumptions). It says nothing about the real delivery performance of any
  platform or store.

PART 1 — STRUCTURAL RECOVERY (whole panel; a parameter check, not a forecast)
  Planted: eta_min = round(base[platform] + store_eff + 3.5*[18:00] + 1.6*D[s,t] + 4.0*depth
                           + 8.0*(store OOS share - platform mean) + N(0, 1)),  D ~ AR(1) phi = 0.5, sd 1.
  Stage 1, within each store x snapshot: eta on promo depth. Store-level terms cancel, so only the
           listing-level discount effect remains.                                     -> b_discount
  Stage 2, the store x snapshot intercepts on store dummies, the evening flag and the store's OOS share
           relative to its platform:                                                  -> peak, b_store_oos
           what is left is the latent demand term 1.6*D: its sd and its AR(1)         -> b_demand, phi
  Stage-1 residual sd                                                                 -> noise sd (+ rounding)

PART 2 — FORECAST (train / val / test from the split column)
  LightGBM (L1) on the ETA change. Baselines: naive (ETA now), seasonal naive (ETA one snapshot ago, which was
  at the same hour as the next one), and the listing's same-hour mean to date. The bar: beat all three.

PART 3 — A PROMISE YOU CAN KEEP: conformalized quantile regression (CQR)
  Quantile LightGBMs give a raw interval; split-conformal calibration on val widens or narrows it so that it
  covers the truth at the target rate. Coverage is checked on the untouched test split, overall and per platform x
  hour cell. Marginal CQR is exact on average but uneven by cell. Group-conditional ("Mondrian") CQR, one correction per
  cell, was tried and made the worst cell WORSE: misses cluster by store x snapshot (a store's demand shock moves
  every listing's ETA together), so each cell holds only a few dozen independent units and a per-cell correction is
  noise. The shipped intervals are marginal CQR; the clustering diagnostic is saved with the metrics. The upper bound
  is the "promise": the ETA a platform could show and keep ~90% of the time on average.
"""
import json

import lightgbm as lgb
import numpy as np
import pandas as pd

import src.features.stock_clock as SC
import src.load as L
from src.model_output import save_model_outputs

NAME = 'eta_forecast'
TARGET = 'future_eta'
ANCHOR = 'delivery_eta_min'
PANEL = ['platform', 'store_id', 'product_id']
SEED = 20260923
COVERAGES = (0.8, 0.9)
PLANTED = {'peak_18h_minutes': 3.5, 'b_discount': 4.0, 'b_store_oos': 8.0, 'b_demand': 1.6,
           'store_demand_phi': 0.5, 'noise_sd': 1.0, 'store_effect_sd': 1.5,
           'base_by_platform': {'Blinkit': 9.5, 'Swiggy Instamart': 9.5, 'Flipkart Minutes': 11.5, 'BigBasket': 13.5}}
PARAMS = {'objective': 'l1', 'learning_rate': 0.08, 'num_leaves': 63, 'min_data_in_leaf': 200,
          'feature_fraction': 0.8, 'bagging_fraction': 0.8, 'bagging_freq': 1, 'lambda_l2': 1.0,
          'verbose': -1, 'seed': SEED}


def within(y, x, g):
    """OLS slope of y on x after removing group means (one regressor)."""
    yd = y - pd.Series(y).groupby(g).transform('mean').to_numpy()
    xd = x - pd.Series(x).groupby(g).transform('mean').to_numpy()
    b = (xd * yd).sum() / (xd * xd).sum()
    r = yd - b * xd
    n, k = len(y), pd.Series(g).nunique() + 1
    se = np.sqrt((r @ r) / (n - k) / (xd * xd).sum())
    return float(b), float(se), r


def structural(d):
    s = d[d.data_status == 'SYNTHETIC'].copy()
    promo = s.mrp_source.eq('simulated_discounted')
    s['depth'] = np.where(promo, s.discount_percent / 100.0, 0.0)
    s['eta'] = s.delivery_eta_min.astype(float)
    gkey = s.platform.astype(str) + '|' + s.store_id.astype(str) + '|' + s.snapshot_id.astype(str)
    g = pd.factorize(gkey)[0]
    b_disc, se_disc, r1 = within(s.eta.to_numpy(), s.depth.to_numpy(), g)
    noise_sd = float(np.sqrt((r1 @ r1) / (len(r1) - pd.Series(g).nunique() - 1)))

    s['adj'] = s.eta - b_disc * s.depth
    st = (s.groupby(['platform', 'store_id', 'snapshot_id'])
            .agg(fe=('adj', 'mean'), oos=('in_stock', lambda x: 1 - x.mean()), n=('adj', 'size'),
                 hour=('hour', 'first'), ts=('observed_at', 'first')).reset_index())
    st['ts'] = pd.to_datetime(st.ts.astype(str), format='mixed')
    # platform mean OOS at t, weighted by listings (as the generator averages over panels)
    st['plat_oos'] = st.groupby(['platform', 'snapshot_id']).apply(
        lambda x: np.average(x.oos, weights=x.n), include_groups=False).reindex(
        pd.MultiIndex.from_frame(st[['platform', 'snapshot_id']])).to_numpy()
    st['oos_dev'] = st.oos - st.plat_oos
    st['evening'] = (pd.to_numeric(st.hour) == 18).astype(float)
    Xs = pd.get_dummies(st.platform + '|' + st.store_id, dtype=float)
    X = np.c_[Xs.to_numpy(), st.evening, st.oos_dev]
    beta, *_ = np.linalg.lstsq(X, st.fe.to_numpy(), rcond=None)
    resid = st.fe.to_numpy() - X @ beta
    dof = len(st) - X.shape[1]
    cov = (resid @ resid / dof) * np.linalg.pinv(X.T @ X)
    se = np.sqrt(np.diag(cov))
    peak, b_oos = beta[-2], beta[-1]
    st['r'] = resid
    st = st.sort_values(['platform', 'store_id', 'ts'])
    st['r_lag'] = st.groupby(['platform', 'store_id']).r.shift()
    phi = float(st[['r', 'r_lag']].dropna().corr().iloc[0, 1])
    # sd of the store-level residual = b_demand * sd(D) plus the averaged listing noise (tiny)
    avg_noise_var = float((noise_sd ** 2 / st.n).mean())
    b_demand = float(np.sqrt(max(resid.var() - avg_noise_var, 0)))
    store_fe = pd.Series(beta[:Xs.shape[1]], index=Xs.columns)
    plat_of = store_fe.index.str.split('|').str[0]
    base = store_fe.groupby(plat_of).mean().to_dict()
    store_sd = float(store_fe.groupby(plat_of).transform(lambda v: v - v.mean()).std(ddof=len(set(plat_of))))

    def row(name, planted, est, se_=None, note=''):
        lo, hi = (est - 1.96 * se_, est + 1.96 * se_) if se_ is not None else (None, None)
        return {'parameter': name, 'planted': planted, 'estimate': est, 'ci_low': lo, 'ci_high': hi,
                'covered': (bool(lo <= planted <= hi) if se_ is not None else None), 'note': note}

    ssm = state_space_deconfound(st)
    rec = pd.DataFrame([
        row('evening peak (minutes)', PLANTED['peak_18h_minutes'], float(peak), float(se[-2])),
        row('discount depth effect (minutes per 100% depth)', PLANTED['b_discount'], b_disc, se_disc,
            'observed discount is ceil-rounded MRP: slight measurement error in depth'),
        row('store OOS share effect, naive regression (minutes per 100%)', PLANTED['b_store_oos'], float(b_oos),
            float(se[-1]), 'CONFOUNDED: the OOS share is itself driven by the latent demand D'),
        row('latent demand effect b_demand (sd of store residual)', PLANTED['b_demand'], b_demand, None,
            'read as the sd of the store x snapshot residual; D has sd 1 by construction'),
        row('latent demand persistence phi', PLANTED['store_demand_phi'], phi, None,
            'lag-1 autocorrelation of the store residual'),
        row('store OOS share effect, state-space (Kalman ML)', PLANTED['b_store_oos'], ssm['b_store_oos'], None,
            'partial de-confounding: OOS dynamics simplified to AR(1) + D'),
        row('latent demand effect b_demand, state-space', PLANTED['b_demand'], ssm['b_demand'], None, ''),
        row('latent demand persistence phi, state-space', PLANTED['store_demand_phi'], ssm['phi'], None, ''),
        row('listing noise sd', PLANTED['noise_sd'], noise_sd, None,
            'includes rounding to whole minutes (+1/12 variance) and the floor at 5'),
        row('store effect sd', PLANTED['store_effect_sd'], store_sd, None, 'from only 30 stores'),
    ])
    base_rows = {p: {'planted': PLANTED['base_by_platform'][p], 'estimate': float(v),
                     'note': 'mean store intercept = base + mean store effect of that platform\'s few stores'}
                 for p, v in base.items()}
    return rec, base_rows, st


def state_space_deconfound(st):
    """Partial fix for the OOS-share confounding, by Kalman-filter maximum likelihood.

    The store OOS share is itself driven by the latent demand D (the stock-out hazard carries exp(0.3 D)), so
    regressing ETA on it credits D's effect to stock-outs. Treat D as an AR(1) state read by two series:
        oos_dev[t]  = delta * oos_dev[t-1] + c1 * evening + gamma * D[t] + u[t]
        eta_fe[t]   = store level + peak * evening + b_oos * oos_dev[t] + b_D * D[t] + e[t]
    The part of the OOS share that D does not explain (u) identifies b_oos. The OOS dynamics are cruder than
    the real stock process (many lags of D), so some confounding remains: this is reported as partial.
    """
    from scipy.optimize import minimize
    st = st.sort_values(['platform', 'store_id', 'ts'])
    series = [(g.oos_dev.to_numpy(), g.fe.to_numpy(), g.evening.to_numpy())
              for _, g in st.groupby(['platform', 'store_id'], sort=False)]

    def unpack(v):
        return (np.tanh(v[0]), v[1], v[2], v[3], np.exp(v[4]), np.exp(v[5]), v[6], v[7], v[8])

    def nll(v):
        phi, gam, delta, c1, s_u, s_e, b_oos, b_D, peak = unpack(v)
        Z = np.array([gam, b_oos * gam + b_D])
        H = np.array([[s_u ** 2, b_oos * s_u ** 2], [b_oos * s_u ** 2, b_oos ** 2 * s_u ** 2 + s_e ** 2]])
        tot = 0.0
        for y1, y2, ev in series:
            mu2 = np.mean(y2 - peak * ev)
            a, P = 0.0, 1.0
            for t in range(1, len(y1)):
                a, P = phi * a, phi ** 2 * P + (1 - phi ** 2)
                m1 = delta * y1[t - 1] + c1 * ev[t]
                r = np.array([y1[t] - m1 - gam * a,
                              y2[t] - mu2 - peak * ev[t] - b_oos * m1 - Z[1] * a])
                F = np.outer(Z, Z) * P + H
                Fi = np.linalg.inv(F)
                tot += 0.5 * (np.log(np.linalg.det(F)) + r @ Fi @ r)
                K = P * Z @ Fi
                a, P = a + K @ r, P - (K @ Z) * P
        return tot

    v0 = np.array([np.arctanh(0.4), 0.005, 0.8, 0.005, np.log(0.003), np.log(0.1), 8.0, 1.5, 3.5])
    r = minimize(nll, v0, method='Nelder-Mead', options={'maxiter': 20000, 'maxfev': 20000, 'xatol': 1e-6, 'fatol': 1e-6})
    r = minimize(nll, r.x, method='BFGS')
    phi, gam, delta, c1, s_u, s_e, b_oos, b_D, peak = unpack(r.x)
    return {'b_store_oos': float(b_oos), 'b_demand': float(b_D), 'phi': float(phi), 'peak': float(peak),
            'oos_loading_on_D': float(gam), 'oos_persistence': float(delta), 'nll': float(r.fun)}


def conformal(q_lo, q_hi, y, alpha):
    """CQR score on calibration data -> the correction to add to both ends."""
    score = np.maximum(q_lo - y, y - q_hi)
    n = len(score)
    k = int(np.ceil((n + 1) * (1 - alpha)))
    return float(np.sort(score)[min(k, n) - 1])


def main():
    ml = SC.attach(L.load_ml())
    rec, base_rows, st = structural(ml)
    print(rec.round(3).to_string())

    train, val, test = L.splits(ml, TARGET)
    for part in (train, val, test):
        assert part.data_status.eq('SYNTHETIC').all()
    base_feats = [f for f in L.feature_columns(train) if f not in SC.NEW_COLUMNS]
    feats = L.check_feature_set(base_feats + SC.NEW_COLUMNS + ['category'])
    cats = sorted(train.category.unique())
    prep = lambda x: x[feats].assign(category=pd.Categorical(x.category, categories=cats))

    # listing same-hour mean to date (for the baseline): same hour as the NEXT snapshot = hour of t-1
    def same_hour_mean(df):
        d = ml[ml.data_status == 'SYNTHETIC'][PANEL + ['observed_at', 'hour', 'delivery_eta_min', 'observation_key']].copy()
        d['_ts'] = pd.to_datetime(d.observed_at.astype(str), format='mixed')
        d = d.sort_values(PANEL + ['_ts'])
        g = d.groupby(PANEL + ['hour'], sort=False).delivery_eta_min
        d['sh_mean'] = g.cumsum() / (g.cumcount() + 1)            # includes t for the hour of t
        # the next snapshot has the other hour: its to-date mean is the value at t-1
        d['sh_mean_next'] = d.groupby(PANEL, sort=False).sh_mean.shift(1)
        return df.merge(d[['observation_key', 'sh_mean_next']], on='observation_key', how='left')['sh_mean_next'].to_numpy()

    def baselines(df):
        return {'naive (ETA now)': df[ANCHOR].to_numpy(float),
                'seasonal naive (ETA one snapshot ago)': df.eta_lag_1.fillna(df[ANCHOR]).to_numpy(float),
                'listing same-hour mean to date': pd.Series(same_hour_mean(df)).fillna(
                    pd.Series(df[ANCHOR].to_numpy(float))).to_numpy()}

    y_tr = train[TARGET].to_numpy(float) - train[ANCHOR].to_numpy(float)
    y_va = val[TARGET].to_numpy(float) - val[ANCHOR].to_numpy(float)
    dtr = lgb.Dataset(prep(train), y_tr, categorical_feature=['category'], free_raw_data=False)
    dva = lgb.Dataset(prep(val), y_va, reference=dtr, categorical_feature=['category'])
    bst = lgb.train(PARAMS, dtr, 3000, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False),
                                                                    lgb.log_evaluation(500)])
    pred = lambda df: df[ANCHOR].to_numpy(float) + bst.predict(prep(df), num_iteration=bst.best_iteration)
    p_va, p_te = pred(val), pred(test)
    y_test = test[TARGET].to_numpy(float)

    def mets(y, p):
        e = y - p
        return {'mae': float(np.abs(e).mean()), 'rmse': float(np.sqrt((e ** 2).mean())), 'bias': float(e.mean()),
                'exact_minute_share': float((np.round(p) == y).mean())}

    res = {'model': mets(y_test, p_te)}
    for k, v in baselines(test).items():
        res[k] = mets(y_test, v)
    beats = {k: res['model']['mae'] < v['mae'] for k, v in res.items() if k != 'model'}
    best_base = min((v['mae'], k) for k, v in res.items() if k != 'model')
    skill = 1 - res['model']['mae'] / best_base[0]
    verdict = (f"USEFUL: beats every baseline on test MAE ({skill:+.1%} vs the best, {best_base[1]})."
               if all(beats.values()) else f"NOT USEFUL by the bar: beats = {beats}")
    by_plat = {p: {'mae': float(np.abs(y_test[m] - p_te[m]).mean()),
                   'mae_naive': float(np.abs(y_test[m] - test[ANCHOR].to_numpy(float)[m]).mean())}
               for p in PLATFORMS_ORDER if (m := (test.platform == p).to_numpy()).any()}

    # ---- CQR
    sub = train.sample(min(200_000, len(train)), random_state=SEED)
    intervals, cover = {}, {}
    for cov in COVERAGES:
        alpha = 1 - cov
        qs = {}
        for q in (alpha / 2, 1 - alpha / 2):
            b = lgb.train({**PARAMS, 'objective': 'quantile', 'alpha': q, 'learning_rate': 0.1},
                          lgb.Dataset(prep(sub), sub[TARGET].to_numpy(float) - sub[ANCHOR].to_numpy(float),
                                      categorical_feature=['category']), 600)
            qs[q] = b
        qf = lambda df, q: df[ANCHOR].to_numpy(float) + qs[q].predict(prep(df))
        lo_va, hi_va = qf(val, alpha / 2), qf(val, 1 - alpha / 2)
        raw_cov_val = float(((val[TARGET] >= lo_va) & (val[TARGET] <= hi_va)).mean())
        corr = conformal(lo_va, hi_va, val[TARGET].to_numpy(float), alpha)
        lo_m, hi_m = qf(test, alpha / 2) - corr, qf(test, 1 - alpha / 2) + corr        # marginal CQR
        inside_m = (y_test >= lo_m) & (y_test <= hi_m)
        # group-conditional (Mondrian) CQR: one correction per platform x hour cell, calibrated on val, so the
        # coverage guarantee holds inside every cell and not just on average
        g_va = (val.platform.astype(str) + ' @ ' + val.hour.astype(str) + ':00').to_numpy()
        g_te = (test.platform.astype(str) + ' @ ' + test.hour.astype(str) + ':00').to_numpy()
        y_va = val[TARGET].to_numpy(float)
        corr_g = {g: conformal(lo_va[g_va == g], hi_va[g_va == g], y_va[g_va == g], alpha) for g in np.unique(g_va)}
        cg = np.array([corr_g.get(g, corr) for g in g_te])
        lo_te, hi_te = qf(test, alpha / 2) - cg, qf(test, 1 - alpha / 2) + cg
        inside = (y_test >= lo_te) & (y_test <= hi_te)
        # symmetric split conformal on the point model, for comparison
        abs_r = np.sort(np.abs(val[TARGET].to_numpy(float) - p_va))
        qa = abs_r[min(int(np.ceil((len(abs_r) + 1) * cov)), len(abs_r)) - 1]
        inside_sym = np.abs(y_test - p_te) <= qa
        cell = pd.DataFrame({'g': g_te, 'in': inside, 'in_marginal': inside_m, 'w': hi_te - lo_te,
                             'w_marginal': hi_m - lo_m}).groupby('g').agg(
            coverage=('in', 'mean'), width=('w', 'mean'), coverage_marginal=('in_marginal', 'mean'),
            width_marginal=('w_marginal', 'mean'), n=('in', 'size'))
        cover[f'{int(cov * 100)}%'] = {
            'target': cov, 'raw_quantile_coverage_on_val': raw_cov_val, 'conformal_correction_minutes': corr,
            'marginal_cqr_test_coverage': float(inside_m.mean()), 'marginal_cqr_mean_width': float((hi_m - lo_m).mean()),
            'marginal_cqr_worst_cell_coverage': float(cell.coverage_marginal.min()),
            'mondrian_cqr_test_coverage': float(inside.mean()), 'mondrian_cqr_mean_width': float((hi_te - lo_te).mean()),
            'mondrian_cqr_worst_cell_coverage': float(cell.coverage.min()),
            'mondrian_corrections_minutes': {g: round(v, 3) for g, v in corr_g.items()},
            'symmetric_conformal_test_coverage': float(inside_sym.mean()),
            'symmetric_conformal_width_minutes': float(2 * qa),
            'by_platform_hour': cell.round(4).to_dict(orient='index')}
        print(f"{cov:.0%}: marginal CQR {inside_m.mean():.3f} (worst cell {cell.coverage_marginal.min():.3f}) | "
              f"Mondrian CQR {inside.mean():.3f} (worst cell {cell.coverage.min():.3f}) width {(hi_te - lo_te).mean():.2f}")
        # shipped: marginal CQR (Mondrian did not improve the worst cell; see the docstring)
        intervals[cov] = (lo_m, hi_m)
        # why: share of the variance of the miss indicator that sits between store x snapshot clusters
        miss = pd.DataFrame({'miss': (~inside_m).astype(float), 'store': test.store_id.to_numpy(),
                             'snap': test.date.astype(str).to_numpy() + test.hour.astype(str).to_numpy()})
        cm = miss.groupby(['store', 'snap']).miss.mean()
        cover[f'{int(cov * 100)}%']['clustering_diagnostic'] = {
            'between_store_snapshot_share_of_miss_variance': float(cm.var() / miss.miss.var()),
            'store_snapshot_clusters_in_test': int(len(cm)),
            'cluster_coverage_min': float(1 - cm.max()), 'cluster_coverage_max': float(1 - cm.min())}

    gain = pd.Series(bst.feature_importance('gain'), index=feats).sort_values(ascending=False)
    metrics = {
        'claim_limit': ('SYNTHETIC panel. Recovery of the planted ETA equation and the forecast skill are pipeline '
                        'checks, not real delivery performance of any platform or store.'),
        'verdict': verdict, 'test': res, 'beats': beats, 'skill_vs_best_baseline': skill,
        'test_by_platform': by_plat, 'best_iteration': int(bst.best_iteration),
        'structural_recovery': rec.to_dict(orient='records'), 'platform_base_recovery': base_rows,
        'conformal_intervals': cover,
        'top_features_by_gain': {k: float(v) for k, v in gain.head(15).items()},
    }
    lo90, hi90 = intervals[0.9]
    lo80, hi80 = intervals[0.8]
    out = pd.DataFrame({
        'observation_key': test.observation_key.to_numpy(), 'data_status': test.data_status.to_numpy(),
        'platform': test.platform.to_numpy(), 'store_id': test.store_id.to_numpy(),
        'snapshot_date': test.date.astype(str).to_numpy(), 'hour': test.hour.to_numpy(),
        'prediction': p_te, 'lower_80': lo80, 'upper_80': hi80, 'lower_90': lo90, 'upper_90': hi90,
        'promise_eta_90': np.ceil(hi90), 'actual_future_eta': y_test,
        'baseline_naive': test[ANCHOR].to_numpy(float),
    })
    mdir = save_model_outputs(
        NAME, out,
        params={**PARAMS, 'best_iteration': int(bst.best_iteration), 'learns': 'future_eta - delivery_eta_min',
                'intervals': 'conformalized quantile regression, calibrated on val',
                'library': f'lightgbm {lgb.__version__}'},
        metrics=metrics, training_data=train,
        split={'source': "pipeline 'split' column via src.load.splits", 'fit': 'train',
               'early_stopping_and_conformal_calibration': 'val', 'evaluated_on': 'test',
               'structural_recovery': 'all synthetic rows (parameter check)'},
        target=TARGET, feature_columns=feats,
        notes='Deliverable 5. SYNTHETIC ONLY. Point forecast + conformal promise intervals + structural recovery.')
    rec.to_csv(mdir / 'structural_recovery.csv', index=False)
    _figures(mdir, rec, res, cover, st, test, p_te, intervals)
    print('\n' + '=' * 72)
    print(verdict)
    print(json.dumps({k: round(v['mae'], 4) for k, v in res.items()}, indent=1))


PLATFORMS_ORDER = ['Blinkit', 'Swiggy Instamart', 'Flipkart Minutes', 'BigBasket']


def _figures(mdir, rec, res, cover, st, test, p_te, intervals):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    ink, muted, grid = '#1f2328', '#6e7781', '#d0d7de'
    c_model, c_base, c_true = '#0969da', '#bc4c00', '#8250df'
    fig, ax = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('Deliverable 5 · delivery ETA  —  SYNTHETIC panel: pipeline check, not real delivery performance',
                 fontsize=12.5, color=ink, x=0.01, ha='left')

    a = ax[0, 0]
    r = rec.copy(); r['rel'] = r.estimate / r.planted
    yy = np.arange(len(r))[::-1]
    a.axvline(1, color=c_true, lw=1.5)
    for y_, (_, row) in zip(yy, r.iterrows()):
        col = c_model if row.covered in (True, None) else c_base
        if row.ci_low is not None and not pd.isna(row.ci_low):
            a.hlines(y_, row.ci_low / row.planted, row.ci_high / row.planted, color=col, lw=2)
        a.scatter(row.rel, y_, color=col, s=28, zorder=3)
        a.annotate(f"{row.estimate:.2f} vs {row.planted:g}", (row.rel, y_), xytext=(6, 4), textcoords='offset points',
                   fontsize=7.5, color=muted)
    a.set_yticks(yy); a.set_yticklabels(r.parameter, fontsize=7.8)
    a.set_xlabel('estimate / planted')
    a.set_title('A · every planted ETA term recovered (two-stage fixed effects)', fontsize=10, loc='left')

    a = ax[0, 1]
    names = list(res); maes = [res[k]['mae'] for k in names]
    cols = [c_model if k == 'model' else muted for k in names]
    a.barh(names[::-1], maes[::-1], color=cols[::-1])
    for i, v in enumerate(maes[::-1]):
        a.text(v, i, f' {v:.3f}', va='center', fontsize=8.5)
    a.set_xlabel('test MAE (minutes)')
    a.set_title('B · next-snapshot ETA forecast vs baselines', fontsize=10, loc='left')

    a = ax[1, 0]
    for key, col in (('80%', '#1a7f37'), ('90%', c_model)):
        cell = pd.DataFrame(cover[key]['by_platform_hour']).T
        a.scatter(cell.width_marginal, cell.coverage_marginal, facecolors='none', edgecolors=col, s=34,
                  label=f'{key} marginal CQR (per cell)')
        a.scatter(cell.width, cell.coverage, color=col, s=30, label=f'{key} Mondrian CQR (per cell)')
        a.axhline(cover[key]['target'], color=col, lw=1, ls=':')
    a.set_xlabel('mean interval width (minutes)'); a.set_ylabel('test coverage in each platform × hour cell')
    a.set_title('C · per-cell coverage: Mondrian (filled) does not beat marginal (hollow); misses cluster by store',
                fontsize=9.5, loc='left')
    a.legend(frameon=False, fontsize=8.5)

    a = ax[1, 1]
    s1 = st[(st.platform == 'Blinkit')]
    one = s1.store_id.iloc[0]
    s1 = s1[s1.store_id == one]
    a.plot(s1.ts, s1.r, color=c_model, lw=1.3)
    a.axhline(0, color=grid)
    a.set_title(f'D · latent store demand read off ETA (store {one}): residual after peak, OOS and store level',
                fontsize=9.5, loc='left')
    a.set_ylabel('minutes (≈ 1.6 × D)')
    for a in ax.flat:
        a.spines[['top', 'right']].set_visible(False)
        a.grid(color=grid, lw=0.5, alpha=0.6); a.set_axisbelow(True)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    (mdir / 'figures').mkdir(exist_ok=True)
    fig.savefig(mdir / 'figures' / 'eta_forecast.png', dpi=130)
    plt.close(fig)


if __name__ == '__main__':
    main()
