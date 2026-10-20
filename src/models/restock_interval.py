"""
restock_interval.py — deliverable 8, restock-interval model (how long a stock-out lasts). SYNTHETIC.

    python -m src.features.stock_clock        # once
    python -m src.models.restock_interval

WHAT THIS MAY AND MAY NOT CLAIM
  Every out-of-stock spell here is SYNTHETIC. Recovering the spell-length distribution, its platform
  multipliers and the hidden FAST / MEDIUM / SLOW grouping shows the pipeline recovers the v15.1
  generator's planted restock process (docs/GENERATOR_v15_PARAMETERS.md B, all 🟠 assumptions). It says
  nothing about real replenishment. This is the honest substitute for reorder prediction (CLAUDE.md s.4).

MODEL — censored negative-binomial spell length, exact maximum likelihood
  An OOS spell lasts D >= 1 snapshots:   D - 1 ~ NegBin(n, mean = mu - 1),   log mu = a[category] + b[platform]
  Spells that started before the panel are dropped (length unknown). Spells still running at the end of
  the data are right-censored: they contribute P(D >= observed).
  Nested alternatives, compared by likelihood ratio / AIC:
    geometric      n = 1 (memoryless: the chance of coming back does not depend on how long it has been out)
    negbin         n free                                                      <- the model
    negbin + null  plus hour, promo depth and store pressure at the stock-out moment. None was planted, so
                   the right answer is "no effect" — a negative control against the model inventing structure.

LATENT GROUPS — discovered, not given
  The generator assigns each category to FAST / MEDIUM / SLOW. The model is never told. The 22 fitted
  category effects a[c] (with their standard errors) are clustered by a 1-D Gaussian mixture that accounts
  for each estimate's own uncertainty; the number of groups is chosen by BIC. The discovered partition is
  then compared with the planted one (adjusted Rand index), and a 3-group model (group x platform, 6
  parameters for the means) is tested against the 22-category model.

FORECAST — "when will it be back?" (test rows out of stock)
  P(back in stock within h snapshots | out for a snapshots so far), h = 1, 2, 4:
      P = [F(a + h - 1) - F(a - 1)] / [1 - F(a - 1)]                    (F = CDF of D)
  Fit on spells that start in train, censored at the train boundary. Baselines: the life table by elapsed
  time x category, the geometric model, deliverable 4's restock head (h = 1 only), and a LightGBM per horizon.
  Each OOS listing also gets a median return snapshot, translated into a date and time via the schedule.
"""
import json

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import nbinom
from sklearn.metrics import adjusted_rand_score, brier_score_loss, log_loss, roc_auc_score

import src.features.stock_clock as SC
import src.load as L
from src.model_output import MODELS_DIR, save_model_outputs

NAME = 'restock_interval'
PANEL = ['platform', 'store_id', 'product_id']
PLATFORMS = ['Blinkit', 'Swiggy Instamart', 'Flipkart Minutes', 'BigBasket']
HORIZONS = (1, 2, 4)
SEED = 20260923
MAX_GROUPS = 5

# planted, docs/GENERATOR_v15_PARAMETERS.md B (🟠 assumptions)
PLANTED = {
    'negbin_n': 2.0,
    'group_mu': {'FAST': 1.6, 'MEDIUM': 2.5, 'SLOW': 4.0},
    'platform_mult': {'Blinkit': 0.85, 'Swiggy Instamart': 0.90, 'Flipkart Minutes': 1.25, 'BigBasket': 1.15},
    'group_of': {'Fruits & Vegetables': 'FAST', 'Dairy, Bread & Eggs': 'FAST',
                 'Home & Cleaning': 'SLOW', 'Kitchen & Dining': 'SLOW', 'Electronics & Stationery': 'SLOW',
                 'Fashion & Lifestyle': 'SLOW', 'Other / General Merchandise': 'SLOW'},   # rest MEDIUM
    'null_effects': {'evening_at_stockout': 0.0, 'promo_depth_at_stockout': 0.0, 'store_pressure_at_stockout': 0.0},
}


def planted_group(c):
    return PLANTED['group_of'].get(c, 'MEDIUM')


