"""
The exact check that caught the original leakage bug.

At the FIRST observation of each (platform, store_id, product_id) panel, nothing
past-only can know any other price, so the expanding min and max must both equal
that row's own selling price. The leaky whole-panel versions failed this in
2,028 (min) and 2,176 (max) panels.

The first observation is found independently from `observed_at`, not from the
pipeline's own `obs_index_in_panel`, so a bug in the pipeline's ordering can't hide.
"""
import numpy as np
import pandas as pd
import pytest

from conftest import PANEL, PLATFORMS, ml_path

TOL = 0.005   # parquet stores prices as float32


@pytest.mark.parametrize('platform', PLATFORMS)
def test_no_leakage(platform):
    cols = PANEL + ['observed_at', 'selling_price', 'price_min_to_date', 'price_max_to_date']
    d = pd.read_parquet(ml_path(platform), columns=cols)
    d['_ts'] = pd.to_datetime(d.observed_at.astype(str), format='mixed', errors='coerce')
    assert d._ts.notna().all(), "unparseable observed_at — date features would silently go null"

    first = (d.sort_values(PANEL + ['_ts'], kind='stable')
               .groupby(PANEL, sort=False, observed=True).head(1))
    assert len(first) > 0

    own = first.selling_price.to_numpy(float)
    for col in ('price_min_to_date', 'price_max_to_date'):
        v = first[col].to_numpy(float)
        bad = ~np.isclose(v, own, atol=TOL, rtol=0)
        examples = first.loc[bad, PANEL + ['selling_price', col]].head(3).to_string()
        assert not bad.any(), (f"{platform}: {col} != own price at t=0 in "
                               f"{int(bad.sum()):,} panels — future prices leaking\n{examples}")
