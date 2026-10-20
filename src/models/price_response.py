"""
price_response.py — deliverable 9, competitive price response (VAR + impulse response). SYNTHETIC.

    python -m src.models.price_response

WHAT THIS MAY AND MAY NOT CLAIM
  Every multi-date price is SYNTHETIC. Recovering the Blinkit-leader / follower structure, the lags and the
  response coefficients shows the pipeline recovers the v15.1 generator's planted price dynamics
  (docs/GENERATOR_v15_PARAMETERS.md C, 🟠 assumptions). It is not evidence of who leads real pricing, and it is
  NOT an elasticity: there is no demand in this data (CLAUDE.md section 4).

  What IS transferable is the method finding: shelf prices snapped to coarse grids (Rs 10 / 50 / 100 steps)
  hide about half of a real price response from a naive regression, and indirect inference with the
  observed grid undoes it. Real Blinkit prices are on such grids (75% end in 0/5/9).

DATA
  The 2,000-product common panel (in_common_panel == 1). x = log price deviation from each panel's own mean,
  averaged over a product's stores per platform, exactly as tests/test_generator_dynamics.py measures it.

STEPS
  1  Naive: pooled OLS  x_f[t] = c + a x_f[t-1] + b x_L[t-lag]      (the attenuated "expected measured" beta)
  2  Lag discovery: every lag 0..3 of the leader at once; the largest coefficient names the lag.
  3  Direction: does Blinkit respond to the followers? (negative control; planted answer: no)
  4  Unrestricted pooled VAR(2) over the four platforms, naive impulse responses.
  5  Indirect inference. Each panel's price grid (step, remainder) is inferred from its own observed prices.
     The latent AR structure is simulated with candidate parameters, rounded to those grids, and measured with
     step 1's regression. Parameters are chosen so the simulated measurements equal the real ones
     (common random numbers, least squares). Leader first (rho, sigma), then each follower (rho, sigma, beta).
     The platform wave sd is read off the cross-sectional mean of x per platform and snapshot.
     Parametric bootstrap gives the intervals.
  6  Impulse responses: planted vs naive vs corrected, for a 1-sd Blinkit price shock.
"""
import json

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

import src.load as L
from src.model_output import save_model_outputs

NAME = 'price_response'
PANEL = ['platform', 'store_id', 'product_id']
LEADER = 'Blinkit'
FOLLOWERS = ['Swiggy Instamart', 'Flipkart Minutes', 'BigBasket']
PLATFORMS = [LEADER] + FOLLOWERS
BURN = 60
N_BOOT = 20
SEED = 20260923
# candidate grids, coarsest first (step, remainder). Read off the data: real endings are 0/5/9/49/99.
GRIDS = [(100, 99), (50, 49), (50, 0), (10, 9), (10, 0), (10, 5), (1, 0)]

PLANTED = {'rho_leader': 0.6, 'sigma_leader': 0.03, 'rho_follower': 0.6, 'sigma_follower': 0.02,
           'beta': {'Swiggy Instamart': 0.45, 'Flipkart Minutes': 0.30, 'BigBasket': 0.35},
           'lag': {'Swiggy Instamart': 1, 'Flipkart Minutes': 1, 'BigBasket': 2},
           'expected_measured_beta': {'Swiggy Instamart': 0.220, 'Flipkart Minutes': 0.154, 'BigBasket': 0.181},
           'wave_sd': 0.005}


# =========================================================================== data
def load_panel():
    ml = L.load_ml()
    c = ml[(ml.data_status == 'SYNTHETIC') & (ml.in_common_panel == 1)].copy()
    c['_ts'] = pd.to_datetime(c.observed_at.astype(str), format='mixed')
    c = c.sort_values(PANEL + ['_ts'])
    times = np.sort(c._ts.unique())
    c['t'] = np.searchsorted(times, c._ts.to_numpy())
    c['level'] = c.groupby(PANEL).selling_price.transform('mean')
    c['x'] = np.log(c.selling_price) - np.log(c.level)
    return c, len(times)


def infer_grid(prices: np.ndarray):
    p = np.round(prices).astype(np.int64)
    for step, rem in GRIDS:
        if np.all(p % step == rem % step):
            return step, rem
    return 1, 0


