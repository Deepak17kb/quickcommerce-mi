"""Data access layer. Import these instead of hard-coding paths, filters or column lists.

Full guide with examples: docs/DATA_ACCESS.md.

Column roles are read LIVE from data/reference/ML_SCHEMA_v2.xlsx :: SCHEMA_FROZEN (written by
src/pipeline/build_features.py) and from the columns of data/ml/ML_targets.parquet. Nothing here
hardcodes a column name list: if the schema changes, every role follows it on the next call.
"""
from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW, ML, REF = ROOT/'data'/'raw', ROOT/'data'/'ml', ROOT/'data'/'reference'
SCHEMA_PATH = REF / 'ML_SCHEMA_v2.xlsx'
TARGETS_PATH = ML / 'ML_targets.parquet'

SPLITS = ('train', 'val', 'test', 'holdout_real')
# columns in ML_targets.parquet that are bookkeeping, not prediction targets
_TARGET_FILE_META = {'observation_key', 'data_status', 'split'}


class FeatureSetError(ValueError):
    """A feature set contains an identifier or a target column."""


# --------------------------------------------------------------------------- loading
def _read(folder: Path, pattern: str, what: str) -> pd.DataFrame:
    files = sorted(folder.glob(pattern))
    if not files:
        raise FileNotFoundError(
            f"No {what} found in {folder}.\n"
            + ("Run `make features` (or python -m src.pipeline.build_features) "
               "to build the ML layer from data/raw." if folder == ML else
               "Unzip the project archive so data/raw is populated."))
    frames = [pd.read_parquet(f) if f.suffix == '.parquet'
              else pd.read_csv(f, low_memory=False) for f in files]
    return pd.concat(frames, ignore_index=True)


def load_raw(platform: str | None = None) -> pd.DataFrame:
    """Frozen observation layer. Never write back to this."""
    return _read(RAW, f"{platform or '*'}_RAW.parquet", 'raw data')


def load_real() -> pd.DataFrame:
    """The REAL rows of the raw layer, and only those: the row filter is applied while reading, so the 588,840
    SYNTHETIC rows never become a DataFrame. Same rows and columns as real_only(load_raw()); the index runs 0..n-1.
    Arrow still decompresses each file to filter it and keeps the freed buffers in its memory pool, so the pool is
    handed back to the system afterwards: measured 2026-10-20, the process keeps +57 MB instead of +859 MB (load_raw).
    That is the difference between the analyst's server fitting in 512 MB and not."""
    files = sorted(RAW.glob('*_RAW.parquet'))
    if not files:
        raise FileNotFoundError(f'No raw data found in {RAW}.')
    frames = [pd.read_parquet(f, filters=[('data_status', '==', 'REAL')]) for f in files]
    try:
        import pyarrow as pa
        pa.default_memory_pool().release_unused()
    except (ImportError, AttributeError):          # an older pyarrow keeps the pool: correct, only larger
        pass
    return pd.concat([f for f in frames if len(f)], ignore_index=True)


def load_targets() -> pd.DataFrame:
    """ML_targets.parquet as stored: observation_key, every target, data_status, split."""
    if not TARGETS_PATH.exists():
        raise FileNotFoundError(f"{TARGETS_PATH} missing. Run python -m src.pipeline.build_features.")
    return pd.read_parquet(TARGETS_PATH)


def load_ml(platform: str | None = None, with_targets: bool = True) -> pd.DataFrame:
    """ML layer for one platform file slug ('Blinkit', 'Instamart', 'FlipkartMinutes', 'BigBasket')
    or all of them. Targets are joined 1:1 on observation_key unless with_targets=False."""
    X = _read(ML, f"{platform or '*'}_ML_price.parquet", 'ML features')
    if not with_targets:
        return X
    y = load_targets().drop(columns=['data_status', 'split'], errors='ignore')
    out = X.merge(y, on='observation_key', how='left', validate='one_to_one')
    assert len(out) == len(X), "target join changed the row count"
    return out


