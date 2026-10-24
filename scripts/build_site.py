"""
build_site.py — the project website: one self-contained file, built from saved outputs only.

    python scripts/build_site.py          # -> outputs/site/index.html

Nothing is recomputed here. Every number on the site comes from outputs/models/*/metrics.json, the run log, or the
project's own analyst run at build time. Sources: site/index.html (shell), site/app.css, site/app.js (pages),
site/analyst.js (the in-browser analyst engine, also run under node for its evaluation).

Pages: Home, Products, Festive planner, Simulate, Optimize, Analyst, Models, Data & trust, Plan the panel, Pipeline. The analyst is
also a floating chat on every page and behind the search box.

How it is meant to be opened: `python scripts/serve_site.py` (http://localhost:8000). Served that way, questions go to
the project's own analyst; opened from disk, the same file answers with the engine embedded in the page. Data is
embedded as JSON blocks and parsed only when a page needs it.

Wording. The pages do not use the project's two data labels as words. They say Snapshot (what was observed on Blinkit
on 2026-07-10) and Lab (the simulated panel and everything fitted to it), and every number still carries one of the
two tags. The mapping lives in site/app.js (`plain`); scripts/site_smoke.js fails the build if either label word
reaches a rendered page.
"""
import importlib.util
import csv
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MODELS = ROOT / 'outputs' / 'models'
SRC = ROOT / 'site'
OUT_DIR = ROOT / 'outputs' / 'site'
OUT = OUT_DIR / 'index.html'              # a complete document: serve it (scripts/serve_site.py) or open it from disk
PLAT = ['Blinkit', 'Swiggy Instamart', 'Flipkart Minutes', 'BigBasket']

# questions offered as one-tap examples (the eval sets are answered too, but not advertised): (as shown, as asked).
# The page shows the first and asks the second, which is the same question in the words the project's documents use.
SUGGESTED_PAIRS = [
    ('How accurate is the next-price forecast?',) * 2,
    ('Does the store column carry any information?', 'Does the store label on the real rows carry information?'),
    ('What happens if Blinkit cuts prices by 3 percent?',) * 2,
    ('Out-of-stock rate by category on Blinkit', 'Out-of-stock rate by category on the real snapshot'),
    ('Is matcher v2 better than v1?',) * 2,
    ('How many days of hand-logged data would be enough?', 'How many days of real data would be enough?'),
    ('What is Blinkit revenue?',) * 2,
    ('How do competitors respond when Blinkit changes a price?',) * 2,
    ('Which results were observed and which were simulated?', 'Which results in this project are real and which are synthetic?'),
]
SUGGESTED = [asked for _, asked in SUGGESTED_PAIRS]


def script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def met(name: str) -> dict:
    return json.loads((MODELS / name / 'metrics.json').read_text(encoding='utf-8'))


def scope(name: str) -> str:
    s = json.loads((MODELS / name / 'manifest.json').read_text(encoding='utf-8'))['claim_scope']
    return 'REAL' if s.startswith('REAL') else 'SYNTHETIC'


# --------------------------------------------------------------------------- blocks
def findings() -> dict:
    """What the observed Blinkit day itself showed, read off saved outputs only (the Findings page and Home lead with it).
    The stock and store-label findings come from the reality block, which the page already holds; this adds the two
    that live elsewhere: the pack-size defect the anomaly detector found, and the prices that were looked up, not seen."""
    import pandas as pd
    an = met('anomaly_real')
    det = an['detector_eval_vs_known_defect']['unit_price_z (|z|)']
    pred = pd.read_parquet(MODELS / 'anomaly_real' / 'predictions.parquet')
    rows = len(pred)
    top = pred.reindex(pred['unit_price_z'].abs().sort_values(ascending=False).index).head(100)
    ex = top[top['known_pack_qty_defect'] == True].iloc[0]                    # the most unusual flag that is the defect
    clean = lambda s: str(s).replace('**', '').strip()
    ratio = re.search(r'([\d.]+)x', str(ex['reason']))
    web = pd.read_csv(ROOT / 'data' / 'reference' / 'REAL_PRICE_SOURCE_AUDIT.csv')
    other = web.loc[~web['price_is_from_blinkit'].astype(bool), 'price_source_site']
    return {
        'defect': {'rows': int(an['known_defect_rows']), 'observed_rows': rows, 'p_at_100': det['precision_at_100'],
                   'base': an['known_defect_rows'] / rows,
                   'example': {'name': clean(ex['product_name']), 'pack': clean(ex['pack_size']), 'price': float(ex['selling_price']),
                               'unit_price': float(ex['unit_price']), 'times': float(ratio.group(1)) if ratio else None}},
        'web': {'n': len(web), 'blinkit': int(web['price_is_from_blinkit'].astype(bool).sum()), 'other': int(len(other)),
                'sites': sorted(other.unique().tolist())},
    }


def review_queue() -> str:
    """The matcher's next step, from the labelling batch itself: how many pairs wait for a person."""
    f = ROOT / 'data' / 'reference' / 'MATCH_REVIEW_PRIORITY.csv'
    if not f.exists():
        return ''
    with f.open(encoding='utf-8', newline='') as fh:
        rows = list(csv.DictReader(fh))
    todo = sum(1 for r in rows if not str(r.get('label') or '').strip())
    if not todo:
        return f'All {len(rows)} pairs of the review batch are labelled: rerun python -m src.matching.train to measure it.'
    return (f'Next step: {todo} of {len(rows)} pairs are queued for a person to label, at a few seconds each. '
            'That turns this into a measured model; nothing else can.')