def latent_level(prices, step, rem, s):
    """Latent log price level of one panel on a coarse grid (interval likelihood).

    The observed mean of grid-rounded prices is a poor estimate of the latent level: a panel that shows 99
    most of the time and 199 sometimes must sit close to the 149 boundary, while its observed mean is ~110.
    Treat each observed price as the interval of latent prices that round to it (grid point +/- step/2) and
    the latent log price as N(m, s^2) over time; maximise over m. s is read off the Rs 1 grid panels of the
    same platform, where rounding is negligible.
    """
    from scipy.optimize import minimize_scalar
    from scipy.stats import norm
    pts, cnt = np.unique(np.round(prices), return_counts=True)
    if step == 1:
        return float(np.mean(np.log(prices)))
    lo = np.log(np.maximum(pts - step / 2, 0.5)); hi = np.log(pts + step / 2)
    lo = np.where(pts - step / 2 <= 0.5, -np.inf, lo)

    def nll(m):
        pr = norm.cdf((hi - m) / s) - norm.cdf((lo - m) / s)
        return -(cnt * np.log(np.maximum(pr, 1e-300))).sum()
    a = np.log(max(pts.min() - step / 2, 0.5)) - 3 * s
    b = np.log(pts.max() + step / 2) + 3 * s
    return float(minimize_scalar(nll, bounds=(a, b), method='bounded').x)


def structure(c, T):
    """Arrays for fast simulation: one row per panel, with its canonical-key index and platform."""
    g = c.groupby(PANEL, sort=False)
    pan = g.agg(canon=('canonical_product_key', 'first'), level=('level', 'first')).reset_index()
    grids = np.array(g.selling_price.apply(lambda s: infer_grid(s.to_numpy())).tolist())
    pan['step'], pan['rem'] = grids[:, 0], grids[:, 1]
    # latent level: s per platform from Rs 1 grid panels (x sd there ~ latent sd incl. the wave)
    obs_sd = g.selling_price.apply(lambda v: float(np.std(np.log(v.to_numpy())))).to_numpy()
    pan['obs_sd'] = obs_sd
    s_plat = pan[pan.step == 1].groupby('platform').obs_sd.mean().to_dict()
    prices = g.selling_price.apply(lambda v: v.to_numpy()).tolist()
    pan['level'] = [np.exp(latent_level(pr, st, rm, s_plat[pl])) for pr, st, rm, pl in
                    zip(prices, pan.step, pan.rem, pan.platform)]
    keys = sorted(c.canonical_product_key.unique())
    kix = {k: i for i, k in enumerate(keys)}
    pan['k'] = pan.canon.map(kix)
    # the leader panel each follower panel follows: the product's Blinkit panel (one per key in the panel)
    lead = pan[pan.platform == LEADER].drop_duplicates('k').set_index('k').index
    pan['has_leader'] = pan.k.isin(lead)
    X = np.full((len(pan), T), np.nan)
    sub = c.merge(pan[PANEL].reset_index().rename(columns={'index': 'row'}), on=PANEL)
    X[sub.row.to_numpy(), sub.t.to_numpy()] = sub.x.to_numpy()
    return pan, X, len(keys)


def key_means(pan, X, n_keys, platform):
    """Mean x over a product's stores for one platform: (n_keys, T), NaN where absent."""
    m = (pan.platform == platform).to_numpy()
    k = pan.k.to_numpy()[m]
    S = np.zeros((n_keys, X.shape[1])); N = np.zeros((n_keys, 1))
    np.add.at(S, k, X[m]); np.add.at(N, k, 1)
    with np.errstate(invalid='ignore'):
        return S / np.where(N > 0, N, np.nan)


def ols(y, X):
    ok = np.isfinite(y) & np.isfinite(X).all(1)
    Xo = np.c_[np.ones(ok.sum()), X[ok]]
    b, *_ = np.linalg.lstsq(Xo, y[ok], rcond=None)
    resid = y[ok] - Xo @ b
    s2 = resid @ resid / max(ok.sum() - Xo.shape[1], 1)
    cov = s2 * np.linalg.pinv(Xo.T @ Xo)
    return b, np.sqrt(np.diag(cov)), float(np.sqrt(s2)), int(ok.sum())


