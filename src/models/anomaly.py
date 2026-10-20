"""
anomaly.py — deliverable 6, price / discount anomaly detection. REAL (cross-sectional) + SYNTHETIC (temporal).

    python -m src.models.anomaly

TWO PARTS, NEVER MIXED
  A  REAL, cross-sectional: the 21,949 REAL Blinkit listings of 2026-07-10. Which listings are unusual WITHIN that
     snapshot. Output model: anomaly_real (data_status REAL only).
  B  SYNTHETIC, temporal: price moves unusual against a listing's OWN past, tested by injecting known anomalies
     into the test-split series. Output model: anomaly_temporal (SYNTHETIC only).

WHAT THIS MAY AND MAY NOT CLAIM
  A flag means "unusual within the snapshot", never "an error" and never "a deal", until someone checks the source
  (docs/PROJECT_PLAN.md, deliverable 6). No temporal statement is made about REAL data: it has one snapshot.

A — DETECTORS (unsupervised; none sees the pack text or the label)
  unit_price_z     log unit price vs its subcategory x pack-unit peers, robust z (median / MAD)
  price_z          log selling price vs its subcategory peers
  cross_store_z    log price vs the same SKU (canonical_product_key) in the other REAL stores
  discount_z       discount vs subcategory peers; plus the recorded invalid-MRP rows (mrp_source)
  isolation_forest on the peer-standardised features together
  combined         the largest absolute robust z of the listing (a simple, explainable union)

A — GROUND TRUTH THAT EXISTS: the raw pack_qty defect (CLAUDE.md s.10; docs/MATCHER_v1.md)
  A REAL listing is labelled defective when its pack text parses (src.matching.blocking.parse_pack) to a base-unit
  quantity that disagrees with the stored pack_qty. The detectors never see the text or the parse, so this is a real
  out-of-sample test of whether "unusual" finds a known, real data error. It is ONE defect type: other flags may be
  genuine premium products, and are reported as unusual only.

B — INJECTION TEST (SYNTHETIC)
  1% of test rows get a known anomaly: price x U(1.3, 2.0) or x U(0.5, 0.75) (a spike or a crash). The detector
  compares log price with the median of the listing's previous 14 prices, scaled by the larger of the past MAD of
  log changes and half a grid step (a price on a Rs 10 grid moves in Rs 10 jumps, which are not anomalies).
"""
import json

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, roc_auc_score

import src.features.price_grid as PG
import src.load as L
from src.matching.blocking import parse_pack
from src.model_output import save_model_outputs

SEED = 20260923
K_TOP = (50, 100, 250, 500)
INJECT_SHARE = 0.01
PANEL = ['platform', 'store_id', 'product_id']


def robust_z(x, groups, min_group=8):
    x = pd.Series(np.asarray(x, float))
    g = pd.Series(groups).astype(str).reset_index(drop=True)
    med = x.groupby(g).transform('median')
    mad = (x - med).abs().groupby(g).transform('median') * 1.4826
    n = x.groupby(g).transform('size')
    z = (x - med) / mad.replace(0, np.nan)
    return z.where(n >= min_group).to_numpy(), med.to_numpy()


def pack_defect_label(r):
    parsed = r.pack_size.map(parse_pack)
    q = parsed.map(lambda t: t[0]).astype(float)
    ok = q.notna() & (q > 0) & r.pack_qty.notna()
    bad = ok & ((r.pack_qty - q).abs() / q > 0.01)
    return bad.astype(int), ok


