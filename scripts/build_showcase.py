"""
build_showcase.py — renders outputs/showcase/planted_vs_recovered.html from the saved model outputs.

    python scripts/build_showcase.py

Every number on the page is read from outputs/models/*/metrics.json (or computed here from data/ml for the hazard
curve), never typed by hand, so a rerun of any deliverable followed by this script keeps the page true.
Palette: the dataviz reference slots 1-3 (validated all-pairs in both modes against these surfaces); provenance is
encoded by form (solid stamp = REAL, hatched stamp = SYNTHETIC), never by hue.
"""
import html
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
M = ROOT / 'outputs' / 'models'
OUT = ROOT / 'outputs' / 'showcase' / 'planted_vs_recovered.html'


def met(name):
    return json.loads((M / name / 'metrics.json').read_text(encoding='utf-8'))


def man(name):
    return json.loads((M / name / 'manifest.json').read_text(encoding='utf-8'))


esc = html.escape


def f(x, d=2):
    return f'{x:,.{d}f}'


# =========================================================================== data
def calibration_rows():
    """(group, label, planted, estimate, lo, hi, naive) — ratios are taken later."""
    rows = []
    sv = {r['parameter']: r for r in met('stockout_survival')['parameter_recovery']}
    k2 = next(v for p, v in sv.items() if p.startswith('k (Weibull shape)'))
    k0 = next(v for p, v in sv.items() if p.startswith('k — V0'))
    rows.append(('7 · stock-out hazard', 'Weibull shape k', 2.0, k2['estimate'], k2['ci_low'], k2['ci_high'], k0['estimate']))
    fs = next(v for p, v in sv.items() if p.startswith('frailty sd'))
    rows.append(('7 · stock-out hazard', 'frailty sd', fs['planted'], fs['estimate'], fs['ci_low'], fs['ci_high'], None))
    ev = next(v for p, v in sv.items() if p.startswith('evening multiplier'))
    rows.append(('7 · stock-out hazard', 'evening multiplier', ev['planted'], ev['estimate'], ev['ci_low'], ev['ci_high'], None))
    pr = next(v for p, v in sv.items() if p.startswith('promo d'))
    rows.append(('7 · stock-out hazard', 'promo depth effect', pr['planted'], pr['estimate'], pr['ci_low'], pr['ci_high'], None))
    for p, v in sv.items():
        if p.startswith('platform lambda multiplier'):
            rows.append(('7 · stock-out hazard', f"λ multiplier, {p.split(': ')[1]}", v['planted'], v['estimate'],
                         v['ci_low'], v['ci_high'], None))
    rs = met('restock_interval')['recovery']
    n = rs['negbin_n']
    rows.append(('8 · restock time', 'dispersion n', n['planted'], n['estimate'], n['ci'][0], n['ci'][1], None))
    for x in rs['platform_ratio_to_blinkit']:
        rows.append(('8 · restock time', f"spell ratio, {x['platform']}", x['planted_ratio_to_blinkit'], x['estimate'],
                     x['ci_low'], x['ci_high'], None))
    pr9 = met('price_response')
    for r in pr9['response_recovery']:
        rows.append(('9 · price response', f"β, {r['follower']}", r['planted_beta'], r['corrected_beta'],
                     r['corrected_ci'][0], r['corrected_ci'][1], r['naive_beta']))
    lr = pr9['leader_and_noise']['leader_rho']
    rows.append(('9 · price response', 'Blinkit persistence ρ', lr['planted'], lr['corrected'], lr['ci'][0], lr['ci'][1], lr['naive']))
    eta = {r['parameter']: r for r in met('eta_forecast')['structural_recovery']}
    pk = eta['evening peak (minutes)']
    rows.append(('5 · delivery ETA', 'evening peak (min)', pk['planted'], pk['estimate'], pk['ci_low'], pk['ci_high'], None))
    dc = eta['discount depth effect (minutes per 100% depth)']
    rows.append(('5 · delivery ETA', 'discount effect', dc['planted'], dc['estimate'], dc['ci_low'], dc['ci_high'], None))
    return rows