def meta() -> dict:
    import src.load as L
    from src import provenance
    raw = L.load_raw()
    mix = raw.groupby(['platform', 'data_status']).size().unstack(fill_value=0)
    run = json.loads((ROOT / 'outputs' / 'run_log' / 'run_all.json').read_text(encoding='utf-8'))
    ledger = json.loads((ROOT / 'outputs' / 'audit' / 'claims_ledger.json').read_text(encoding='utf-8'))
    tests = run.get('tests') or {}
    cases = tests.get('cases', [])
    return {
        'built': date.today().isoformat(),
        'rows': int(len(raw)),
        'mix': [{'platform': p, 'real': int(mix.loc[p].get('REAL', 0)), 'synthetic': int(mix.loc[p].get('SYNTHETIC', 0))}
                for p in PLAT if p in mix.index],
        'stores': int(raw.store_id.nunique()), 'products': int(L.load_catalog().shape[0]),
        'snapshots': int(raw[raw.data_status == 'SYNTHETIC'].snapshot_id.nunique()),
        # tests = the ones that ran (passed or failed); a test skipped for want of an input is counted apart, not as failing
        'run': {'steps': len(run['steps']), 'ok': sum(s['ok'] for s in run['steps']), 'finished': run.get('finished_utc'),
                'tests': sum(c['state'] != 'skipped' for c in cases), 'passed': sum(c['state'] == 'passed' for c in cases),
                'skipped': sum(c['state'] == 'skipped' for c in cases)},
        'ledger': {'claims': ledger['claims'], 'numbers': ledger['numbers_checked'], 'stale': ledger['counts']['stale']},
        'contracts': (lambda k: {'passed': k['passed'], 'total': k['passed'] + k['failed']} if k else None)(contracts()),
        'api': remote_api(),
        'storeLabel': provenance.store_label_status(),
        'webPrices': len(L.web_researched_price_ids()),
        'suggested': [shown for shown, _ in SUGGESTED_PAIRS],
        'ask': {shown: asked for shown, asked in SUGGESTED_PAIRS if shown != asked},
    }


