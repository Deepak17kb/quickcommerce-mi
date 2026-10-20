"""Shared paths and loaders for the guardrail tests. Reads only; never writes."""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RAW = ROOT / 'data' / 'raw'
ML = ROOT / 'data' / 'ml'
REF = ROOT / 'data' / 'reference'
PLATFORMS = ['Blinkit', 'Instamart', 'FlipkartMinutes', 'BigBasket']
PANEL = ['platform', 'store_id', 'product_id']


def ml_path(platform: str) -> Path:
    p = ML / f'{platform}_ML_price.parquet'
    if not p.exists():
        pytest.skip(f"{p.relative_to(ROOT)} not built — run `make features` first")
    return p


def raw_path(platform: str) -> Path:
    p = RAW / f'{platform}_RAW.parquet'
    if not p.exists():
        pytest.fail(f"{p.relative_to(ROOT)} missing")
    return p


@pytest.fixture(scope='session')
def id_columns() -> list[str]:
    ids = pd.read_excel(REF / 'ML_SCHEMA_v2.xlsx', sheet_name='ID_COLUMNS')
    return ids['identifier_columns'].dropna().astype(str).tolist()