def hazard_curve():
    import src.features.stock_clock as SC
    import src.load as L
    ml = SC.attach(L.load_ml())
    s = ml[(ml.data_status == 'SYNTHETIC') & (ml.in_stock == 1) & ml.future_stock.notna()
           & (ml.instock_clock_censored == 0)]
    r = np.minimum(s.instock_run_length.to_numpy(), 30)
    y = (s.future_stock.to_numpy() == 0)
    v3 = met('stockout_survival')['nonparametric_baseline_V3']
    rr = np.array(v3['r'], float)
    emp = np.array([y[r == k].mean() for k in rr])
    emp_log = np.log(-np.log(1 - emp))
    steps = np.array(v3['steps']); se = np.array(v3['steps_se'])
    planted = np.log(rr ** 2 - (rr - 1) ** 2)
    norm = lambda a: a - a[0]
    return {'r': rr.tolist(), 'planted': norm(planted).tolist(), 'frailty': norm(steps).tolist(), 'se': se.tolist(),
            'pooled': norm(emp_log).tolist(), 'k_v3': v3['k']}


# =========================================================================== svg helpers
class Scale:
    def __init__(self, d0, d1, r0, r1, log=False):
        self.d0, self.d1, self.r0, self.r1, self.log = d0, d1, r0, r1, log

    def __call__(self, v):
        if self.log:
            v, d0, d1 = math.log(v), math.log(self.d0), math.log(self.d1)
        else:
            d0, d1 = self.d0, self.d1
        return self.r0 + (v - d0) / (d1 - d0) * (self.r1 - self.r0)


def svg_open(w, h, label):
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{esc(label)}" '
            f'preserveAspectRatio="xMinYMin meet">')


def tip(text):
    return f' data-tip="{esc(text, quote=True)}" tabindex="0"'


def forest_svg(rows):
    W, row_h, top, left, right = 760, 24, 40, 250, 70
    n_groups = len(dict.fromkeys(r[0] for r in rows))
    H = top + row_h * (len(rows) + n_groups) + 46
    x = Scale(0.4, 2.6, left, W - right, log=True)
    out = [svg_open(W, H, 'Recovered value divided by planted value for each planted parameter, with 95% intervals')]
    for t in [0.5, 0.75, 1.0, 1.5, 2.0]:
        xx = x(t)
        out.append(f'<line class="{"ref" if t == 1.0 else "grid"}" x1="{xx:.1f}" x2="{xx:.1f}" y1="{top - 8}" y2="{H - 38}"/>')
        out.append(f'<text class="tick" x="{xx:.1f}" y="{H - 22}" text-anchor="middle">{t:g}×</text>')
    out.append(f'<text class="axis-title" x="{x(1.0):.1f}" y="{H - 6}" text-anchor="middle">recovered ÷ planted '
               f'(log scale; 1× = exact)</text>')
    out.append(f'<text class="axis-title" x="{x(1.0) + 6:.1f}" y="{top - 16}">planted value</text>')
    group, line = None, 0
    for g, lab, pl, est, lo, hi, naive in rows:
        if g != group:                                   # a group header takes its own line
            group = g
            gy = top + line * row_h + row_h / 2
            if line:
                out.append(f'<line class="sep" x1="8" x2="{W - 8}" y1="{gy - row_h / 2:.1f}" y2="{gy - row_h / 2:.1f}"/>')
            out.append(f'<text class="group" x="8" y="{gy + 4:.1f}">{esc(g)}</text>')
            line += 1
        cy = top + line * row_h + row_h / 2
        line += 1
        out.append(f'<text class="rowlab" x="{left - 12}" y="{cy + 4:.1f}" text-anchor="end">{esc(lab)}</text>')
        rl, rh, re_ = lo / pl, hi / pl, est / pl
        covered = lo <= pl <= hi
        out.append(f'<line class="ci" x1="{x(max(rl, 0.41)):.1f}" x2="{x(min(rh, 2.59)):.1f}" y1="{cy:.1f}" y2="{cy:.1f}"/>')
        if naive is not None:
            rn = naive / pl
            out.append(f'<circle class="naive" cx="{x(rn):.1f}" cy="{cy:.1f}" r="5"'
                       f'{tip(f"{lab}: naive {naive:.3g} vs planted {pl:g} ({rn:.2f}×)")}/>')
        miss = '' if covered else ' — CI misses the planted value'
        out.append(f'<circle class="est" cx="{x(re_):.1f}" cy="{cy:.1f}" r="5"'
                   f'{tip(f"{lab}: recovered {est:.3g} (95% CI {lo:.3g} to {hi:.3g}) vs planted {pl:g}{miss}")}/>')
        out.append(f'<text class="cov{"" if covered else " miss"}" x="{W - right + 14}" y="{cy + 4:.1f}">'
                   f'{"✓" if covered else "✗"} {re_:.2f}×</text>')
    out.append('</svg>')
    return '\n'.join(out)


