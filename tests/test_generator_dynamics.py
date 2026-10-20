"""
The v15.1 generator planted learnable structure in the SYNTHETIC rows and calibrated two parts of it to the
REAL Blinkit snapshot (docs/GENERATOR_v15_PARAMETERS.md). These tests read data/raw directly.

Passing proves the DATA carries the structure models 2-9 are meant to learn, and that the calibrated parts
match the real snapshot. It is not a market finding.
"""
import numpy as np
import pandas as pd
import pytest

from conftest import PLATFORMS, raw_path
from src.diagnostics import completed_oos_spells, last_digit_distance, run_length_hazard, stock_matrix
from src.pipeline.build_v15_dynamics import GROUP_OF, PARAMS, REAL_CATEGORY_OOS_TARGET_PCT, SOURCE

PANEL = ['platform', 'store_id', 'product_id']
COLS = PANEL + ['observed_at', 'snapshot_id', 'hour', 'category', 'canonical_product_key', 'in_common_panel',
                'selling_price', 'discount_percent', 'in_stock', 'delivery_eta_min', 'data_status', 'source']


@pytest.fixture(scope='module')
def allrows():
    d = pd.concat([pd.read_parquet(raw_path(p), columns=COLS) for p in PLATFORMS], ignore_index=True)
    for c in PANEL + ['category', 'canonical_product_key', 'snapshot_id']:
        d[c] = d[c].astype(str)
    return d


@pytest.fixture(scope='module')
def syn(allrows):
    return allrows[allrows.data_status == 'SYNTHETIC'].sort_values(PANEL + ['observed_at']).reset_index(drop=True)


@pytest.fixture(scope='module')
def real(allrows):
    return allrows[allrows.data_status == 'REAL']


@pytest.fixture(scope='module')
def ins(syn):
    return stock_matrix(syn)


def test_all_synthetic_rows_are_current_generator(syn):
    assert syn.source.eq(SOURCE).all()


# ------------------------------------------------------------------ the estimator itself
def test_hazard_estimator_is_unbiased_without_duration_dependence():
    """Check 1 (2026-09-17): on memoryless stock the corrected estimator must return ~1.0.
    The naive estimator's left-censoring bias is what hid the planted effect (2.4 vs 13.1)."""
    rng = np.random.default_rng(0)
    ratios = []
    for _ in range(3):
        m = (rng.random((9814, 60)) >= 0.089).astype(int)
        h, at_risk = run_length_hazard(m)
        assert at_risk.min() > 1_000
        ratios.append(h[9] / h[0])
    assert 0.9 <= np.mean(ratios) <= 1.1, ratios


# ------------------------------------------------------------------ A. duration-dependent hazard
def test_hazard_rises_with_run_length(ins):
    h, _ = run_length_hazard(ins, exclude_left_censored=True)
    rho = pd.Series(h).corr(pd.Series(range(1, 11)), method='spearman')
    assert rho >= 0.9, f"hazard does not rise monotonically with time in stock: {np.round(h, 4)}"
    assert h[9] / h[0] >= 5, f"corrected hazard ratio run10/run1 = {h[9] / h[0]:.2f}"


# ------------------------------------------------------------------ B. restock spread
def test_restock_duration_has_real_variance(syn, ins):
    lengths, rows = completed_oos_spells(ins)
    assert len(lengths) > 10_000
    assert (lengths == 1).mean() < 0.60, f"single-snapshot restocks {(lengths == 1).mean():.3f}"
    assert lengths.std() >= 1.0, f"restock duration std {lengths.std():.2f}"
    group = syn.groupby(PANEL, sort=False).category.first().map(GROUP_OF).fillna('MEDIUM').to_numpy()
    by_group = pd.Series(lengths).groupby(group[rows]).mean()
    assert by_group['FAST'] < by_group['MEDIUM'] < by_group['SLOW'], by_group.to_dict()


