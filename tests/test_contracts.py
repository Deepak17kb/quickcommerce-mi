"""The data contracts (src/pipeline/contracts.py) hold on the shipped data, and each one catches a violation planted in
a copy of it. A gate that never fails proves nothing, so every contract has a negative control here. The planted
copies are Blinkit only, to keep memory down; the contracts that count the whole dataset are checked on all of it."""
import numpy as np
import pandas as pd
import pytest

from conftest import ROOT, ml_path
from src.pipeline import contracts as C


@pytest.fixture(scope='module')
def blinkit():
    ml_path('Blinkit')                                       # skips when the ML layer is not built
    import src.load as L
    return L.load_raw('Blinkit'), L.load_ml('Blinkit')


def _holds(cid, **frames) -> bool:
    (r,) = C.run(C.Context(frames), only=[cid])
    return r['ok']


def test_every_contract_holds_on_the_shipped_data():
    ml_path('Blinkit')
    res = C.run()
    assert len(res) == len(C.CONTRACTS) and len({r['id'] for r in res}) == len(res)
    assert [r for r in res if not r['ok']] == []


def test_contract_ids_and_references_are_documented():
    for k in C.CONTRACTS:
        assert k.layer in ('raw', 'ml', 'derived') and k.id.startswith(k.layer + '.')
        assert k.rule and k.ref
        ref_file = k.ref.split(' §')[0]
        if ref_file.endswith('.md'):
            assert (ROOT / ref_file).exists(), k.ref


def test_the_clean_blinkit_copy_passes_the_row_level_contracts(blinkit):
    raw, ml = blinkit
    row_level = ['raw.key_unique', 'raw.provenance', 'raw.labels_agree', 'raw.observed_day', 'raw.sentinels',
                 'raw.schedule', 'raw.prices', 'raw.mrp_source', 'raw.stock_flag', 'raw.eta', 'raw.stores',
                 'ml.shape', 'ml.splits', 'ml.chronological', 'ml.past_only', 'ml.no_leaky_names', 'ml.structural_nulls']
    res = C.run(C.Context({'raw': raw, 'ml': ml}), only=row_level)
    assert [r['id'] for r in res if not r['ok']] == []
    # ... while the whole-dataset counts see three platforms missing
    assert not _holds('raw.composition', raw=raw) and not _holds('raw.shape', raw=raw)


def _real_index(raw):
    return raw.index[raw.data_status.eq('REAL')][0]


def _syn_index(raw):
    return raw.index[raw.data_status.eq('SYNTHETIC')][0]


RAW_PLANTS = {
    'raw.key_unique': lambda r: r.assign(observation_key=r.observation_key.where(r.index != 1, r.observation_key.iloc[0])),
    'raw.provenance': lambda r: r.assign(source=r.source.where(r.index != 5, None)),
    'raw.labels_agree': lambda r: r.assign(is_real_observation=r.is_real_observation.where(r.index != _real_index(r), 0)),
    'raw.observed_day': lambda r: r.assign(snapshot_date=r.snapshot_date.where(r.index != _real_index(r), '2026-07-11')),
    'raw.sentinels': lambda r: r.assign(hour=r.hour.where(r.index != _real_index(r), 9)),               # an imputed hour
    'raw.schedule': lambda r: r.assign(hour=r.hour.where(r.index != _syn_index(r), 13)),
    'raw.prices': lambda r: r.assign(mrp=r.mrp.where(r.index != 3, r.selling_price - 1)),
    'raw.mrp_source': lambda r: r.assign(mrp=r.mrp.where(
        r.index != r.index[r.mrp_source.eq('assumed_equal_to_selling_price')][0], r.selling_price + 5)),
    'raw.stock_flag': lambda r: r.assign(in_stock=r.in_stock.where(r.index != 7, 1 - r.in_stock)),
    'raw.eta': lambda r: r.assign(delivery_eta_max=r.delivery_eta_max.where(r.index != 9, r.delivery_eta_min - 1)),
    'raw.stores': lambda r: r.assign(store_id=r.store_id.where(r.index != 11, 'INS-BBSR-001')),       # wrong platform
}