def models() -> list:
    pf, pdn, sc, eta = met('price_forecast_lgbm'), met('price_direction'), met('stockout_classifier'), met('eta_forecast')
    an, sv, ri, pr, ag = met('anomaly_real'), met('stockout_survival'), met('restock_interval'), met('price_response'), met('assortment_gaps')
    v2 = met('product_matcher_v2')
    k_frailty = sv['parameter_recovery'][0]
    k_pooled = sv['parameter_recovery'][2]
    ev = ag['evaluation']['mean_by_method']
    eta_bars = [[n.replace('listing same-hour mean to date', 'Same-hour mean so far').replace('naive (ETA now)', 'ETA now')
                 .replace('seasonal naive (ETA one snapshot ago)', 'ETA at the last check').replace('model', 'Model'), v['mae'], n == 'model']
                for n, v in eta['test'].items() if isinstance(v, dict) and 'mae' in v]
    dir_bars = [[n.replace('_', ' ').capitalize(), v['log_loss'], n == 'model'] for n, v in pdn['test'].items()
                if isinstance(v, dict) and 'log_loss' in v]
    cards = [
        {'n': '1', 'name': 'Product matcher', 'data': 'REAL', 'q': 'Are two listings the same product?',
         'result': 'Accuracy on name variation as shoppers see it is not measured: no pair has a human label yet.',
         'detail': f"Version 2 learns from constructed edits and abstains on {v2['support_on_unlabelled_real_pairs']['decisions']['abstain']:,} "
                   f"of {v2['support_on_unlabelled_real_pairs']['unlabelled_real_pairs']:,} unlabelled pairs.",
         'supported': 'No claim until people label pairs.', 'doc': 'docs/MATCHER_v2.md',
         'next': review_queue()},
        {'n': '2', 'name': 'Next price', 'data': 'SYNTHETIC', 'q': 'What will this listing cost at the next check?',
         'unit': 'Test error in rupees, lower is better',
         'bars': [['Model', pf['test']['model']['mae'], True], ['Tomorrow = today', pf['test']['baseline_naive']['mae'], False],
                  ['Running mean', pf['test']['baseline_price_avg_to_date']['mae'], False]],
         'result': f"Beats both baselines by {100 * pf['test']['skill_vs_naive']:.1f}% against the stronger one.",
         'supported': 'In the Lab only.', 'doc': 'docs/PRICE_FORECAST_v1.md'},
        {'n': '3', 'name': 'Price direction', 'data': 'SYNTHETIC', 'q': 'Up, down or flat next?',
         'unit': 'Test log loss, lower is better', 'bars': dir_bars,
         'result': f"Its top 5% of drop alerts are right {100 * pdn['price_drop_radar'][0]['precision_model']:.0f}% of the time.",
         'supported': 'In the Lab only.', 'doc': 'docs/PRICE_DIRECTION_v1.md'},
        {'n': '4', 'name': 'Stock-out risk', 'data': 'SYNTHETIC', 'q': 'Will it be out of stock at the next check?',
         'result': f"Beats the transition-table baseline on log loss. Its top 1% of alerts catch "
                   f"{sc['stockout_radar']['model'][0]['lift']:.1f} times the base rate.",
         'detail': f"ROC AUC {sc['test']['full']['overall']['roc_auc']:.3f} on the test split.",
         'supported': 'In the Lab only.', 'doc': 'docs/STOCKOUT_CLASSIFIER_v1.md'},
        {'n': '5', 'name': 'Delivery time', 'data': 'SYNTHETIC', 'q': 'What ETA will the app promise next?',
         'unit': 'Test error in minutes, lower is better', 'bars': eta_bars,
         'result': f"90% intervals cover {100 * eta['conformal_intervals']['90%']['marginal_cqr_test_coverage']:.1f}% of test rows.",
         'supported': 'In the Lab only. Store-driven delivery time is an assumption the observed day does not show.',
         'doc': 'docs/ETA_FORECAST_v1.md'},
        {'n': '6', 'name': 'Anomaly detection', 'data': 'REAL', 'q': 'Which listings look unusual on the observed day?',
         'result': f"Finds a known pack-size defect: {100 * an['detector_eval_vs_known_defect']['unit_price_z (|z|)']['precision_at_100']:.0f}% "
                   'of its top 100 flags are that defect.',
         'supported': 'Yes, for "unusual on the observed day". Never "error" or "deal".', 'doc': 'docs/ANOMALY_v1.md'},
        {'n': '7', 'name': 'Time until stock-out', 'data': 'SYNTHETIC', 'q': 'How long does an in-stock run last?',
         'unit': 'Hazard shape recovered, planted value 2',
         'bars': [['Planted', 2.0, False], ['Model with shared frailty', k_frailty['estimate'], True],
                  ['Pooled curve, no frailty', k_pooled['estimate'], False]],
         'result': 'Recovers the planted shape once listing differences are modelled; a pooled curve reads it far too low.',
         'supported': 'In the Lab only.', 'doc': 'docs/STOCKOUT_SURVIVAL_v1.md'},
        {'n': '8', 'name': 'Time to restock', 'data': 'SYNTHETIC', 'q': 'How long does an outage last?',
         'result': f"Finds the three planted restock groups with no labels (agreement {ri['recovery']['latent_groups']['adjusted_rand_vs_planted']:.2f} of 1).",
         'detail': f"Dispersion {ri['recovery']['negbin_n']['estimate']:.2f} against a planted 2.",
         'supported': 'In the Lab only.', 'doc': 'docs/RESTOCK_INTERVAL_v1.md'},
        {'n': '9', 'name': 'Competitor response', 'data': 'SYNTHETIC', 'q': "How far do rivals follow Blinkit's price?",
         'unit': 'Response coefficient',
         'groups': [{'label': r['follower'], 'bars': [['Planted', r['planted_beta'], False], ['Plain regression', r['naive_beta'], False],
                                                     ['Corrected for price grids', r['corrected_beta'], True]]}
                    for r in pr['response_recovery']],
         'result': 'Rounded shelf prices hide about half the response from a plain regression; the correction recovers it.',
         'supported': 'Causal only because the simulator planted a leader. On observed data it would be association.',
         'doc': 'docs/PRICE_RESPONSE_v1.md'},
        {'n': '10', 'name': 'Assortment gaps', 'data': 'REAL', 'q': 'What might a store be missing?',
         'unit': 'Hidden listings recovered in the top 100, higher is better',
         'bars': [[m.replace('_', ' ').capitalize(), v['recall@100'], m == 'hybrid_ranker'] for m, v in ev.items()],
         'result': f"The hybrid ranker recovers {ag['hybrid_vs_popularity_recall@100']:.1f} times as many hidden listings as popularity.",
         'supported': 'The method stands. The store reading does not: the store label is unverified.',
         'storeLevel': True, 'doc': 'docs/ASSORTMENT_GAPS_v1.md'},
    ]
    charts = model_charts()
    for c in cards:
        c["chart"] = charts.get(c["n"])
    return cards


