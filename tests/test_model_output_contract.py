"""Phase 3 model output contract (docs/MODEL_OUTPUT_CONTRACT.md). Dummy frames only — no model."""
import json

import pandas as pd
import pytest

from src.model_output import ContractError, load_model_outputs, save_model_outputs


def _frames():
    train = pd.DataFrame({'observation_key': ['a', 'b', 'c'], 'data_status': ['SYNTHETIC'] * 3,
                          'platform': ['Blinkit'] * 3, 'split': ['train'] * 3,
                          'snapshot_date': ['2026-09-15', '2026-09-16', '2026-09-17']})
    pred = pd.DataFrame({'observation_key': ['x', 'y'], 'data_status': ['SYNTHETIC', 'REAL'],
                         'prediction': [1.0, 2.0]})
    return train, pred


def test_writes_all_files_and_manifest(tmp_path):
    train, pred = _frames()
    out = save_model_outputs('dummy_model', pred, {'alpha': 0.1}, {'mae': 1.23}, train,
                             {'fit': 'train', 'evaluated_on': 'test'}, target='future_price',
                             feature_columns=['price_lag_1'], base_dir=tmp_path)
    assert sorted(p.name for p in out.iterdir()) == ['manifest.json', 'metrics.json', 'params.json',
                                                     'predictions.parquet']
    m = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    for key in ('training_data', 'training_row_mix', 'raw_data_hashes', 'split', 'date', 'claim_scope'):
        assert key in m
    assert m['training_row_mix'] == {'rows': 3, 'REAL': 0, 'SYNTHETIC': 3, 'real_share': 0.0}
    assert m['prediction_row_mix']['REAL'] == 1
    assert 'NOT market findings' in m['claim_scope']
    assert len(m['raw_data_hashes']) == 4 and m['raw_hashes_match_verified_baseline'] is True
    back = load_model_outputs('dummy_model', base_dir=tmp_path)
    assert list(back['predictions'].columns[:2]) == ['observation_key', 'data_status']


@pytest.mark.parametrize('drop', ['observation_key', 'data_status'])
def test_predictions_must_carry_provenance(tmp_path, drop):
    train, pred = _frames()
    with pytest.raises(ContractError):
        save_model_outputs('dummy_model', pred.drop(columns=drop), {}, {}, train, 'test', base_dir=tmp_path)


def test_rejects_id_or_target_features_and_bad_status(tmp_path):
    train, pred = _frames()
    with pytest.raises(ValueError):
        save_model_outputs('dummy_model', pred, {}, {}, train, 'test', feature_columns=['store_id'], base_dir=tmp_path)
    with pytest.raises(ContractError):
        save_model_outputs('dummy_model', pred.assign(data_status='MAYBE'), {}, {}, train, 'test', base_dir=tmp_path)
