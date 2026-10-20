"""
stockout_survival.py — deliverable 7, stockout-hazard survival (time until out of stock). SYNTHETIC.

    python -m src.features.stock_clock          # once: the stock clock + store pressure index
    python -m src.models.stockout_survival

WHAT THIS MAY AND MAY NOT CLAIM
  Every in-stock spell here is SYNTHETIC. Recovering k, the platform and category scales, the evening
  and promo multipliers and the frailty sd demonstrates that the MODELLING PIPELINE can recover the
  v15.1 generator's planted hazard (docs/GENERATOR_v15_PARAMETERS.md A). It says nothing about real
  depletion. The category scales are calibrated to a real stock-out PREVALENCE, which cannot separate
  depletion from replenishment, so never "category X sells out faster than Y".
  This is the honest substitute for demand forecasting (CLAUDE.md section 4), not demand forecasting.

MODEL — discrete-time Weibull hazard with shared log-normal frailty, fitted by exact maximum likelihood
  A listing in stock with clock r (consecutive in-stock snapshots, including t) goes out at t+1 with

      h = 1 - exp( -exp(eta + s*z) * (r^k - (r-1)^k) ),      z ~ N(0, 1) per listing, shared by its spells
      eta = a[category] + b[platform] + g*evening(t+1) + log(1 + d*depth(t+1)) + th*pressure(t+1)

  This is the grouped-time proportional-hazards form of a Weibull, so k, a, b, g, d, th, s have direct
  meanings. z is integrated out with 24-point Gauss-Hermite quadrature; gradients are analytic; the fit is
  L-BFGS; standard errors come from a finite-difference Hessian of the analytic gradient.
  Covariates at t+1 are EVENT-TIME covariates, standard for estimation. The forecaster below never sees
  them: it uses the schedule for the hour, the panel's past discount for depth, and an AR(1) forecast of
  the pressure index.

  `platform` enters as a 4-level stratum of this structural model because the plan's claim for this
  deliverable IS the per-platform scale (docs/PROJECT_PLAN.md, deliverable 7). The rule behind the
  identifier guard is about models that memorise IDs; four platform offsets are parameters to recover,
  not a lookup.

WHY FRAILTY
  Deliverable 4 read k = 1.40 off pooled hazard curves. Fragile listings run out early, so the listings
  still in stock at long clocks are the sturdy ones and the pooled curve flattens. Integrating out a
  per-listing frailty is the standard correction. Three nested fits make the point:
      V0  no covariates, no frailty     (the pooled curve)
      V1  covariates, no frailty
      V2  covariates + frailty          <- the model
      V3  covariates + frailty, nonparametric baseline (one step per clock value, no Weibull assumed)

SPELLS USED
  Only clocks started by an OBSERVED restock (instock_clock_censored == 0). A clock that started before
  the panel is a lower bound. Fitted on transitions whose t is in the train split.

FORECAST (test) — P(out of stock within h snapshots), h = 1, 2, 4, 6 (6 = three days)
  Dynamic prediction: each listing's frailty posterior is updated with its own history up to t (every
  earlier spell and the survival of the current run so far). For a clock that started before the panel,
  the unknown elapsed time is integrated out under the equilibrium (backward-recurrence) law of the
  fitted model: P(age a, z | survived o snapshots) ∝ phi(z) * S(a + o | z).
  Baselines: life table (category x clock bucket, from train), V1 (no frailty), LightGBM trained
  directly on each horizon with every feature, including the stock clock.
"""
import json

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

import src.features.stock_clock as SC
import src.load as L
from src.model_output import save_model_outputs

NAME = 'stockout_survival'
PANEL = ['platform', 'store_id', 'product_id']
PLATFORMS = ['Blinkit', 'Swiggy Instamart', 'Flipkart Minutes', 'BigBasket']    # Blinkit = reference
HORIZONS = (1, 2, 4, 6)
Q = 24
GH_X, GH_W = np.polynomial.hermite_e.hermegauss(Q)       # probabilists' Hermite: weight exp(-x^2/2)
GH_LOGW = np.log(GH_W / GH_W.sum())
NP_MAX_R = 30          # V3: clocks above this share one step
AGE_MAX = 120          # equilibrium age support for pre-panel clocks
PROFILE_GRID = (0.0, 0.2, 0.35, 0.5, 0.65, 0.8, 1.0)
PRESSURE_CLIP = 4.0
SEED = 20260923

# planted values, docs/GENERATOR_v15_PARAMETERS.md (assumptions unless marked)
PLANTED = {
    'k': 2.0,
    'evening_ratio': 1.4 / 0.7,
    'promo_d': 1.5,
    'pressure_theta_per_sd_of_D': 0.30,
    'frailty_sd_on_log_hazard': 2.0 * 0.25,         # k * lognormal sd of lambda
    'platform_lambda_mult': {'Blinkit': 1.0, 'Swiggy Instamart': 0.9943,
                             'Flipkart Minutes': 1.0637, 'BigBasket': 1.5239},
    'category_lambda_blinkit': {
        'Baby Care': 48.8, 'Bakery & Biscuits': 28.73, 'Beverages': 116.67, 'Dairy, Bread & Eggs': 45.09,
        'Dry Fruits & Nuts': 18.88, 'Electronics & Stationery': 50.24, 'Fashion & Lifestyle': 95.53,
        'Frozen Foods': 46.78, 'Fruits & Vegetables': 16.29, 'Health & Wellness': 41.21,
        'Home & Cleaning': 111.07, 'Instant & Ready to Eat': 37.71, 'Kitchen & Dining': 65.94,
        'Masala, Oil & More': 33.69, 'Other / General Merchandise': 71.54, 'Personal Care': 55.96,
        'Pet Supplies': 83.03, 'Sauces, Spreads & Pickles': 47.73, 'Snacks & Munchies': 15.28,
        'Staples & Grains': 19.98, 'Sweets & Chocolates': 50.54, 'Tea, Coffee & More': 35.62},
    'm_morning_anchor': 0.7,     # only used to put category scales on the planted lambda scale
    'store_demand_phi': 0.5,
}


