"""
diagnostics.py — shared measurement code for the generator audit and tests. No models.

Stock series are panel x time matrices of in_stock (1/0), one row per (platform, store_id, product_id),
columns in chronological order.
"""
import numpy as np
import pandas as pd

PANEL = ['platform', 'store_id', 'product_id']


def stock_matrix(df: pd.DataFrame) -> np.ndarray:
    """in_stock as a panel x time matrix. Every panel must have the same number of snapshots."""
    d = df.sort_values(PANEL + ['observed_at'])
    n = d.groupby(PANEL, sort=False, observed=True).ngroups
    return d.in_stock.to_numpy().astype(int).reshape(n, -1)


def run_length_hazard(ins: np.ndarray, max_run: int = 10, exclude_left_censored: bool = True):
    """P(out of stock at t+1 | in stock at t with run length r), r = 1..max_run.

    exclude_left_censored=True drops in-stock spells already running at the first observed snapshot:
    their true run length is unknown, and counting them as run 1 inflates h(1) and hides duration
    dependence (the naive estimator reported a ratio of 2.4 where the uncensored one reports 13).
    Validated 2026-09-17: ~1.0 on homogeneous i.i.d. stock; below 1 under between-item heterogeneity
    (high-hazard items leave the risk set first), i.e. conservative, never inflated.

    Returns (hazard array, at-risk counts).
    """
    n, T = ins.shape
    run = np.zeros_like(ins)
    cens = np.zeros(ins.shape, dtype=bool)
    for t in range(T):
        prev_run = run[:, t - 1] if t else np.zeros(n, dtype=ins.dtype)
        prev_c = cens[:, t - 1] if t else np.zeros(n, dtype=bool)
        run[:, t] = np.where(ins[:, t] == 1, prev_run + 1, 0)
        cens[:, t] = (ins[:, t] == 1) & np.where(prev_run > 0, prev_c, t == 0)
    out_next = ins[:, 1:] == 0
    R, C = run[:, :-1], cens[:, :-1]
    keep = ~C if exclude_left_censored else np.ones_like(C)
    h = np.array([out_next[(R == r) & keep].mean() for r in range(1, max_run + 1)])
    at_risk = np.array([int(((R == r) & keep).sum()) for r in range(1, max_run + 1)])
    return h, at_risk


def completed_oos_spells(ins: np.ndarray):
    """Lengths of out-of-stock spells that both started and ended inside the window.
    Returns (lengths, panel row index of each spell)."""
    lengths, rows = [], []
    count = np.zeros(ins.shape[0], dtype=int)
    seen_in = ins[:, 0] == 1
    for t in range(1, ins.shape[1]):
        back = (ins[:, t] == 1) & (count > 0) & seen_in
        idx = np.flatnonzero(back)
        lengths.extend(count[idx]); rows.extend(idx)
        count = np.where(ins[:, t] == 0, count + 1, 0)
        seen_in |= ins[:, t] == 1
    return np.array(lengths), np.array(rows)


PRICE_BANDS = [(0, 20, '<20'), (20, 100, '20-99'), (100, 500, '100-499'), (500, float('inf'), '500+')]


def last_digit_distance(prices, reference) -> dict:
    """Total-variation distance (0-100 points) between last-digit distributions of whole-rupee prices,
    overall and per price band, plus the share ending in 0/5/9."""
    p, r = np.asarray(prices, float), np.asarray(reference, float)

    def tv(a, b):
        pa = np.bincount(np.round(a).astype(int) % 10, minlength=10) / max(len(a), 1)
        pb = np.bincount(np.round(b).astype(int) % 10, minlength=10) / max(len(b), 1)
        return round(float(50 * np.abs(pa - pb).sum()), 2)

    out = {'ALL': tv(p, r)}
    for lo, hi, lab in PRICE_BANDS:
        out[lab] = tv(p[(p >= lo) & (p < hi)], r[(r >= lo) & (r < hi)])
    out['share_end_0_5_9_pct'] = round(float(100 * np.isin(np.round(p).astype(int) % 10, [0, 5, 9]).mean()), 2)
    out['integer_share'] = round(float(np.isclose(p, np.round(p)).mean()), 4)
    return out


def tied_minimum_share(df: pd.DataFrame) -> float:
    """Share of (snapshot, product) groups in the common panel whose minimum price is shared by 2+ platforms."""
    c = df[df.in_common_panel == 1]
    keys = [c.snapshot_id, c.canonical_product_key]
    mn = c.groupby(keys, observed=True).selling_price.transform('min')
    at_min = (c.selling_price == mn).groupby(keys, observed=True).sum()
    return float((at_min > 1).mean())
