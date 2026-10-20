"""The collection planner: its estimators on a toy panel and the structure of its saved result."""
import json

import numpy as np
import pytest

from src.model_output import MODELS_DIR
from src.planner import collection as C


def _toy(T=8, K=3):
    """Four platforms; Flipkart Minutes is 10% cheaper everywhere; evening ETA is 3 minutes longer."""
    P = np.full((4, K, T), 100.0)
    P[C.FKM] = 90.0
    S = np.ones((4, K, T))
    S[C.BLK, 0, :2] = 0                                            # one Blinkit listing out for the first two snapshots
    evening = np.arange(T) % 2 == 1
    E = np.full((4, K, T), 10.0) + 3.0 * evening
    return P, S, E, evening


def test_estimators_on_a_toy_panel():
    P, S, E, evening = _toy()
    e = C.estimate(P, S, E, evening, True)
    assert e['price_gap'] == pytest.approx(-10.0)
    assert e['cheapest_share'] == pytest.approx(100.0)
    assert e['oos_rate'] == pytest.approx(100 * 2 / 24)
    assert e['evening_eta'] == pytest.approx(3.0)
    once = C.estimate(P[:, :, ~evening], S[:, :, ~evening], E[:, :, ~evening], evening[~evening], False)
    assert once['price_gap'] == pytest.approx(-10.0)
    assert all(np.isnan(once[q]) for q in ('restock_mean', 'hazard_ratio', 'response_beta', 'evening_eta'))
    P[C.BLK] = 90.0                                                # a tie counts for every tied platform
    assert C.estimate(P, S, E, evening, True)['cheapest_share'] == pytest.approx(100.0)


def test_every_quantity_has_a_tolerance_and_a_transfer_note():
    for q, (tol, unit, needs_both, planted, transfer) in C.QUANTITIES.items():
        assert tol > 0 and unit and isinstance(needs_both, bool) and len(transfer) > 20
    assert C.WATCHLIST_SKUS in C.SKUS


def test_saved_plan_is_labelled_and_consistent():
    p = MODELS_DIR / C.NAME / 'metrics.json'
    if not p.exists():
        pytest.skip('collection planner has not been run')
    m = json.loads(p.read_text(encoding='utf-8'))
    man = json.loads((p.parent / 'manifest.json').read_text(encoding='utf-8'))
    assert man['claim_scope'].startswith('SYNTHETIC-DERIVED') and 'planning prior' in m['NOTE']
    q = m['quantities']
    assert abs(q['price_gap']['full_panel_value'] - (-5.34)) < 0.1            # the regression value (CLAUDE.md §6)
    assert abs(q['cheapest_share']['full_panel_value'] - 56.6) < 0.5
    # one snapshot a day cannot estimate anything that needs both, whatever the size
    for name in ('restock_mean', 'hazard_ratio', 'response_beta', 'evening_eta'):
        assert q[name]['needs_both_daily_snapshots'] and not q[name]['identified_once_a_day']
    # a short window sees only short spells: the bias is negative and shrinks as the window grows
    bias = {int(k): v for k, v in m['bias_from_a_short_window_at_1000_products']['restock_mean'].items() if v is not None}
    assert bias[2] < bias[7] < bias[21] < 0.05 and bias[2] < -0.5
    # products limit the price gap, days limit the evening ETA
    gap = q['price_gap']['precision_with_the_watchlist_90pct_half_width']
    eta = q['evening_eta']['precision_with_the_watchlist_90pct_half_width']
    assert gap['30'] > 0.5 * gap['2'] and eta['30'] < 0.25 * eta['2']
    cl = m['same_product_stock_clustering']
    if cl['REAL_across_records_of_one_name_pack']:
        assert cl['REAL_across_records_of_one_name_pack']['lift_over_rate'] > 3 * cl['SYNTHETIC_across_platforms']['lift_over_rate']