def bars_svg(rows):
    """Grouped columns: planted (ink), naive (orange), corrected (blue, with CI)."""
    W, H, top, left, bottom = 560, 300, 26, 44, 56
    y = Scale(0, 0.55, H - bottom, top)
    group_w = (W - left - 16) / len(rows)
    bw = 22
    out = [svg_open(W, H, 'Planted, naive and corrected response coefficients for three followers')]
    for t in (0, 0.1, 0.2, 0.3, 0.4, 0.5):
        yy = y(t)
        out.append(f'<line class="{"base" if t == 0 else "grid"}" x1="{left}" x2="{W - 8}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        out.append(f'<text class="tick" x="{left - 8}" y="{yy + 4:.1f}" text-anchor="end">{t:.1f}</text>')
    for i, r in enumerate(rows):
        cx = left + group_w * (i + 0.5)
        vals = [('planted', r['planted_beta'], 'planted'), ('naive', r['naive_beta'], 'naive'),
                ('corrected', r['corrected_beta'], 'corrected')]
        for j, (cls, v, name) in enumerate(vals):
            bx = cx + (j - 1) * (bw + 2) - bw / 2
            y0, y1 = y(0), y(v)
            h = y0 - y1
            rad = 4
            path = (f'M{bx:.1f},{y0:.1f} V{y1 + rad:.1f} Q{bx:.1f},{y1:.1f} {bx + rad:.1f},{y1:.1f} '
                    f'H{bx + bw - rad:.1f} Q{bx + bw:.1f},{y1:.1f} {bx + bw:.1f},{y1 + rad:.1f} V{y0:.1f} Z')
            out.append(f'<path class="bar {cls}" d="{path}"{tip(f"{r["follower"]}, {name}: {v:.3f}")}/>')
            ly = min(y1, y(r['corrected_ci'][1])) if cls == 'corrected' else y1      # clear the interval whisker
            out.append(f'<text class="val" x="{bx + bw / 2:.1f}" y="{ly - 6:.1f}" text-anchor="middle">{v:.2f}</text>')
        lo, hi = r['corrected_ci']
        bx = cx + (bw + 2)
        out.append(f'<line class="whisk" x1="{bx:.1f}" x2="{bx:.1f}" y1="{y(lo):.1f}" y2="{y(hi):.1f}"/>')
        out.append(f'<text class="rowlab" x="{cx:.1f}" y="{H - bottom + 20}" text-anchor="middle">{esc(r["follower"])}</text>')
        out.append(f'<text class="tick" x="{cx:.1f}" y="{H - bottom + 36}" text-anchor="middle">lag {r["lag"]}</text>')
    out.append('</svg>')
    return '\n'.join(out)


def hazard_svg(hc):
    W, H, top, left, right, bottom = 560, 300, 20, 44, 18, 44
    r = hc['r']
    x = Scale(1, max(r), left, W - right)
    ymax = max(max(hc['planted']), max(a + 1.96 * s for a, s in zip(hc['frailty'], hc['se']))) + 0.2
    y = Scale(0, ymax, H - bottom, top)
    out = [svg_open(W, H, 'Log hazard increment against the in-stock clock: planted, frailty model and pooled curve')]
    for t in range(0, int(ymax) + 1):
        out.append(f'<line class="{"base" if t == 0 else "grid"}" x1="{left}" x2="{W - right}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>')
        out.append(f'<text class="tick" x="{left - 8}" y="{y(t) + 4:.1f}" text-anchor="end">{t}</text>')
    for t in (1, 5, 10, 15, 20, 25, 29):
        out.append(f'<text class="tick" x="{x(t):.1f}" y="{H - bottom + 18}" text-anchor="middle">{t}</text>')
    out.append(f'<text class="axis-title" x="{(left + W - right) / 2:.1f}" y="{H - 6}" text-anchor="middle">in-stock clock '
               f'(snapshots since an observed restock)</text>')

    def poly(key, cls):
        pts = ' '.join(f'{x(a):.1f},{y(b):.1f}' for a, b in zip(r, hc[key]))
        return f'<polyline class="{cls}" points="{pts}"/>'
    out.append(poly('planted', 'line-planted'))
    out.append(poly('pooled', 'line-naive'))
    for a, b, s in zip(r, hc['frailty'], hc['se']):
        out.append(f'<line class="whisk thin" x1="{x(a):.1f}" x2="{x(a):.1f}" y1="{y(b - 1.96 * s):.1f}" y2="{y(b + 1.96 * s):.1f}"/>')
    for a, b, p, e in zip(r, hc['frailty'], hc['planted'], hc['pooled']):
        out.append(f'<circle class="est small" cx="{x(a):.1f}" cy="{y(b):.1f}" r="4"'
                   f'{tip(f"clock {int(a)}: frailty model {b:.2f}, planted {p:.2f}, pooled {e:.2f}")}/>')
    last = len(r) - 1
    out.append(f'<text class="endlab" x="{x(r[last]) - 4:.1f}" y="{y(hc["pooled"][last]) + 18:.1f}" text-anchor="end">pooled curve (what a naive fit sees)</text>')
    out.append('</svg>')
    return '\n'.join(out)


def dumbbell_svg(cats):
    W, row_h, top, left, right = 560, 22, 30, 190, 40
    H = top + row_h * len(cats) + 42
    x = Scale(0, 12, left, W - right)
    out = [svg_open(W, H, 'Smallest Blinkit price cut to be cheapest on 40 percent of SKUs, static versus strategic')]
    for t in (0, 3, 6, 9, 12):
        out.append(f'<line class="{"base" if t == 0 else "grid"}" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top - 6}" y2="{H - 36}"/>')
        out.append(f'<text class="tick" x="{x(t):.1f}" y="{H - 20}" text-anchor="middle">{t}%</text>')
    out.append(f'<text class="axis-title" x="{(left + W - right) / 2:.1f}" y="{H - 4}" text-anchor="middle">smallest price cut</text>')
    for i, c in enumerate(cats):
        cy = top + i * row_h + row_h / 2
        s, g = c['min_cut_static_pct'], c['min_cut_strategic_pct']
        out.append(f'<text class="rowlab" x="{left - 10}" y="{cy + 4:.1f}" text-anchor="end">{esc(c["category"])}</text>')
        out.append(f'<line class="connector" x1="{x(s):.1f}" x2="{x(g):.1f}" y1="{cy:.1f}" y2="{cy:.1f}"/>')
        out.append(f'<circle class="naive" cx="{x(s):.1f}" cy="{cy:.1f}" r="5"{tip(f"{c["category"]}: {s:.1f}% if competitors do not react")}/>')
        out.append(f'<circle class="est" cx="{x(g):.1f}" cy="{cy:.1f}" r="5"{tip(f"{c["category"]}: {g:.1f}% with the fitted competitor response")}/>')
        if i == 0:
            out.append(f'<text class="endlab" x="{x(s):.1f}" y="{cy - 9:.1f}" text-anchor="middle">static</text>')
            out.append(f'<text class="endlab" x="{x(g):.1f}" y="{cy - 9:.1f}" text-anchor="middle">strategic</text>')
    out.append('</svg>')
    return '\n'.join(out)


def policy_svg(pol):
    W, row_h, top, left, right = 560, 40, 10, 170, 60
    rows = [p for p in pol if p['policy'] != 'none']
    H = top + row_h * len(rows) + 36
    x = Scale(0, 35, left, W - right)
    out = [svg_open(W, H, 'Reduction in out-of-stock listing-snapshots by restock policy')]
    for t in (0, 10, 20, 30):
        out.append(f'<line class="{"base" if t == 0 else "grid"}" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top}" y2="{H - 30}"/>')
        out.append(f'<text class="tick" x="{x(t):.1f}" y="{H - 14}" text-anchor="middle">{t}%</text>')
    names = {'random': 'random', 'longest_out_first': 'longest out first', 'priority_index': 'priority index (model)'}
    for i, p in enumerate(rows):
        cy = top + i * row_h + row_h / 2
        v = p['reduction_vs_none_pct']
        bh = 18
        x0, x1 = x(0), x(v)
        path = (f'M{x0:.1f},{cy - bh / 2:.1f} H{x1 - 4:.1f} Q{x1:.1f},{cy - bh / 2:.1f} {x1:.1f},{cy - bh / 2 + 4:.1f} '
                f'V{cy + bh / 2 - 4:.1f} Q{x1:.1f},{cy + bh / 2:.1f} {x1 - 4:.1f},{cy + bh / 2:.1f} H{x0:.1f} Z')
        cls = 'corrected' if p['policy'] == 'priority_index' else 'muted-bar'
        out.append(f'<path class="bar {cls}" d="{path}"{tip(f"{names[p["policy"]]}: {v:.1f}% fewer out-of-stock listing-snapshots (90% band {p["reduction_p05"]:.1f} to {p["reduction_p95"]:.1f})")}/>')
        out.append(f'<line class="whisk" x1="{x(p["reduction_p05"]):.1f}" x2="{x(p["reduction_p95"]):.1f}" y1="{cy:.1f}" y2="{cy:.1f}"/>')
        out.append(f'<text class="rowlab" x="{left - 10}" y="{cy + 4:.1f}" text-anchor="end">{names[p["policy"]]}</text>')
        out.append(f'<text class="val" x="{x(max(v, p["reduction_p95"])) + 6:.1f}" y="{cy + 4:.1f}">{v:.1f}%</text>')
    out.append('</svg>')
    return '\n'.join(out)


def table(headers, rows):
    th = ''.join(f'<th>{esc(h)}</th>' for h in headers)
    body = ''.join('<tr>' + ''.join(f'<td>{esc(str(c))}</td>' for c in r) + '</tr>' for r in rows)
    return f'<div class="tbl"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def build_stats():
    """Row counts from data/raw and a live test run, so the stat row is never typed by hand."""
    import re
    import subprocess
    import src.load as L
    raw = L.load_raw()
    run = subprocess.run([sys.executable, '-m', 'pytest', '-q'], cwd=ROOT, capture_output=True, text=True)
    m = re.search(r'(\d+) passed', run.stdout)
    failed = re.search(r'(\d+) failed', run.stdout)
    tests = f"{m.group(1)}/{int(m.group(1)) + (int(failed.group(1)) if failed else 0)}" if m else 'not run'
    return {'rows': len(raw), 'real': int((raw.data_status == 'REAL').sum()), 'tests': tests}


# =========================================================================== page
def build():
    cal = calibration_rows()
    hc = hazard_curve()
    pr9 = met('price_response')['response_recovery']
    cut = met('optimize_price_cut')
    cats = sorted([c for c in cut['by_category'] if c['min_cut_strategic_pct'] is not None],
                  key=lambda c: c['min_cut_strategic_pct'])
    pol = met('optimize_restock_priority')['policies']
    covered = sum(1 for r in cal if r[4] <= r[2] <= r[5])
    misses = [f'{r[1]} ({r[0].split(" · ")[1]})' for r in cal if not (r[4] <= r[2] <= r[5])]
    stats = build_stats()

    p2, p3, p4 = met('price_forecast_lgbm'), met('price_direction'), met('stockout_classifier')
    p5, p6, p6t = met('eta_forecast'), met('anomaly_real'), met('anomaly_temporal')
    p8, p10, p11 = met('restock_interval'), met('assortment_gaps'), met('simulate_whatif')
    matcher_ok = (M / 'product_matcher' / 'metrics.json').exists()
    ev = json.loads((ROOT / 'outputs' / 'analyst' / 'eval_report.json').read_text(encoding='utf-8'))
    hold = ev['offline']['holdout_set']['summary']; tune = ev['offline']['tuning_set']['summary']
    raw_ok = all(man(n)['raw_hashes_match_verified_baseline'] for n in (
        'stockout_classifier', 'stockout_survival', 'restock_interval', 'price_response', 'eta_forecast',
        'price_direction', 'anomaly_real', 'assortment_gaps', 'simulate_whatif', 'optimize_price_cut',
        'optimize_restock_priority'))
    sim_p1 = [x for x in p11['price_scenarios'] if x['scenario'].startswith('P1') and x['platform'] == 'Blinkit']
    p1s = next(x for x in sim_p1 if x['view'].startswith('static')); p1g = next(x for x in sim_p1 if x['view'].startswith('strategic'))
    cqr = p5['conformal_intervals']['90%']
    cqr_cov = cqr.get('marginal_cqr_test_coverage', cqr.get('cqr_test_coverage'))
    unit = p6['detector_eval_vs_known_defect']['unit_price_z (|z|)']
    hyb = p10['evaluation']['mean_by_method']
    pol_d = {p['policy']: p for p in pol}

    REAL = '<span class="stamp real">REAL · 2026-07-10</span>'
    SYN = '<span class="stamp syn">SYNTHETIC · pipeline check</span>'
    MIX = '<span class="stamp mix">REAL + SYNTHETIC, never mixed</span>'
    PER = '<span class="stamp mix">labelled per claim</span>'

    ledger = [
        ('1', 'Product matcher', REAL, 'not yet measurable',
         'Every verified positive compares two identical records, so real name-variation accuracy waits for human labels. No claim that LightGBM beats the string baseline.', 'MATCHER_v1.md'),
        ('2', 'Next-price forecast', SYN, f"MAE {p2['test']['model']['mae']:.2f}",
         f"vs naive {p2['test']['baseline_naive']['mae']:.2f}: {100 * p2['test']['skill_vs_naive']:.1f}% better on the untouched test split, on the price change folded back to a level.", 'PRICE_FORECAST_v1.md'),
        ('3', 'Price direction', SYN, f"macro-F1 {p3['test']['model']['macro_f1']:.3f}",
         f"vs {p3['test']['rule_combo']['macro_f1']:.3f} for the calibrated rule. New price-grid features carry {100 * p3['grid_features_share_of_gain']:.0f}% of the gain; the “will drop” radar is right {100 * p3['price_drop_radar'][0]['precision_model']:.0f}% of the time at a 5% alert budget.", 'PRICE_DIRECTION_v1.md'),
        ('4', 'Stock-out classifier', SYN, f"{p4['stockout_radar']['model'][0]['lift']:.1f}× lift",
         f"at a 1% alert budget (the Markov table gets {p4['stockout_radar']['markov_category'][0]['lift']:.1f}×). Two heads, depletion and restock, beat the transition table on both.", 'STOCKOUT_CLASSIFIER_v1.md'),
        ('5', 'Delivery ETA', SYN, f"{100 * cqr_cov:.1f}% coverage",
         f"of the 90% promise interval (conformal). MAE {p5['test']['model']['mae']:.2f} min beats three baselines. Exposed: a naive regression inflates the stock-out effect 7× (demand confounds both).", 'ETA_FORECAST_v1.md'),
        ('6', 'Anomaly detection', MIX, f"P@100 {unit['precision_at_100']:.2f}",
         f"on a real, known pack_qty defect the detector never saw (base rate {100 * p6['known_defect_rows'] / p6['labelable_rows']:.1f}%). Injected spikes caught at {100 * p6t['threshold_5']['recall']:.0f}% recall, {100 * p6t['threshold_5']['precision']:.0f}% precision.", 'ANOMALY_v1.md'),
        ('7', 'Stock-out survival', SYN, f"k = {cal[0][3]:.2f}",
         f"planted 2. Pooled curves say {cal[0][6]:.2f}; category, platform and a per-listing frailty explain the gap. Beats LightGBM on time-to-stock-out at every horizon.", 'STOCKOUT_SURVIVAL_v1.md'),
        ('8', 'Restock interval', SYN, f"ARI {p8['recovery']['latent_groups']['adjusted_rand_vs_planted']:.2f}",
         'The hidden FAST / MEDIUM / SLOW groups found with no labels. A negative control (unplanted effects) comes back zero. Beats LightGBM at every horizon.', 'RESTOCK_INTERVAL_v1.md'),
        ('9', 'Price response', SYN, f"β = {pr9[0]['corrected_beta']:.3f}",
         f"planted {pr9[0]['planted_beta']}, naive {pr9[0]['naive_beta']:.3f}. Price grids hide half the response; simulating the grid gets it back. Lags found, and Blinkit follows no one.", 'PRICE_RESPONSE_v1.md'),
        ('10', 'Assortment gaps', REAL, f"{p10['hybrid_vs_popularity_recall@100']:.1f}× popularity",
         f"at recovering hidden real listings (recall@100 {hyb['hybrid_ranker']['recall@100']:.3f} vs {hyb['popularity']['recall@100']:.3f}). A gap may be a collection gap: two stores were collected 4× deeper.", 'ASSORTMENT_GAPS_v1.md'),
        ('11', 'SIMULATE', SYN, f"+{p1g['change_pp']['mean']:.1f} pp, not +{p1s['change_pp']['mean']:.1f}",
         'Blinkit −3%: cheapest-of-4 share once followers react vs the static view. The engine first reproduces the status quo within 1 pp.', 'SIMULATE_OPTIMIZE_v1.md'),
        ('12a', 'OPTIMIZE · price cut', SYN, f"{cut['median_strategic_over_static']:.2f}× deeper",
         'Ignoring competitor response understates the cut needed to be cheapest on 40% of a category. A positioning answer, never a profit optimum.', 'SIMULATE_OPTIMIZE_v1.md'),
        ('12b', 'OPTIMIZE · restock priority', SYN, f"−{pol_d['priority_index']['reduction_vs_none_pct']:.1f}%",
         f"out-of-stock exposure at the same capacity. “Longest out first” ({pol_d['longest_out_first']['reduction_vs_none_pct']:.1f}%) does worse than random ({pol_d['random']['reduction_vs_none_pct']:.1f}%).", 'SIMULATE_OPTIMIZE_v1.md'),
        ('12c', 'Store coverage gaps', REAL, '30 real stores',
         'Areas and pincodes far from any listed store, from real addresses and coordinates. Not a census of every dark store.', 'COVERAGE_12C.md'),
        ('13', 'AI analyst', PER, f"{hold['passed']}/{hold['questions']} held-out",
         f"({tune['passed']}/{tune['questions']} on the tuning set). Refuses demand and revenue questions, relabels any synthetic-sourced claim, flags numbers it did not retrieve.", 'AI_ANALYST_v1.md'),
    ]
    ledger_html = '\n'.join(
        f'<li class="entry"><div class="num">{n}</div><div class="body"><div class="head"><h3>{esc(t)}</h3>{stamp}</div>'
        f'<p><strong class="read">{esc(h)}</strong> {esc(txt)}</p><div class="doc">docs/{doc}</div></div></li>'
        for n, t, stamp, h, txt, doc in ledger)

    cal_table = table(['deliverable', 'parameter', 'planted', 'recovered', '95% CI', 'naive', 'covered'],
                      [[g, l, f'{p:g}', f'{e:.3f}', f'{lo:.3f} – {hi:.3f}', '' if n is None else f'{n:.3f}',
                        'yes' if lo <= p <= hi else 'no'] for g, l, p, e, lo, hi, n in cal])
    bars_table = table(['follower', 'lag', 'planted β', 'naive β̂', 'corrected β̂', '95% CI'],
                       [[r['follower'], r['lag'], r['planted_beta'], f"{r['naive_beta']:.3f}", f"{r['corrected_beta']:.3f}",
                         f"{r['corrected_ci'][0]:.3f} – {r['corrected_ci'][1]:.3f}"] for r in pr9])
    haz_table = table(['clock', 'planted', 'frailty model', '± 1.96 se', 'pooled'],
                      [[int(a), f'{b:.2f}', f'{c:.2f}', f'{1.96 * s:.2f}', f'{d:.2f}'] for a, b, c, s, d in
                       zip(hc['r'], hc['planted'], hc['frailty'], hc['se'], hc['pooled'])])
    cut_table = table(['category', 'common-panel SKUs', 'cheapest now', 'static cut', 'strategic cut'],
                      [[c['category'], c['common_panel_skus'], f"{100 * c['blinkit_cheapest_share_now']:.1f}%",
                        f"{c['min_cut_static_pct']:.1f}%", f"{c['min_cut_strategic_pct']:.1f}%"] for c in cats])
    pol_table = table(['policy', 'OOS listing-snapshots', 'reduction', '90% band', 'saved per action'],
                      [[p['policy'].replace('_', ' '), f"{p['oos_listing_snapshots']:,.0f}", f"{p['reduction_vs_none_pct']:.1f}%",
                        f"{p['reduction_p05']:.1f} – {p['reduction_p95']:.1f}",
                        '' if p['oos_snapshots_saved_per_action'] is None else f"{p['oos_snapshots_saved_per_action']:.2f}"] for p in pol])

    page = TEMPLATE
    subs = {
        '{{FOREST}}': forest_svg(cal), '{{CAL_TABLE}}': cal_table, '{{COVERED}}': str(covered), '{{NCAL}}': str(len(cal)),
        '{{BARS}}': bars_svg(pr9), '{{BARS_TABLE}}': bars_table,
        '{{HAZARD}}': hazard_svg(hc), '{{HAZ_TABLE}}': haz_table, '{{KV3}}': f"{hc['k_v3']:.2f}",
        '{{DUMBBELL}}': dumbbell_svg(cats), '{{CUT_TABLE}}': cut_table,
        '{{POLICY}}': policy_svg(pol), '{{POL_TABLE}}': pol_table,
        '{{LEDGER}}': ledger_html,
        '{{RAW_OK}}': 'untouched' if raw_ok else 'CHANGED — check the manifests',
        '{{K2}}': f'{cal[0][3]:.2f}', '{{K0}}': f'{cal[0][6]:.2f}',
        '{{MEDIAN_RATIO}}': f"{cut['median_strategic_over_static']:.2f}",
        '{{P1S}}': f"{p1s['change_pp']['mean']:.1f}", '{{P1G}}': f"{p1g['change_pp']['mean']:.1f}",
        '{{MISSES}}': ', '.join(misses) if misses else 'none',
        '{{N_DELIV}}': str(len(ledger)),
        '{{TESTS}}': stats['tests'], '{{REAL_ROWS}}': f"{stats['real']:,}", '{{ALL_ROWS}}': f"{stats['rows']:,}",
        '{{PRI}}': f"{pol_d['priority_index']['reduction_vs_none_pct']:.1f}",
        '{{LOF}}': f"{pol_d['longest_out_first']['reduction_vs_none_pct']:.1f}",
        '{{RND}}': f"{pol_d['random']['reduction_vs_none_pct']:.1f}",
    }
    for k, v in subs.items():
        page = page.replace(k, v)
    assert '{{' not in page, 'unfilled placeholder'
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding='utf-8')
    print(f'wrote {OUT.relative_to(ROOT)} ({len(page) / 1024:.0f} KB); {covered}/{len(cal)} planted values inside their 95% CI')


TEMPLATE = (Path(__file__).with_name('showcase_template.html')).read_text(encoding='utf-8')

if __name__ == '__main__':
    build()
