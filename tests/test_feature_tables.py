"""The derived feature tables (stock clock, price grid) must use nothing after t: every panel is truncated at snapshot
30, the table is rebuilt from the truncated data, and every column must equal the full build on the kept rows."""
import pytest

import src.features.price_grid as PG
import src.features.stock_clock as SC
import src.load as L


@pytest.fixture(scope='module')
def ml():
    return L.load_ml(with_targets=False)


@pytest.mark.parametrize('module', [SC, PG], ids=['stock_clock', 'price_grid'])
def test_feature_table_is_past_only(module, ml):
    res = module.verify(ml)
    assert set(res) == set(module.NEW_COLUMNS)
    assert all(v == 'PASS' for v in res.values()), res