# =========================================================================== spells
def load_rows():
    ml = SC.attach(L.load_ml())
    d = ml[ml.data_status == 'SYNTHETIC'].copy()
    d['_ts'] = pd.to_datetime(d.observed_at.astype(str), format='mixed')
    d = d.sort_values(PANEL + ['_ts'], kind='stable').reset_index(drop=True)
    g = d.groupby(PANEL, sort=False)
    d['panel'] = g.ngroup()
    d['pos'] = g.cumcount()
    d['in_stock'] = d.in_stock.astype(int)
    for j in range(1, max(HORIZONS) + 1):
        d[f'in_{j}'] = g.in_stock.shift(-j).astype(float)
    promo = d.mrp_source.eq('simulated_discounted')
    d['depth'] = np.where(promo, d.discount_percent / 100.0, 0.0)
    d['pressure'] = d.store_pressure_index.clip(-4, 4).fillna(0.0)
    d['evening'] = (pd.to_numeric(d.hour, errors='coerce') == 18).astype(float)
    return d


def spells(d, last_pos=None):
    """One row per OOS spell whose start was observed. Right-censored at `last_pos` (or the panel end)."""
    oos = d.in_stock.eq(0)
    new_panel = d.panel.ne(d.panel.shift())
    start = oos & (new_panel | d.in_stock.shift().eq(1))
    sid = start.cumsum().where(oos)
    left_cens = (oos & new_panel)                      # spell already running at the panel start
    first = d[start].copy()
    first['spell'] = sid[start].to_numpy()
    lc = left_cens.groupby(sid).max()
    first = first[~first.spell.map(lc).fillna(False).astype(bool)]
    end_pos = d[oos].groupby(sid[oos]).pos.max()
    panel_last = d.groupby('panel').pos.max()
    first['end_pos'] = first.spell.map(end_pos)
    first['cap'] = first.panel.map(panel_last)
    if last_pos is not None:
        first['cap'] = np.minimum(first.cap, last_pos)
    first['length'] = np.minimum(first.end_pos, first.cap) - first.pos + 1
    # censored if the spell was still out at the cap (the panel end or the train boundary)
    first['censored'] = (first.end_pos >= first.cap).astype(int)
    return first[['panel', 'platform', 'category', 'store_id', 'pos', 'split', 'length', 'censored',
                  'evening', 'depth', 'pressure']].reset_index(drop=True)


# =========================================================================== likelihood
class NB:
    def __init__(self, sp, cats, *, free_n=True, null_effects=False, groups=None):
        self.cats, self.free_n, self.null, self.groups = cats, free_n, null_effects, groups
        self.L = sp.length.to_numpy(float)
        self.c = sp.censored.to_numpy(bool)
        if groups is None:
            self.cat = pd.Categorical(sp.category, categories=cats).codes
            self.n_cat = len(cats)
            names = [f'a[{c}]' for c in cats]
        else:
            labels = sorted(set(groups.values()))
            self.cat = pd.Categorical(sp.category.map(groups), categories=labels).codes
            self.n_cat = len(labels)
            names = [f'a[group {g}]' for g in labels]
        assert (self.cat >= 0).all()
        self.plat = pd.Categorical(sp.platform, categories=PLATFORMS).codes
        names += [f'b[{p}]' for p in PLATFORMS[1:]]
        self.X = sp[['evening', 'depth', 'pressure']].to_numpy(float) if null_effects else None
        if null_effects:
            names += ['null[evening]', 'null[depth]', 'null[pressure]']
        if free_n:
            names += ['log_n']
        self.names = names
        self.ix = {n: i for i, n in enumerate(names)}

    def mu(self, x):
        e = x[:self.n_cat][self.cat] + np.r_[0.0, x[self.n_cat:self.n_cat + 3]][self.plat]
        if self.null:
            i = self.ix['null[evening]']
            e = e + self.X @ x[i:i + 3]
        return np.exp(e)

    def n_of(self, x):
        return np.exp(x[self.ix['log_n']]) if self.free_n else 1.0

    def nll(self, x):
        mu = self.mu(x)
        m = np.maximum(mu - 1, 1e-6)
        n = self.n_of(x)
        p = n / (n + m)
        k = self.L - 1
        logpmf = gammaln(k + n) - gammaln(n) - gammaln(k + 1) + n * np.log(p) + k * np.log1p(-p)
        logsf = np.log(np.maximum(nbinom.sf(k - 1, n, p), 1e-300))      # P(D - 1 >= k)
        return -np.where(self.c, logsf, logpmf).sum()

    def x0(self, sp):
        x = np.zeros(len(self.names))
        x[:self.n_cat] = np.log(max(sp.length.mean(), 1.2))
        if self.free_n:
            x[self.ix['log_n']] = 0.0
        return x