def load_catalog() -> pd.DataFrame:
    """12,188 real Blinkit products — names, brands, categories, pack sizes."""
    return pd.read_parquet(REF / 'MASTER_CATALOG.parquet')


def load_stores() -> pd.DataFrame:
    return (pd.concat([pd.read_csv(f) for f in sorted(REF.glob('STORES*.csv'))],
                      ignore_index=True).drop_duplicates('store_id'))


# --------------------------------------------------------------------------- column roles
@lru_cache(maxsize=8)
def _schema_cached(path: str, mtime: float) -> pd.DataFrame:
    s = pd.read_excel(path, sheet_name='SCHEMA_FROZEN')
    missing = {'column', 'role'} - set(s.columns)
    if missing:
        raise ValueError(f"{path} :: SCHEMA_FROZEN is missing {missing}")
    return s


def schema() -> pd.DataFrame:
    """SCHEMA_FROZEN, re-read whenever the file changes on disk."""
    p = Path(SCHEMA_PATH)
    if not p.exists():
        raise FileNotFoundError(f"{p} missing. Run python -m src.pipeline.build_features.")
    return _schema_cached(str(p), p.stat().st_mtime).copy()


def _role(prefix: str) -> list[str]:
    s = schema()
    return s.loc[s.role.astype(str).str.upper().str.startswith(prefix.upper()), 'column'].tolist()


def identifier_columns() -> list[str]:
    """Columns tagged IDENTIFIER in SCHEMA_FROZEN. Never model inputs."""
    return _role('IDENTIFIER')


def past_only_columns() -> list[str]:
    """Columns tagged 'past-only feature' (lags, *_to_date, rolling windows)."""
    return _role('past-only')


def feature_role_columns() -> list[str]:
    """Every schema column tagged 'feature' or 'past-only feature' (any dtype)."""
    return _role('feature') + [c for c in past_only_columns() if c not in _role('feature')]


def target_columns() -> list[str]:
    """Prediction targets: columns tagged TARGET in SCHEMA_FROZEN plus every non-bookkeeping column
    of ML_targets.parquet (read from its parquet schema, not from a list)."""
    cols = _role('TARGET')
    if TARGETS_PATH.exists():
        import pyarrow.parquet as pq
        cols += [c for c in pq.read_schema(TARGETS_PATH).names if c not in _TARGET_FILE_META]
    return list(dict.fromkeys(cols))


def columns_by_role() -> dict[str, list[str]]:
    return {'identifiers': identifier_columns(), 'past_only': past_only_columns(),
            'features': feature_role_columns(), 'targets': target_columns()}


def __getattr__(name):
    # backwards compatibility: `from src.load import ID_COLS` now reads the schema
    if name == 'ID_COLS':
        return identifier_columns()
    raise AttributeError(name)


# --------------------------------------------------------------------------- feature guard
def check_feature_set(cols) -> list[str]:
    """Raise FeatureSetError if cols contain any identifier or target column. Returns cols."""
    cols = list(cols)
    ids = set(identifier_columns())
    tgts = set(target_columns())
    bad_id = [c for c in cols if c in ids]
    bad_t = [c for c in cols if c in tgts]
    if bad_id or bad_t:
        raise FeatureSetError(
            "Refusing feature set: "
            + (f"identifier columns {bad_id} " if bad_id else "")
            + (f"target columns {bad_t} " if bad_t else "")
            + "(roles from data/reference/ML_SCHEMA_v2.xlsx and data/ml/ML_targets.parquet)")
    return cols


def feature_columns(df: pd.DataFrame | None = None, numeric: bool = True,
                    past_only: bool = False) -> list[str]:
    """Feature columns by schema role, identifiers and targets excluded and guarded.

    df        restrict to columns present in df (and use its dtypes for `numeric`)
    numeric   keep only numeric dtypes (needs df)
    past_only only 'past-only feature' columns
    """
    cols = past_only_columns() if past_only else feature_role_columns()
    if df is not None:
        cols = [c for c in cols if c in df.columns]
        if numeric:
            cols = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
    return check_feature_set(cols)