def model_charts() -> dict:
    """One chart per model card, read off the model's own saved metrics. Keyed by the card number."""
    pf, pdn, sc, eta = met('price_forecast_lgbm'), met('price_direction'), met('stockout_classifier'), met('eta_forecast')
    an, sv, ri, pr, ag = met('anomaly_real'), met('stockout_survival'), met('restock_interval'), met('price_response'), met('assortment_gaps')
    v2 = met('product_matcher_v2')
    dec = v2['support_on_unlabelled_real_pairs']['decisions']
    t = pf['test']
    radar = sc['stockout_radar']
    det = an['detector_eval_vs_known_defect']
    ks = (50, 100, 250, 500)
    names = {'unit_price_z (|z|)': 'Unit price', 'combined (max |z|)': 'Combined', 'isolation_forest': 'Isolation forest',
             'price_z (|z|)': 'Price alone'}
    methods = {'hybrid_ranker': 'Hybrid ranker', 'store_knn': 'Similar stores', 'popularity': 'Popularity',
               'mf_svd': 'Matrix factorisation', 'brand_affinity': 'Brand affinity'}
    ev = ag['evaluation']['mean_by_method']
    return {
        '1': {'type': 'donut', 'title': f"What version 2 decides on {dec['same'] + dec['different'] + dec['abstain']:,} unlabelled pairs",
              'note': 'It abstains where its training never saw that kind of difference.',
              'parts': [['Different products', dec['different'], 'base'], ['Abstains', dec['abstain'], 'alt'], ['Same product', dec['same'], 'own']]},
        '2': {'type': 'columns', 'title': 'Test error in rupees, three ways', 'note': 'Lower is better. On the median listing, "tomorrow = today" is hard to beat.',
              'series': [['Model', 'own'], ['Tomorrow = today', 'alt'], ['Running mean', 'base']],
              'groups': [[label, [t['model'][k], t['baseline_naive'][k], t['baseline_price_avg_to_date'][k]]]
                         for label, k in (('Mean error', 'mae'), ('Root mean square', 'rmse'), ('Median error', 'median_ae'))]},
        '3': {'type': 'lines', 'title': 'How often a drop alert is right', 'note': 'Precision when the most likely listings are flagged.',
              'x': {'title': 'Share of listings flagged', 'fmt': 'pct0'}, 'y': {'title': 'Alerts that were right', 'fmt': 'pct0', 'min': 0},
              'series': [{'name': 'Model', 'cls': 'own', 'pts': [[r['budget'], r['precision_model']] for r in pdn['price_drop_radar']], 'area': True},
                         {'name': 'Rule combo', 'cls': 'alt', 'pts': [[r['budget'], r['precision_rule_combo']] for r in pdn['price_drop_radar']]},
                         {'name': 'Base rate', 'cls': 'base', 'dash': True, 'pts': [[r['budget'], r['base_rate']] for r in pdn['price_drop_radar']]}]},
        '4': {'type': 'lines', 'title': 'Stock-outs caught for the alerts raised', 'note': 'A capture curve: the steeper, the better. Random flags sit on the diagonal.',
              'x': {'title': 'Share of listings flagged', 'fmt': 'pct0'}, 'y': {'title': 'Share of next stock-outs caught', 'fmt': 'pct0', 'min': 0},
              'series': [{'name': 'Model', 'cls': 'own', 'area': True, 'pts': [[0, 0]] + [[r['budget'], r['capture']] for r in radar['model']]},
                         {'name': 'Transition table', 'cls': 'alt', 'pts': [[0, 0]] + [[r['budget'], r['capture']] for r in radar['markov_category']]},
                         {'name': 'Random', 'cls': 'base', 'dash': True, 'pts': [[0, 0], [radar['model'][-1]['budget']] * 2]}]},
        '5': {'type': 'columns', 'title': 'Do the 80% and 90% intervals hold?', 'note': 'Share of test deliveries inside the interval. The line marks the promise.',
              'series': [['Raw model quantiles', 'base'], ['After conformal correction', 'own']], 'fmt': 'pct0', 'max': 1,
              'groups': [[f"{lvl} interval", [eta['conformal_intervals'][lvl]['raw_quantile_coverage_on_val'],
                                              eta['conformal_intervals'][lvl]['marginal_cqr_test_coverage']], eta['conformal_intervals'][lvl]['target']]
                         for lvl in ('80%', '90%')]},
        '6': {'type': 'lines', 'title': 'Of the top flags, how many are the known defect', 'note': 'Precision at the top k flags, on the observed Blinkit rows.',
              'x': {'title': 'Top flags checked', 'fmt': 'int', 'cat': list(ks)}, 'y': {'title': 'Flags that are the defect', 'fmt': 'pct0', 'min': 0, 'max': 0.8},
              'series': [{'name': label, 'cls': cls, 'area': cls == 'own', 'pts': [[k, det[key][f'precision_at_{k}']] for k in ks]}
                         for key, label, cls in (('unit_price_z (|z|)', 'Unit price', 'own'), ('combined (max |z|)', 'Combined', 'alt'),
                                                 ('isolation_forest', 'Isolation forest', 'c3'), ('price_z (|z|)', 'Price alone', 'base'))],
              'refs': [{'y': an['known_defect_rows'] / an['labelable_rows'], 'label': 'base rate'}]},
        '7': {'type': 'forest', 'title': 'Each recovered parameter against the value planted', 'note': 'Estimate divided by the planted value, with its 95% interval. 1 is a perfect recovery.',
              'rows': [[r['parameter'].replace('—', '-'), r['estimate'] / r['planted'], r['ci_low'] / r['planted'], r['ci_high'] / r['planted'], bool(r['covered'])]
                       for r in sv['parameter_recovery']]},
        '8': {'type': 'scatter', 'title': 'Mean outage length, recovered against planted', 'note': 'Twelve restock group by platform cells, with 95% intervals. The diagonal is a perfect recovery.',
              'x': {'title': 'Planted mean (checks)'}, 'y': {'title': 'Recovered mean (checks)'},
              'groups': [['Fast', 'own'], ['Medium', 'alt'], ['Slow', 'c3']],
              'points': [[c['group'].title(), c['platform'], c['planted_mean_snapshots'], c['estimate'], c['ci_low'], c['ci_high'], bool(c['covered'])]
                         for c in ri['recovery']['cells_group_x_platform']]},
        '9': {'type': 'dumbbell', 'title': 'How far each rival follows Blinkit', 'note': 'Plain regression on rounded shelf prices finds about half the planted response; the correction recovers it.',
              'marks': [['Planted', 'ring'], ['Plain regression', 'base'], ['Corrected for price grids', 'own']],
              'rows': [[r['follower'], [r['planted_beta'], r['naive_beta'], r['corrected_beta']]] for r in pr['response_recovery']]},
        '10': {'type': 'lines', 'title': 'Hidden listings recovered as the list grows', 'note': "Recall at k: hide 20% of a store's products and see how many come back in the top k.",
               'x': {'title': 'Top k suggestions', 'fmt': 'int', 'cat': [20, 50, 100, 250]}, 'y': {'title': 'Hidden listings recovered', 'fmt': 'pct0', 'min': 0},
               'series': [{'name': label, 'cls': cls, 'area': cls == 'own', 'pts': [[k, ev[key][f'recall@{k}']] for k in (20, 50, 100, 250)]}
                          for key, label, cls in (('hybrid_ranker', 'Hybrid ranker', 'own'), ('store_knn', 'Similar stores', 'alt'),
                                                  ('popularity', 'Popularity', 'c3'), ('brand_affinity', 'Brand affinity', 'base'))]},
    }