def num_grad(f, x, h=1e-5):
    g = np.zeros_like(x)
    for i in range(len(x)):
        e = np.zeros_like(x); e[i] = h
        g[i] = (f(x + e) - f(x - e)) / (2 * h)
    return g


def fit(model, sp, label, se=True):
    f = model.nll
    res = minimize(lambda x: (f(x), num_grad(f, x)), model.x0(sp), jac=True, method='L-BFGS-B',
                   options={'maxiter': 3000, 'gtol': 1e-6})
    x = res.x
    out = {'x': x, 'nll': float(res.fun), 'k': len(x), 'aic': float(2 * res.fun + 2 * len(x)),
           'model': model, 'success': bool(res.success)}
    if se:
        n = len(x); H = np.zeros((n, n))
        for i in range(n):
            e = np.zeros(n); e[i] = 1e-4
            H[:, i] = (num_grad(f, x + e) - num_grad(f, x - e)) / 2e-4
        H = (H + H.T) / 2
        out['cov'] = np.linalg.pinv(H)
        out['se'] = np.sqrt(np.clip(np.diag(out['cov']), 0, None))
    print(f"  {label:<40} nll {res.fun:,.2f}  AIC {out['aic']:,.1f}  params {len(x)}  "
          f"{'converged' if res.success else res.message}")
    return out


# =========================================================================== latent groups
def mixture_1d(x, se, K, n_init=30, seed=SEED):
    """EM for a 1-D Gaussian mixture where point i has known measurement variance se_i^2 plus a shared
    within-group variance tau^2. Returns (loglik, labels, means, tau)."""
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(n_init):
        mu = np.sort(rng.choice(x, K, replace=False)) if K <= len(x) else np.sort(x)
        pi, tau2 = np.full(K, 1 / K), 0.01
        for _ in range(500):
            var = se[:, None] ** 2 + tau2
            logp = np.log(pi)[None, :] - 0.5 * np.log(2 * np.pi * var) - 0.5 * (x[:, None] - mu[None, :]) ** 2 / var
            mx = logp.max(1, keepdims=True)
            r = np.exp(logp - mx); ll = float((mx[:, 0] + np.log(r.sum(1))).sum()); r /= r.sum(1, keepdims=True)
            pi = np.clip(r.mean(0), 1e-6, None); pi /= pi.sum()
            w = r / var
            mu = (w * x[:, None]).sum(0) / np.maximum(w.sum(0), 1e-12)
            resid = (r * ((x[:, None] - mu[None, :]) ** 2 - se[:, None] ** 2)).sum() / len(x)
            tau2 = max(resid, 1e-6)
        if best is None or ll > best[0]:
            best = (ll, r.argmax(1), mu, np.sqrt(tau2))
    return best


def discover_groups(cats, a_hat, a_se):
    rows = []
    for K in range(1, MAX_GROUPS + 1):
        ll, lab, mu, tau = mixture_1d(a_hat, a_se, K)
        n_par = 2 * K          # K means + (K - 1) weights + tau
        rows.append({'K': K, 'loglik': ll, 'bic': -2 * ll + n_par * np.log(len(a_hat)), 'labels': lab,
                     'means': mu, 'tau': tau})
    tab = pd.DataFrame(rows)
    best = tab.loc[tab.bic.idxmin()]
    order = np.argsort(best.means)                     # name groups by speed
    names = {int(g): ['G1_fastest', 'G2', 'G3', 'G4', 'G5'][i] for i, g in enumerate(order)}
    disc = {c: names[int(l)] for c, l in zip(cats, best.labels)}
    planted = [planted_group(c) for c in cats]
    ari = adjusted_rand_score(planted, [disc[c] for c in cats])
    return tab, int(best.K), disc, float(ari)


# =========================================================================== forecasting
def cdf_D(d_vals, mu, n):
    """P(D <= d) for D = 1 + NegBin(n, mean mu - 1); d may be < 1."""
    m = np.maximum(mu - 1, 1e-6); p = n / (n + m)
    return np.where(d_vals >= 1, nbinom.cdf(d_vals - 1, n, p), 0.0)


def p_back_within(a, h, mu, n):
    Fa = cdf_D(a - 1, mu, n)
    return (cdf_D(a + h - 1, mu, n) - Fa) / np.maximum(1 - Fa, 1e-12)


