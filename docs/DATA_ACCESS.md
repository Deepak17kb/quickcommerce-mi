# Data access layer — `src/load.py`

Every model loads, filters and selects columns through `src/load.py`. Do not re-implement any of it.

## Loading

```python
import src.load as L

df  = L.load_ml()                 # all platforms, 610,789 rows, targets joined 1:1 on observation_key
bl  = L.load_ml('Blinkit')        # one platform file: 'Blinkit' | 'Instamart' | 'FlipkartMinutes' | 'BigBasket'
X   = L.load_ml(with_targets=False)
y   = L.load_targets()            # ML_targets.parquet as stored
raw = L.load_raw()                # frozen raw layer (read-only)
cat, stores = L.load_catalog(), L.load_stores()
```

## Splits — never filter dates by hand

The pipeline's `split` column is the only split. Every split comes back in chronological order
(`observed_at`, then platform / store / product).

```python
train = L.get_split('train', df, target='future_price')   # drops rows with no target
val   = L.get_split('val', df, target='future_price')
test  = L.get_split('test', df, target='future_price')
real  = L.get_split('holdout_real', df)                    # the 21,949 REAL rows

train, val, test = L.splits(df, 'future_price')
train, val, test, holdout = L.splits(df, 'future_price', include_holdout=True)
```

`holdout_real` is never target-filtered. It is one real snapshot, so every temporal target
(`future_*`) is null there by construction (CLAUDE.md §3.6).

## Columns by role — read live, never hardcoded

| Function | Source |
|---|---|
| `L.identifier_columns()` | `SCHEMA_FROZEN` rows whose role starts with `IDENTIFIER` |
| `L.past_only_columns()` | role `past-only feature` (lags, `*_to_date`, rolling windows) |
| `L.feature_role_columns()` | role `feature` + `past-only feature` (any dtype) |
| `L.target_columns()` | role `TARGET` in the schema + the non-bookkeeping columns of `ML_targets.parquet` (read from its parquet schema) |
| `L.columns_by_role()` | all four as a dict |

The schema is `data/reference/ML_SCHEMA_v2.xlsx :: SCHEMA_FROZEN`, written by
`src/pipeline/build_features.py`. It is re-read whenever the file changes on disk, so every role follows
it with no code change. `SCHEMA_FROZEN` does not list target columns (targets live in a separate
table), which is why `target_columns()` also reads `ML_targets.parquet`'s schema.
`from src.load import ID_COLS` still works and resolves to `identifier_columns()`.

## Building model inputs — the guard

```python
feats = L.feature_columns(train)                  # numeric, by role, IDs + targets excluded
feats = L.feature_columns(train, past_only=True)  # only past-only features
Xtr   = L.select_features(train, feats)           # df[cols] after the guard
ytr   = train['future_price']

L.check_feature_set(['price_lag_1', 'store_id'])  # raises FeatureSetError
L.select_features(train, ['future_price'])        # raises FeatureSetError
```

`check_feature_set` raises `FeatureSetError` (a `ValueError`) as soon as a feature set contains any
identifier or target column, so a leaky feature set cannot be built through this layer.
`feature_columns` and `select_features` always call it. Caution: the numeric `feature` role still
includes provenance flags such as `is_real_observation` and `in_common_panel`; they are not IDs, but
think before feeding them to a model.

## Provenance filters

```python
L.real_only(df)        # data_status == 'REAL'  — the only rows reportable as market fact
L.synthetic_only(df)   # data_status == 'SYNTHETIC' — method demonstration only
L.preferred_only(df)   # is_preferred_listing == 1 (drops 339 redundant identical-repeat listings)
```

## Saving model results

See `docs/MODEL_OUTPUT_CONTRACT.md` and `src/model_output.py`.

Tests: `tests/test_data_access.py`.