def optimize() -> dict:
    pc, rp = met('optimize_price_cut'), met('optimize_restock_priority')
    return {'target': pc['target_cheapest_share'], 'maxCut': pc['max_cut_searched'],
            'byCategory': [{'category': r['category'], 'now': r['blinkit_cheapest_share_now'], 'static': r['min_cut_static_pct'],
                            'strategic': r['min_cut_strategic_pct'], 'skus': r['common_panel_skus']}
                           for r in pc['by_category']],
            'ratio': pc['median_strategic_over_static'],
            'policies': [{'policy': p['policy'], 'reduction': p['reduction_vs_none_pct'], 'lo': p['reduction_p05'],
                          'hi': p['reduction_p95'], 'actions': p['actions']} for p in rp['policies']],
            'capacity': rp['capacity_share_per_store_per_snapshot']}


def pipeline() -> dict:
    run = script('build_run_page').payload()
    def clean(ln: str) -> str:                       # a log line may quote this machine's own folder: keep the project path only
        for prefix in (str(ROOT) + '\\', str(ROOT) + '/', str(ROOT).replace('\\', '\\\\') + '\\\\', str(ROOT)):
            ln = ln.replace(prefix, '')
        return ln[:170]
    steps = [{'group': s['group'], 'step': s['step'], 'what': s['what'], 'ok': s['ok'], 'seconds': s['seconds'],
              'command': s['command'], 'outputs': s.get('outputs', []), 'blocked_by': s.get('blocked_by'),
              'timed_out': bool(s.get('timed_out')), 'reused': bool(s.get('resumed_from_earlier_run')),
              'tail': [clean(ln) for ln in s.get('tail', [])[-6:]]} for s in run['steps']]
    t = run.get('tests') or {}
    files = {}
    for c in t.get('cases', []):
        f = files.setdefault(c['file'], {'file': c['file'], 'passed': 0, 'failed': 0})
        f['passed' if c['state'] == 'passed' else 'failed'] += 1
    runner = script('run_all')
    return {'steps': steps, 'groups': run['groups'], 'started': run.get('started_utc'), 'finished': run.get('finished_utc'),
            'tests': sorted(files.values(), key=lambda f: f['file']), 'summary': (t.get('summary') or [''])[0],
            'needs': {k: v for k, v in runner.NEEDS.items() if v}, 'contracts': contracts()}


def remote_api() -> str:
    """The project's public analyst the live page may ask (site/config.json, or $QCOM_API); '' when there is none."""
    import os
    api = os.environ.get('QCOM_API')
    if api is None:
        f = SRC / 'config.json'
        api = json.loads(f.read_text(encoding='utf-8')).get('api', '') if f.exists() else ''
    api = str(api or '').strip()
    import re
    if api and not (api.startswith('https://') or re.match(r'http://(localhost|127\.0\.0\.1)(:\d+)?(/|$)', api)):
        raise ValueError(f'the analyst URL must be https (the live site is), or this machine while trying it: {api}')
    return api


def badges(m: dict) -> dict:
    """Shields.io endpoint badges for the README, read from this build's own numbers, so they never go stale:
    https://img.shields.io/endpoint?url=<raw URL of site_dist/badges/NAME.json>."""
    def badge(label, done, total, unit, ok_color='0c8a4b'):
        full = total and done == total
        return {'schemaVersion': 1, 'label': label, 'labelColor': '111216',
                'message': f'{done} {unit}' if full else f'{done} of {total} {unit}',
                'color': ok_color if full else 'd63a3f'}
    run, ev = m['run'], None
    tests = badge('tests', run['passed'], run['tests'], 'passing')
    if run.get('skipped'):
        tests['message'] += f", {run['skipped']} skipped"
    out = {'tests': tests,
           'pipeline': badge('pipeline', run['ok'], run['steps'], 'steps OK', 'c9f24a')}
    if m.get('contracts'):
        out['contracts'] = badge('data contracts', m['contracts']['passed'], m['contracts']['total'], 'hold', 'c9f24a')
    f = OUT_DIR / 'analyst_eval.json'
    if f.exists():
        s = json.loads(f.read_text(encoding='utf-8'))['summary']
        ev = (s['tuning']['passed'] + s['holdout']['passed'], s['tuning']['questions'] + s['holdout']['questions'])
        out['analyst'] = badge('analyst', ev[0], ev[1], 'test questions', '2a78d6')
    out['claims'] = badge('doc numbers', m['ledger']['claims'] - m['ledger']['stale'], m['ledger']['claims'], 'claims match outputs', '2a78d6')
    return out


