"""Headline numbers in the docs must match the saved outputs they came from (scripts/check_claims.py)."""
import importlib.util

import pytest

from conftest import ROOT


def _module():
    spec = importlib.util.spec_from_file_location('check_claims', ROOT / 'scripts' / 'check_claims.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_rounding_rule():
    c = _module()
    assert c.check_number('9.66', {'a': 9.6609}, ['a'], 1)['ok']
    assert not c.check_number('9.66', {'a': 9.67}, ['a'], 1)['ok']
    assert c.check_number('78', {'a': 0.77858}, ['a'], 100)['ok']            # a share quoted as a percentage
    assert c.check_number('4', {'a': 0.0755, 'n': 53}, lambda m: m['a'] * m['n'], 1)['ok']


def test_no_registered_claim_is_stale():
    rows = _module().ledger()
    built = [r for r in rows if r['status'] != 'not_built']
    if not built:
        pytest.skip('no outputs built')
    bad = [(r['status'], r['doc'], r['quote'][:70], [n for n in r['numbers'] if not n['ok']])
           for r in built if r['status'] != 'ok']
    assert not bad, bad
