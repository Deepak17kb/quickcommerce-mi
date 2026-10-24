"""
run_all.py — execute the whole project end to end, in dependency order, and record what happened.

    python scripts/run_all.py                    # -> outputs/run_log/run_all.json (+ one .log per step), then the test suite
    python scripts/run_all.py --only matching    # one group
    python scripts/run_all.py --step anomaly,grid  # named steps only
    python scripts/run_all.py --from whatif      # this step and every one after it
    python scripts/run_all.py --resume           # keep the steps already recorded OK in run_all.json, run the rest
    python scripts/run_all.py --list             # the steps and what each one needs
    python scripts/run_all.py --dry-run          # what would run, be reused or be blocked, without running anything
    python scripts/run_all.py --timeout 1800     # stop any one step after 30 minutes and record it as failed

Every step is a real subprocess run of the documented command. For each step it records the exit code, wall time, the
tail of its output, and which outputs/models/<name>/ folders it rewrote (found by manifest timestamps, not by a
hand-kept map).

DEPENDENCIES. Each step names the steps whose outputs it reads (NEEDS). When a step fails, every step that needs it,
directly or through another step, is recorded as BLOCKED and not run: it would otherwise fit on stale or broken inputs
and its result would look current. Steps that do not depend on the failure still run, so one failure never hides the
rest. A step outside this run (--only, --step, --from, or reused by --resume) counts as satisfied: its saved outputs
are used. --keep-going runs blocked steps anyway (the old behaviour).

The data contracts (src/pipeline/contracts.py) are a step of their own right after the data layer, and every model
step needs them: a broken contract blocks the models instead of being found by the tests at the end.

Exit code: 0 when every step that ran passed and the tests passed, 1 otherwise.

NOT run, on purpose: the synthetic generator and raw patches (src/pipeline/build_v1x*, patch_raw_*; CLAUDE.md: do not
re-run casually, and data/raw is frozen), and the interactive labelling tools (review, import_labels, priority).
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / 'outputs' / 'models'
LOG_DIR = ROOT / 'outputs' / 'run_log'
PY = sys.executable

# (group, step name, what it is, command)
STEPS = [
    ('data', 'verify_raw_integrity', 'Frozen raw data still matches its sha256 baseline', ['scripts/verify_raw_integrity.py']),
    ('data', 'build_features', 'RAW -> ML feature layer, with leakage verification', ['-m', 'src.pipeline.build_features']),
    ('data', 'stock_clock', 'Past-only stock-clock table', ['-m', 'src.features.stock_clock']),
    ('data', 'price_grid', 'Past-only price-grid table', ['-m', 'src.features.price_grid']),
    ('data', 'data_contracts', 'Data contracts: the invariants every model relies on, checked as a gate', ['-m', 'src.pipeline.contracts']),
    ('matching', 'matcher_train', 'Model 1: product matcher (REAL)', ['-m', 'src.matching.train']),
    ('matching', 'matcher_ai_review', 'Model 1: AI-proxy check (not tier 1)', ['-m', 'src.matching.ai_review']),
    ('matching', 'matcher_behaviour', 'Model 1: behavioural test, no labels', ['-m', 'src.matching.behaviour']),
    ('matching', 'matcher_v2_train', 'Model 1 v2: difference-aware features + constructed edits', ['-m', 'src.matching.train_v2']),
    ('matching', 'matcher_v2_ai_review', 'Model 1 v2: AI-proxy check (not tier 1)', ['-m', 'src.matching.ai_review', '--model', 'v2']),
    ('audit', 'store_label_audit', 'Does the REAL store label carry information? (REAL)', ['-m', 'src.audit.store_label']),
    ('audit', 'store_label_stamp', 'Store-label status written into the manifests that depend on it', ['-m', 'src.provenance']),
    ('models', 'price_forecast', '2: next-price forecast', ['-m', 'src.models.price_forecast']),
    ('models', 'price_direction', '3: price direction', ['-m', 'src.models.price_direction']),
    ('models', 'stockout_classifier', '4: stock-out classifier', ['-m', 'src.models.stockout_classifier']),
    ('models', 'eta_forecast', '5: ETA forecast', ['-m', 'src.models.eta_forecast']),
    ('models', 'anomaly', '6: anomaly detection (REAL + temporal)', ['-m', 'src.models.anomaly']),
    ('models', 'stockout_survival', '7: stock-out survival', ['-m', 'src.models.stockout_survival']),
    ('models', 'restock_interval', '8: restock interval', ['-m', 'src.models.restock_interval']),
    ('models', 'price_response', '9: competitive price response', ['-m', 'src.models.price_response']),
    ('models', 'assortment_gaps', '10: assortment gaps (REAL)', ['-m', 'src.models.assortment_gaps']),
    ('simulate', 'whatif', '11: what-if simulator', ['-m', 'src.simulate.whatif']),
    ('simulate', 'price_cut', '12a: price cut optimiser', ['-m', 'src.optimize.price_cut']),
    ('simulate', 'restock_priority', '12b: restock priority', ['-m', 'src.optimize.restock_priority']),
    ('simulate', 'store_coverage', '12c: store coverage gaps (REAL)', ['-m', 'src.coverage.store_coverage']),
    ('simulate', 'grid', 'What-if grid (cuts and raises)', ['-m', 'src.simulate.grid']),
    ('simulate', 'promo_frontier', 'Promo vs list price frontier', ['-m', 'src.optimize.promo_frontier']),
    ('simulate', 'restock_lab', 'Restock capacity lab', ['-m', 'src.optimize.restock_lab']),
    ('simulate', 'price_headroom', 'Price-increase headroom', ['-m', 'src.optimize.price_headroom']),
    ('simulate', 'unavailable', 'Outage scenarios', ['-m', 'src.simulate.unavailable']),
    ('simulate', 'store_adds', 'Store adds products', ['-m', 'src.simulate.store_adds']),
    ('simulate', 'restock_objective', 'Lost-wins restock objective', ['-m', 'src.optimize.restock_objective']),
    ('planner', 'collection_planner', 'How much real data would be enough?', ['-m', 'src.planner.collection']),
    ('chain', 'listing_chain', 'One listing through all seven stages', ['-m', 'src.chain.listing', '--demo']),
    ('analyst', 'analyst_question', '13: analyst answers one question', ['-m', 'src.analyst', 'How accurate is the next-price forecast?']),
    ('analyst', 'analyst_refusal', '13: analyst refuses a question the data cannot support', ['-m', 'src.analyst', 'What is Blinkit revenue?']),
    ('analyst', 'analyst_evaluate', '13: analyst evaluation (tuning + held-out)', ['-m', 'src.analyst.evaluate']),
    ('pages', 'build_explorer', 'Listing Chain Explorer page', ['scripts/build_explorer.py']),
    ('pages', 'build_whatif_lab', 'What-If Lab page', ['scripts/build_whatif_lab.py']),
    ('pages', 'build_reality_check', 'Reality Check page', ['scripts/build_reality_check.py']),
    ('pages', 'festive_planner', 'Festive planner: festival calendar and the snapshot listings it calls for', ['-m', 'src.seasonal.festive']),
    ('pages', 'check_claims', 'Headline numbers in the docs match the saved outputs', ['scripts/check_claims.py']),
]

# The steps whose saved outputs each step reads (CLAUDE.md §5 and the module docs). A step not listed needs nothing.
_MODELS = ['price_forecast', 'price_direction', 'stockout_classifier', 'eta_forecast', 'anomaly', 'stockout_survival',
           'restock_interval', 'price_response', 'assortment_gaps']
_EXPERIMENTS = ['grid', 'promo_frontier', 'restock_lab', 'price_headroom', 'unavailable', 'store_adds',
                'restock_objective', 'collection_planner', 'store_coverage', 'listing_chain']
NEEDS = {
    'build_features': ['verify_raw_integrity'],
    'stock_clock': ['build_features'],
    'price_grid': ['build_features'],
    'data_contracts': ['build_features', 'stock_clock', 'price_grid'],
    'matcher_train': ['data_contracts'],
    'matcher_ai_review': ['matcher_train'],
    'matcher_behaviour': ['matcher_train'],
    'matcher_v2_train': ['matcher_train'],
    'matcher_v2_ai_review': ['matcher_v2_train'],
    'store_label_audit': ['data_contracts'],
    'store_label_stamp': ['store_label_audit'],
    **{m: ['data_contracts'] for m in _MODELS},
    'assortment_gaps': ['data_contracts', 'store_label_stamp'],
    'whatif': ['eta_forecast', 'stockout_survival', 'restock_interval', 'price_response'],       # 11 needs 5, 7, 8, 9
    'price_cut': ['whatif'],
    'restock_priority': ['whatif'],
    'store_coverage': ['data_contracts', 'store_label_stamp'],
    'grid': ['whatif'],
    'promo_frontier': ['grid'],
    'restock_lab': ['restock_priority'],
    'price_headroom': ['grid'],
    'unavailable': ['whatif'],
    'store_adds': ['assortment_gaps', 'whatif'],
    'restock_objective': ['restock_priority'],
    'collection_planner': ['data_contracts', 'store_label_audit'],
    'listing_chain': _MODELS + ['grid', 'price_cut', 'restock_priority'],                        # 2-10 + the grid
    'analyst_question': _EXPERIMENTS,
    'analyst_refusal': [],                                                                       # the guard runs before any data
    'analyst_evaluate': _EXPERIMENTS + ['matcher_v2_ai_review', 'store_label_stamp'],
    'build_explorer': ['listing_chain'],
    'build_whatif_lab': ['grid', 'promo_frontier', 'restock_lab', 'price_headroom'],
    'build_reality_check': ['store_label_audit', 'matcher_v2_ai_review', 'collection_planner'],
    'festive_planner': ['verify_raw_integrity'],
}


def check_graph(steps=STEPS, needs=NEEDS) -> list:
    """Problems with the dependency graph: a name that is not a step, or a step that needs one that runs after it."""
    order = {s[1]: i for i, s in enumerate(steps)}
    problems = []
    for step, deps in needs.items():
        if step not in order:
            problems.append(f'{step}: not a step')
            continue
        for d in deps:
            if d not in order:
                problems.append(f'{step} needs {d}: not a step')
            elif order[d] >= order[step]:
                problems.append(f'{step} needs {d}, which runs after it')
    return problems


def manifests() -> dict:
    return {p.parent.name: p.stat().st_mtime for p in MODELS.glob('*/manifest.json')}


def _env() -> dict:
    return {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}


def _command(args) -> str:
    return 'python ' + ' '.join(a if ' ' not in a else f'"{a}"' for a in args)


def run_step(group, name, what, args, timeout=None) -> dict:
    before = manifests()
    t0 = time.time()
    timed_out = False
    try:
        p = subprocess.run([PY, *args], cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace',
                           env=_env(), timeout=timeout)
        code, stdout, stderr = p.returncode, p.stdout or '', p.stderr or ''
    except subprocess.TimeoutExpired as e:                     # the step was stopped: keep what it printed
        timed_out, code = True, None
        stdout = e.stdout.decode('utf-8', 'replace') if isinstance(e.stdout, bytes) else (e.stdout or '')
        stderr = (e.stderr.decode('utf-8', 'replace') if isinstance(e.stderr, bytes) else (e.stderr or '')) + \
            f'\nstopped after the {timeout} s timeout'
    secs = time.time() - t0
    out = stdout + (('\n[stderr]\n' + stderr) if stderr.strip() else '')
    (LOG_DIR / f'{name}.log').write_text(out, encoding='utf-8')
    after = manifests()
    rewrote = sorted(k for k, v in after.items() if before.get(k) != v)
    lines = [ln for ln in out.splitlines() if ln.strip()]
    rec = {'group': group, 'step': name, 'what': what, 'command': _command(args),
           'exit_code': code, 'ok': code == 0, 'seconds': round(secs, 1),
           'outputs_rewritten': rewrote, 'output_lines': len(lines), 'tail': lines[-25:]}
    if timed_out:
        rec['timed_out'] = True
    return rec


def blocked_step(group, name, what, args, by) -> dict:
    msg = f"blocked: needs {', '.join(by)}, which did not pass in this run; not run, so nothing stale looks current"
    (LOG_DIR / f'{name}.log').write_text(msg + '\n', encoding='utf-8')
    return {'group': group, 'step': name, 'what': what, 'command': _command(args), 'exit_code': None, 'ok': False,
            'blocked_by': list(by), 'seconds': 0.0, 'outputs_rewritten': [], 'output_lines': 1, 'tail': [msg]}


def select(a) -> list:
    """The steps this invocation covers, in order."""
    names = [s[1] for s in STEPS]
    picked = STEPS
    if a.only:
        picked = [s for s in picked if s[0] == a.only]
    if a.step:
        want = [n.strip() for n in a.step.split(',') if n.strip()]
        unknown = [n for n in want if n not in names]
        if unknown:
            sys.exit(f'unknown step(s): {", ".join(unknown)}  (python scripts/run_all.py --list)')
        picked = [s for s in picked if s[1] in want]
    if a.from_:
        if a.from_ not in names:
            sys.exit(f'unknown step: {a.from_}  (python scripts/run_all.py --list)')
        start = names.index(a.from_)
        picked = [s for s in picked if names.index(s[1]) >= start]
    return picked


def plan(picked, done, keep_going=False, failed=()) -> list:
    """(step, action, blockers) for each picked step: action is 'reuse', 'run' or 'block'. `failed` seeds steps already
    known to have failed (used by the dry run to show what a failure would block)."""
    bad, out = set(failed), []
    for s in picked:
        name = s[1]
        if name in done:
            out.append((s, 'reuse', []))
            continue
        blockers = [d for d in NEEDS.get(name, []) if d in bad]
        if blockers and not keep_going:
            bad.add(name)
            out.append((s, 'block', blockers))
        else:
            out.append((s, 'run', []))
    return out


def run_tests() -> dict:
    xml = LOG_DIR / 'pytest.xml'
    t0 = time.time()
    p = subprocess.run([PY, '-m', 'pytest', '-q', f'--junitxml={xml}'], cwd=ROOT, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    import xml.etree.ElementTree as ET
    cases = []
    if xml.exists():
        for tc in ET.parse(xml).getroot().iter('testcase'):
            state = 'failed' if tc.find('failure') is not None or tc.find('error') is not None else \
                    'skipped' if tc.find('skipped') is not None else 'passed'
            cases.append({'file': tc.get('classname', '').split('.')[-1], 'name': tc.get('name'), 'state': state,
                          'seconds': float(tc.get('time') or 0)})
    return {'exit_code': p.returncode, 'seconds': round(time.time() - t0, 1),
            'summary': [ln for ln in p.stdout.splitlines() if ln.strip()][-1:], 'cases': cases}


def list_steps():
    width = max(len(s[1]) for s in STEPS)
    for i, (g, n, w, _) in enumerate(STEPS, 1):
        needs = ', '.join(NEEDS.get(n, [])) or '-'
        print(f'{i:02d}  {g:<9} {n:<{width}}  needs: {needs}')


def keep_awake(on: bool) -> bool:
    """Windows: ask the system not to go to sleep while a run is going, and give the request back afterwards. Sleep
    kills console processes: on 2026-10-22 at 01:42 an idle laptop went to sleep and took step 34 of 42 with it.
    This is the request a media player or a download makes (SetThreadExecutionState); no setting is changed, and the
    system drops it anyway when the process ends. The screen may still turn off."""
    if sys.platform != 'win32':
        return False
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0)
        return bool(ctypes.windll.kernel32.SetThreadExecutionState(flags))
    except Exception:                                   # not a reason to stop a run
        return False


def merged(results: list, base: list) -> list:
    """The run record: this invocation's steps, and for every other step what the earlier record says, in pipeline
    order. A run of one step (--step, --only, --from) or a --resume updates the record; it never replaces it."""
    got, old = {r['step']: r for r in results}, {r['step']: r for r in base}
    return [got.get(n) or old[n] for _, n, _, _ in STEPS if n in got or n in old]


def summary(results: list):
    ran = [r for r in results if not r.get('resumed_from_earlier_run') and not r.get('blocked_by')]
    slow = sorted(ran, key=lambda r: -r['seconds'])[:5]
    if slow:
        print('slowest: ' + ', '.join(f"{r['step']} {r['seconds']:.0f}s" for r in slow))
    for label, rows in (('FAILED', [r for r in ran if not r['ok']]), ('BLOCKED', [r for r in results if r.get('blocked_by')])):
        if rows:
            print(f'{label}: ' + ', '.join(r['step'] + (f" (needs {', '.join(r['blocked_by'])})" if r.get('blocked_by') else '')
                                           for r in rows))


def main():
    ap = argparse.ArgumentParser(description='Run the whole project in dependency order and record what happened.')
    ap.add_argument('--only', help='run one group: ' + ', '.join(sorted({s[0] for s in STEPS})))
    ap.add_argument('--step', help='run these steps only (comma-separated names, see --list)')
    ap.add_argument('--from', dest='from_', metavar='STEP', help='run this step and every step after it')
    ap.add_argument('--no-tests', action='store_true')
    ap.add_argument('--resume', action='store_true', help='reuse steps already recorded OK in run_all.json')
    ap.add_argument('--keep-going', action='store_true', help='run steps even when a step they need failed')
    ap.add_argument('--timeout', type=float, default=None, help='seconds before any one step is stopped and failed')
    ap.add_argument('--list', action='store_true', help='list the steps and their dependencies, then exit')
    ap.add_argument('--dry-run', action='store_true', help='show what would run, be reused or be blocked, then exit')
    a = ap.parse_args()
    problems = check_graph()
    if problems:
        sys.exit('the dependency graph is broken:\n  ' + '\n  '.join(problems))
    if a.list:
        list_steps()
        return 0
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    done, base, prev_tests = {}, [], None
    partial = bool(a.only or a.step or a.from_)
    if (a.resume or partial) and (LOG_DIR / 'run_all.json').exists():
        prev = json.loads((LOG_DIR / 'run_all.json').read_text(encoding='utf-8'))
        started, base, prev_tests = datetime.fromisoformat(prev['started_utc']), prev['steps'], prev.get('tests')
        if a.resume:
            done = {r['step']: r for r in prev['steps'] if r['ok']}
    picked = select(a)
    if a.dry_run:
        for (g, n, w, _), action, by in plan(picked, done, a.keep_going):
            print(f"{action.upper():<6} {n:<22} {w}" + (f"   (needs {', '.join(by)})" if by else ''))
        return 0
    if keep_awake(True):
        print('keeping this computer awake until the run ends (the screen may still turn off)', flush=True)
    try:
        return _run(a, picked, done, base, started, partial, prev_tests)
    finally:
        keep_awake(False)


def _run(a, picked, done, base, started, partial, prev_tests) -> int:
    results, bad = [], set()
    for s in picked:
        name = s[1]
        if name in done:
            results.append({**done[name], 'resumed_from_earlier_run': True})
            print(f'[{len(results):02d}] {name:<22} OK (recorded earlier)', flush=True)
            continue
        blockers = [d for d in NEEDS.get(name, []) if d in bad]
        if blockers and not a.keep_going:
            bad.add(name)
            results.append(blocked_step(*s, by=blockers))
            print(f"[{len(results):02d}] {name:<22} BLOCKED (needs {', '.join(blockers)})", flush=True)
        else:
            print(f'[{len(results) + 1:02d}] {name:<22}', end=' ', flush=True)
            r = run_step(*s, timeout=a.timeout)
            results.append(r)
            if not r['ok']:
                bad.add(name)
            state = 'OK  ' if r['ok'] else ('TIME' if r.get('timed_out') else 'FAIL')
            print(state + f" {r['seconds']:>7.1f}s  {', '.join(r['outputs_rewritten'])}", flush=True)
        (LOG_DIR / 'run_all.json').write_text(json.dumps({'started_utc': started.isoformat(timespec='seconds'),
                                                          'python': sys.version.split()[0], 'steps': merged(results, base),
                                                          'finished': False}, indent=1), encoding='utf-8')
    tests = None if a.no_tests else run_tests()
    if tests:
        print('TESTS', tests['summary'])
    steps = merged(results, base)
    doc = {'started_utc': started.isoformat(timespec='seconds'), 'resumed': bool(done) or partial,
           'finished_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
           'python': sys.version.split()[0], 'platform': sys.platform, 'steps': steps,
           'tests': tests if tests is not None else prev_tests,   # --no-tests keeps the last suite's result
           'finished': True}
    (LOG_DIR / 'run_all.json').write_text(json.dumps(doc, indent=1), encoding='utf-8')
    print(f"{sum(r['ok'] for r in steps)}/{len(steps)} steps OK -> {LOG_DIR / 'run_all.json'}"
          + (f" ({sum(not r.get('resumed_from_earlier_run') for r in results)} run in this invocation)" if partial or done else ''))
    summary(results)
    if not partial:
        doc['after_run'] = finalize()
        (LOG_DIR / 'run_all.json').write_text(json.dumps(doc, indent=1), encoding='utf-8')
    ok = all(r['ok'] for r in steps) and (tests is None or tests['exit_code'] == 0) and \
        all(r['ok'] for r in doc.get('after_run', []))
    return 0 if ok else 1


# Pages that show the run itself (its steps and test results) can only be built once the run log is complete.
AFTER_RUN = [('build_run_page', 'Run Log page', ['scripts/build_run_page.py']),
             ('build_site', 'The website (all pages, analyst included)', ['scripts/build_site.py']),
             ('check_site', 'Every page and control of the website runs', ['scripts/check_site.py'])]


def finalize() -> list:
    out = []
    for name, what, args in AFTER_RUN:
        t0 = time.time()
        p = subprocess.run([PY, *args], cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace', env=_env())
        text = (p.stdout or '') + (('\n[stderr]\n' + p.stderr) if p.stderr.strip() else '')
        (LOG_DIR / f'{name}.log').write_text(text, encoding='utf-8')
        lines = [ln for ln in text.splitlines() if ln.strip()]
        out.append({'step': name, 'what': what, 'ok': p.returncode == 0, 'seconds': round(time.time() - t0, 1), 'tail': lines[-6:]})
        print(f"[after] {name:<22} {'OK  ' if p.returncode == 0 else 'FAIL'} {out[-1]['seconds']:>7.1f}s", flush=True)
    return out


if __name__ == '__main__':
    sys.exit(main())
