# Model output contract

Every model saves its results through `src/model_output.py :: save_model_outputs`. This makes each
model directly consumable by SIMULATE, OPTIMIZE and the AI analyst with no retrofitting.
No model exists yet; this is the contract they must follow.

## Location and files

```
outputs/models/<model_name>/
    predictions.parquet   one row per prediction
    params.json           fitted parameters / hyperparameters
    metrics.json          evaluation metrics
    manifest.json         provenance record (below)
```

`<model_name>`: lowercase letters, digits, `_` or `-`, 2–64 characters.

## predictions.parquet — required columns

| Column | Why |
|---|---|
| `observation_key` | joins every prediction back to `data/ml` and `data/raw`; may not be null |
| `data_status` | `REAL` or `SYNTHETIC`, so provenance survives into every downstream layer |

Any other columns are free (`prediction`, `proba`, `horizon`, …). Writing is refused if either
required column is missing or `data_status` has any other value.

## manifest.json

| Key | Content |
|---|---|
| `contract_version` | 1 |
| `model_name`, `created_at_utc`, `date` | when it was produced |
| `target` | target column (validated as a target by the caller's data) |
| `split` | split name, or a dict such as `{"fit": "train", "evaluated_on": "test"}` |
| `feature_columns` | passed through `src.load.check_feature_set`: IDs and targets are refused |
| `training_data` | source, rows, rows by platform, rows by split, snapshot date range |
| `training_row_mix` / `prediction_row_mix` | rows, REAL, SYNTHETIC, real_share |
| `raw_data_hashes` | sha256 (first 16 hex) of every `data/raw/*.parquet` at save time |
| `raw_hashes_match_verified_baseline` | true only if those equal the baseline in `scripts/verify_raw_integrity.py` |
| `ml_layer_hashes` | sha256 (first 16 hex) of every `data/ml/*.parquet` |
| `claim_scope` | set automatically: any SYNTHETIC row in training or predictions ⇒ "SYNTHETIC-DERIVED … NOT market findings" |
| `notes` | free text |

## Usage

```python
import src.load as L
from src.model_output import save_model_outputs, load_model_outputs

train, val, test = L.splits(L.load_ml(), 'future_price')
feats = L.feature_columns(train)
# ... fit a model (not part of this contract) ...
pred = test[['observation_key', 'data_status']].assign(prediction=yhat)

save_model_outputs('price_forecast_lgbm', pred, params={'n_estimators': 400},
                   metrics={'mae_test': 7.9, 'mae_naive': 10.6}, training_data=train,
                   split={'fit': 'train', 'evaluated_on': 'test'},
                   target='future_price', feature_columns=feats)

out = load_model_outputs('price_forecast_lgbm')   # predictions, params, metrics, manifest
```

## Rules for consumers (SIMULATE, OPTIMIZE, analyst)

- Read `claim_scope` and carry it with every number derived from the model.
- Join on `observation_key`; never re-derive provenance, use the `data_status` in `predictions.parquet`.
- If `raw_hashes_match_verified_baseline` is false, the model was trained on different raw data than
  the current frozen baseline: rebuild or flag it, never silently reuse it.

Tests: `tests/test_model_output_contract.py`.