def select_features(df: pd.DataFrame, cols) -> pd.DataFrame:
    """df[cols], after the guard. Use this instead of df[cols] when building model inputs."""
    return df[check_feature_set(cols)]


# --------------------------------------------------------------------------- provenance filters
def real_only(df: pd.DataFrame) -> pd.DataFrame:
    """The ONLY rows you may report as real market fact."""
    return df[df.data_status == 'REAL']


def synthetic_only(df: pd.DataFrame) -> pd.DataFrame:
    """Generated rows. Results from these demonstrate method, never market facts."""
    return df[df.data_status == 'SYNTHETIC']


def preferred_only(df: pd.DataFrame) -> pd.DataFrame:
    """Drop redundant identical-repeat listings (is_preferred_listing == 1)."""
    return df[df.is_preferred_listing == 1]


PRICE_SOURCE_AUDIT = REF / 'REAL_PRICE_SOURCE_AUDIT.csv'


def web_researched_price_ids() -> set:
    """product_id of the REAL rows whose price was NOT observed in the 2026-07-10 snapshot.

    The source workbook marks 27 rows 'Web researched' with a URL: 14 from blinkit.com product pages and 13 from
    other sites (brand stores, other retailers). data/raw is frozen and labels all of them price_provenance =
    'observed', so the correction lives here and in data/reference/REAL_PRICE_SOURCE_AUDIT.csv (source file, sha256 and
    date checked are columns of that table). Stock status on these rows is unaffected."""
    if not PRICE_SOURCE_AUDIT.exists():
        return set()
    return set(pd.read_csv(PRICE_SOURCE_AUDIT, usecols=['product_id']).product_id)


def real_observed_price_only(df: pd.DataFrame) -> pd.DataFrame:
    """REAL rows whose selling price was observed in the snapshot: real_only() minus the web-researched prices.
    Use it for any statement about real Blinkit PRICES; real_only() stays right for stock and assortment."""
    r = real_only(df)
    return r[~r.product_id.isin(web_researched_price_ids())]


# --------------------------------------------------------------------------- splits
def _chronological(d: pd.DataFrame) -> pd.DataFrame:
    ts = pd.to_datetime(d.observed_at.astype(str), format='mixed')
    keys = [c for c in ('platform', 'store_id', 'product_id') if c in d.columns]
    return (d.assign(_ts=ts).sort_values(['_ts'] + keys, kind='stable')
             .drop(columns='_ts'))


def get_split(name: str, df: pd.DataFrame | None = None, target: str | None = None,
              platform: str | None = None) -> pd.DataFrame:
    """One split ('train', 'val', 'test', 'holdout_real') in chronological order.

    Uses the pipeline's `split` column; never filters by date by hand. If `target` is given,
    rows without that target are dropped. Loads the ML layer if df is None.
    """
    if name not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}, got {name!r}")
    if target is not None and target not in target_columns():
        raise ValueError(f"{target!r} is not a target column")
    d = load_ml(platform) if df is None else df
    d = d[d.split == name]
    if target is not None:
        d = d[d[target].notna()]
    return _chronological(d)


def splits(df: pd.DataFrame | None = None, target: str = 'future_price',
           include_holdout: bool = False):
    """(train, val, test[, holdout_real]), each chronological.

    Rows without `target` are dropped from train/val/test. holdout_real is returned UNFILTERED:
    it is the single real Blinkit snapshot, so it has no next observation and every temporal
    target is null there by construction (see CLAUDE.md §3.6).
    """
    if df is None:
        df = load_ml()
    out = tuple(get_split(n, df, target=target) for n in SPLITS[:3])
    return out + (get_split('holdout_real', df),) if include_holdout else out