# =========================================================================== data
def build_panel_rows():
    """Every SYNTHETIC row with the next snapshot's covariates, in panel/time order."""
    ml = SC.attach(L.load_ml())
    d = ml[ml.data_status == 'SYNTHETIC'].copy()
    d['_ts'] = pd.to_datetime(d.observed_at.astype(str), format='mixed')
    d = d.sort_values(PANEL + ['_ts'], kind='stable').reset_index(drop=True)
    g = d.groupby(PANEL, sort=False)
    d['panel'] = g.ngroup()
    d['pos'] = g.cumcount()
    promo = d.mrp_source.eq('simulated_discounted')
    d['depth'] = np.where(promo, d.discount_percent / 100.0, 0.0)
    d['pressure'] = d.store_pressure_index.clip(-PRESSURE_CLIP, PRESSURE_CLIP)
    for c in ('depth', 'pressure', 'in_stock'):
        d[f'next_{c}'] = g[c].shift(-1)
    d['next_evening'] = d.next_snapshot_is_evening
    # past-only forecasts of the next covariates (what a forecaster may use)
    d['depth_hat'] = np.where(promo, d.discount_7d_avg.fillna(d.discount_percent) / 100.0, 0.0)
    # future in-stock path, for multi-horizon labels
    for j in range(1, max(HORIZONS) + 1):
        d[f'in_{j}'] = g.in_stock.shift(-j)
    return d


def transitions(d, uncensored=True):
    """Person-period rows: in stock at t, next snapshot observed."""
    m = (d.in_stock == 1) & d.next_in_stock.notna()
    if uncensored:
        m &= d.instock_clock_censored == 0
    t = d[m].copy()
    t['y'] = (t.next_in_stock == 0).astype(np.int8)
    t['r'] = t.instock_run_length.astype(float)
    t['next_pressure'] = t.next_pressure.fillna(0.0)
    return t


# =========================================================================== likelihood
class Design:
    def __init__(self, t, cats, *, covariates=True, frailty=True, nonparam=False):
        self.cats = cats
        self.covariates, self.frailty, self.nonparam = covariates, frailty, nonparam
        self.y = t.y.to_numpy(float)
        self.r = t.r.to_numpy(float)
        self.cat = pd.Categorical(t.category, categories=cats).codes.astype(np.int64) if covariates else np.zeros(len(t), np.int64)
        self.plat = pd.Categorical(t.platform, categories=PLATFORMS).codes.astype(np.int64)
        self.eve = t.next_evening.to_numpy(float)
        self.dep = t.next_depth.to_numpy(float)
        self.prs = t.next_pressure.to_numpy(float)
        pan = t.panel.to_numpy()
        self.pan_codes, self.pan = np.unique(pan, return_inverse=True)
        self.n_pan = len(self.pan_codes)
        self.rstep = (np.minimum(self.r, NP_MAX_R) - 1).astype(np.int64)
        self.n_cat = len(cats) if covariates else 1
        # parameter layout
        names = [f'a[{c}]' for c in (cats if covariates else ['all'])]
        if covariates:
            names += [f'b[{p}]' for p in PLATFORMS[1:]] + ['g_evening', 'log_d_promo', 'th_pressure']
        if nonparam:
            names += [f'step[{i + 1}]' for i in range(1, NP_MAX_R)]      # step[1] = 0 (reference)
        else:
            names += ['log_k']
        if frailty:
            names += ['log_s']
        self.names = names
        self.ix = {n: i for i, n in enumerate(names)}

    def x0(self):
        x = np.zeros(len(self.names))
        base = np.log(max(self.y.mean(), 1e-4))
        x[:self.n_cat] = base
        if self.covariates:
            x[self.ix['g_evening']] = 0.3
            x[self.ix['log_d_promo']] = 0.0
        if not self.nonparam:
            x[self.ix['log_k']] = np.log(1.3)
        if self.frailty:
            x[self.ix['log_s']] = np.log(0.3)
        return x

    def unpack(self, x):
        p = {'a': x[:self.n_cat]}
        if self.covariates:
            p['b'] = np.r_[0.0, x[self.ix[f'b[{PLATFORMS[1]}]']:self.ix[f'b[{PLATFORMS[1]}]'] + 3]]
            p['g'] = x[self.ix['g_evening']]
            p['d'] = np.exp(x[self.ix['log_d_promo']])
            p['th'] = x[self.ix['th_pressure']]
        if self.nonparam:
            i0 = self.ix['step[2]']
            p['steps'] = np.r_[0.0, x[i0:i0 + NP_MAX_R - 1]]
        else:
            p['k'] = np.exp(x[self.ix['log_k']])
        p['s'] = np.exp(x[self.ix['log_s']]) if self.frailty else 0.0
        return p

    def eta(self, p):
        e = p['a'][self.cat]
        if self.covariates:
            e = e + p['b'][self.plat] + p['g'] * self.eve + np.log1p(p['d'] * self.dep) + p['th'] * self.prs
        return e

    def log_g(self, p):
        """log of the baseline increment and its derivative wrt log k (parametric only)."""
        if self.nonparam:
            return p['steps'][self.rstep], None
        k, r = p['k'], self.r
        rk, r1k = r ** k, np.where(r > 1, (r - 1) ** k, 0.0)
        gval = rk - r1k
        lr, lr1 = np.log(r), np.where(r > 1, np.log(np.maximum(r - 1, 1)), 0.0)
        dg_dk = rk * lr - r1k * lr1
        return np.log(gval), k * dg_dk / gval           # d log g / d log k

    def nll(self, x):
        with np.errstate(over='ignore', divide='ignore', invalid='ignore'):
            return self._nll(x)

    def _nll(self, x):
        p = self.unpack(x)
        eta = self.eta(p)
        lg, dlg_dlk = self.log_g(p)
        zs = GH_X if self.frailty else np.zeros(1)
        logw = GH_LOGW if self.frailty else np.zeros(1)
        base = eta + lg
        # per row, per node
        H = np.exp(base[:, None] + p['s'] * zs[None, :])
        y = self.y[:, None]
        em1 = np.expm1(H)
        ll = np.where(y == 1, np.log(-np.expm1(-H)), -H)
        dll_deta = np.where(y == 1, H / np.where(em1 > 0, em1, 1e-300), -H)       # dl/dH * H
        # panel log-lik per node
        Lp = np.zeros((self.n_pan, len(zs)))
        for q in range(len(zs)):
            Lp[:, q] = np.bincount(self.pan, weights=ll[:, q], minlength=self.n_pan)
        A = Lp + logw[None, :]
        mx = A.max(1, keepdims=True)
        lse = mx[:, 0] + np.log(np.exp(A - mx).sum(1))
        post = np.exp(A - lse[:, None])                                          # panel posterior over nodes
        pr = post[self.pan]                                                      # row x node
        G = (pr * dll_deta).sum(1)                                               # d nll / d eta (neg later)
        grad = np.zeros(len(x))
        grad[:self.n_cat] = np.bincount(self.cat, weights=G, minlength=self.n_cat)
        if self.covariates:
            gb = np.bincount(self.plat, weights=G, minlength=4)
            i = self.ix[f'b[{PLATFORMS[1]}]']
            grad[i:i + 3] = gb[1:]
            grad[self.ix['g_evening']] = (G * self.eve).sum()
            grad[self.ix['log_d_promo']] = (G * p['d'] * self.dep / (1 + p['d'] * self.dep)).sum()
            grad[self.ix['th_pressure']] = (G * self.prs).sum()
        if self.nonparam:
            gs = np.bincount(self.rstep, weights=G, minlength=NP_MAX_R)
            i0 = self.ix['step[2]']
            grad[i0:i0 + NP_MAX_R - 1] = gs[1:]
        else:
            grad[self.ix['log_k']] = (G * dlg_dlk).sum()
        if self.frailty:
            grad[self.ix['log_s']] = ((pr * dll_deta) * zs[None, :]).sum() * p['s']
        return -lse.sum(), -grad

    def posterior_node_weights(self, x):
        """Panel posterior over quadrature nodes (for inspection)."""
        p = self.unpack(x)
        H = np.exp((self.eta(p) + self.log_g(p)[0])[:, None] + p['s'] * GH_X[None, :])
        ll = np.where(self.y[:, None] == 1, np.log(-np.expm1(-H)), -H)
        Lp = np.stack([np.bincount(self.pan, weights=ll[:, q], minlength=self.n_pan) for q in range(Q)], 1)
        A = Lp + GH_LOGW
        return np.exp(A - A.max(1, keepdims=True)) / np.exp(A - A.max(1, keepdims=True)).sum(1, keepdims=True)