# =========================================================================== A: REAL
def part_a():
    r = L.real_only(L.load_raw()).reset_index(drop=True)
    assert r.data_status.eq('REAL').all()
    label, labelable = pack_defect_label(r)
    lp = np.log(r.selling_price.astype(float))
    lu = np.log(r.unit_price.astype(float).where(r.unit_price > 0))
    sub = r.subcategory.fillna(r.category).astype(str)
    z_unit, med_unit = robust_z(lu, sub + '|' + r.pack_unit.astype(str))
    z_price, _ = robust_z(lp, sub)
    z_disc, _ = robust_z(r.discount_percent.astype(float), sub)
    z_cross, med_cross = robust_z(lp, r.canonical_product_key, min_group=3)
    invalid_mrp = r.mrp_source.astype(str).str.startswith('invalid_source_mrp').to_numpy()

    Z = pd.DataFrame({'unit_price_z': z_unit, 'price_z': z_price, 'cross_store_z': z_cross, 'discount_z': z_disc})
    X = Z.fillna(0).clip(-50, 50).to_numpy()
    iso = IsolationForest(n_estimators=400, contamination='auto', random_state=SEED).fit(X)
    iso_score = -iso.score_samples(X)
    combined = np.nanmax(np.abs(Z.to_numpy()), axis=1)
    combined = np.where(np.isnan(combined), 0, combined)

    scores = {'unit_price_z (|z|)': np.nan_to_num(np.abs(z_unit)), 'price_z (|z|)': np.nan_to_num(np.abs(z_price)),
              'cross_store_z (|z|)': np.nan_to_num(np.abs(z_cross)), 'discount_z (|z|)': np.nan_to_num(np.abs(z_disc)),
              'isolation_forest': iso_score, 'combined (max |z|)': combined}
    m = labelable.to_numpy()
    y = label.to_numpy()[m]
    evals = {}
    for k, s in scores.items():
        s_ = s[m]
        order = np.argsort(-s_)
        evals[k] = {'pr_auc': float(average_precision_score(y, s_)), 'roc_auc': float(roc_auc_score(y, s_)),
                    **{f'precision_at_{kk}': float(y[order[:kk]].mean()) for kk in K_TOP},
                    'recall_at_top_5pct': float(y[order[:int(0.05 * len(y))]].sum() / y.sum())}
    # which defect type each detector catches
    kind = np.where(r.pack_size.astype(str).str.contains(r'\*\*'), 'markup ** stored as 1',
                    np.where(r.pack_size.astype(str).str.contains(r'\+'), 'combo pack', 'other'))
    top = np.argsort(-combined)[:500]
    caught = pd.Series(kind[top][label.to_numpy()[top] == 1]).value_counts().to_dict()

    # reasons, in words
    def reason(i):
        out = []
        if abs(Z.unit_price_z[i]) >= 5:
            out.append(f"unit price {np.exp(lu[i] - med_unit[i]):.3g}x its subcategory-unit median")
        if abs(Z.price_z[i]) >= 5:
            out.append('price far from subcategory peers')
        if abs(Z.cross_store_z[i]) >= 5:
            out.append(f"price {np.exp(lp[i] - med_cross[i]):.3g}x the same SKU in other stores")
        if abs(Z.discount_z[i]) >= 5:
            out.append('discount far from subcategory peers')
        if invalid_mrp[i]:
            out.append('source MRP below selling price (recorded, patch v2)')
        return '; '.join(out)

    flag = (combined >= 5) | invalid_mrp
    reasons = np.array([reason(i) if flag[i] else '' for i in range(len(r))])
    pred = pd.DataFrame({
        'observation_key': r.observation_key, 'data_status': r.data_status, 'store_id': r.store_id,
        'product_name': r.product_name, 'pack_size': r.pack_size, 'category': r.category,
        'selling_price': r.selling_price, 'unit_price': r.unit_price, **Z,
        'isolation_forest': iso_score, 'prediction': combined, 'flag_unusual': flag.astype(int),
        'reason': reasons, 'known_pack_qty_defect': label, 'defect_label_available': labelable.astype(int),
        'claim': 'unusual within the REAL 2026-07-10 snapshot; not an error or a deal until checked at source'})
    summary = {'rows': int(len(r)), 'flagged_unusual': int(flag.sum()), 'known_defect_rows': int(label.sum()),
               'labelable_rows': int(labelable.sum()), 'detector_eval_vs_known_defect': evals,
               'defect_types_in_top_500_combined': caught,
               'flagged_not_known_defect': int((flag & (label.to_numpy() == 0)).sum()),
               'invalid_mrp_rows': int(invalid_mrp.sum())}
    return r, pred, summary


