"""
stock_clock.py — derived feature table for the stock models (deliverables 4, 7, 8). Past-only.

    python -m src.features.stock_clock        # builds data/ml/stock_clock.parquet (~seconds)

    import src.features.stock_clock as SC
    df = SC.attach(L.load_ml())               # joins the new columns on observation_key

WHY THIS EXISTS
  The ML layer tracks how long a listing has been OUT of stock (`oos_run_length`) but not how long it
  has been IN stock. A duration-dependent stock-out process is driven by exactly that second clock,
  and nothing in the layer carries it. The store's demand pressure is also latent, and only
  per-row stock and ETA columns exist, so the model cannot see the whole store at once. This module adds both,
  plus the snapshot schedule, as a separate derived table. data/raw and the frozen ML files are not
  touched.

LEAKAGE CONVENTION (CLAUDE.md section 3.4)
  Every column uses data up to and INCLUDING t. The only forward-looking column is
  `next_snapshot_is_evening`, which comes from the published snapshot SCHEDULE (09:00 / 18:00
  alternate on every day), not from any observation at t+1. It is known before t+1 happens.
  `verify()` checks the leakage-sensitive columns by recomputing them on truncated panels.

LEFT CENSORING
  Panels start mid-life (the generator burns in 60 snapshots before the grid), so the in-stock clock
  of a listing that has not yet been seen out of stock is a LOWER BOUND. `instock_clock_censored`
  says so. Parameter-recovery checks must use uncensored runs only.
"""
from pathlib import Path

import numpy as np
import pandas as pd

import src.load as L

OUT = L.ML / 'stock_clock.parquet'
PANEL = ['data_status', 'platform', 'store_id', 'product_id']
NEW_COLUMNS = [
    'instock_run_length',          # consecutive in-stock snapshots up to and including t (0 if OOS)
    'instock_clock_censored',      # 1 = no OOS seen yet in this panel, so the clock is a lower bound
    'oos_spells_to_date',          # completed + current OOS spells seen so far
    'mean_oos_spell_to_date',      # mean length of COMPLETED OOS spells before t (NaN if none)
    'snapshots_since_restock',     # = instock_run_length when restock was observed, else NaN
    'store_oos_share',             # share of the store's listings OOS at t   (demand-pressure proxy)
    'store_oos_share_lag_1',
    'store_eta_mean',              # store's mean ETA at t                    (demand-pressure proxy)
    'store_eta_z',                 # store_eta_mean vs that store's own past mean, in past sd units
    'store_eta_delta',             # store_eta_mean(t) - store_eta_mean(t-1)
    'catplat_oos_share',           # share OOS at t for this platform x category, across all stores
    'next_snapshot_is_evening',    # schedule: the t+1 snapshot is the 18:00 one
    'store_pressure_index',        # latent store demand read off ETA: see _pressure_index
]


def _pressure_index(st: pd.DataFrame) -> pd.Series:
    """Store demand pressure recovered from delivery times, past-only.

    A store's mean promised ETA at t, minus that store's mean ETA at the SAME hour over snapshots
    strictly before t, removes the store's own level and the evening peak without estimating either.
    What is left is dominated by whatever moves a whole store's ETA at once. Scaled by the store's
    own past sd of that residual, so the index is in sd units. Needs 5 prior same-hour snapshots and
    5 prior residuals; NaN before that. Uses nothing after t.
    """
    st = st.copy()
    gh = st.groupby(['data_status', 'platform', 'store_id', 'hour'], sort=False).store_eta_min_mean
    n_h = gh.cumcount()
    prior_mean = (gh.cumsum() - st.store_eta_min_mean) / n_h.replace(0, np.nan)
    raw = np.where(n_h >= 5, st.store_eta_min_mean - prior_mean, np.nan)
    st['_raw'] = raw
    gs = st.groupby(['data_status', 'platform', 'store_id'], sort=False)._raw
    ok = st._raw.notna().astype(int)
    k = ok.groupby([st.data_status, st.platform, st.store_id], sort=False).cumsum() - ok
    x = st._raw.fillna(0)
    s1 = x.groupby([st.data_status, st.platform, st.store_id], sort=False).cumsum() - x
    s2 = (x ** 2).groupby([st.data_status, st.platform, st.store_id], sort=False).cumsum() - x ** 2
    mu = s1 / k.replace(0, np.nan)
    sd = np.sqrt((s2 / k.replace(0, np.nan) - mu ** 2).clip(lower=0)).replace(0, np.nan)
    del gs
    return pd.Series(np.where(k >= 5, st._raw / sd, np.nan), index=st.index)


def _ts(d):
    return pd.to_datetime(d.observed_at.astype(str), format='mixed')