@pytest.mark.parametrize('cid', sorted(RAW_PLANTS))
def test_each_raw_contract_catches_its_planted_violation(blinkit, cid):
    raw, _ = blinkit
    assert _holds(cid, raw=raw)
    assert not _holds(cid, raw=RAW_PLANTS[cid](raw.copy()))


def test_a_missing_column_breaks_the_contract_instead_of_crashing_the_gate(blinkit):
    raw, _ = blinkit
    (r,) = C.run(C.Context({'raw': raw.drop(columns=['hour'])}), only=['raw.sentinels'])
    assert not r['ok'] and r['observed'].startswith('could not be checked')


def _panel_start(ml):
    d = C._ordered(ml[['observation_key', 'observed_at', 'data_status'] + C.PANEL])
    return d.index[d.groupby(['data_status'] + C.PANEL, sort=False).cumcount().eq(0)]


def test_each_ml_contract_catches_its_planted_violation(blinkit):
    raw, ml = blinkit
    def broken(cid, m):
        return not _holds(cid, raw=raw, ml=m)
    syn = ml.index[ml.data_status.eq('SYNTHETIC')]
    train = ml.index[ml.split.eq('train')]
    assert broken('ml.shape', ml.drop(index=ml.index[:1]))
    assert broken('ml.splits', ml.assign(split=ml.split.where(ml.index != syn[0], 'holdout_real')))
    assert broken('ml.chronological', ml.assign(snapshot_date=ml.snapshot_date.where(ml.index != train[0], '2026-10-10')))
    x = ml.index[ml.price_max_to_date.notna()][0]                  # a maximum that already knows a later, higher price
    assert broken('ml.past_only', ml.assign(price_min_to_date=ml.price_min_to_date.where(
        ml.index != x, ml.selling_price + 1)))
    assert broken('ml.no_leaky_names', ml.assign(price_median=ml.selling_price))
    start = _panel_start(ml)[0]                                    # a structural NULL "fixed" by imputation
    assert broken('ml.structural_nulls', ml.assign(price_lag_1=ml.price_lag_1.where(ml.index != start, 1.0)))
    mid = ml.index[ml.price_lag_1.notna()][0]
    assert broken('ml.structural_nulls', ml.assign(price_lag_1=ml.price_lag_1.where(ml.index != mid, np.nan)))


@pytest.mark.parametrize('table', ['stock_clock', 'price_grid'])
def test_derived_tables_must_stay_keyed_one_row_per_observation(blinkit, table):
    _, ml = blinkit
    import src.load as L
    cid = 'derived.' + table
    t = pd.read_parquet(L.ML / f'{table}.parquet')
    t = t[t.observation_key.isin(ml.observation_key)].reset_index(drop=True)
    assert _holds(cid, ml=ml, **{table: t})
    dup = pd.concat([t, t.iloc[:1]], ignore_index=True)
    assert not _holds(cid, ml=ml, **{table: dup})
    orphan = t.assign(observation_key=t.observation_key.where(t.index != 0, 'nope'))
    assert not _holds(cid, ml=ml, **{table: orphan})
    assert not _holds(cid, ml=ml, **{table: t.drop(columns=[c for c in t.columns if c != 'observation_key'][-1])})


def test_every_contract_has_a_planted_violation_here():
    """The page says each contract has a negative control. This keeps that true when a contract is added."""
    src = (ROOT / 'tests' / 'test_contracts.py').read_text(encoding='utf-8')
    planted = set(RAW_PLANTS) | {'raw.composition', 'raw.shape'} | {k.id for k in C.CONTRACTS if k.layer == 'derived'}
    planted |= {cid for cid in (k.id for k in C.CONTRACTS if k.layer == 'ml') if f"broken('{cid}'" in src}
    assert planted == {k.id for k in C.CONTRACTS}, sorted({k.id for k in C.CONTRACTS} - planted)


def test_the_report_counts_what_was_checked():
    doc = C.report([{'ok': True}, {'ok': False}, {'ok': True}], 1.234)
    assert (doc['ok'], doc['passed'], doc['failed'], doc['seconds']) == (False, 2, 1, 1.2)