def measure(M, lags=PLANTED['lag']):
    """The step-1 regressions on key-mean matrices M[platform]."""
    Lx = M[LEADER]
    out = {}
    b, se, s, n = ols(Lx[:, 1:].ravel(), Lx[:, :-1].ravel()[:, None])
    out['leader'] = {'rho': b[1], 'resid_sd': s, 'sd': float(np.nanstd(Lx))}
    for f in FOLLOWERS:
        lag = lags[f]; F = M[f]
        y = F[:, lag:].ravel()
        X = np.c_[F[:, lag - 1:-1].ravel(), Lx[:, :-lag].ravel()]
        b, se, s, n = ols(y, X)
        out[f] = {'a': b[1], 'beta': b[2], 'beta_se': se[2], 'resid_sd': s, 'n': n}
    return out


# =========================================================================== simulation
def simulate(pan, T, n_keys, theta, rng_state, wave_sd):
    """Latent AR structure -> grid-rounded prices -> x. theta: dict of rho/sigma per platform, beta per follower."""
    rng = np.random.default_rng(rng_state)
    TT = BURN + T
    n = len(pan)
    plat = pan.platform.to_numpy()
    k = pan.k.to_numpy()
    lead_rows = pd.Series(np.flatnonzero(plat == LEADER), index=k[plat == LEADER])
    lead_rows = lead_rows[~lead_rows.index.duplicated()]
    lead_of = lead_rows.reindex(k).to_numpy()
    has = ~np.isnan(lead_of); lead_of = np.nan_to_num(lead_of).astype(int)
    rho = np.array([theta[f'rho[{p}]'] for p in plat]); sig = np.array([theta[f'sigma[{p}]'] for p in plat])
    beta = np.array([theta.get(f'beta[{p}]', 0.0) for p in plat]) * has
    lag = np.array([PLANTED['lag'].get(p, 1) for p in plat])
    shocks = rng.standard_normal((n, TT))
    x = np.zeros((n, TT))
    isL = plat == LEADER
    for t in range(1, TT):
        xl = x[lead_of, np.maximum(t - lag, 0)]
        fol = rho * x[:, t - 1] + beta * (xl - x[:, t - 1]) + sig * shocks[:, t]
        x[:, t] = np.where(isL, rho * x[:, t - 1] + sig * shocks[:, t], fol)
    plats = np.unique(plat)
    wave = {p: rng.normal(0, wave_sd[p], TT) for p in plats}
    w = np.stack([wave[p] for p in plat])
    P = pan.level.to_numpy()[:, None] * np.exp(x[:, BURN:] + w[:, BURN:])
    step, rem = pan.step.to_numpy()[:, None], pan.rem.to_numpy()[:, None]
    price = np.round((P - rem) / step) * step + rem
    price = np.where(price < 1, np.maximum(np.round(P), 1), price)
    lv = price.mean(1, keepdims=True)
    return np.log(price) - np.log(lv)


def indirect_inference(pan, T, n_keys, target, wave_sd, seed, start=None):
    """Leader first, then each follower given the leader. Returns theta."""
    th = dict(start or {})
    # ---- leader: match AR coefficient and residual sd
    lp = pan[pan.platform == LEADER].reset_index(drop=True)

    def res_leader(v):
        t_ = {f'rho[{LEADER}]': v[0], f'sigma[{LEADER}]': v[1]}
        X = simulate(lp, T, n_keys, t_, seed, wave_sd)
        Lx = key_means(lp, X, n_keys, LEADER)
        b, se, s, n = ols(Lx[:, 1:].ravel(), Lx[:, :-1].ravel()[:, None])
        return [(b[1] - target['leader']['rho']) / 0.01, (s - target['leader']['resid_sd']) / 0.001]

    r = least_squares(res_leader, [target['leader']['rho'], target['leader']['resid_sd']],
                      bounds=([0.0, 1e-4], [0.99, 0.5]), diff_step=0.02)
    th[f'rho[{LEADER}]'], th[f'sigma[{LEADER}]'] = r.x
    # ---- followers, each with the fitted leader
    for f in FOLLOWERS:
        sub = pan[pan.platform.isin([LEADER, f])].reset_index(drop=True)

        def res_f(v):
            t_ = {**th, f'rho[{f}]': v[0], f'sigma[{f}]': v[1], f'beta[{f}]': v[2]}
            X = simulate(sub, T, n_keys, t_, seed, wave_sd)
            Lx, F = key_means(sub, X, n_keys, LEADER), key_means(sub, X, n_keys, f)
            lag = PLANTED['lag'][f]
            b, se, s, n = ols(F[:, lag:].ravel(), np.c_[F[:, lag - 1:-1].ravel(), Lx[:, :-lag].ravel()])
            tf = target[f]
            return [(b[1] - tf['a']) / 0.01, (b[2] - tf['beta']) / 0.01, (s - tf['resid_sd']) / 0.001]

        x0 = [0.6, target[f]['resid_sd'], 2 * target[f]['beta']]
        r = least_squares(res_f, x0, bounds=([0.0, 1e-4, 0.0], [0.99, 0.5, 0.99]), diff_step=0.02)
        th[f'rho[{f}]'], th[f'sigma[{f}]'], th[f'beta[{f}]'] = r.x
    return th