def contracts() -> dict | None:
    """The data-contract gate's last report (src/pipeline/contracts.py), as the Pipeline page shows it."""
    f = ROOT / 'outputs' / 'run_log' / 'contracts.json'
    if not f.exists():
        return None
    doc = json.loads(f.read_text(encoding='utf-8'))
    return {'checked': doc['checked_utc'], 'ok': doc['ok'], 'passed': doc['passed'], 'failed': doc['failed'],
            'seconds': doc['seconds'], 'items': [{k: c[k] for k in ('id', 'layer', 'rule', 'ref', 'ok', 'observed')}
                                                for c in doc['contracts']]}


def tool_answers(K) -> dict:
    """The project analyst's own claims for every experiment its offline router can reach, verified at build time.
    The page looks them up; it never rebuilds them. (A price move is the exception: 2,240 cells, formatted in the page
    from the same grid.)"""
    from src.analyst import guard
    from src.analyst.agent import claims_from_experiment
    from src.analyst.tools import PLATFORM_NAMES, run_tool
    from src.simulate.grid import load_grid
    out = {}

    def add(key, tool, args):
        res = run_tool(tool, args)
        if 'error' in res:
            return
        claims = guard.verify(claims_from_experiment(tool, res), json.dumps(res, default=str), K)
        cav = res.get('note') or res.get('claim_scope')
        if tool == 'store_adds':
            cav = [res['real']['claim_limit'], res['synthetic']['claim_limit']]
        out[key] = {'tool': tool, 'claims': claims, 'caveats': cav if isinstance(cav, list) else ([cav] if cav else []),
                    'product': (res.get('1_observe') or {}).get('listing', {}).get('product_name'),
                    'store': (res.get('1_observe') or {}).get('listing', {}).get('store_id')}
    groups = [g for g in load_grid()['groups'] if g != 'All']
    for p in PLATFORM_NAMES:
        add(f'outage|{p}|', 'outage_impact', {'platform': p, 'category': None})
    for g in groups:
        add(f'outage|Blinkit|{g}', 'outage_impact', {'platform': 'Blinkit', 'category': g})
        add(f'promo|{g}', 'promo_frontier', {'category': g})
    for g in ['All'] + groups:
        add(f'headroom|{g}', 'price_headroom', {'category': g})
    for n in (10, 25, 50):
        add(f'adds||{n}', 'store_adds', {'store': None, 'n': n})
        for s in range(1, 9):
            add(f'adds|{s:03d}|{n}', 'store_adds', {'store': f'{s:03d}', 'n': n})
    add('objective', 'restock_objective', {})
    add('capacity', 'restock_capacity', {})
    add('listing|default', 'explain_listing', {'product': None, 'store': None})
    for f in sorted((MODELS / 'listing_chain' / 'chains').glob('*.json')):
        lst = json.loads(f.read_text(encoding='utf-8'))['1_observe']['listing']
        add(f'listing|{f.name}', 'explain_listing', {'product': lst['product_name'], 'store': lst['store_id'][-3:]})
    return out


def metric_leaves(K, cap: int = 160) -> dict:
    """For each metric passage, its values as (path, value) pairs, so the page can quote the ones a question is about."""
    from src.analyst.agent import _fmt_leaf, _leaves
    out = {}
    for p in K.passages:
        if p.kind != 'metric':
            continue
        obj = json.loads((MODELS / p.model / 'metrics.json').read_text(encoding='utf-8')).get(p.section)
        out[p.pid] = [[path, _fmt_leaf(v)] for path, v in _leaves(obj) if v is not None][:cap]
    return out


def model_leads(K) -> dict:
    """Per model: its headline sentence and its claim limit, as the analyst quotes them."""
    out = {}
    for name, info in K.catalog.items():
        m = json.loads((MODELS / name / 'metrics.json').read_text(encoding='utf-8'))
        k = next((k for k in ('verdict', 'headline', 'transferable_method_finding') if isinstance(m.get(k), str)), None)
        out[name] = {'key': k, 'text': m[k] if k else None,
                     'limit': m['claim_limit'] if isinstance(m.get('claim_limit'), str) else None,
                     'prov': info['provenance'], 'date': info['date'], 'src': info['metrics_file']}
    return out


