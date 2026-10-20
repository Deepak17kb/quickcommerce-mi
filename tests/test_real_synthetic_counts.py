"""
Real vs synthetic row counts per platform, from the raw layer.

Expected values are the documented composition (README.md, CLAUDE.md §2).
Only Blinkit has REAL rows: one observed snapshot, 2026-07-10.
"""
import pandas as pd
import pytest

from conftest import PLATFORMS, raw_path

EXPECTED = {
    'Blinkit':         {'REAL': 21_949, 'SYNTHETIC': 148_740},
    'Instamart':       {'REAL': 0,      'SYNTHETIC': 150_480},
    'FlipkartMinutes': {'REAL': 0,      'SYNTHETIC': 142_320},
    'BigBasket':       {'REAL': 0,      'SYNTHETIC': 147_300},
}


@pytest.mark.parametrize('platform', PLATFORMS)
def test_real_synthetic_counts(platform):
    d = pd.read_parquet(raw_path(platform),
                        columns=['data_status', 'is_real_observation', 'snapshot_date'])
    status = d.data_status.astype(str)
    want = EXPECTED[platform]

    assert set(status.unique()) <= {'REAL', 'SYNTHETIC'}, f"unknown labels: {set(status.unique())}"
    counts = status.value_counts().to_dict()
    assert counts.get('REAL', 0) == want['REAL'], counts
    assert counts.get('SYNTHETIC', 0) == want['SYNTHETIC'], counts
    assert len(d) == want['REAL'] + want['SYNTHETIC'], "labels don't sum to the platform total"

    # the two provenance flags must agree row by row
    assert (d.is_real_observation.astype(int).eq(1) == status.eq('REAL')).all()

    if want['REAL']:
        assert set(d.loc[status.eq('REAL'), 'snapshot_date'].astype(str)) == {'2026-07-10'}


def test_total_rows():
    assert sum(sum(v.values()) for v in EXPECTED.values()) == 610_789