# =========================================================================== B: SYNTHETIC temporal
def part_b():
    ml = PG.attach(L.load_ml(with_targets=False))
    s = ml[ml.data_status == 'SYNTHETIC'].copy()
    s['_ts'] = pd.to_datetime(s.observed_at.astype(str), format='mixed')
    s = s.sort_values(PANEL + ['_ts']).reset_index(drop=True)
    rng = np.random.default_rng(SEED)
    test_ix = np.flatnonzero((s.split == 'test').to_numpy())
    inj = rng.choice(test_ix, int(INJECT_SHARE * len(test_ix)), replace=False)
    price = s.selling_price.to_numpy(float).copy()
    kind = np.where(rng.random(len(inj)) < 0.5, 'spike', 'crash')
    mult = np.where(kind == 'spike', rng.uniform(1.3, 2.0, len(inj)), rng.uniform(0.5, 0.75, len(inj)))
    price[inj] = np.round(price[inj] * mult)
    s['p_obs'] = price
    s['is_injected'] = 0
    s.loc[inj, 'is_injected'] = 1
    g = s.groupby(PANEL, sort=False)
    lp = np.log(s.p_obs)
    s['lp'] = lp
    past_med = g.lp.transform(lambda v: v.shift(1).rolling(14, min_periods=4).median())
    dl = g.lp.diff()
    s['dl'] = dl
    past_mad = g.dl.transform(lambda v: v.shift(1).abs().rolling(14, min_periods=4).median()) * 1.4826
    floor = 0.5 * s.grid_step_pct.clip(upper=1.0)       # half a grid step, in log terms roughly
    scale = np.maximum(past_mad.fillna(0), floor.fillna(0.05)).clip(lower=0.01)
    s['temporal_z'] = (s.lp - past_med) / scale
    t = s.iloc[test_ix].dropna(subset=['temporal_z'])
    y = t.is_injected.to_numpy(); sc = t.temporal_z.abs().to_numpy()
    order = np.argsort(-sc)
    res = {'test_rows_scored': int(len(t)), 'injected': int(y.sum()),
           'pr_auc': float(average_precision_score(y, sc)), 'roc_auc': float(roc_auc_score(y, sc)),
           'precision_at_n_injected': float(y[order[:int(y.sum())]].mean())}
    for thr in (3, 5, 8):
        f = sc >= thr
        res[f'threshold_{thr}'] = {'flagged': int(f.sum()), 'recall': float(y[f].sum() / y.sum()),
                                   'precision': float(y[f].mean()) if f.any() else None,
                                   'natural_rows_flagged_share': float(f[y == 0].mean())}
    by_kind = {}
    ti = t[t.is_injected == 1]
    kmap = dict(zip(inj, kind))
    for k in ('spike', 'crash'):
        idx = [i for i in ti.index if kmap.get(i) == k]
        by_kind[k] = float((ti.loc[idx].temporal_z.abs() >= 5).mean())
    res['recall_at_5_by_kind'] = by_kind
    # the naive detector without the grid floor, for comparison
    naive = ((s.lp - past_med) / past_mad.fillna(0).clip(lower=0.01)).iloc[test_ix].loc[t.index].abs().to_numpy()
    f = naive >= 5
    res['naive_no_grid_floor_threshold_5'] = {'recall': float(y[f].sum() / y.sum()),
                                              'precision': float(y[f].mean()) if f.any() else None,
                                              'natural_rows_flagged_share': float(f[y == 0].mean())}
    pred = pd.DataFrame({'observation_key': t.observation_key, 'data_status': t.data_status, 'platform': t.platform,
                         'snapshot_date': t.date.astype(str), 'prediction': t.temporal_z.abs(),
                         'is_injected': t.is_injected, 'observed_price_after_injection': t.p_obs})
    return s[s.split == 'train'], pred, res


