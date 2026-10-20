"""
The 6 identifier columns in ML_SCHEMA_v2.xlsx :: ID_COLUMNS must never be model features.

Covers:
  - src.load.feature_columns() on the real ML layer
  - every module-level feature list anywhere under src/ — any name containing FEAT
    assigned a literal list/tuple of strings (today: src/matching/train.py FEATS).
    Future model builders are picked up automatically if they follow that convention.
"""
import ast
from pathlib import Path

import pandas as pd
import pytest

from conftest import ROOT, ml_path

SRC = ROOT / 'src'


def _feature_lists():
    found = []
    for py in sorted(SRC.rglob('*.py')):
        tree = ast.parse(py.read_text(encoding='utf-8'), filename=str(py))
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, (ast.List, ast.Tuple)):
                continue
            for t in node.targets:
                if isinstance(t, ast.Name) and 'FEAT' in t.id.upper():
                    vals = [e.value for e in node.value.elts
                            if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                    found.append((f"{py.relative_to(ROOT)}::{t.id}", vals))
    return found


def test_id_sheet_matches_loader(id_columns):
    from src.load import ID_COLS
    assert len(id_columns) == 6, id_columns
    assert set(id_columns) == set(ID_COLS)


def test_matching_feature_list_is_discovered():
    names = [n for n, _ in _feature_lists()]
    assert any(n.endswith('src\\matching\\train.py::FEATS') or
               n.endswith('src/matching/train.py::FEATS') for n in names), names


@pytest.mark.parametrize('name,feats', _feature_lists(), ids=lambda x: x if isinstance(x, str) else '')
def test_id_columns_excluded(name, feats, id_columns):
    leaked = sorted(set(feats) & set(id_columns))
    assert not leaked, f"{name} contains identifier columns: {leaked}"


def test_feature_columns_excludes_ids(id_columns):
    from src.load import feature_columns
    sample = pd.read_parquet(ml_path('Blinkit')).head(2000)
    feats = feature_columns(sample)
    assert feats, "feature_columns returned nothing"
    leaked = sorted(set(feats) & set(id_columns))
    assert not leaked, f"feature_columns() leaks identifiers: {leaked}"
    assert not [c for c in feats if c.startswith('future_')], "targets in feature list"