def predict_mu(fr, frame, cats):
    """mu and n of a fitted category x platform model for arbitrary rows."""
    m, x = fr['model'], fr['x']
    e = (x[:m.n_cat][pd.Categorical(frame.category, categories=cats).codes]
         + np.r_[0.0, x[m.n_cat:m.n_cat + 3]][pd.Categorical(frame.platform, categories=PLATFORMS).codes])
    return np.exp(e), m.n_of(x)


def score(y, p):
    y = np.asarray(y, int); p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return {'log_loss': float(log_loss(y, p, labels=[0, 1])), 'brier': float(brier_score_loss(y, p)),
            'roc_auc': float(roc_auc_score(y, p)) if 0 < y.mean() < 1 else None,
            'base_rate': float(y.mean()), 'mean_pred': float(p.mean()), 'n': int(len(y))}


# =========================================================================== main
def main():
    d = load_rows()
    cats = sorted(d.category.unique())
    last_train = int(d[d.split == 'train'].pos.max())

    # ---------------- RECOVERY on every observed-start spell
    sp_all = spells(d)
    print(f"RECOVERY: {len(sp_all):,} spells ({sp_all.censored.sum():,} right-censored)")
    geo = fit(NB(sp_all, cats, free_n=False), sp_all, 'geometric (n = 1, memoryless)', se=False)
    nbm = fit(NB(sp_all, cats), sp_all, 'negbin, 22 categories x platform')
    nul = fit(NB(sp_all, cats, null_effects=True), sp_all, 'negbin + unplanted effects (negative control)')
    M = nbm['model']
    a_hat, a_se = nbm['x'][:len(cats)], nbm['se'][:len(cats)]
    n_hat, n_se = np.exp(nbm['x'][M.ix['log_n']]), np.exp(nbm['x'][M.ix['log_n']]) * nbm['se'][M.ix['log_n']]

    tab, K, disc, ari = discover_groups(cats, a_hat, a_se)
    print(f"  latent groups: BIC picks K = {K}; adjusted Rand vs planted = {ari:.3f}")
    grp_disc = fit(NB(sp_all, cats, groups=disc), sp_all, f'negbin, {K} discovered groups x platform')
    grp_plant = fit(NB(sp_all, cats, groups={c: planted_group(c) for c in cats}), sp_all,
                    'negbin, 3 planted groups x platform')
    lr_groups = 2 * (grp_disc['nll'] - nbm['nll']); df_groups = nbm['k'] - grp_disc['k']
    from scipy.stats import chi2
    p_groups = float(chi2.sf(lr_groups, df_groups))

    # recovery table: 12 cells group x platform from the planted-group fit (identical to discovered if ARI = 1)
    G = grp_plant['model']; xg = grp_plant['x']; seg = grp_plant['se']
    labels = sorted(set(PLANTED['group_mu']))
    cells = []
    b = np.r_[0.0, xg[G.n_cat:G.n_cat + 3]]
    for gi, gname in enumerate(labels):
        for pi_, pl in enumerate(PLATFORMS):
            est = float(np.exp(xg[gi] + b[pi_]))
            gv = np.zeros(len(xg)); gv[gi] = est
            if pi_ > 0:
                gv[G.n_cat + pi_ - 1] = est
            se_ = float(np.sqrt(gv @ grp_plant['cov'] @ gv))
            planted = PLANTED['group_mu'][gname] * PLANTED['platform_mult'][pl]
            cells.append({'group': gname, 'platform': pl, 'planted_mean_snapshots': planted,
                          'estimate': est, 'ci_low': est - 1.96 * se_, 'ci_high': est + 1.96 * se_,
                          'covered': bool(est - 1.96 * se_ <= planted <= est + 1.96 * se_)})
    cells = pd.DataFrame(cells)
    # platform multipliers are identified only as ratios to Blinkit
    plat_ratio = []
    for j, pl in enumerate(PLATFORMS[1:]):
        i = G.n_cat + j
        v, s_ = float(np.exp(xg[i])), float(np.exp(xg[i]) * seg[i])
        pr = PLANTED['platform_mult'][pl] / PLANTED['platform_mult']['Blinkit']
        plat_ratio.append({'platform': pl, 'planted_ratio_to_blinkit': pr, 'estimate': v,
                           'ci_low': v - 1.96 * s_, 'ci_high': v + 1.96 * s_,
                           'covered': bool(v - 1.96 * s_ <= pr <= v + 1.96 * s_)})
    plat_ratio = pd.DataFrame(plat_ratio)
    Mn = nul['model']
    null_rows = []
    for nm in ('evening', 'depth', 'pressure'):
        i = Mn.ix[f'null[{nm}]']
        v, s_ = float(nul['x'][i]), float(nul['se'][i])
        null_rows.append({'effect_on_log_mean': nm, 'planted': 0.0, 'estimate': v, 'ci_low': v - 1.96 * s_,
                          'ci_high': v + 1.96 * s_, 'covers_zero': bool(v - 1.96 * s_ <= 0 <= v + 1.96 * s_)})
    null_rows = pd.DataFrame(null_rows)
    lr_null = 2 * (nbm['nll'] - nul['nll'])
    p_null = float(chi2.sf(lr_null, 3))
    lr_geo = 2 * (geo['nll'] - nbm['nll'])
    print(cells.round(3).to_string()); print(plat_ratio.round(3).to_string()); print(null_rows.round(4).to_string())
    print(f"  n: {n_hat:.3f} ± {1.96 * n_se:.3f} (planted 2.0);  LR geometric -> negbin {lr_geo:,.1f};  "
          f"22 cats -> {K} groups LR {lr_groups:.1f} on {df_groups} df, p = {p_groups:.3f}")

    # ---------------- FORECAST: fit on spells starting in train, censored at the train boundary
    sp_tr = spells(d[d.split == 'train'], last_pos=last_train)
    print(f"FORECAST fit: {len(sp_tr):,} train spells")
    f_nb = fit(NB(sp_tr, cats), sp_tr, 'negbin (train)', se=False)
    f_geo = fit(NB(sp_tr, cats, free_n=False), sp_tr, 'geometric (train)', se=False)

    oos_now = d.in_stock.eq(0)
    new_panel = d.panel.ne(d.panel.shift())
    sid = ((oos_now & (new_panel | d.in_stock.shift().eq(1))).cumsum()).where(oos_now)
    left = (oos_now & new_panel).groupby(sid).transform('max').fillna(False).astype(bool)
    T = d[(d.split == 'test') & oos_now & ~left].copy()
    a = T.oos_run_length.to_numpy(float)
    for h in HORIZONS:
        fut = T[[f'in_{j}' for j in range(1, h + 1)]]
        T[f'back_within_{h}'] = np.where(fut.notna().all(axis=1), (fut == 1).any(axis=1).astype(float), np.nan)

    def model_pred(fr, h):
        mu_, n_ = predict_mu(fr, T, cats)
        return p_back_within(a, h, mu_, n_)

    # life table: P(back within h | category, elapsed) from train rows
    trn = d[(d.split == 'train') & oos_now & ~left].copy()
    for h in HORIZONS:
        fut = trn[[f'in_{j}' for j in range(1, h + 1)]]
        ok = fut.notna().all(axis=1) & (trn.pos + h <= last_train)
        trn[f'back_within_{h}'] = np.where(ok, (fut == 1).any(axis=1).astype(float), np.nan)
    trn['el'] = np.minimum(trn.oos_run_length, 8)
    T['el'] = np.minimum(T.oos_run_length, 8)

    # LightGBM per horizon, all non-identifier features + stock clock + category
    base_feats = [f for f in L.feature_columns(d) if f not in SC.NEW_COLUMNS]
    feats = L.check_feature_set(base_feats + SC.NEW_COLUMNS + ['category'])
    prep = lambda x: x[feats].assign(category=pd.Categorical(x.category, categories=cats))
    val = d[(d.split == 'val') & oos_now & ~left].copy()
    last_val = int(d[d.split == 'val'].pos.max())

    d4 = pd.read_parquet(MODELS_DIR / 'stockout_classifier' / 'predictions.parquet',
                         columns=['observation_key', 'p_restock_next'])
    T = T.merge(d4, on='observation_key', how='left')

    results, preds = {}, {}
    for h in HORIZONS:
        lab = f'back_within_{h}'
        tab_ = trn.dropna(subset=[lab]).groupby(['category', 'el'])[lab].agg(['sum', 'count'])
        prior = trn.dropna(subset=[lab]).groupby('el')[lab].mean()
        pr_ = tab_.index.get_level_values(1).map(prior).to_numpy()
        rate = (tab_['sum'] + 10 * pr_) / (tab_['count'] + 10)
        lt = pd.Series(rate.reindex(pd.MultiIndex.from_arrays([T.category, T.el])).to_numpy()).fillna(
            T.el.map(prior).reset_index(drop=True)).to_numpy()
        fv = val[[f'in_{j}' for j in range(1, h + 1)]]
        val[lab] = np.where(fv.notna().all(axis=1) & (val.pos + h <= last_val), (fv == 1).any(axis=1).astype(float), np.nan)
        A_, B_ = trn.dropna(subset=[lab]), val.dropna(subset=[lab])
        bst = lgb.train({'objective': 'binary', 'learning_rate': 0.05, 'num_leaves': 31, 'min_data_in_leaf': 100,
                         'feature_fraction': 0.8, 'bagging_fraction': 0.8, 'bagging_freq': 1, 'lambda_l2': 5.0,
                         'verbose': -1, 'seed': SEED},
                        lgb.Dataset(prep(A_), A_[lab], categorical_feature=['category']), 2000,
                        valid_sets=[lgb.Dataset(prep(B_), B_[lab], categorical_feature=['category'])],
                        callbacks=[lgb.early_stopping(100, verbose=False)])
        cand = {'negbin model': model_pred(f_nb, h), 'geometric (memoryless)': model_pred(f_geo, h),
                'life table (category x elapsed)': lt,
                'lightgbm_direct': bst.predict(prep(T), num_iteration=bst.best_iteration)}
        if h == 1:
            cand['deliverable 4 restock head'] = T.p_restock_next.to_numpy()
        ok = T[lab].notna().to_numpy()
        if h == 1:
            ok = ok & T.p_restock_next.notna().to_numpy()
        results[f'h{h}'] = {k: score(T[lab].to_numpy()[ok], v[ok]) for k, v in cand.items()}
        preds[h] = cand

    # median return snapshot and a readable "back by" time from the schedule
    mu_v, n_v = predict_mu(f_nb, T, cats)
    j = np.zeros(len(T), int)
    for step in range(1, 25):
        hit = (j == 0) & (p_back_within(a, step, mu_v, n_v) >= 0.5)
        j[hit] = step
    j[j == 0] = 24
    ts = pd.to_datetime(T.observed_at.astype(str), format='mixed')
    days, rem = np.divmod(j + (pd.to_numeric(T.hour) == 18).astype(int).to_numpy(), 2)
    back_date = ts.dt.normalize() + pd.to_timedelta(days, unit='D')
    back_hour = np.where(rem == 0, 9, 18)
    T['median_back_snapshots'] = j
    T['back_by'] = back_date.dt.strftime('%a %d %b').to_numpy() + np.where(back_hour == 9, ' 09:00', ' 18:00')
    # E[D - a | D >= a] = sum over s >= 1 of P(still out after s more snapshots)
    T['expected_remaining_snapshots'] = sum(1 - p_back_within(a, s_, mu_v, n_v) for s_ in range(1, 61))

    verdict = {h: {'beats_life_table': results[f'h{h}']['negbin model']['log_loss']
                   < results[f'h{h}']['life table (category x elapsed)']['log_loss'],
                   'beats_geometric': results[f'h{h}']['negbin model']['log_loss']
                   < results[f'h{h}']['geometric (memoryless)']['log_loss'],
                   'minus_lightgbm_log_loss': results[f'h{h}']['negbin model']['log_loss']
                   - results[f'h{h}']['lightgbm_direct']['log_loss']} for h in HORIZONS}

    metrics = {
        'claim_limit': ('SYNTHETIC panel. Recovery of the planted restock process (negative binomial, '
                        'group x platform means, the hidden FAST/MEDIUM/SLOW grouping) is a pipeline check. '
                        'Not real replenishment performance, and not reorder prediction.'),
        'recovery': {
            'spells': int(len(sp_all)), 'censored': int(sp_all.censored.sum()),
            'negbin_n': {'planted': 2.0, 'estimate': float(n_hat), 'ci': [float(n_hat - 1.96 * n_se), float(n_hat + 1.96 * n_se)]},
            'lr_geometric_vs_negbin': float(lr_geo),
            'aic': {'geometric': geo['aic'], 'negbin_22_categories': nbm['aic'],
                    f'negbin_{K}_discovered_groups': grp_disc['aic'], 'negbin_3_planted_groups': grp_plant['aic'],
                    'negbin_plus_null_effects': nul['aic']},
            'cells_group_x_platform': cells.to_dict(orient='records'),
            'platform_ratio_to_blinkit': plat_ratio.to_dict(orient='records'),
            'negative_control_unplanted_effects': null_rows.to_dict(orient='records'),
            'negative_control_lr': {'lr': float(lr_null), 'df': 3, 'p': p_null},
            'latent_groups': {'bic_by_K': tab[['K', 'loglik', 'bic', 'tau']].to_dict(orient='records'),
                              'K_chosen': K, 'adjusted_rand_vs_planted': ari, 'discovered': disc,
                              'planted': {c: planted_group(c) for c in cats},
                              'lr_22_categories_vs_groups': {'lr': float(lr_groups), 'df': int(df_groups), 'p': p_groups}},
            'category_mu_blinkit': {c: {'estimate': float(np.exp(a_hat[i])), 'se_log': float(a_se[i]),
                                        'planted': PLANTED['group_mu'][planted_group(c)] * PLANTED['platform_mult']['Blinkit']}
                                    for i, c in enumerate(cats)},
        },
        'forecast_test': results,
        'verdict_by_horizon': verdict,
    }
    out = pd.DataFrame({
        'observation_key': T.observation_key.to_numpy(), 'data_status': T.data_status.to_numpy(),
        'platform': T.platform.to_numpy(), 'store_id': T.store_id.to_numpy(), 'category': T.category.to_numpy(),
        'snapshot_date': T.date.astype(str).to_numpy(), 'hour': T.hour.to_numpy(),
        'out_for_snapshots': T.oos_run_length.to_numpy(),
        'prediction': preds[1]['negbin model'],
        **{f'p_back_within_{h}': preds[h]['negbin model'] for h in HORIZONS},
        **{f'actual_back_within_{h}': T[f'back_within_{h}'].to_numpy() for h in HORIZONS},
        'median_back_snapshots': T.median_back_snapshots.to_numpy(), 'back_by': T.back_by.to_numpy(),
        'expected_remaining_snapshots': T.expected_remaining_snapshots.to_numpy(),
    })
    mdir = save_model_outputs(
        NAME, out,
        params={'model': 'D = 1 + NegBin(n, mu - 1), log mu = a[category] + b[platform]; right-censored ML',
                'recovery_estimates': dict(zip(M.names, nbm['x'].tolist())),
                'forecast_estimates_train': dict(zip(f_nb['model'].names, f_nb['x'].tolist())),
                'categories': cats, 'platforms': PLATFORMS},
        metrics=metrics, training_data=d[d.split == 'train'],
        split={'recovery_fit': 'all observed-start spells', 'forecast_fit': 'spells starting in train, censored at the train boundary',
               'lightgbm_early_stopping_on': 'val', 'evaluated_on': 'test rows out of stock'},
        target='time to restock (P(back within 1, 2, 4 snapshots))', feature_columns=feats,
        notes=('Deliverable 8. SYNTHETIC ONLY. Censored negative-binomial spell model; hidden restock groups '
               'discovered by a measurement-error Gaussian mixture; negative control on unplanted effects. '
               'platform is a 4-level stratum of the structural model.'))
    cells.to_csv(mdir / 'recovery_cells.csv', index=False)
    _figures(mdir, sp_all, nbm, cats, a_hat, a_se, disc, ari, K, cells, null_rows, results)

    print('\n' + '=' * 72)
    for h in HORIZONS:
        print(f"h={h}: " + ' | '.join(f"{k} {v['log_loss']:.4f}/{(v['roc_auc'] or 0):.3f}" for k, v in results[f'h{h}'].items()))
    print(json.dumps(verdict, indent=1))
    print(T[['platform', 'category', 'oos_run_length', 'back_by']].head(5).to_string())


