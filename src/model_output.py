"""
model_output.py — the one way a model saves its results. Contract: docs/MODEL_OUTPUT_CONTRACT.md.

    from src.model_output import save_model_outputs
    save_model_outputs('price_forecast_lgbm', predictions, params, metrics,
                       training_data=train, split={'fit': 'train', 'evaluated_on': 'test'},
                       target='future_price', feature_columns=feats)

Writes outputs/models/<model_name>/
    predictions.parquet   must carry observation_key + data_status (provenance survives downstream)
    params.json           fitted parameters / hyperparameters
    metrics.json          evaluation metrics
    manifest.json         training data, REAL/SYNTHETIC mix, raw-data hashes, split, date, claim scope

This module contains no model.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.integrity import ml_hashes, raw_baseline, raw_hashes
from src.load import check_feature_set
from src.provenance import STORE_LEVEL_REAL_OUTPUTS, store_label_status

ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / 'outputs' / 'models'
CONTRACT_VERSION = 1
REQUIRED_PREDICTION_COLUMNS = ('observation_key', 'data_status')
STATUSES = {'REAL', 'SYNTHETIC'}


class ContractError(ValueError):
    """Model outputs do not conform to docs/MODEL_OUTPUT_CONTRACT.md."""


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    raise ContractError(f"not JSON-serialisable: {type(obj).__name__}")


def _mix(df: pd.DataFrame, what: str) -> dict:
    if 'data_status' not in df.columns:
        raise ContractError(f"{what} has no data_status column — provenance would be lost")
    s = df.data_status.astype(str)
    unknown = set(s.unique()) - STATUSES
    if unknown:
        raise ContractError(f"{what} has unknown data_status values {unknown}")
    n_real, n_syn = int(s.eq('REAL').sum()), int(s.eq('SYNTHETIC').sum())
    return {'rows': len(df), 'REAL': n_real, 'SYNTHETIC': n_syn,
            'real_share': round(n_real / len(df), 6) if len(df) else None}


def _describe(df: pd.DataFrame) -> dict:
    out = {'rows': len(df)}
    for c in ('platform', 'split'):
        if c in df.columns:
            out[f'rows_by_{c}'] = df[c].astype(str).value_counts().sort_index().to_dict()
    if 'snapshot_date' in df.columns and len(df):
        out['snapshot_date_range'] = [str(df.snapshot_date.min()), str(df.snapshot_date.max())]
    return out


def claim_scope(training_mix: dict, prediction_mix: dict) -> str:
    if training_mix['SYNTHETIC'] or prediction_mix['SYNTHETIC']:
        return ('SYNTHETIC-DERIVED: results demonstrate that the modelling pipeline works (e.g. it '
                'recovers planted generator parameters). They are NOT market findings and must not be '
                'reported as such.')
    return 'REAL-ONLY: trained and evaluated on data_status == REAL rows only.'


def save_model_outputs(model_name: str, predictions: pd.DataFrame, params: dict, metrics: dict,
                       training_data: pd.DataFrame, split, *, target: str | None = None,
                       feature_columns=None, training_source: str = 'data/ml via src.load',
                       notes: str = '', base_dir: Path | None = None) -> Path:
    """Validate and write one model's outputs. Returns the model directory. Raises ContractError."""
    if not re.fullmatch(r'[a-z0-9][a-z0-9_\-]{1,63}', model_name or ''):
        raise ContractError("model_name must be lowercase letters, digits, '_' or '-' (2-64 chars)")
    if not isinstance(predictions, pd.DataFrame) or predictions.empty:
        raise ContractError("predictions must be a non-empty DataFrame")
    missing = [c for c in REQUIRED_PREDICTION_COLUMNS if c not in predictions.columns]
    if missing:
        raise ContractError(f"predictions missing required columns {missing}")
    if predictions.observation_key.isna().any():
        raise ContractError("predictions contain null observation_key")
    if not isinstance(split, (str, dict)) or not split:
        raise ContractError("split must be a split name or a dict such as {'fit': 'train', 'evaluated_on': 'test'}")
    if feature_columns is not None:
        feature_columns = check_feature_set(feature_columns)

    pred_mix = _mix(predictions, 'predictions')
    train_mix = _mix(training_data, 'training_data')

    now = datetime.now(timezone.utc)
    hashes = raw_hashes()
    try:
        baseline = raw_baseline()
        matches = hashes == baseline
    except Exception as e:                      # baseline script missing or broken
        baseline, matches = {'error': str(e)}, False
    manifest = {
        'contract_version': CONTRACT_VERSION,
        'model_name': model_name,
        'created_at_utc': now.isoformat(timespec='seconds'),
        'date': now.date().isoformat(),
        'target': target,
        'split': split,
        'feature_columns': feature_columns,
        'training_data': {'source': training_source, **_describe(training_data)},
        'training_row_mix': train_mix,
        'prediction_row_mix': pred_mix,
        'raw_data_hashes': hashes,
        'raw_hashes_match_verified_baseline': matches,
        'ml_layer_hashes': ml_hashes(),
        'claim_scope': claim_scope(train_mix, pred_mix),
        'notes': notes,
        'files': ['predictions.parquet', 'params.json', 'metrics.json', 'manifest.json'],
    }
    if model_name in STORE_LEVEL_REAL_OUTPUTS:          # the result reads store_id on REAL rows: carry the label's status
        manifest['store_label'] = store_label_status()

    out = Path(base_dir or MODELS_DIR) / model_name
    out.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(out / 'predictions.parquet', index=False)
    (out / 'params.json').write_text(json.dumps(_jsonable(params), indent=2), encoding='utf-8')
    (out / 'metrics.json').write_text(json.dumps(_jsonable(metrics), indent=2), encoding='utf-8')
    (out / 'manifest.json').write_text(json.dumps(_jsonable(manifest), indent=2), encoding='utf-8')
    return out


def load_model_outputs(model_name: str, base_dir: Path | None = None) -> dict:
    """Read a saved model back: {'predictions', 'params', 'metrics', 'manifest'}."""
    d = Path(base_dir or MODELS_DIR) / model_name
    return {'predictions': pd.read_parquet(d / 'predictions.parquet'),
            'params': json.loads((d / 'params.json').read_text(encoding='utf-8')),
            'metrics': json.loads((d / 'metrics.json').read_text(encoding='utf-8')),
            'manifest': json.loads((d / 'manifest.json').read_text(encoding='utf-8'))}