def fit(design, label, hessian=True, x0=None):
    x0 = design.x0() if x0 is None else x0
    res = minimize(design.nll, x0, jac=True, method='L-BFGS-B',
                   options={'maxiter': 2000, 'maxfun': 4000, 'gtol': 1e-6})
    x = res.x
    if not hessian:
        print(f"  {label:<34} nll {res.fun:,.1f}  iters {res.nit}  {'converged' if res.success else res.message}")
        return {'x': x, 'se': np.full(len(x), np.nan), 'cov': None, 'nll': float(res.fun), 'n_params': len(x),
                'success': bool(res.success), 'n_rows': int(len(design.y)), 'n_panels': int(design.n_pan),
                'design': design}
    # SE: finite-difference Hessian of the analytic gradient
    n = len(x)
    Hm = np.zeros((n, n))
    for i in range(n):
        h = 1e-4 * max(1.0, abs(x[i]))
        e = np.zeros(n); e[i] = h
        Hm[:, i] = (design.nll(x + e)[1] - design.nll(x - e)[1]) / (2 * h)
    Hm = (Hm + Hm.T) / 2
    try:
        cov = np.linalg.inv(Hm)
        se = np.sqrt(np.clip(np.diag(cov), 0, None))
    except np.linalg.LinAlgError:
        cov, se = None, np.full(n, np.nan)
    print(f"  {label:<34} nll {res.fun:,.1f}  iters {res.nit}  {'converged' if res.success else res.message}")
    return {'x': x, 'se': se, 'cov': cov, 'nll': float(res.fun), 'n_params': n, 'success': bool(res.success),
            'n_rows': int(len(design.y)), 'n_panels': int(design.n_pan), 'design': design}


def profile_frailty(design, x_start, grid):
    """Profile likelihood of the frailty sd: re-optimise everything else at each fixed s."""
    i = design.ix['log_s']
    out, xm = [], np.delete(x_start, i)
    for sv in grid:
        ls = np.log(max(sv, 1e-6))
        def f(xm_):
            v, g = design.nll(np.insert(xm_, i, ls))
            return v, np.delete(g, i)
        res = minimize(f, xm, jac=True, method='L-BFGS-B', options={'maxiter': 2000, 'gtol': 1e-6})
        xm = res.x
        k = float(np.exp(np.insert(res.x, i, ls)[design.ix['log_k']]))
        out.append({'s': float(sv), 'nll': float(res.fun), 'k_at_s': k})
        print(f"    profile s = {sv:.2f}: nll {res.fun:,.2f}  k {k:.3f}")
    return pd.DataFrame(out)


def profile_ci(prof, nll_hat, s_hat, crit=3.84):
    """95% profile-likelihood interval for the frailty sd: a parabola through the optimum and its grid
    neighbours on each side, solved for 2 * (nll - nll_hat) = crit."""
    pts = pd.concat([prof[['s', 'nll']], pd.DataFrame({'s': [s_hat], 'nll': [nll_hat]})]).sort_values('s')
    pts = pts.drop_duplicates('s').reset_index(drop=True)
    i = int(pts.nll.idxmin())
    out = []
    for side in (-1, 1):
        j = i + side
        if j < 0 or j >= len(pts):
            out.append(np.nan); continue
        k = j + side if 0 <= j + side < len(pts) else i - side
        a, b, c = np.polyfit(pts.s[[i, j, k]], 2 * (pts.nll[[i, j, k]] - pts.nll[i]), 2)
        roots = np.roots([a, b, c - crit]).real
        roots = roots[(roots - pts.s[i]) * side > 0]
        out.append(float(roots[np.argmin(np.abs(roots - pts.s[i]))]) if len(roots) else np.nan)
    return out[0], out[1]


