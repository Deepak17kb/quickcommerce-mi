"""
Cross-platform join regression check (CLAUDE.md §6).

Flipkart Minutes is generated at -6% positioning. If the cross-platform join breaks, these values drift.

HISTORY OF THE EXPECTED VALUES (cheapest-of-4 share, %, ties count for every tied platform: rank 'min')
  v14   68.6 / 29.3 / 21.4 / 18.9   psychological Rs 10 / Rs 50 steps -> 27.9% of panel snapshots have a tied minimum
  v15.0 58.6 / 20.3 / 13.8 / 13.5   Rs 1 rounding -> 5.7% tied; follower moves coupled to Blinkit
  v15.1 56.6 / 24.6 / 18.0 / 17.5   REAL-calibrated price endings (one style per panel: x9, x0, x5, x99, x49/x99,
                                    x50/x00 or Rs 1) -> 14.0% tied (current)
  The shares sum to more than 100% because every platform at a tied minimum counts as cheapest; the tie rate is
  set by the price grid, so any change to rounding moves these values even when positioning is unchanged.
  Positioning is unchanged across all three: Flipkart's median gap vs competitors is -5.35 / -5.49 / -5.34%.
"""
import pandas as pd
import pytest

from conftest import PLATFORMS, ml_path

EXPECTED = {   # platform: (cheapest-of-4 share %, median gap vs competitor avg %)   — v15.1
    'Flipkart Minutes': (56.64, -5.343),
    'Swiggy Instamart': (24.59, 0.368),
    'BigBasket':        (17.96, 2.267),
    'Blinkit':          (17.54, 2.951),
}


@pytest.fixture(scope='module')
def table():
    cols = ['platform', 'platform_count_for_sku', 'is_cheapest', 'price_gap_vs_avg_pct']
    d = pd.concat([pd.read_parquet(ml_path(p), columns=cols) for p in PLATFORMS], ignore_index=True)
    four = d[d.platform_count_for_sku == 4]
    t = four.groupby('platform', observed=True).agg(cheapest=('is_cheapest', 'mean'),
                                                    gap=('price_gap_vs_avg_pct', 'median'))
    t['cheapest'] = t.cheapest * 100
    return t


@pytest.mark.parametrize('platform', list(EXPECTED))
def test_cheapest_of_four(table, platform):
    cheapest, gap = EXPECTED[platform]
    assert table.loc[platform, 'cheapest'] == pytest.approx(cheapest, abs=0.15)
    assert table.loc[platform, 'gap'] == pytest.approx(gap, abs=0.05)


def test_ordering(table):
    assert list(table.sort_values('cheapest', ascending=False).index[:2]) == ['Flipkart Minutes', 'Swiggy Instamart']
