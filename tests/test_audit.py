"""The store-label audit (REAL): its statistics, its saved verdict and its positive controls."""
import json

import numpy as np
import pytest

from src.audit import store_label as A
from src.model_output import MODELS_DIR


def test_statistics_on_a_toy_table():
    store = np.array([0, 0, 1, 1])
    assert A.eta_squared(np.array([1.0, 1.0, 3.0, 3.0]), store, 2) == pytest.approx(1.0)   # all variance between stores
    assert A.eta_squared(np.array([1.0, 3.0, 1.0, 3.0]), store, 2) == pytest.approx(0.0)   # none
    # two keys with two records each: one key split across stores, one inside a store -> 1 of 2 pairs
    assert A.same_store_pair_share(np.array([0, 0, 1, 1]), np.array([0, 1, 1, 1]), 2, 2) == 0.5
    assert A.chi_square(np.array([0, 0, 1, 1]), store, 2, 2) == pytest.approx(4.0)
    assert A.store_changes(np.array([0, 0, 1, 0])) == 2
    s = A._summary(5.0, np.array([1.0, 2.0, 3.0, 4.0]), 'upper')
    assert s['p_permutation'] == pytest.approx(1 / 5)


def _load(name):
    p = MODELS_DIR / name / 'metrics.json'
    if not p.exists():
        pytest.skip(f'{name} has not been run')
    return (json.loads(p.read_text(encoding='utf-8')),
            json.loads((p.parent / 'manifest.json').read_text(encoding='utf-8')))


def test_store_label_audit_result_and_scope():
    m, man = _load('real_store_label_audit')
    assert man['claim_scope'].startswith('REAL-ONLY') and man['raw_hashes_match_verified_baseline'] is True
    assert m['rows'] == 21_949 and len(m['stores']) == 8
    v = m['verdict']
    assert v['departures_after_bonferroni'] == []                       # the documented result; a change needs a look
    pair = m['permutation_tests']['same_key_pairs_in_same_store_share']
    assert 0.9 < pair['observed_over_null_mean'] < 1.1                  # at the random-label rate, nowhere near 0
    assert 'collect' in v['what_it_does_not_show']                      # never a claim about how the source was made
    stock = m['record_level_anatomy']['stock']
    assert stock['lift_over_rate'] > 3 and stock['null_shuffled_within_category']['p_permutation'] < 0.01


def test_store_label_audit_can_see_a_store_effect():
    """A null result only means something if the test detects an effect that exists."""
    m, _ = _load('real_store_label_audit')
    power = {r['planted_eta_shift_minutes']: r['detected_share_at_5pct'] for r in m['positive_control_planted_eta_shift']}
    assert power[0.5] >= 0.99 and power[0.2] >= 0.8
    c, man = _load('real_store_label_audit_synthetic_control')
    assert man['claim_scope'].startswith('SYNTHETIC-DERIVED')
    assert c['permutation_tests']['eta2_eta_minutes']['p_permutation'] < 0.01
    assert c['eta2_eta_minutes_by_snapshot']['min'] > 100 * c['real_value_for_comparison']