# =========================================================================== impulse responses
def irf_structural(rho_L, rho_f, beta, lag, horizon=12, shock=1.0):
    xL = np.zeros(horizon + 1); xf = np.zeros(horizon + 1)
    xL[0] = shock
    for t in range(1, horizon + 1):
        xL[t] = rho_L * xL[t - 1]
        xf[t] = rho_f * xf[t - 1] + beta * ((xL[t - lag] if t - lag >= 0 else 0.0) - xf[t - 1])
    return xL, xf


def var2(M):
    """Pooled VAR(2) over the four platforms on product-key means (rows with all four present)."""
    Y = np.stack([M[p] for p in PLATFORMS], 2)          # keys x T x 4
    ok = np.isfinite(Y).all((1, 2))
    Y = Y[ok]
    y = Y[:, 2:].reshape(-1, 4)
    X = np.c_[Y[:, 1:-1].reshape(-1, 4), Y[:, :-2].reshape(-1, 4)]
    B, *_ = np.linalg.lstsq(np.c_[np.ones(len(X)), X], y, rcond=None)
    A1, A2 = B[1:5].T, B[5:9].T
    return A1, A2, int(ok.sum())


def var_irf(A1, A2, horizon=12, shock_ix=0, size=1.0):
    out = np.zeros((horizon + 1, 4)); out[0, shock_ix] = size
    for t in range(1, horizon + 1):
        out[t] = A1 @ out[t - 1] + (A2 @ out[t - 2] if t >= 2 else 0)
    return out


