"""scripts/run_all.py: the dependency graph is sound, a failure blocks exactly what depends on it, and a step that hangs
is stopped and recorded. Nothing here runs a pipeline step: the planner is pure and the timeout probe is a tiny script."""
import importlib.util
import json
import sys
from argparse import Namespace

import pytest

from conftest import ROOT


@pytest.fixture(scope='module')
def R():
    spec = importlib.util.spec_from_file_location('run_all', ROOT / 'scripts' / 'run_all.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ancestors(R, name, seen=None):
    seen = set() if seen is None else seen
    for d in R.NEEDS.get(name, []):
        if d not in seen:
            seen.add(d)
            _ancestors(R, d, seen)
    return seen


def test_the_graph_names_real_steps_in_a_runnable_order(R):
    assert R.check_graph() == []
    names = [s[1] for s in R.STEPS]
    assert len(names) == len(set(names))
    assert all(len(s) == 4 for s in R.STEPS)                 # build_run_page.py unpacks (group, name, what, args)


def test_a_broken_graph_is_reported(R):
    steps = [('g', 'a', '', []), ('g', 'b', '', [])]
    assert R.check_graph(steps, {'a': ['b']}) == ['a needs b, which runs after it']
    assert R.check_graph(steps, {'b': ['zzz']}) == ['b needs zzz: not a step']


def test_every_model_sits_behind_the_data_contracts(R):
    gated = [s[1] for s in R.STEPS if s[0] in ('matching', 'audit', 'models', 'simulate', 'chain')]
    assert gated and all('data_contracts' in _ancestors(R, n) for n in gated)
    assert R.NEEDS['data_contracts'] == ['build_features', 'stock_clock', 'price_grid']


def test_a_failure_blocks_its_descendants_and_nothing_else(R):
    p = {s[1]: (action, by) for s, action, by in R.plan(R.STEPS, {}, failed=['eta_forecast'])}
    blocked = {n for n, (action, _) in p.items() if action == 'block'}
    assert blocked == {n for n in p if 'eta_forecast' in _ancestors(R, n)}
    assert {'whatif', 'listing_chain', 'analyst_evaluate'} <= blocked
    assert p['whatif'][1] == ['eta_forecast'] and p['price_cut'][1] == ['whatif']        # the direct blocker is named
    assert p['price_forecast'][0] == 'run' and p['anomaly'][0] == 'run' and p['check_claims'][0] == 'run'


def test_reused_and_keep_going_steps_are_not_blocked(R):
    p = R.plan(R.STEPS, {'whatif': {}}, failed=['eta_forecast'])
    action = {s[1]: a for s, a, _ in p}
    assert action['whatif'] == 'reuse' and action['grid'] == 'run'      # its saved outputs stand in for it
    assert all(a != 'block' for _, a, _ in R.plan(R.STEPS, {}, keep_going=True, failed=['data_contracts']))


def test_selection_by_group_step_and_start(R):
    sel = lambda **k: [s[1] for s in R.select(Namespace(**{'only': None, 'step': None, 'from_': None, **k}))]
    assert sel(only='matching')[0] == 'matcher_train'
    assert sel(step='grid,anomaly') == ['anomaly', 'grid']                # always in pipeline order
    assert sel(from_='check_claims') == ['check_claims']
    with pytest.raises(SystemExit):
        sel(step='nope')


def test_a_hanging_step_is_stopped_and_recorded(R, tmp_path, monkeypatch):
    monkeypatch.setattr(R, 'LOG_DIR', tmp_path)
    monkeypatch.setattr(R, 'MODELS', tmp_path / 'none')
    rec = R.run_step('g', 'probe', 'sleeps', ['-c', 'import time; print("started", flush=True); time.sleep(30)'], timeout=1)
    assert rec['ok'] is False and rec.get('timed_out') is True and rec['exit_code'] is None
    assert rec['seconds'] < 25 and 'timeout' in (tmp_path / 'probe.log').read_text(encoding='utf-8')
    ok = R.run_step('g', 'quick', 'prints', ['-c', 'print("hi")'], timeout=30)
    assert ok['ok'] and ok['tail'] == ['hi'] and 'timed_out' not in ok


def test_a_blocked_record_has_what_the_pages_read(R, tmp_path, monkeypatch):
    monkeypatch.setattr(R, 'LOG_DIR', tmp_path)
    rec = R.blocked_step('g', 'x', 'what', ['-m', 'mod'], by=['data_contracts'])
    for key in ('group', 'step', 'what', 'command', 'ok', 'seconds', 'outputs_rewritten', 'tail'):
        assert key in rec
    assert rec['ok'] is False and rec['blocked_by'] == ['data_contracts']
    json.dumps(rec)