def _figures(mdir, sp, nbm, cats, a_hat, a_se, disc, ari, K, cells, null_rows, results):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    ink, muted, grid = '#1f2328', '#6e7781', '#d0d7de'
    c_model, c_base, c_true = '#0969da', '#bc4c00', '#8250df'
    gcol = {'FAST': '#1a7f37', 'MEDIUM': '#0969da', 'SLOW': '#bc4c00'}
    fig, ax = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('Deliverable 8 · restock interval  —  SYNTHETIC panel: pipeline check, not a market finding',
                 fontsize=12.5, color=ink, x=0.01, ha='left')

    # A: spell length distribution vs fitted negbin (uncensored spells, Blinkit)
    a = ax[0, 0]
    M = nbm['model']
    n = float(np.exp(nbm['x'][M.ix['log_n']]))
    for pl, col in (('Blinkit', c_model), ('Flipkart Minutes', c_base)):
        s = sp[(sp.platform == pl) & (sp.censored == 0)]
        emp = s.length.value_counts(normalize=True).sort_index().reindex(range(1, 11), fill_value=0)
        mu = M.mu(nbm['x'])[((sp.platform == pl) & (sp.censored == 0)).to_numpy()]
        m = np.maximum(mu - 1, 1e-6); p = n / (n + m)
        fitted = [np.mean(nbinom.pmf(k - 1, n, p)) for k in range(1, 11)]
        a.bar(np.arange(1, 11) + (-0.2 if pl == 'Blinkit' else 0.2), emp.values, width=0.4, color=col, alpha=0.35,
              label=f'{pl} observed')
        a.plot(range(1, 11), fitted, 'o-', color=col, lw=1.6, ms=4, label=f'{pl} negbin fit')
    a.set_xlabel('stock-out spell length (snapshots)'); a.set_ylabel('share of spells')
    a.set_title(f'A · spell lengths: negative binomial, n̂ = {n:.2f} (planted 2.0)', fontsize=10, loc='left')
    a.legend(frameon=False, fontsize=8.5)

    # B: discovered groups
    a = ax[0, 1]
    order = np.argsort(a_hat)
    yy = np.arange(len(cats))
    for yi, i in zip(yy, order):
        g = planted_group(cats[i])
        a.errorbar(np.exp(a_hat[i]), yi, xerr=[[np.exp(a_hat[i]) - np.exp(a_hat[i] - 1.96 * a_se[i])],
                                               [np.exp(a_hat[i] + 1.96 * a_se[i]) - np.exp(a_hat[i])]],
                   fmt='o', color=gcol[g], ms=5, lw=1.2)
    a.set_yticks(yy); a.set_yticklabels([f'{cats[i]}  [{disc[cats[i]]}]' for i in order], fontsize=7.5)
    for g, v in PLANTED['group_mu'].items():
        a.axvline(v * PLANTED['platform_mult']['Blinkit'], color=gcol[g], lw=1, ls=':')
    a.set_xlabel('mean spell length on Blinkit (snapshots, 95% CI)')
    a.set_title(f'B · hidden groups found without labels: K = {K}, adjusted Rand = {ari:.2f}\n'
                f'(colour = planted group, bracket = discovered, dotted = planted means)', fontsize=10, loc='left')

    # C: 12-cell recovery
    a = ax[1, 0]
    lim = [1, cells[['planted_mean_snapshots', 'ci_high']].max().max() * 1.08]
    a.plot(lim, lim, color=grid, lw=1)
    for g, s in cells.groupby('group'):
        a.errorbar(s.planted_mean_snapshots, s.estimate, yerr=[s.estimate - s.ci_low, s.ci_high - s.estimate],
                   fmt='o', color=gcol[g], label=g, ms=5)
    a.set_xlabel('planted mean spell (group × platform)'); a.set_ylabel('recovered (95% CI)')
    a.set_title(f'C · 12 planted cells, {int(cells.covered.sum())}/12 inside the 95% CI', fontsize=10, loc='left')
    a.legend(frameon=False, fontsize=8.5)

    # D: forecast
    a = ax[1, 1]
    hs = list(HORIZONS)
    for key, col, lab in (('negbin model', c_model, 'negbin model'), ('lightgbm_direct', '#1a7f37', 'LightGBM per horizon'),
                          ('geometric (memoryless)', muted, 'geometric (memoryless)'),
                          ('life table (category x elapsed)', c_base, 'life table')):
        a.plot(hs, [results[f'h{h}'][key]['log_loss'] for h in hs], 'o-', color=col, lw=2 if key == 'negbin model' else 1.3, label=lab)
    a.set_xticks(hs); a.set_xlabel('horizon (snapshots)'); a.set_ylabel('test log loss (lower is better)')
    a.set_title('D · "back in stock within h" forecast on test', fontsize=10, loc='left')
    a.legend(frameon=False, fontsize=8.5)
    for a in ax.flat:
        a.spines[['top', 'right']].set_visible(False)
        a.grid(color=grid, lw=0.5, alpha=0.6); a.set_axisbelow(True)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    (mdir / 'figures').mkdir(exist_ok=True)
    fig.savefig(mdir / 'figures' / 'restock_interval.png', dpi=130)
    plt.close(fig)


if __name__ == '__main__':
    main()