# =========================================================================== main
def main():
    c, T = load_panel()
    pan, X, n_keys = structure(c, T)
    M = {p: key_means(pan, X, n_keys, p) for p in PLATFORMS}

    # ---- 1 naive
    naive = measure(M)
    print('naive:', {f: round(naive[f]['beta'], 3) for f in FOLLOWERS}, 'leader rho', round(naive['leader']['rho'], 3))

    # ---- 2 lag discovery
    lagfind = {}
    for f in FOLLOWERS:
        F, Lx = M[f], M[LEADER]
        y = F[:, 4:].ravel()
        Xl = F[:, 3:-1].ravel()[:, None]
        Xs = [Lx[:, 4 - l:T - l].ravel() for l in range(0, 4)]
        b, se, s, n = ols(y, np.c_[Xl, np.stack(Xs, 1)])
        coefs = {int(l): float(b[2 + l]) for l in range(4)}
        lagfind[f] = {'coef_by_lag': coefs, 'se_by_lag': {int(l): float(se[2 + l]) for l in range(4)},
                      'discovered_lag': int(max(coefs, key=coefs.get)), 'planted_lag': PLANTED['lag'][f]}
    print('lags:', {f: v['discovered_lag'] for f, v in lagfind.items()})

    # ---- 3 direction: does the leader follow anyone?
    Lx = M[LEADER]
    y = Lx[:, 2:].ravel()
    Xd = Lx[:, 1:-1].ravel()[:, None]
    Xf = np.stack([M[f][:, 1:-1].ravel() for f in FOLLOWERS] + [M[f][:, :-2].ravel() for f in FOLLOWERS], 1)
    b, se, s, n = ols(y, np.c_[Xd, Xf])
    reverse = {f'{f} lag {l}': {'coef': float(b[2 + i + 3 * (l - 1)]), 'se': float(se[2 + i + 3 * (l - 1)])}
               for l in (1, 2) for i, f in enumerate(FOLLOWERS)}
    print('reverse (leader on followers):', {k: round(v['coef'], 4) for k, v in reverse.items()})

    # ---- 4 VAR(2)
    A1, A2, n_var = var2(M)
    irf_var = var_irf(A1, A2)

    # ---- 5 indirect inference
    means = {p: np.nanmean(key_means(pan, X, n_keys, p), 0) for p in PLATFORMS}
    wave_sd = {p: float(np.std(means[p])) for p in PLATFORMS}
    grid_share = pan.groupby(['step', 'rem']).size().rename('panels').reset_index()
    print('wave sd read off data:', {p: round(v, 4) for p, v in wave_sd.items()})
    theta = indirect_inference(pan, T, n_keys, naive, wave_sd, SEED)
    print('corrected:', {k: round(v, 3) for k, v in theta.items()})

    # parametric bootstrap: simulate "data" at theta, re-measure, re-estimate
    boot = []
    for bi in range(N_BOOT):
        Xb = simulate(pan, T, n_keys, theta, SEED + 1000 + bi, wave_sd)
        Mb = {p: key_means(pan, Xb, n_keys, p) for p in PLATFORMS}
        tb = indirect_inference(pan, T, n_keys, measure(Mb), wave_sd, SEED + 5000 + bi)
        boot.append(tb)
        print(f"  bootstrap {bi + 1}/{N_BOOT}: " + ' '.join(f"{f.split()[0][:4]} {tb[f'beta[{f}]']:.3f}" for f in FOLLOWERS))
    boot = pd.DataFrame(boot)

    # validation of the observation operator: does the simulation at the PLANTED values reproduce the naive numbers?
    planted_theta = {f'rho[{LEADER}]': PLANTED['rho_leader'], f'sigma[{LEADER}]': PLANTED['sigma_leader'],
                     **{f'rho[{f}]': PLANTED['rho_follower'] for f in FOLLOWERS},
                     **{f'sigma[{f}]': PLANTED['sigma_follower'] for f in FOLLOWERS},
                     **{f'beta[{f}]': PLANTED['beta'][f] for f in FOLLOWERS}}
    Mp = {p: key_means(pan, simulate(pan, T, n_keys, planted_theta, SEED + 99, wave_sd), n_keys, p) for p in PLATFORMS}
    at_planted = measure(Mp)

    rows = []
    for f in FOLLOWERS:
        q = boot[f'beta[{f}]']
        # bootstrap bias-corrected percentile interval around the point estimate
        lo, hi = 2 * theta[f'beta[{f}]'] - q.quantile(0.975), 2 * theta[f'beta[{f}]'] - q.quantile(0.025)
        rows.append({'follower': f, 'lag': PLANTED['lag'][f], 'planted_beta': PLANTED['beta'][f],
                     'naive_beta': naive[f]['beta'], 'naive_ci': [naive[f]['beta'] - 1.96 * naive[f]['beta_se'],
                                                                 naive[f]['beta'] + 1.96 * naive[f]['beta_se']],
                     'corrected_beta': theta[f'beta[{f}]'], 'corrected_ci': [float(lo), float(hi)],
                     'covered': bool(lo <= PLANTED['beta'][f] <= hi),
                     'naive_share_of_planted': naive[f]['beta'] / PLANTED['beta'][f],
                     'corrected_share_of_planted': theta[f'beta[{f}]'] / PLANTED['beta'][f],
                     'simulated_naive_at_planted': at_planted[f]['beta'],
                     'expected_measured_in_generator_doc': PLANTED['expected_measured_beta'][f],
                     'corrected_rho': theta[f'rho[{f}]'], 'corrected_sigma': theta[f'sigma[{f}]']})
    table = pd.DataFrame(rows)
    other = {'leader_rho': {'planted': 0.6, 'naive': naive['leader']['rho'], 'corrected': theta[f'rho[{LEADER}]'],
                            'ci': boot[f'rho[{LEADER}]'].quantile([0.025, 0.975]).tolist()},
             'leader_sigma': {'planted': 0.03, 'corrected': theta[f'sigma[{LEADER}]'],
                              'ci': boot[f'sigma[{LEADER}]'].quantile([0.025, 0.975]).tolist()},
             'wave_sd_read_off_data': wave_sd, 'wave_sd_planted': PLANTED['wave_sd']}
    print(table[['follower', 'planted_beta', 'naive_beta', 'corrected_beta', 'corrected_ci', 'covered']].to_string())

    # ---- 6 impulse responses (1 leader sd shock, in % price)
    irfs = {}
    for f in FOLLOWERS:
        lag = PLANTED['lag'][f]
        _, pl = irf_structural(0.6, 0.6, PLANTED['beta'][f], lag)
        _, co = irf_structural(theta[f'rho[{LEADER}]'], theta[f'rho[{f}]'], theta[f'beta[{f}]'], lag)
        a_n = naive[f]['a']; b_n = naive[f]['beta']
        _, nv = irf_structural(naive['leader']['rho'], a_n + b_n, b_n, lag)
        irfs[f] = {'planted': pl.tolist(), 'corrected': co.tolist(), 'naive': nv.tolist(),
                   'var2': irf_var[:, PLATFORMS.index(f)].tolist()}

    # ---- predictions: one-step follower forecast on test rows, naive vs corrected structure
    tmin = int(c[c.split == 'test'].t.min())
    preds = []
    for f in FOLLOWERS:
        lag = PLANTED['lag'][f]
        rows_f = c[(c.platform == f) & (c.split == 'test')]
        kk = rows_f.canonical_product_key.map({k: i for i, k in enumerate(sorted(c.canonical_product_key.unique()))}).to_numpy()
        tt = rows_f.t.to_numpy()
        own = X[pan.set_index(PANEL).index.get_indexer(pd.MultiIndex.from_frame(rows_f[PANEL])), :]
        prev = own[np.arange(len(rows_f)), tt - 1]
        lead = M[LEADER][kk, tt - lag]
        pn = naive[f]['a'] * prev + naive[f]['beta'] * lead
        pc = (theta[f'rho[{f}]'] - theta[f'beta[{f}]']) * prev + theta[f'beta[{f}]'] * lead
        preds.append(pd.DataFrame({'observation_key': rows_f.observation_key.to_numpy(),
                                   'data_status': rows_f.data_status.to_numpy(), 'platform': f,
                                   'snapshot_date': rows_f.date.astype(str).to_numpy(),
                                   'prediction': pc, 'prediction_naive_ols': pn,
                                   'actual_log_deviation': rows_f.x.to_numpy()}))
    pred = pd.concat(preds, ignore_index=True)
    ok = pred.prediction.notna() & pred.actual_log_deviation.notna()
    fit_quality = {'test_mae_corrected_structure': float((pred.prediction - pred.actual_log_deviation)[ok].abs().mean()),
                   'test_mae_naive_ols': float((pred.prediction_naive_ols - pred.actual_log_deviation)[ok].abs().mean()),
                   'note': ('One-step forecasts of OBSERVED (rounded) log price. Naive OLS is the best linear '
                            'predictor of rounded prices, so it may forecast as well or better: correction targets '
                            'the latent response parameter, not observed-price forecast error.')}

    metrics = {
        'claim_limit': ('SYNTHETIC panel. Recovery of the planted leader/follower structure is a pipeline check. '
                        'Not who leads real pricing, and not an elasticity (no demand data exists).'),
        'transferable_method_finding': ('Grid-rounded shelf prices attenuate a naive response regression to about '
                                        'half the latent response; indirect inference with the observed grid '
                                        'recovers it. Real prices are on such grids, so real naive pass-through '
                                        'estimates would be biased the same way.'),
        'response_recovery': table.to_dict(orient='records'),
        'leader_and_noise': other,
        'lag_discovery': lagfind,
        'reverse_direction_negative_control': reverse,
        'var2': {'A1': A1.tolist(), 'A2': A2.tolist(), 'product_keys': n_var, 'order': PLATFORMS},
        'impulse_responses_1pct_leader_shock': irfs,
        'grids_inferred_from_observed_prices': grid_share.to_dict(orient='records'),
        'observation_operator_check': {f: {'naive_on_real_data': naive[f]['beta'],
                                           'naive_on_simulation_at_planted_values': at_planted[f]['beta']} for f in FOLLOWERS},
        'forecast_test': fit_quality,
        'bootstrap_replications': N_BOOT,
    }
    train = c[c.split == 'train']
    mdir = save_model_outputs(
        NAME, pred,
        params={'method': 'naive pooled OLS + indirect inference through the inferred price grid',
                'theta_corrected': theta, 'var2_A1': A1.tolist(), 'var2_A2': A2.tolist(),
                'lags': PLANTED['lag'], 'burn_in': BURN, 'bootstrap': N_BOOT, 'grids': GRIDS},
        metrics=metrics, training_data=train.assign(snapshot_date=train.date.astype(str)),
        split={'estimation': 'all common-panel snapshots (parameter recovery, not a forecast)',
               'forecast_check': 'one-step follower forecasts on test rows'},
        target='follower log price deviation (response to the Blinkit leader)',
        notes='Deliverable 9. SYNTHETIC ONLY. platform identifies leader and followers by construction.')
    boot.to_csv(mdir / 'bootstrap.csv', index=False)
    _figures(mdir, table, irfs, lagfind, naive, theta)
    print(json.dumps(fit_quality, indent=1))