def analyst_data() -> tuple[dict, dict]:
    """(what the page needs, what the node evaluation needs)."""
    from src.analyst import evaluate as EV
    from src.analyst.agent import answer
    from src.analyst.kb import ALIASES, PLANNING_WORDS, STOP
    from src.analyst.tools import REAL_GROUPS, REAL_METRICS, kb, query_real_snapshot
    from src import provenance
    K = kb()
    passages = [{'id': p.pid, 'kind': p.kind, 'src': p.source_file.replace('\\', '/'), 'sec': p.section, 'text': p.text,
                 'prov': p.provenance, 'date': p.date, 'hist': p.historical, 'plan': p.planning, 'model': p.model}
                for p in K.passages]
    file_prov = {}
    for p in passages:
        file_prov.setdefault(p['src'], set()).add(p['prov'])
    file_prov = {f: (next(iter(v)) if len(v) == 1 else 'MIXED') for f, v in file_prov.items()}
    cube = {}
    for m in REAL_METRICS:
        for g in REAL_GROUPS:
            r = query_real_snapshot(m, g, top_n=50)
            cube[f'{m}|{g}'] = {'rows': r['rows'], 'caveats': r['caveats'], 'source': r['source'], 'date': r['date']}
    from src.analyst.tools import real_rows
    all_cats = sorted(real_rows().category.unique())
    for m in REAL_METRICS:                                    # one category, no grouping: "listings in Snacks & Munchies"
        for c in all_cats:
            r = query_real_snapshot(m, 'none', category=c)
            if 'error' not in r:
                cube[f'{m}|none|{c}'] = {'rows': r['rows'], 'caveats': r['caveats'], 'source': r['source'], 'date': r['date']}
    tools, leaves, lead = tool_answers(K), metric_leaves(K), model_leads(K)
    evalq = [{**q, 'set': 'tuning'} for q in EV.QUESTIONS] + [{**q, 'set': 'holdout'} for q in EV.HOLDOUT]
    keep = ('q', 'refuse', 'must_label', 'forbid_only', 'sources', 'must_mention', 'labels_all', 'stage_order', 'set')
    for q in evalq:                                           # the expected REAL value, as evaluate.grade accepts it
        if q.get('real_check'):
            v, m = EV.real_value(*q['real_check']), q['real_check'][0]
            q['want'] = ([f'{100 * v:.2f}', f'{100 * v:.1f}'] if m == 'oos_rate' else
                         [f'{v:,.0f}', f'{v:.0f}'] if m == 'listings' else [f'{v:g}', f'{v:.0f}'])
    evalq = [{k: v for k, v in q.items() if k in keep + ('want',)} for q in evalq]
    answers = {}
    for q in SUGGESTED + [e['q'] for e in evalq]:
        a = answer(q)
        answers[q] = {k: a.get(k) for k in ('question', 'refused', 'refusal_reason', 'answer_summary', 'claims', 'caveats',
                                             'banner', 'external_banner', 'store_label_banner', 'all_claims_verified')}
    page = {'passages': passages, 'fileProv': file_prov, 'cube': cube, 'answers': answers, 'suggested': SUGGESTED,
            'tools': tools, 'leaves': leaves, 'lead': lead, 'categories': all_cats,
            'stop': sorted(STOP), 'aliases': ALIASES, 'planningWords': list(PLANNING_WORDS),
            'storeOutputs': list(provenance.STORE_LEVEL_REAL_OUTPUTS), 'storeDocs': list(provenance.STORE_LEVEL_DOCS),
            'storeBanner': provenance.BANNER, 'storeUnverified': provenance.unverified()}
    return page, {'evalq': evalq}


def run_node_eval(page_analyst: dict, evalq: dict, whatif: dict) -> dict | None:
    """Score the in-browser engine on the project's own question sets, with its answer cache switched off."""
    node = shutil.which('node')
    if not node:
        return None
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    inp = OUT_DIR / '_analyst_eval_input.json'
    inp.write_text(json.dumps({**page_analyst, **evalq, 'whatif': whatif}, ensure_ascii=False, default=str), encoding='utf-8')
    p = subprocess.run([node, str(ROOT / 'scripts' / 'site_analyst_eval.js'), str(SRC / 'analyst.js'), str(inp),
                        str(OUT_DIR / 'analyst_eval.json')], capture_output=True, text=True, encoding='utf-8')
    inp.unlink(missing_ok=True)
    if p.returncode != 0:
        raise RuntimeError('in-browser analyst evaluation failed:\n' + p.stdout[-2000:] + p.stderr[-2000:])
    return json.loads((OUT_DIR / 'analyst_eval.json').read_text(encoding='utf-8'))


def festive() -> dict:
    """The festive stock planner (src/seasonal/festive.py): the calendar, the product groups and their snapshot rows."""
    f = ROOT / 'outputs' / 'festive' / 'festive_planner.json'
    if not f.exists():
        from src.seasonal import festive as F
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(F.build(), indent=1, ensure_ascii=False), encoding='utf-8', newline='\n')
    return json.loads(f.read_text(encoding='utf-8'))


PHOTO_HOSTS = ('https://images.openfoodfacts.org/', 'https://upload.wikimedia.org/')


def photos() -> dict:
    """Real product photos from scripts/fetch_product_photos.py: name|pack -> the photo's address, what it shows and
    whose it is. Exact photos come from Open Food Facts (the 400 px one: the 200 px one looked blurred on a card);
    `kind` marks a typical-look photo of the product's kind from Wikimedia Commons, which the page labels as such.
    Empty when the file has not been made: the page then draws."""
    f = ROOT / 'data' / 'reference' / 'PRODUCT_PHOTOS.json'
    if not f.exists():
        return {}
    keep = ('image', 'shows', 'source', 'license', 'credit', 'same_pack', 'kind')
    out = {}
    for k, v in json.loads(f.read_text(encoding='utf-8'))['photos'].items():
        v = {**v, 'image': v.get('image_large') or v.get('image', '')}
        if v['image'].startswith(PHOTO_HOSTS):
            out[k] = {x: v[x] for x in keep if x in v}
    return out