# =========================================================================== recovery
def recovery_table(f2, f1, f0, f3, cats, prof):
    d2 = f2['design']; x, se = f2['x'], f2['se']
    p = d2.unpack(x)
    k, k_se = p['k'], p['k'] * se[d2.ix['log_k']]
    rows = []

    def row(name, planted, est, lo, hi, note=''):
        rows.append({'parameter': name, 'planted': planted, 'estimate': est, 'ci_low': lo, 'ci_high': hi,
                     'covered': bool(lo <= planted <= hi) if planted is not None else None, 'note': note})

    row('k (Weibull shape) — V2 frailty', PLANTED['k'], k, k - 1.96 * k_se, k + 1.96 * k_se)
    for f, lab in ((f1, 'V1 covariates, no frailty'), (f0, 'V0 pooled, no frailty')):
        kk = f['design'].unpack(f['x'])['k']; kse = kk * f['se'][f['design'].ix['log_k']]
        row(f'k — {lab}', PLANTED['k'], kk, kk - 1.96 * kse, kk + 1.96 * kse, 'expected biased low')
    g, g_se = p['g'], se[d2.ix['g_evening']]
    row('evening multiplier (18:00 / 09:00)', PLANTED['evening_ratio'], np.exp(g),
        np.exp(g - 1.96 * g_se), np.exp(g + 1.96 * g_se))
    dd, d_se = p['d'], p['d'] * se[d2.ix['log_d_promo']]
    row('promo d in (1 + d * depth)', PLANTED['promo_d'], dd, dd - 1.96 * d_se, dd + 1.96 * d_se)
    th, th_se = p['th'], se[d2.ix['th_pressure']]
    row('store pressure theta (per sd of index)', PLANTED['pressure_theta_per_sd_of_D'], th,
        th - 1.96 * th_se, th + 1.96 * th_se,
        'index is an ETA-based estimate of the latent D: errors-in-variables attenuate it toward 0')
    # frailty sd: profile-likelihood interval (a Wald interval is invalid near the s = 0 boundary)
    s = p['s']
    lo, hi = profile_ci(prof, f2['nll'], s)
    row('frailty sd on log hazard (= k x 0.25)', PLANTED['frailty_sd_on_log_hazard'], s, lo, hi,
        'profile-likelihood 95% interval (quadratic through the grid points around the optimum); '
        'listings with an observed restock only (a selected sample)')
    # platform multipliers on lambda: lambda_p / lambda_Blinkit = exp(-b_p / k)
    for j, pl in enumerate(PLATFORMS[1:]):
        i = d2.ix[f'b[{pl}]']
        # delta method on exp(-b/k)
        b = x[i]
        grad = np.zeros(len(x))
        val = np.exp(-b / k)
        grad[i] = -val / k
        grad[d2.ix['log_k']] = val * b / k            # d/dlogk of exp(-b e^{-logk}) = val * b / k
        v = float(grad @ f2['cov'] @ grad) if f2['cov'] is not None else np.nan
        row(f'platform lambda multiplier: {pl}', PLANTED['platform_lambda_mult'][pl], val,
            val - 1.96 * np.sqrt(v), val + 1.96 * np.sqrt(v))
    # category scales, anchored on m(09:00) = 0.7: exp(a_c) = 0.7 * lambda_c^-k
    lam_hat = {c: float((PLANTED['m_morning_anchor'] / np.exp(p['a'][i])) ** (1 / k)) for i, c in enumerate(cats)}
    lam_true = {c: PLANTED['category_lambda_blinkit'][c] for c in cats}
    lt, lh = np.log(list(lam_true.values())), np.log(list(lam_hat.values()))
    cat_summary = {'log_corr': float(np.corrcoef(lt, lh)[0, 1]),
                   'median_abs_pct_error': float(np.median(np.abs(np.exp(lh - lt) - 1))),
                   'slope_log_hat_on_log_true': float(np.polyfit(lt, lh, 1)[0]),
                   'per_category': {c: {'planted': lam_true[c], 'estimate': lam_hat[c]} for c in cats},
                   'note': ('Category scale and the hazard multiplier m are not separately identified; '
                            'estimates are put on the planted scale with m(09:00) = 0.7 as the anchor. '
                            'The correlation and slope do not depend on the anchor.')}
    # V3 nonparametric baseline: fit k to its steps
    d3 = f3['design']; p3 = d3.unpack(f3['x'])
    rr = np.arange(1, NP_MAX_R)            # exclude the pooled top step
    steps = p3['steps'][:NP_MAX_R - 1]
    from scipy.optimize import curve_fit
    fk = lambda r, c, k: c + np.log(r ** k - (r - 1) ** k)
    se3 = f3['se']; i0 = d3.ix['step[2]']
    sig = np.r_[0.05, se3[i0:i0 + NP_MAX_R - 2]]
    (c3, k3), cov3 = curve_fit(fk, rr, steps, p0=[0, 1.5], sigma=np.maximum(sig, 1e-3))
    row('k — V3 read off the nonparametric frailty baseline', PLANTED['k'], k3,
        k3 - 1.96 * np.sqrt(cov3[1, 1]), k3 + 1.96 * np.sqrt(cov3[1, 1]),
        'no Weibull assumed in the fit; the shape is fitted to the free steps afterwards')
    return pd.DataFrame(rows), cat_summary, {'r': rr.tolist(), 'steps': steps.tolist(),
                                             'steps_se': sig.tolist(), 'c': float(c3), 'k': float(k3)}


# =========================================================================== forecasting
def _eta_forecast(p, cat_code, plat_code, eve, dep, prs):
    return p['a'][cat_code] + p['b'][plat_code] + p['g'] * eve + np.log1p(p['d'] * dep) + p['th'] * prs


