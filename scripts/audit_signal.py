"""
audit_signal.py — does the SYNTHETIC panel contain the structure each planned model is meant to learn?

    python scripts/audit_signal.py [output_name.csv]

Read-only. Run before building a model, not after: if the generator never put a signal in,
a model "finding" one is an artefact, and a model finding nothing is not a model failure.
Writes outputs/audit/signal_audit.csv; findings are written up in docs/DATA_AUDIT.md.

Uses only past-and-present features plus the documented targets, same as a model would.
REAL rows are excluded: one snapshot, no time series.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.load import load_ml   # noqa: E402

OUT = ROOT / 'outputs' / 'audit'
PANEL = ['platform', 'store_id', 'product_id']
results = []


def record(model, question, metric, value, reading):
    results.append({'model': model, 'question': question, 'metric': metric,
                    'value': round(float(value), 4), 'reading': reading})
    print(f"  {metric:<58} {value:>9.4f}   {reading}")


def main():
    m = load_ml()
    d = m[m.data_status == 'SYNTHETIC'].copy()
    d['_ts'] = pd.to_datetime(d.observed_at.astype(str), format='mixed')
    d = d.sort_values(PANEL + ['_ts']).reset_index(drop=True)
    g = d.groupby(PANEL, observed=True, sort=False)
    nxt = d.dropna(subset=['future_price']).copy()
    print(f"synthetic rows {len(d):,} | panels {g.ngroups:,}")

    # ---------------------------------------------------------------- price
    print("\n[price]  next-price forecast / price direction")
    base = g.selling_price.transform('mean')
    d['dev'] = (d.selling_price - base) / base
    d['dev_lag'] = g.dev.shift(1)
    ac = d[['dev', 'dev_lag']].dropna().corr().iat[0, 1]
    record('price_forecast', 'is price persistent around its panel level?',
           'lag-1 autocorr of deviation from panel mean', ac,
           'near 0 = i.i.d. noise around a fixed level; nothing to forecast beyond the level')
    record('price_forecast', 'how big is the noise?', 'std of deviation from panel mean', d.dev.std(),
           'relative price noise')
    t = nxt[nxt.split == 'test'].dropna(subset=['price_7d_avg'])
    naive = np.abs(t.future_price - t.selling_price).mean()
    todate = np.abs(t.future_price - t.price_avg_to_date).mean()
    record('price_forecast', 'naive baseline', 'test MAE: future = current price', naive, '')
    record('price_forecast', 'mean-reversion baseline', 'test MAE: future = price_avg_to_date', todate,
           'beats naive by construction - a model must beat THIS, not naive')

    # ---------------------------------------------------------- competition
    print("\n[competition]  competitive price-response (VAR / impulse response)")
    y = nxt.dropna(subset=['price_gap_vs_avg_pct', 'future_price_change_pct']).copy()
    y['dev'] = d.set_index('observation_key').dev.reindex(y.observation_key).to_numpy()
    X = np.c_[np.ones(len(y)), y.dev, y.price_gap_vs_avg_pct / 100]
    b = np.linalg.lstsq(X, y.future_price_change_pct / 100, rcond=None)[0]
    record('competitive_response', 'does own reversion explain next change?',
           'coef on own deviation (-1 = full reversion)', b[1], '')
    record('competitive_response', 'does a competitor gap move own price, given own deviation?',
           'coef on competitor gap', b[2], 'near 0 = no competitive response in the generator')
    common = d[d.in_common_panel == 1]
    cp = (common.groupby(['snapshot_id', 'canonical_product_key', 'platform'], observed=True)
                .dev.mean().unstack('platform'))
    c = cp.corr().to_numpy()
    record('competitive_response', 'do platforms co-move?', 'mean cross-platform same-snapshot corr',
           c[np.triu_indices_from(c, 1)].mean(), 'near 0 = platforms priced independently')

    # ---------------------------------------------------------------- stock
    print("\n[stock]  stock-out classifier / stockout-hazard / restock-interval")
    s = d.dropna(subset=['future_price']).copy()          # rows that have a next observation
    s['oos'] = 1 - s.in_stock.astype(int)
    s['oos_next'] = 1 - s.future_stock.astype(int)
    record('stock', 'base rate', 'P(OOS at t+1)', s.oos_next.mean(), '')
    record('stock', 'is stock-out persistent?', 'P(OOS at t+1 | OOS at t)', s[s.oos == 1].oos_next.mean(),
           'close to base rate = memoryless')
    ends = s[(s.oos == 1) & (s.oos_next == 0)]
    record('restock_interval', 'how long do stock-outs last?', 'share of completed OOS spells of length 1',
           (ends.oos_run_length == 1).mean(), 'geometric spells = constant restock hazard')
    ins = d.in_stock.astype(int).eq(1)
    blk = (ins != ins.groupby([d.platform, d.store_id, d.product_id], observed=True).shift()).cumsum()
    run = np.where(ins, d.groupby(PANEL + [blk], observed=True).cumcount() + 1, 0)
    s['in_run'] = pd.Series(run, index=d.index).loc[s.index]
    hz = s[(s.oos == 0) & (s.in_run <= 10)].groupby('in_run').oos_next.mean()
    record('stockout_hazard', 'does hazard change with time in stock?', 'hazard range over in-stock run 1..10',
           hz.max() - hz.min(), 'small = flat hazard; survival model reduces to a constant rate')
    by_panel = 1 - g.in_stock.mean()
    record('stock', 'is there per-panel heterogeneity?', 'panel OOS-rate p90 - p10',
           by_panel.quantile(.9) - by_panel.quantile(.1), 'the learnable part: which panels, not when')
    cat = 1 - d.groupby('category', observed=True).in_stock.mean()
    record('stock', 'category effect', 'max - min category OOS rate', cat.max() - cat.min(),
           f"highest: {', '.join(cat.nlargest(2).index)}")
    hr = 1 - d.groupby('hour').in_stock.mean()
    record('stock', 'time-of-day effect', 'OOS rate 18:00 - 09:00', hr.get(18, np.nan) - hr.get(9, np.nan), '')

    # ------------------------------------------------------------------ ETA
    print("\n[eta]  ETA prediction")
    e = s.dropna(subset=['future_eta'])
    record('eta', 'is ETA persistent?', 'corr(eta_t, eta_t+1)', e.delivery_eta_min.corr(e.future_eta), '')
    grp = d.groupby(['platform', 'hour'], observed=True).delivery_eta_min.transform('mean')
    r2 = 1 - ((d.delivery_eta_min - grp) ** 2).sum() / ((d.delivery_eta_min - d.delivery_eta_min.mean()) ** 2).sum()
    record('eta', 'how much do platform x hour explain?', 'R2 of platform x hour mean', r2,
           'remaining variance is noise unless store/product add more')
    grp2 = d.groupby(['platform', 'store_id', 'hour'], observed=True).delivery_eta_min.transform('mean')
    r2b = 1 - ((d.delivery_eta_min - grp2) ** 2).sum() / ((d.delivery_eta_min - d.delivery_eta_min.mean()) ** 2).sum()
    record('eta', 'does store add anything?', 'R2 of platform x store x hour mean', r2b, '')

    # ------------------------------------------------ sharper checks (added for v15)
    print("\n[stock, detail]")
    from src.diagnostics import last_digit_distance, run_length_hazard, stock_matrix, tied_minimum_share
    rho = pd.Series(hz.index).corr(pd.Series(hz.to_numpy()), method='spearman')
    record('stockout_hazard', 'NAIVE estimator (biased: left-censored runs counted as run 1)',
           'spearman(run length 1..10, hazard)', rho, 'kept for comparison only')
    record('stockout_hazard', 'NAIVE estimator (biased: left-censored runs counted as run 1)',
           'hazard at run 10 / hazard at run 1', hz.get(10, np.nan) / hz.get(1, np.nan), 'kept for comparison only')
    hz_c, _ = run_length_hazard(stock_matrix(d), exclude_left_censored=True)
    record('stockout_hazard', 'does hazard RISE with time in stock? (corrected estimator)',
           'CORRECTED spearman(run 1..10, hazard)', pd.Series(hz_c).corr(pd.Series(range(1, 11)), method='spearman'),
           'near +1 = hazard rises with depletion')
    record('stockout_hazard', 'how much does it rise? (corrected estimator)', 'CORRECTED hazard run 10 / run 1',
           hz_c[9] / hz_c[0], '~1.0 = none (validated: 0.994 on homogeneous i.i.d.; <1 under heterogeneity)')
    spell = ends.oos_run_length.astype(float)
    record('restock_interval', 'do restock times vary?', 'mean completed OOS spell length (snapshots)', spell.mean(), '')
    record('restock_interval', 'do restock times vary?', 'std of completed OOS spell length', spell.std(), '')

    print("\n[calibration vs REAL Blinkit snapshot]")
    real = m[m.data_status == 'REAL']
    record('calibration', 'overall stock-out level', 'REAL Blinkit OOS rate', 1 - real.in_stock.mean(), 'benchmark')
    record('calibration', 'overall stock-out level', 'SYNTHETIC OOS rate (all platforms)', 1 - d.in_stock.mean(), '')
    rc = real.groupby('category', observed=True).in_stock.agg(['size', 'mean'])
    bl = 1 - d[d.platform == 'Blinkit'].groupby('category', observed=True).in_stock.mean()
    w = rc['size'].reindex(bl.index).fillna(0)
    record('calibration', 'Blinkit synthetic at the real category mix', 'SYNTHETIC Blinkit OOS reweighted to REAL mix',
           (bl * w).sum() / w.sum(), 'compare with REAL rate')
    record('calibration', 'category pattern', 'corr(Blinkit synthetic category OOS, REAL category OOS)',
           bl.corr((1 - rc['mean']).reindex(bl.index)), '')
    ld = last_digit_distance(d.selling_price, real.selling_price)
    record('price_rounding', 'do synthetic prices end like real ones?', 'last-digit distance vs REAL (0-100)', ld['ALL'],
           '0 = identical ending distribution')
    record('price_rounding', 'psychological endings', 'share of synthetic prices ending 0/5/9 (%)',
           ld['share_end_0_5_9_pct'], 'REAL: ' + str(last_digit_distance(real.selling_price, real.selling_price)['share_end_0_5_9_pct']))
    record('price_rounding', 'whole rupees', 'share of synthetic prices that are whole rupees', ld['integer_share'], 'REAL: 1.0')
    record('price_rounding', 'cheapest-of-4 ties', 'share of common-panel snapshots with a tied minimum',
           tied_minimum_share(d), 'drives the cheapest-of-4 regression values')

    print("\n[competition, detail]  follower regression on leader (Blinkit), common panel")
    pv = (common.assign(ldev=np.log(common.selling_price) - np.log(common.groupby(PANEL, observed=True)
                                                                        .selling_price.transform('mean')))
                .pivot_table(index='canonical_product_key', columns=['platform', '_ts'], values='ldev'))
    lead = pv['Blinkit'].to_numpy()
    for plat in ['Swiggy Instamart', 'Flipkart Minutes', 'BigBasket']:
        fol = pv[plat].to_numpy()
        for lag in (1, 2):
            y_ = fol[:, lag:].ravel(); own = fol[:, lag - 1:-1].ravel(); ld = lead[:, :-lag].ravel()
            X_ = np.c_[np.ones_like(y_), own, ld]
            ok = np.isfinite(X_).all(1) & np.isfinite(y_)
            bb = np.linalg.lstsq(X_[ok], y_[ok], rcond=None)[0]
            record('competitive_response', f'{plat} follows Blinkit at lag {lag}?',
                   f'beta: {plat} dev_t on Blinkit dev_t-{lag} (given own t-1)', bb[2],
                   'near 0 = no leader/follower response')

    print("\n[eta, detail]  demand pressure")
    resid = d.delivery_eta_min - grp
    store_oos = 1 - d.groupby(['store_id', 'snapshot_id'], observed=True).in_stock.transform('mean')
    record('eta', 'does ETA rise when the store is running out?', 'corr(ETA residual, store-snapshot OOS share)',
           resid.corr(store_oos), 'near 0 = no demand-pressure link')
    record('eta', 'does ETA rise with deep discounts?', 'corr(ETA residual, discount_percent)',
           resid.corr(d.discount_percent.astype(float)), '')
    pk = d.groupby('hour').delivery_eta_min.mean()
    record('eta', 'peak slot effect', 'mean ETA 18:00 - 09:00 (minutes)', pk.get(18, np.nan) - pk.get(9, np.nan), '')
    store_mean = d.groupby(['platform', 'store_id'], observed=True).delivery_eta_min.mean()
    record('eta', 'do stores differ?', 'std of store mean ETA within platform (minutes)',
           store_mean.groupby(level=0).std().mean(), 'near 0 = store has no effect')
    e2 = e.assign(resid=resid.loc[e.index], fres=e.future_eta - grp.loc[e.index])
    record('eta', 'is congestion persistent?', 'corr(ETA residual t, ETA residual t+1)', e2.resid.corr(e2.fres), '')

    # --------------------------------------------------------------- offers
    print("\n[offers]  effective price")
    clipped = (m.effective_price <= 0.011)
    record('effective_price', 'generator offers worth more than the item', 'rows with effective_price clipped to 0.01',
           clipped.sum(), 'flat/bank/combo offer_value >= selling_price; synthetic only')

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / (sys.argv[1] if len(sys.argv) > 1 else 'signal_audit.csv')
    pd.DataFrame(results).to_csv(out, index=False)
    print(f"\nwrote {out.relative_to(ROOT)} ({len(results)} measurements)")


if __name__ == '__main__':
    main()
