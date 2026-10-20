"""No snapshot_date may appear in more than one of train / val / test / holdout_real."""
import pandas as pd

from conftest import PLATFORMS, ml_path

SPLITS = {'train', 'val', 'test', 'holdout_real'}


def test_split_no_date_overlap():
    d = pd.concat([pd.read_parquet(ml_path(p), columns=['snapshot_date', 'split'])
                   for p in PLATFORMS], ignore_index=True)
    d = d.astype(str)

    assert set(d.split.unique()) <= SPLITS, f"unexpected split labels: {set(d.split) - SPLITS}"
    assert d.snapshot_date.ne('nan').all(), "rows with no snapshot_date"

    per_date = d.groupby('snapshot_date').split.unique()
    shared = per_date[per_date.map(len) > 1]
    assert shared.empty, f"dates in more than one split:\n{shared.head(10).to_string()}"

    # chronological, not just disjoint: every train date < every val date < every test date
    rng = d[d.split != 'holdout_real'].groupby('split').snapshot_date.agg(['min', 'max'])
    assert rng.loc['train', 'max'] < rng.loc['val', 'min'], rng.to_string()
    assert rng.loc['val', 'max'] < rng.loc['test', 'min'], rng.to_string()