def _log_g(r, k):
    return np.log(r ** k - np.where(r > 1, (r - 1) ** k, 0.0))


def dynamic_forecast(d, fitres, cats, phi, rows_mask, use_frailty=True):
    """P(OOS within h) for rows_mask rows of d (in stock at t). Frailty posterior uses history < t."""
    des = fitres['design']
    p = des.unpack(fitres['x'])
    s = p['s'] if use_frailty else 0.0
    zs = GH_X if use_frailty else np.zeros(1)
    logw = GH_LOGW if use_frailty else np.zeros(1)
    nq = len(zs)
    cat_all = pd.Categorical(d.category, categories=cats).codes
    plat_all = pd.Categorical(d.platform, categories=PLATFORMS).codes

    # ---- history log-lik per row per node: transitions with uncensored clocks, realised event-time covariates
    hist = (d.in_stock == 1) & d.next_in_stock.notna() & (d.instock_clock_censored == 0)
    eta_h = _eta_forecast(p, cat_all, plat_all, d.next_evening.fillna(0).to_numpy(),
                          d.next_depth.fillna(0).to_numpy(), d.next_pressure.fillna(0).clip(-PRESSURE_CLIP, PRESSURE_CLIP).to_numpy())
    r_all = np.maximum(d.instock_run_length.to_numpy(float), 1)
    Hh = np.exp((eta_h + _log_g(r_all, p['k']))[:, None] + s * zs[None, :])
    yh = (d.next_in_stock.fillna(-1) == 0).to_numpy(bool)[:, None]
    llh = np.where(yh, np.log(-np.expm1(-Hh)), -Hh)
    llh[~hist.to_numpy()] = 0.0
    # exclusive cumulative sum within panel: history strictly before t
    cs = pd.DataFrame(llh).groupby(d.panel.to_numpy()).cumsum().to_numpy() - llh

    idx = np.flatnonzero(rows_mask.to_numpy())
    sub = d.iloc[idx]
    cens = sub.instock_clock_censored.to_numpy() == 1
    r0 = sub.instock_run_length.to_numpy(float)
    eve0 = sub.next_snapshot_is_evening.to_numpy(float)
    dep0 = sub.depth_hat.to_numpy(float)
    prs0 = sub.pressure.fillna(0).to_numpy(float)
    c0, p0 = cat_all[idx], plat_all[idx]

    def cumH(r_start, n_steps, z_scale):
        """cumulative hazard over the next n_steps from clock r_start, per node."""
        tot = np.zeros((len(idx), nq))
        out = {}
        for j in range(1, n_steps + 1):
            eve = eve0 if j % 2 == 1 else 1 - eve0             # 09:00 / 18:00 alternate
            e = _eta_forecast(p, c0, p0, eve, dep0, prs0 * phi ** j)
            H = np.exp((e + _log_g(r_start + j - 1, p['k']))[:, None] + z_scale * zs[None, :])
            tot = tot + H
            out[j] = tot.copy()
        return out

    hmax = max(HORIZONS)
    res = {h: np.zeros(len(idx)) for h in HORIZONS}
    # ---- uncensored clocks: posterior over z from history
    u = ~cens
    if u.any():
        A = cs[idx[u]] + logw[None, :]
        post = np.exp(A - A.max(1, keepdims=True)); post /= post.sum(1, keepdims=True)
        # the current run's survival so far (r0-1 transitions) is already inside cs
        ch = cumH(r0, hmax, s)
        for h in HORIZONS:
            res[h][u] = 1 - (post * np.exp(-ch[h][u])).sum(1)
    # ---- censored clocks: integrate the unknown pre-panel age a (equilibrium law) and z
    if cens.any():
        ci = np.flatnonzero(cens)
        # baseline cumulative hazard for an average snapshot (hour effect averaged, current depth, no pressure)
        e_avg = (_eta_forecast(p, c0[ci], p0[ci], 0.5 * np.ones(len(ci)), dep0[ci], np.zeros(len(ci))))
        ages = np.arange(0, AGE_MAX + 1, dtype=float)
        o = r0[ci]                                            # snapshots survived inside the panel
        # Lambda0(x) = x^k: survival to clock x is exp(-exp(e + s z) * x^k)
        acc = {h: np.zeros(len(ci)) for h in HORIZONS}
        wz_tot = np.zeros(len(ci))
        e_steps = np.stack([_eta_forecast(p, c0[ci], p0[ci], eve0[ci] if j % 2 == 1 else 1 - eve0[ci],
                                          dep0[ci], prs0[ci] * phi ** j) for j in range(1, hmax + 1)], 1)
        clock = ages[None, :] + o[:, None]                     # true clock at t = pre-panel age + o
        for q in range(nq):
            mult = np.exp(e_avg + s * zs[q])
            # reaching clock c takes c - 1 in-stock transitions: cumulative hazard (c - 1)^k
            lw = logw[q] - mult[:, None] * (clock - 1) ** p['k']
            mx = lw.max(1, keepdims=True)
            w = np.exp(lw - mx)
            scale = np.exp(mx[:, 0])
            wz_tot += w.sum(1) * scale
            Hs = np.zeros_like(clock)
            for j in range(1, hmax + 1):
                cj = clock + j - 1                             # clock during step j, same convention as the fit
                Hs = Hs + np.exp(e_steps[:, j - 1][:, None] + s * zs[q]) * (cj ** p['k'] - (cj - 1) ** p['k'])
                if j in acc:
                    acc[j] += (w * np.exp(-Hs)).sum(1) * scale
        for h in HORIZONS:
            res[h][ci] = 1 - acc[h] / wz_tot
    return res