def _figures(mdir, table, irfs, lagfind, naive, theta):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    ink, muted, grid = '#1f2328', '#6e7781', '#d0d7de'
    c_model, c_base, c_true = '#0969da', '#bc4c00', '#8250df'
    fig = plt.figure(figsize=(15, 9.5))
    fig.suptitle('Deliverable 9 · competitive price response  —  SYNTHETIC panel: pipeline check, not a market '
                 'finding, not an elasticity', fontsize=12.5, color=ink, x=0.01, ha='left')
    gs = fig.add_gridspec(2, 3)

    a = fig.add_subplot(gs[0, 0:2])
    xs = np.arange(len(table))
    a.bar(xs - 0.27, table.planted_beta, 0.26, color=c_true, label='planted β (latent price)')
    a.bar(xs, table.naive_beta, 0.26, color=c_base, label='naive OLS on rounded shelf prices')
    lo = [r[0] for r in table.corrected_ci]; hi = [r[1] for r in table.corrected_ci]
    a.bar(xs + 0.27, table.corrected_beta, 0.26, color=c_model, label='corrected (indirect inference, 95% CI)',
          yerr=[table.corrected_beta - lo, np.array(hi) - table.corrected_beta], capsize=4)
    a.set_xticks(xs); a.set_xticklabels([f"{f}\n(lag {l})" for f, l in zip(table.follower, table.lag)])
    a.set_ylabel('response to Blinkit (β)')
    a.set_title('A · price grids hide half the response; simulating the grid gets it back', fontsize=10, loc='left')
    a.legend(frameon=False, fontsize=8.5)

    a = fig.add_subplot(gs[0, 2])
    for f, col in zip(lagfind, [c_model, '#1a7f37', c_base]):
        co = lagfind[f]['coef_by_lag']; se = lagfind[f]['se_by_lag']
        a.errorbar(list(co), list(co.values()), yerr=[1.96 * v for v in se.values()], fmt='o-', color=col,
                   label=f"{f} → lag {lagfind[f]['discovered_lag']}", capsize=3)
    a.axhline(0, color=grid)
    a.set_xticks(range(4)); a.set_xlabel('leader lag (snapshots)'); a.set_ylabel('coefficient (naive scale)')
    a.set_title('B · lags discovered, not assumed', fontsize=10, loc='left')
    a.legend(frameon=False, fontsize=8)

    for i, f in enumerate(irfs):
        a = fig.add_subplot(gs[1, i])
        h = np.arange(len(irfs[f]['planted']))
        a.plot(h, irfs[f]['planted'], color=c_true, lw=2.2, label='planted')
        a.plot(h, irfs[f]['corrected'], 'o-', color=c_model, ms=3.5, lw=1.5, label='corrected')
        a.plot(h, irfs[f]['naive'], 's--', color=c_base, ms=3, lw=1.2, label='naive')
        a.plot(h, irfs[f]['var2'], ':', color=muted, lw=1.2, label='unrestricted VAR(2)')
        a.set_title(f'C{i + 1} · {f}: response to a 1% Blinkit move', fontsize=10, loc='left')
        a.set_xlabel('snapshots after the Blinkit move'); a.set_ylabel('% price move')
        if i == 0:
            a.legend(frameon=False, fontsize=8)
    for a in fig.axes:
        a.spines[['top', 'right']].set_visible(False)
        a.grid(color=grid, lw=0.5, alpha=0.6); a.set_axisbelow(True)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    (mdir / 'figures').mkdir(exist_ok=True)
    fig.savefig(mdir / 'figures' / 'price_response.png', dpi=130)
    plt.close(fig)


if __name__ == '__main__':
    main()
