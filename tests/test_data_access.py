"""Phase 2 data access layer: splits, live schema roles, provenance filters, feature guard."""
import shutil

import pandas as pd
import pytest

from conftest import ml_path
import src.load as L


@pytest.fixture(scope='module')
def ml():
    ml_path('Blinkit')      # skip if not built
    return L.load_ml()


def test_load_ml_platform_and_targets(ml):
    b = L.load_ml('Blinkit')
    assert set(b.platform.astype(str)) == {'Blinkit'}
    assert len(ml) == 610_789 and ml.observation_key.is_unique
    for t in L.target_columns():
        assert t in ml.columns


def test_splits_are_correct_and_chronological(ml):
    tr, va, te, ho = L.splits(ml, 'future_price', include_holdout=True)
    for name, part in zip(L.SPLITS, (tr, va, te, ho)):
        assert set(part.split.astype(str)) <= {name}
        ts = pd.to_datetime(part.observed_at.astype(str), format='mixed')
        assert ts.is_monotonic_increasing, f"{name} not chronological"
    assert tr.future_price.notna().all() and te.future_price.notna().all()
    assert tr.snapshot_date.max() < va.snapshot_date.min() <= va.snapshot_date.max() < te.snapshot_date.min()
    assert len(ho) == 21_949 and ho.data_status.eq('REAL').all()
    want = ml[ml.split == 'train'].future_price.notna().sum()
    assert len(tr) == want
    with pytest.raises(ValueError):
        L.get_split('validation', ml)


def test_roles_come_from_schema_file(tmp_path, monkeypatch):
    src = pd.read_excel(L.SCHEMA_PATH, sheet_name=None)
    s = src['SCHEMA_FROZEN']
    extra = pd.DataFrame([{'column': 'brand_new_id', 'dtype': 'str', 'null_count': 0, 'null_pct': 0,
                           'role': 'IDENTIFIER — do not feed to model'},
                          {'column': 'brand_new_feat', 'dtype': 'float', 'null_count': 0, 'null_pct': 0,
                           'role': 'past-only feature'}])
    src['SCHEMA_FROZEN'] = pd.concat([s, extra], ignore_index=True)
    p = tmp_path / 'schema.xlsx'
    with pd.ExcelWriter(p) as w:
        for k, v in src.items():
            v.to_excel(w, sheet_name=k, index=False)
    monkeypatch.setattr(L, 'SCHEMA_PATH', p)
    assert 'brand_new_id' in L.identifier_columns()
    assert 'brand_new_feat' in L.past_only_columns() and 'brand_new_feat' in L.feature_role_columns()
    with pytest.raises(L.FeatureSetError):
        L.check_feature_set(['brand_new_id'])


def test_feature_guard_refuses_ids_and_targets(ml):
    for bad in (['price_lag_1', 'store_id'], ['price_lag_1', 'future_price'], ['observation_key']):
        with pytest.raises(L.FeatureSetError):
            L.check_feature_set(bad)
        with pytest.raises(L.FeatureSetError):
            L.select_features(ml.head(5), [c for c in bad if c in ml.columns])
    feats = L.feature_columns(ml.head(1000))
    assert feats and not set(feats) & (set(L.identifier_columns()) | set(L.target_columns()))
    assert set(L.feature_columns(past_only=True)) == set(L.past_only_columns())


def test_provenance_filters(ml):
    assert L.real_only(ml).data_status.eq('REAL').all() and len(L.real_only(ml)) == 21_949
    assert L.synthetic_only(ml).data_status.eq('SYNTHETIC').all()
    pref = L.preferred_only(ml)
    assert pref.is_preferred_listing.eq(1).all() and len(ml) - len(pref) == 339


def test_load_real_reads_exactly_the_real_rows():
    """The filtered reader the analyst uses gives the same rows and columns as real_only(load_raw())."""
    fast, full = L.load_real(), L.real_only(L.load_raw()).reset_index(drop=True)
    assert len(fast) == 21_949 and fast.data_status.eq("REAL").all()
    pd.testing.assert_frame_equal(fast, full)