def life_table(train_rows, cats):
    """P(OOS within h | category, clock bucket, censored flag) from train rows."""
    t = train_rows.copy()
    t['bucket'] = np.minimum(t.instock_run_length, 30).astype(int)
    out = {}
    for h in HORIZONS:
        lab = f'oos_within_{h}'
        ok = t[lab].notna()
        tab = t[ok].groupby(['category', 'instock_clock_censored', 'bucket'])[lab].agg(['sum', 'count'])
        prior = t[ok].groupby('category')[lab].mean()
        pr = tab.index.get_level_values(0).map(prior).to_numpy()
        tab['rate'] = (tab['sum'] + 20 * pr) / (tab['count'] + 20)
        out[h] = (tab['rate'], prior)
    return out


def life_table_predict(lt, rows, h):
    tab, prior = lt[h]
    idx = pd.MultiIndex.from_arrays([rows.category, rows.instock_clock_censored,
                                     np.minimum(rows.instock_run_length, 30).astype(int)])
    p = pd.Series(tab.reindex(idx).to_numpy(), index=rows.index)
    return p.fillna(rows.category.map(prior)).to_numpy()


def add_horizon_labels(d):
    for h in HORIZONS:
        fut = d[[f'in_{j}' for j in range(1, h + 1)]]
        fut = fut.astype(float)
        complete = fut.notna().all(axis=1)
        d[f'oos_within_{h}'] = np.where(complete, (fut == 0).any(axis=1).astype(float), np.nan)
    return d


def score(y, p):
    y = np.asarray(y, int); p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return {'log_loss': float(log_loss(y, p, labels=[0, 1])), 'brier': float(brier_score_loss(y, p)),
            'roc_auc': float(roc_auc_score(y, p)), 'base_rate': float(y.mean()), 'mean_pred': float(p.mean()),
            'n': int(len(y))}