# ------------------------------------------------------------------ calibration to REAL (v15.1)
def test_stockout_level_calibrated_to_real(syn, real):
    real_rate = 1 - real.in_stock.mean()
    bl = 1 - syn[syn.platform == 'Blinkit'].groupby('category').in_stock.mean()
    w = real.groupby('category').size().reindex(bl.index).fillna(0)
    reweighted = (bl * w).sum() / w.sum()
    assert abs(reweighted - real_rate) <= 0.005, f"Blinkit synthetic at real mix {reweighted:.4f} vs REAL {real_rate:.4f}"
    target = pd.Series(REAL_CATEGORY_OOS_TARGET_PCT).reindex(bl.index) / 100
    assert bl.corr(target) >= 0.9 and (bl - target).abs().mean() <= 0.01
    plat = 1 - syn.groupby('platform').in_stock.mean()
    assert plat['BigBasket'] < plat['Blinkit'] < plat['Swiggy Instamart'] < plat['Flipkart Minutes'], plat.to_dict()


def test_price_endings_match_real(syn, real):
    ld = last_digit_distance(syn.selling_price, real.selling_price)
    real_059 = last_digit_distance(real.selling_price, real.selling_price)['share_end_0_5_9_pct']
    assert ld['integer_share'] == 1.0, "synthetic prices must be whole rupees like the real ones"
    assert ld['ALL'] <= 15, f"last-digit distance to REAL {ld['ALL']}"
    assert abs(ld['share_end_0_5_9_pct'] - real_059) <= 12, (ld['share_end_0_5_9_pct'], real_059)


# ------------------------------------------------------------------ C. price response
@pytest.mark.parametrize('follower', list(PARAMS['price']['followers']))
def test_competitor_price_response_recovered(syn, follower):
    """Range is around the EXPECTED MEASURED coefficient, not the planted one: v15.1 snaps prices to
    real-style grids (Rs 10 / 50 / 100 steps), which attenuates the measured coefficient to ~0.5x planted.
    See 'Rounding attenuation' in docs/GENERATOR_v15_PARAMETERS.md."""
    cfg = PARAMS['price']['followers'][follower]
    expected, lag = PARAMS['price']['expected_measured_beta'][follower], cfg['lag']
    c = syn[syn.in_common_panel == 1]
    x = np.log(c.selling_price) - np.log(c.groupby(PANEL).selling_price.transform('mean'))
    pv = c.assign(x=x).pivot_table(index='canonical_product_key', columns=['platform', 'observed_at'], values='x')
    lead, fol = pv[PARAMS['price']['leader']].to_numpy(), pv[follower].to_numpy()
    y = fol[:, lag:].ravel()
    X = np.c_[np.ones_like(y), fol[:, lag - 1:-1].ravel(), lead[:, :-lag].ravel()]
    b = np.linalg.lstsq(X, y, rcond=None)[0][2]
    assert b > 0.08, f"{follower}: no response to leader (beta_hat {b:.3f})"
    assert 0.7 * expected <= b <= 1.3 * expected, f"{follower}: beta_hat {b:.3f} outside {expected} +/- 30%"
    assert b < cfg['beta'], "measured coefficient should be attenuated below the planted one"


# ------------------------------------------------------------------ D. ETA
def test_eta_rises_with_demand_pressure(syn):
    grp = syn.groupby(['platform', 'hour']).delivery_eta_min.transform('mean')
    resid = syn.delivery_eta_min - grp
    store_oos = 1 - syn.groupby(['store_id', 'snapshot_id']).in_stock.transform('mean')
    assert resid.corr(store_oos) >= 0.2, f"ETA vs store OOS share corr {resid.corr(store_oos):.3f}"
    assert resid.corr(syn.discount_percent.astype(float)) >= 0.05
    peak = syn.groupby('hour').delivery_eta_min.mean()
    assert peak[18] - peak[9] >= 2.0
    store_sd = syn.groupby(['platform', 'store_id']).delivery_eta_min.mean().groupby(level=0).std().mean()
    assert store_sd >= 0.5, f"stores barely differ: {store_sd:.2f} min"
