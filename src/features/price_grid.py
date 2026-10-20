"""
price_grid.py — past-only price-grid features (deliverables 3, 11, 12a).

    python -m src.features.price_grid          # builds data/ml/price_grid.parquet, prints its leakage check

WHY
  Shelf prices sit on grids (Rs 1, or Rs 10 steps ending in 0/5/9, or Rs 50 / 100 steps ending in 49/99; the
  REAL Blinkit snapshot shows 75% of prices end in 0, 5 or 9). On a coarse grid a price moves only when the
  underlying price crosses a boundary, so how coarse the grid is and how long the price has been stuck are
  direct evidence about the next move. None of this is in the ML layer.

COLUMNS (all use prices up to and INCLUDING t)
  grid_step_to_date        coarsest grid step consistent with every price seen so far (1, 10, 50, 100)
  grid_step_pct            grid_step_to_date / selling_price: a one-step move in % of price
  n_distinct_prices_to_date
  snapshots_at_price       consecutive snapshots at the current price (including t)
  share_time_at_price      share of the listing's snapshots so far spent at the current price
  price_level_rank_to_date where the current price sits among the distinct prices seen so far (0 = lowest, 1 = highest)
  steps_above_min_to_date  (price - min to date) / grid step
  steps_below_max_to_date  (max to date - price) / grid step
"""
import numpy as np
import pandas as pd

import src.load as L

OUT = L.ML / 'price_grid.parquet'
PANEL = ['data_status', 'platform', 'store_id', 'product_id']
GRIDS = [(100, 99), (50, 49), (50, 0), (10, 9), (10, 0), (10, 5), (1, 0)]
NEW_COLUMNS = ['grid_step_to_date', 'grid_step_pct', 'n_distinct_prices_to_date', 'snapshots_at_price',
               'share_time_at_price', 'price_level_rank_to_date', 'steps_above_min_to_date',
               'steps_below_max_to_date']


def build(ml: pd.DataFrame | None = None) -> pd.DataFrame:
    d = (L.load_ml(with_targets=False) if ml is None else ml)[
        PANEL + ['observation_key', 'observed_at', 'selling_price']].copy()
    d['_ts'] = pd.to_datetime(d.observed_at.astype(str), format='mixed')
    d = d.sort_values(PANEL + ['_ts'], kind='stable').reset_index(drop=True)
    p = np.round(d.selling_price.to_numpy(float)).astype(np.int64)
    new_panel = d[PANEL].ne(d[PANEL].shift()).any(axis=1).to_numpy()
    pid = np.cumsum(new_panel)

    # coarsest grid consistent with every price so far: per candidate, a running AND
    step = np.ones(len(d))
    chosen = np.zeros(len(d), bool)
    for s, r in GRIDS:
        ok = pd.Series((p % s) == (r % s)).groupby(pid).cummin().to_numpy()
        take = ok & ~chosen
        step[take] = s
        chosen |= ok
    d['grid_step_to_date'] = step
    d['grid_step_pct'] = step / d.selling_price.to_numpy(float)

    # distinct prices so far: first occurrence of each (panel, price)
    first_seen = ~pd.DataFrame({'pid': pid, 'p': p}).duplicated().to_numpy()
    d['n_distinct_prices_to_date'] = pd.Series(first_seen.astype(int)).groupby(pid).cumsum().to_numpy()

    # consecutive snapshots at the current price
    blk = np.cumsum(new_panel | np.r_[True, p[1:] != p[:-1]])
    d['snapshots_at_price'] = pd.Series(np.ones(len(d))).groupby(blk).cumsum().to_numpy()

    # share of time at the current price, to date
    cnt_pp = pd.Series(np.ones(len(d))).groupby([pid, p]).cumsum().to_numpy()
    n_so_far = pd.Series(np.ones(len(d))).groupby(pid).cumsum().to_numpy()
    d['share_time_at_price'] = cnt_pp / n_so_far

    # rank of the current price among distinct prices so far, and distance to min/max in grid steps
    mn = pd.Series(p).groupby(pid).cummin().to_numpy(); mx = pd.Series(p).groupby(pid).cummax().to_numpy()
    d['steps_above_min_to_date'] = (p - mn) / step
    d['steps_below_max_to_date'] = (mx - p) / step
    # rank on the grid: steps above the min over the grid span to date (0.5 while the span is zero)
    span = (mx - mn) / step
    d['price_level_rank_to_date'] = np.where(span > 0, (p - mn) / step / np.where(span > 0, span, 1), 0.5)

    out = d[['observation_key'] + NEW_COLUMNS].copy()
    for c in NEW_COLUMNS:
        out[c] = out[c].astype('float32')
    return out


def verify(ml: pd.DataFrame | None = None, cutoff: int = 30) -> dict:
    full_ml = L.load_ml(with_targets=False) if ml is None else ml
    full = build(full_ml).set_index('observation_key')
    syn = full_ml[full_ml.data_status == 'SYNTHETIC'].copy()
    syn['_ts'] = pd.to_datetime(syn.observed_at.astype(str), format='mixed')
    syn = syn.sort_values(PANEL + ['_ts'])
    syn['_i'] = syn.groupby(PANEL, sort=False).cumcount()
    trunc = build(syn[syn._i < cutoff].drop(columns=['_ts', '_i'])).set_index('observation_key')
    a = full.loc[trunc.index]
    return {c: ('PASS' if np.allclose(a[c].to_numpy(float), trunc[c].to_numpy(float), equal_nan=True, atol=1e-5)
                else 'FAIL') for c in NEW_COLUMNS}


def load() -> pd.DataFrame:
    return pd.read_parquet(OUT)


def attach(df: pd.DataFrame) -> pd.DataFrame:
    out = df.merge(load(), on='observation_key', how='left', validate='one_to_one')
    assert len(out) == len(df)
    return out


def main():
    ml = L.load_ml(with_targets=False)
    t = build(ml)
    t.to_parquet(OUT, index=False)
    print(f"wrote {OUT.relative_to(L.ROOT)}  {t.shape}")
    print(t.describe().T[['mean', 'min', 'max']].round(3).to_string())
    print('\nleakage verification (panels truncated at 30 snapshots, rebuilt, compared):')
    for c, r in verify(ml).items():
        print(f"  {c:<28} {r}")


if __name__ == '__main__':
    main()