# =========================================================================== main
def main():
    d = add_horizon_labels(build_panel_rows())
    cats = sorted(d.category.unique())
    assert set(cats) <= set(PLANTED['category_lambda_blinkit']), 'category without a planted scale'

    # ---- store pressure persistence (recovers the AR(1) phi of the latent demand)
    st = (d.groupby(['platform', 'store_id', 'pos']).pressure.first().rename('p').reset_index())
    st['lag'] = st.groupby(['platform', 'store_id']).p.shift()
    st_tr = st.merge(d[['platform', 'store_id', 'pos', 'split']].drop_duplicates(['platform', 'store_id', 'pos']),
                     on=['platform', 'store_id', 'pos'])
    st_tr = st_tr[st_tr.split == 'train'][['p', 'lag']].dropna()
    phi = float(np.corrcoef(st_tr.p, st_tr.lag)[0, 1])
    print(f"store pressure index AR(1) phi on train: {phi:.3f} (planted {PLANTED['store_demand_phi']})")

    # ---- fit on train transitions with observed-restock clocks
    tr_all = transitions(d)
    tr = tr_all[tr_all.split == 'train']

    # ---- RECOVERY: the whole 60-snapshot panel (a parameter check, not a forecast, so no split needed;
    # on train alone most listings have a single spell and the frailty sd is not identified)
    print(f"RECOVERY fit on {len(tr_all):,} transitions, {tr_all.panel.nunique():,} listings, "
          f"{int(tr_all.y.sum()):,} stock-outs (all splits)")
    f0 = fit(Design(tr_all, cats, covariates=False, frailty=False), 'V0 pooled Weibull')
    f1 = fit(Design(tr_all, cats, covariates=True, frailty=False), 'V1 + covariates')
    d2 = Design(tr_all, cats, covariates=True, frailty=True)
    f2 = fit(d2, 'V2 + covariates + frailty')
    f3 = fit(Design(tr_all, cats, covariates=True, frailty=True, nonparam=True), 'V3 nonparametric + frailty')
    lr = 2 * (f1['nll'] - f2['nll'])
    print('  frailty profile likelihood:')
    prof = profile_frailty(d2, f2['x'], PROFILE_GRID)
    rec, cat_summary, np_curve = recovery_table(f2, f1, f0, f3, cats, prof)
    print(rec.round(3).to_string())
    print({k: round(v, 3) for k, v in cat_summary.items() if not isinstance(v, (dict, str))})

    # ---- FORECAST models: train transitions only
    print(f"FORECAST fit on {len(tr):,} train transitions")
    g1 = fit(Design(tr, cats, covariates=True, frailty=False), 'V1 train', hessian=False)
    g2 = fit(Design(tr, cats, covariates=True, frailty=True), 'V2 train', hessian=False)

    # ---- forecast on test rows in stock
    test_rows = (d.split == 'test') & (d.in_stock == 1)
    print(f"forecasting {int(test_rows.sum()):,} test rows ...")
    fc2 = dynamic_forecast(d, g2, cats, phi, test_rows, use_frailty=True)
    fc1 = dynamic_forecast(d, g1, cats, phi, test_rows, use_frailty=False)
    T = d[test_rows].copy()
    lt = life_table(d[(d.split == 'train') & (d.in_stock == 1)], cats)

    # ---- LightGBM direct, one model per horizon (all features incl. stock clock; label within train)
    base_feats = [f for f in L.feature_columns(d) if f not in SC.NEW_COLUMNS]
    feats = L.check_feature_set(base_feats + SC.NEW_COLUMNS + ['category'])
    cat_levels = cats
    def prep(x):
        X = x[feats].copy(); X['category'] = pd.Categorical(X.category, categories=cat_levels); return X
    tr_in = d[(d.split == 'train') & (d.in_stock == 1)]
    va_in = d[(d.split == 'val') & (d.in_stock == 1)]
    # labels must not reach past the split's last snapshot
    last_pos = d.groupby('split').pos.max()
    lgb_pred = {}
    for h in HORIZONS:
        lab = f'oos_within_{h}'
        a = tr_in[tr_in[lab].notna() & (tr_in.pos + h <= last_pos['train'])]
        b = va_in[va_in[lab].notna() & (va_in.pos + h <= last_pos['val'])]
        booster = lgb.train({'objective': 'binary', 'learning_rate': 0.05, 'num_leaves': 63,
                             'min_data_in_leaf': 200, 'feature_fraction': 0.8, 'bagging_fraction': 0.8,
                             'bagging_freq': 1, 'lambda_l2': 5.0, 'verbose': -1, 'seed': SEED},
                            lgb.Dataset(prep(a), a[lab], categorical_feature=['category']), 3000,
                            valid_sets=[lgb.Dataset(prep(b), b[lab], categorical_feature=['category'])],
                            callbacks=[lgb.early_stopping(100, verbose=False)])
        lgb_pred[h] = booster.predict(prep(T), num_iteration=booster.best_iteration)

    results = {}
    for h in HORIZONS:
        lab = f'oos_within_{h}'
        ok = T[lab].notna().to_numpy()
        y = T[lab].to_numpy()[ok]
        cand = {'frailty_survival (V2)': fc2[h][ok], 'weibull_no_frailty (V1)': fc1[h][ok],
                'life_table (category x clock)': life_table_predict(lt, T[ok], h),
                'lightgbm_direct': lgb_pred[h][ok]}
        res_h = {k: score(y, v) for k, v in cand.items()}
        cm = T.instock_clock_censored.to_numpy()[ok] == 0
        res_h['frailty_survival (V2) | observed-restock clocks'] = score(y[cm], fc2[h][ok][cm])
        res_h['frailty_survival (V2) | pre-panel clocks'] = score(y[~cm], fc2[h][ok][~cm])
        res_h['life_table | observed-restock clocks'] = score(y[cm], cand['life_table (category x clock)'][cm])
        res_h['lightgbm_direct | observed-restock clocks'] = score(y[cm], lgb_pred[h][ok][cm])
        results[f'h{h}'] = res_h

    # ---- expected time to OOS and median, from V2 (per row), plus a "fragility" posterior mean
    T['p_oos_1'], T['p_oos_2'], T['p_oos_4'], T['p_oos_6'] = fc2[1], fc2[2], fc2[4], fc2[6]

    verdict_bits = {}
    for h in HORIZONS:
        r = results[f'h{h}']
        verdict_bits[h] = {
            'beats_life_table': r['frailty_survival (V2)']['log_loss'] < r['life_table (category x clock)']['log_loss'],
            'beats_no_frailty': r['frailty_survival (V2)']['log_loss'] < r['weibull_no_frailty (V1)']['log_loss'],
            'vs_lightgbm_log_loss': r['frailty_survival (V2)']['log_loss'] - r['lightgbm_direct']['log_loss']}
    covered = rec[rec.parameter.str.contains('V2|evening|promo|platform|V3')]
    metrics = {
        'claim_limit': ('SYNTHETIC panel. Parameter recovery shows the pipeline recovers the v15.1 planted '
                        'hazard; the forecasts are forecasts of generated stock. Not market findings, and not '
                        'a demand forecast.'),
        'fit': {v: {'nll': f['nll'], 'n_params': f['n_params'], 'rows': f['n_rows'], 'listings': f['n_panels'],
                    'converged': f['success']} for v, f in
                (('V0', f0), ('V1', f1), ('V2', f2), ('V3', f3))},
        'frailty_likelihood_ratio_V1_vs_V2': float(lr),
        'frailty_profile': prof.to_dict(orient='records'),
        'forecast_fit_train': {'V1': {'nll': g1['nll']}, 'V2': {'nll': g2['nll'], 's': float(g2['design'].unpack(g2['x'])['s']),
                                                                'k': float(g2['design'].unpack(g2['x'])['k'])}},
        'parameter_recovery': rec.to_dict(orient='records'),
        'category_scale_recovery': cat_summary,
        'nonparametric_baseline_V3': np_curve,
        'store_pressure_phi': {'estimate': phi, 'planted': PLANTED['store_demand_phi']},
        'forecast_test': results,
        'verdict_by_horizon': verdict_bits,
    }

    out = pd.DataFrame({
        'observation_key': T.observation_key.to_numpy(), 'data_status': T.data_status.to_numpy(),
        'platform': T.platform.to_numpy(), 'store_id': T.store_id.to_numpy(), 'category': T.category.to_numpy(),
        'snapshot_date': T.date.astype(str).to_numpy(), 'hour': T.hour.to_numpy(),
        'instock_run_length': T.instock_run_length.to_numpy(),
        'clock_started_before_panel': T.instock_clock_censored.to_numpy(),
        'prediction': fc2[6],                                   # headline: P(OOS within 3 days)
        **{f'p_oos_within_{h}': fc2[h] for h in HORIZONS},
        **{f'actual_oos_within_{h}': T[f'oos_within_{h}'].to_numpy() for h in HORIZONS},
        **{f'lightgbm_p_oos_within_{h}': lgb_pred[h] for h in HORIZONS},
    })
    mdir = save_model_outputs(
        NAME, out,
        params={'model': 'discrete-time Weibull PH, shared log-normal frailty, exact ML (Gauss-Hermite Q=24)',
                'estimates_V2': dict(zip(f2['design'].names, f2['x'].tolist())),
                'se_V2': dict(zip(f2['design'].names, f2['se'].tolist())),
                'estimates_V1': dict(zip(f1['design'].names, f1['x'].tolist())),
                'forecast_estimates_V2_train': dict(zip(g2['design'].names, g2['x'].tolist())),
                'nonparam_max_clock': NP_MAX_R, 'age_support_for_pre_panel_clocks': AGE_MAX,
                'pressure_clip': PRESSURE_CLIP, 'pressure_phi_used_for_forecast': phi,
                'categories': cats, 'platforms': PLATFORMS},
        metrics=metrics, training_data=d[d.split == 'train'],
        split={'source': "pipeline 'split' column", 'recovery_fit': 'all synthetic transitions (parameter check)',
               'forecast_fit': 'train transitions (observed-restock clocks)',
               'lightgbm_early_stopping_on': 'val', 'evaluated_on': 'test rows in stock'},
        target='time to out-of-stock (P(OOS within 1, 2, 4, 6 snapshots))',
        feature_columns=feats,
        notes=('Deliverable 7. SYNTHETIC ONLY. Structural frailty survival model: recovers the planted '
               'discrete-Weibull hazard and forecasts time to stock-out. platform is a 4-level stratum of the '
               'structural model (its scale is the parameter the plan asks to recover); feature_columns lists '
               'the LightGBM comparison model inputs.'))
    rec.to_csv(mdir / 'parameter_recovery.csv', index=False)
    _figures(mdir, d, tr_all, f0, f2, f3, np_curve, rec, cat_summary, results)

    print('\n' + '=' * 72)
    print(f"frailty LR test V1 -> V2: {lr:,.1f} (1 df)")
    for h in HORIZONS:
        print(f"h={h}: " + ' | '.join(f"{k.split(' ')[0]} {v['log_loss']:.4f}/{v['roc_auc']:.3f}"
                                      for k, v in results[f'h{h}'].items() if '|' not in k))
    print(json.dumps(verdict_bits, indent=1))