def app_icons():
    """Icons and a web manifest, so a phone or tablet can add ShelfPulse to its home screen (Android: Add to Home screen;
    iPhone and iPad: Share, then Add to Home Screen). Drawn here, four times larger and scaled down for smooth edges."""
    from PIL import Image, ImageDraw
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bolt = [(13, 2), (4, 14), (11, 14), (10, 22), (19, 10), (12, 10)]
    for name, size in (('icon-192.png', 192), ('icon-512.png', 512), ('apple-touch-icon.png', 180)):
        big = size * 4
        img = Image.new('RGB', (big, big), (201, 242, 74))
        k = big * 0.5 / 24                                   # the bolt fills half the icon: inside the maskable safe zone
        off = (big - 24 * k) / 2
        ImageDraw.Draw(img).polygon([(off + x * k, off + y * k) for x, y in bolt], fill=(27, 37, 0))
        img.resize((size, size), Image.LANCZOS).save(OUT_DIR / name, optimize=True)
    manifest = {'name': 'ShelfPulse · Quick-commerce intelligence', 'short_name': 'ShelfPulse', 'start_url': './', 'scope': './',
                'display': 'standalone', 'orientation': 'any', 'background_color': '#f6f7f9', 'theme_color': '#111216',
                'icons': [{'src': f'icon-{s}.png', 'sizes': f'{s}x{s}', 'type': 'image/png', 'purpose': 'any maskable'} for s in (192, 512)]}
    (OUT_DIR / 'manifest.webmanifest').write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding='utf-8', newline='\n')


def embed(name: str, obj) -> str:
    body = json.dumps(obj, separators=(',', ':'), ensure_ascii=False, default=str).replace('</', '<\\/')
    return f'<script type="application/json" id="d-{name}">{body}</script>'


def main():
    whatif = script('build_whatif_lab').data()
    explorer = script('build_explorer').data()
    reality = script('build_reality_check').payload()
    page_analyst, evalq = analyst_data()
    ev = run_node_eval(page_analyst, evalq, whatif)
    python_eval = json.loads((ROOT / 'outputs' / 'analyst' / 'eval_report.json').read_text(encoding='utf-8'))['offline']
    blocks = {
        'meta': meta(), 'models': models(), 'optimize': optimize(), 'pipeline': pipeline(),
        'whatif': whatif, 'explorer': explorer, 'reality': reality, 'analyst': page_analyst, 'festive': festive(), 'photos': photos(),
        'findings': findings(),
        'analystEval': {'browser': ev, 'python': {s: {'questions': python_eval[s]['summary']['questions'],
                                                      'passed': python_eval[s]['summary']['passed']}
                                                  for s in ('tuning_set', 'holdout_set')}},
    }
    html = (SRC / 'index.html').read_text(encoding='utf-8')
    html = html.replace('/*__CSS__*/', (SRC / 'app.css').read_text(encoding='utf-8'))
    html = html.replace('/*__ANALYST_JS__*/', (SRC / 'analyst.js').read_text(encoding='utf-8').replace('</script', '<\\/script'))
    html = html.replace('/*__APP_JS__*/', (SRC / 'app.js').read_text(encoding='utf-8').replace('</script', '<\\/script'))
    html = html.replace('<!--__DATA__-->', '\n'.join(embed(k, v) for k, v in blocks.items()))
    assert '__CSS__' not in html and '__APP_JS__' not in html and '__DATA__' not in html
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    app_icons()
    shutil.copyfile(SRC / 'sw.js', OUT_DIR / 'sw.js')         # offline after the first visit (served at /sw.js)
    first = '<div class="ticker"'                          # the first element of the body in site/index.html
    head, body = html.split(first, 1)
    shell = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
             '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n')
    OUT.write_text(shell + head + '</head><body>\n' + first + body + '</body></html>\n', encoding='utf-8', newline='\n')
    (OUT_DIR / 'badges').mkdir(exist_ok=True)
    for name, doc in badges(blocks['meta']).items():
        (OUT_DIR / 'badges' / f'{name}.json').write_text(json.dumps(doc, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    dist = script('deploy_pages').stage(ROOT / 'site_dist')   # what GitHub Pages serves; a push deploys it (.github/workflows/pages.yml)
    sizes = {k: round(len(json.dumps(v, default=str)) / 1024) for k, v in blocks.items()}
    print(f'wrote {OUT.relative_to(ROOT)} ({len(html) / 1024:.0f} KB)  blocks KB: {sizes}')
    print(f'staged {dist} for GitHub Pages: commit and push it to publish (python scripts/deploy_pages.py does both)')
    print('open it with: python scripts/serve_site.py   (http://localhost:8000)')
    if ev:
        print('in-browser analyst, cache off:', json.dumps(ev['summary']))
    else:
        print('node not found: the in-browser analyst was not evaluated')


if __name__ == '__main__':
    main()