def build(ml: pd.DataFrame | None = None) -> pd.DataFrame:
    d = (L.load_ml(with_targets=False) if ml is None else ml).copy()
    d['_ts'] = _ts(d)
    d = d.sort_values(PANEL + ['_ts'], kind='stable').reset_index(drop=True)
    g = d.groupby(PANEL, sort=False)

    inst = d.in_stock.astype(int)
    oos = 1 - inst
    new_panel = d[PANEL].ne(d[PANEL].shift()).any(axis=1)

    # ---- run blocks: a new block starts at a panel start or at a stock-state change
    block = (new_panel | inst.ne(inst.shift())).cumsum()
    run_pos = d.groupby(block).cumcount() + 1
    d['instock_run_length'] = np.where(inst == 1, run_pos, 0)

    seen_oos = oos.groupby([d[c] for c in PANEL], sort=False).cummax()
    # the clock is censored while the current in-stock run began at the panel's first snapshot
    run_started_at_panel_start = new_panel.groupby(block).transform('first')
    d['instock_clock_censored'] = ((inst == 1) & run_started_at_panel_start).astype(int)

    # ---- OOS spells
    spell_start = (oos == 1) & (new_panel | inst.shift().eq(1))
    d['oos_spells_to_date'] = spell_start.astype(int).groupby([d[c] for c in PANEL], sort=False).cumsum()
    # completed spell lengths: at the first in-stock row after a spell, record the spell's length
    spell_len_at_end = np.where((inst == 1) & ~new_panel & inst.shift().eq(0),
                                d.oos_run_length.shift().fillna(0), np.nan)
    spell_len_at_end = pd.Series(spell_len_at_end, index=d.index)
    # a spell that started at the panel start is left-censored: its length is a lower bound, drop it
    first_block_oos = (new_panel & (oos == 1)).groupby(block).transform('first')
    prev_block_censored = first_block_oos.shift().fillna(False).astype(bool)
    spell_len_at_end[prev_block_censored] = np.nan
    keys = [d[c] for c in PANEL]
    n_done = spell_len_at_end.notna().astype(int).groupby(keys, sort=False).cumsum()
    s_done = spell_len_at_end.fillna(0).groupby(keys, sort=False).cumsum()
    d['mean_oos_spell_to_date'] = np.where(n_done > 0, s_done / n_done.replace(0, np.nan), np.nan)
    d['snapshots_since_restock'] = np.where((inst == 1) & (d.instock_clock_censored == 0),
                                            d.instock_run_length, np.nan)
    del seen_oos

    # ---- store-level pressure at t (cross-section of the store at the same snapshot)
    st = (d.groupby(['data_status', 'platform', 'store_id', 'snapshot_id'], sort=False)
            .agg(store_oos_share=('in_stock', lambda s: 1 - s.mean()),
                 store_eta_mean=('eta_average', 'mean'),
                 store_eta_min_mean=('delivery_eta_min', 'mean'),
                 hour=('hour', 'first'), _ts=('_ts', 'first'))
            .reset_index().sort_values(['data_status', 'platform', 'store_id', '_ts']))
    st['store_pressure_index'] = _pressure_index(st)
    st = st.drop(columns=['store_eta_min_mean', 'hour'])
    sg = st.groupby(['data_status', 'platform', 'store_id'], sort=False)
    st['store_oos_share_lag_1'] = sg.store_oos_share.shift(1)
    st['store_eta_delta'] = st.store_eta_mean - sg.store_eta_mean.shift(1)
    # z vs the store's own history strictly BEFORE t (cumulative sums, native ops)
    c1 = sg.store_eta_mean.cumsum() - st.store_eta_mean
    c2 = sg.store_eta_mean.transform(lambda s: (s ** 2).cumsum()) - st.store_eta_mean ** 2
    k = sg.cumcount()
    mu = c1 / k.replace(0, np.nan)
    var = (c2 / k.replace(0, np.nan)) - mu ** 2
    sd = np.sqrt(var.clip(lower=0)).replace(0, np.nan)
    st['store_eta_z'] = np.where(k >= 3, (st.store_eta_mean - mu) / sd, np.nan)
    d = d.merge(st.drop(columns='_ts'), on=['data_status', 'platform', 'store_id', 'snapshot_id'],
                how='left', validate='many_to_one')

    cp = (d.groupby(['data_status', 'platform', 'category', 'snapshot_id'])
            .in_stock.mean().rsub(1).rename('catplat_oos_share').reset_index())
    d = d.merge(cp, on=['data_status', 'platform', 'category', 'snapshot_id'], how='left',
                validate='many_to_one')

    # ---- schedule: 09:00 and 18:00 alternate; the next snapshot after 09:00 is 18:00 and vice versa
    hour = pd.to_numeric(d.hour, errors='coerce')
    d['next_snapshot_is_evening'] = np.where(hour == 9, 1.0, np.where(hour == 18, 0.0, np.nan))

    out = d[['observation_key'] + NEW_COLUMNS].copy()
    for c in NEW_COLUMNS:
        out[c] = out[c].astype('float32')
    return out


def verify(ml: pd.DataFrame | None = None, cutoff_snapshots: int = 30) -> dict:
    """Leakage check: truncate every panel after `cutoff_snapshots`, rebuild, and require the columns
    at rows <= cutoff to be identical to the full build. If any column used t+1, it would differ."""
    full_ml = L.load_ml(with_targets=False) if ml is None else ml
    full = build(full_ml).set_index('observation_key')
    syn = full_ml[full_ml.data_status == 'SYNTHETIC'].copy()
    syn['_ts'] = _ts(syn)
    syn = syn.sort_values(PANEL + ['_ts'])
    syn['_i'] = syn.groupby(PANEL, sort=False).cumcount()
    cut = syn[syn._i < cutoff_snapshots].drop(columns=['_ts', '_i'])
    trunc = build(cut).set_index('observation_key')
    a, b = full.loc[trunc.index], trunc
    res = {}
    for c in NEW_COLUMNS:
        same = np.isclose(a[c].to_numpy(float), b[c].to_numpy(float), equal_nan=True, atol=1e-5)
        res[c] = 'PASS' if same.all() else f'FAIL ({(~same).sum()} rows differ)'
    return res


def load() -> pd.DataFrame:
    if not OUT.exists():
        raise FileNotFoundError(f"{OUT} missing. Run python -m src.features.stock_clock")
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
    print(t.describe().T[['count', 'mean', 'min', 'max']].round(3).to_string())
    print('\nleakage verification (panels truncated at 30 snapshots, rebuilt, compared):')
    for c, r in verify(ml).items():
        print(f"  {c:<28} {r}")


if __name__ == '__main__':
    main()