def _figures(mdir, d, tr, f0, f2, f3, np_curve, rec, cat_summary, results):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    ink, muted, grid = '#1f2328', '#6e7781', '#d0d7de'
    c_model, c_base, c_emp, c_true = '#0969da', '#bc4c00', '#1a7f37', '#8250df'
    fig, ax = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('Deliverable 7 · stockout-hazard survival (frailty model)  —  SYNTHETIC panel: '
                 'pipeline check, not a market finding', fontsize=12.5, color=ink, x=0.01, ha='left')

    # A: the frailty correction un-flattens the hazard shape
    a = ax[0, 0]
    r = np.arange(1, NP_MAX_R)
    true = np.log(r ** 2.0 - (r - 1) ** 2.0)
    v3 = np.array(np_curve['steps']); v3se = np.array(np_curve['steps_se'])
    emp = tr.groupby(np.minimum(tr.r, NP_MAX_R)).y.mean().reindex(r)
    emp_log = np.log(-np.log(1 - emp.to_numpy()))
    norm = lambda v: v - v[0]
    a.plot(r, norm(true), color=c_true, lw=2.2, label='planted shape, k = 2')
    a.errorbar(r, norm(v3), yerr=1.96 * v3se, fmt='o', ms=4, color=c_model, lw=1,
               label=f'frailty model, free steps (V3)  → k̂ = {np_curve["k"]:.2f}')
    a.plot(r, norm(emp_log), 's--', ms=3.5, color=c_base, lw=1,
           label='pooled observed hazard (no frailty)')
    a.set_xlabel('in-stock clock r (snapshots since an observed restock)')
    a.set_ylabel('log hazard increment, relative to r = 1')
    a.set_title('A · integrating out product frailty restores the rising hazard', fontsize=10, loc='left')
    a.legend(frameon=False, fontsize=8.5, loc='lower right')

    # B: recovery forest
    a = ax[0, 1]
    rr = rec[rec.planted.notna()].copy()
    rr['rel'] = rr.estimate / rr.planted
    rr['lo'] = rr.ci_low / rr.planted; rr['hi'] = rr.ci_high / rr.planted
    yy = np.arange(len(rr))[::-1]
    cols = [c_model if cov else c_base for cov in rr.covered]
    a.axvline(1, color=c_true, lw=1.5)
    a.hlines(yy, rr.lo, rr.hi, color=cols, lw=2)
    a.scatter(rr.rel, yy, color=cols, zorder=3, s=26)
    a.set_yticks(yy); a.set_yticklabels(rr.parameter, fontsize=8)
    a.set_xlabel('estimate / planted   (95% CI; blue = CI covers the planted value)')
    a.set_title('B · planted-parameter recovery', fontsize=10, loc='left')

    # C: category scales
    a = ax[1, 0]
    pc = cat_summary['per_category']
    t = np.array([v['planted'] for v in pc.values()]); e = np.array([v['estimate'] for v in pc.values()])
    lim = [min(t.min(), e.min()) * 0.85, max(t.max(), e.max()) * 1.15]
    a.plot(lim, lim, color=grid, lw=1)
    a.scatter(t, e, color=c_model, s=28)
    for name, x_, y_ in zip(pc, t, e):
        if name in ('Beverages', 'Snacks & Munchies', 'Home & Cleaning', 'Fruits & Vegetables', 'Staples & Grains'):
            a.annotate(name, (x_, y_), fontsize=7.5, color=muted, xytext=(4, -3), textcoords='offset points')
    a.set_xscale('log'); a.set_yscale('log')
    a.set_xlabel('planted category scale λ (Blinkit, snapshots)'); a.set_ylabel('recovered λ')
    a.set_title(f'C · 22 category scales, log-corr {cat_summary["log_corr"]:.3f}  '
                f'(generated values, not depletion rates)', fontsize=10, loc='left')

    # D: forecast skill by horizon
    a = ax[1, 1]
    hs = list(HORIZONS)
    for key, col, lab in (('frailty_survival (V2)', c_model, 'frailty survival (V2)'),
                          ('lightgbm_direct', c_emp, 'LightGBM, one model per horizon'),
                          ('weibull_no_frailty (V1)', muted, 'Weibull, no frailty (V1)'),
                          ('life_table (category x clock)', c_base, 'life table')):
        a.plot(hs, [results[f'h{h}'][key]['roc_auc'] for h in hs], 'o-', color=col, lw=2 if 'V2' in key else 1.3, label=lab)
    a.set_xticks(hs); a.set_xticklabels([f'{h}\n({h / 2:g} d)' for h in hs])
    a.set_xlabel('horizon (snapshots)'); a.set_ylabel('ROC-AUC, P(out of stock within h)')
    a.set_title('D · time-to-stock-out forecast on test', fontsize=10, loc='left')
    a.legend(frameon=False, fontsize=8.5)

    for a in ax.flat:
        a.spines[['top', 'right']].set_visible(False)
        a.grid(color=grid, lw=0.5, alpha=0.6); a.set_axisbelow(True)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    (mdir / 'figures').mkdir(exist_ok=True)
    fig.savefig(mdir / 'figures' / 'stockout_survival.png', dpi=130)
    plt.close(fig)


if __name__ == '__main__':
    main()