def main():
    r, pred_a, sum_a = part_a()
    print(json.dumps({k: v for k, v in sum_a.items() if k != 'detector_eval_vs_known_defect'}, indent=1))
    for k, v in sum_a['detector_eval_vs_known_defect'].items():
        print(f"  {k:<22} PR-AUC {v['pr_auc']:.3f}  ROC {v['roc_auc']:.3f}  P@100 {v['precision_at_100']:.2f}  "
              f"recall@5% {v['recall_at_top_5pct']:.2f}")
    save_model_outputs('anomaly_real', pred_a,
                       params={'detectors': ['unit_price_z', 'price_z', 'cross_store_z', 'discount_z', 'isolation_forest'],
                               'flag_rule': 'max |robust z| >= 5 or recorded invalid MRP', 'seed': SEED},
                       metrics={'claim_limit': 'REAL-ONLY. Unusual within the 2026-07-10 snapshot. Not an error or a '
                                               'deal until checked against the source.', **sum_a},
                       training_data=r, split={'data': 'REAL snapshot 2026-07-10, unsupervised', 'evaluated_on':
                                                'known raw pack_qty defect labels (never seen by the detectors)'},
                       target='unusual listing (unsupervised); evaluated against the known pack_qty defect',
                       training_source='data/raw via src.load (REAL rows)',
                       notes='Deliverable 6, part A. REAL ONLY.')
    tr, pred_b, res_b = part_b()
    print(json.dumps(res_b, indent=1))
    save_model_outputs('anomaly_temporal', pred_b,
                       params={'window': 14, 'min_periods': 4, 'scale': 'max(past MAD of log changes, half a grid step)',
                               'injection_share': INJECT_SHARE, 'spike': 'x U(1.3, 2.0)', 'crash': 'x U(0.5, 0.75)'},
                       metrics={'claim_limit': 'SYNTHETIC with injected anomalies: measures the detector, not any market.',
                                **res_b},
                       training_data=tr, split={'evaluated_on': 'test rows, 1% injected'},
                       target='injected temporal price anomaly', notes='Deliverable 6, part B. SYNTHETIC ONLY.')
    _figures(sum_a, res_b, pred_a)


def _figures(sum_a, res_b, pred_a):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from src.model_output import MODELS_DIR
    ink, muted, grid = '#1f2328', '#6e7781', '#d0d7de'
    c_model, c_base = '#0969da', '#bc4c00'
    fig, ax = plt.subplots(1, 3, figsize=(16, 5.2))
    fig.suptitle('Deliverable 6 · anomaly detection  —  A: REAL 2026-07-10 snapshot (unusual ≠ error)   '
                 'B: SYNTHETIC injection test', fontsize=12, color=ink, x=0.01, ha='left')
    a = ax[0]
    ev = sum_a['detector_eval_vs_known_defect']
    names = list(ev)
    a.barh(names[::-1], [ev[k]['pr_auc'] for k in names][::-1], color=c_model)
    base = sum_a['known_defect_rows'] / sum_a['labelable_rows']
    a.axvline(base, color=c_base, ls=':', label=f'random = {base:.3f}')
    for i, k in enumerate(names[::-1]):
        a.text(ev[k]['pr_auc'], i, f" {ev[k]['pr_auc']:.2f}", va='center', fontsize=8.5)
    a.set_xlabel('PR-AUC against the known REAL pack_qty defect')
    a.set_title('A1 · which detector finds a real, known data error', fontsize=10, loc='left')
    a.legend(frameon=False, fontsize=8.5)
    a = ax[1]
    p = pred_a[pred_a.unit_price_z.notna()]
    a.scatter(p.unit_price_z.clip(-30, 60), p.cross_store_z.fillna(0).clip(-30, 30), s=4,
              c=np.where(p.known_pack_qty_defect == 1, c_base, '#8c959f'), alpha=0.5)
    a.set_xlabel('unit-price robust z (subcategory × unit)'); a.set_ylabel('cross-store robust z (same SKU)')
    a.set_title('A2 · REAL listings; orange = known pack_qty defect', fontsize=10, loc='left')
    a = ax[2]
    thr = [3, 5, 8]
    a.plot(thr, [res_b[f'threshold_{t}']['recall'] for t in thr], 'o-', color=c_model, label='recall of injected')
    a.plot(thr, [res_b[f'threshold_{t}']['precision'] for t in thr], 's-', color='#1a7f37', label='precision')
    a.plot(thr, [res_b[f'threshold_{t}']['natural_rows_flagged_share'] for t in thr], '^--', color=c_base,
           label='natural rows flagged')
    a.set_xlabel('|temporal z| threshold'); a.set_ylim(-0.02, 1.02)
    a.set_title('B · injected spikes / crashes in SYNTHETIC test series', fontsize=10, loc='left')
    a.legend(frameon=False, fontsize=8.5)
    for a in ax:
        a.spines[['top', 'right']].set_visible(False); a.grid(color=grid, lw=0.5, alpha=0.6); a.set_axisbelow(True)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    d = MODELS_DIR / 'anomaly_real' / 'figures'
    d.mkdir(exist_ok=True)
    fig.savefig(d / 'anomaly.png', dpi=130)
    plt.close(fig)


if __name__ == '__main__':
    main()
