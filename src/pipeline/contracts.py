"""
contracts.py — the data contracts: every invariant the models rely on, checked as one gate before any model runs.

    python -m src.pipeline.contracts            # -> outputs/run_log/contracts.json; exit 1 if any contract is broken
    python -m src.pipeline.contracts --list     # the contracts, with where each rule is written down

WHY
  The rules in CLAUDE.md (composition, provenance on every row, the structural NULLs, past-only features, a
  chronological split) were each enforced by a test, and the tests run at the END of `scripts/run_all.py`. A broken
  ML layer was therefore found only after forty steps had fitted models on it. run_all.py now runs this module right
  after the data layer is built, and every model step depends on it: a broken contract blocks them instead.

A CONTRACT is one rule, the place it is written down, and a check that returns (holds, what was observed). The check
reads the frames it needs from a lazy context, so the gate loads raw, ML and the two derived tables once each.
Nothing here writes data: the output is the report only.

Contracts complement the tests, they do not replace them. The regression check on the cheapest platform
(tests/test_regression_cheapest.py) and the sha256 baseline of data/raw (scripts/verify_raw_integrity.py, its own
pipeline step) are not repeated here.
"""
import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import src.load as L  # noqa: E402

OUT = ROOT / 'outputs' / 'run_log' / 'contracts.json'
PANEL = ['platform', 'store_id', 'product_id']
PROVENANCE = ['source', 'price_provenance', 'enrichment_provenance', 'data_status', 'is_real_observation']
# CLAUDE.md §2: rows per platform and data_status
COMPOSITION = {('Blinkit', 'REAL'): 21_949, ('Blinkit', 'SYNTHETIC'): 148_740, ('Swiggy Instamart', 'SYNTHETIC'): 150_480,
               ('Flipkart Minutes', 'SYNTHETIC'): 142_320, ('BigBasket', 'SYNTHETIC'): 147_300}
ROWS, RAW_COLS, ML_COLS = 610_789, 51, 116
OBSERVED_DAY = '2026-07-10'
STORE_PREFIX = {'Blinkit': 'BLK', 'Swiggy Instamart': 'INS', 'Flipkart Minutes': 'FKM', 'BigBasket': 'BGB'}
STORES = {'Blinkit': 8, 'Swiggy Instamart': 10, 'Flipkart Minutes': 6, 'BigBasket': 6}                    # 30 in all
MRP_SOURCES = {'observed_distinct', 'observed_at_mrp', 'assumed_equal_to_selling_price',
               'invalid_source_mrp_below_selling_price_set_to_selling_price', 'simulated_discounted', 'simulated_at_mrp'}
MRP_FILLED = {'assumed_equal_to_selling_price', 'invalid_source_mrp_below_selling_price_set_to_selling_price'}
LEAKY_NAMES = ['price_min', 'price_max', 'price_avg', 'price_median', 'price_volatility']   # §3.4: removed for good
CHECK_HOURS = {9, 18}                                                                       # the published schedule


class Context:
    """The frames a check may ask for, each loaded once. Tests pass their own frames in `given`."""

    def __init__(self, given: dict | None = None):
        self._f = dict(given or {})

    def __getitem__(self, name: str) -> pd.DataFrame:
        if name not in self._f:
            self._f[name] = {'raw': L.load_raw, 'ml': L.load_ml,
                             'stock_clock': lambda: pd.read_parquet(L.ML / 'stock_clock.parquet'),
                             'price_grid': lambda: pd.read_parquet(L.ML / 'price_grid.parquet')}[name]()
        return self._f[name]


@dataclass(frozen=True)
class Contract:
    id: str
    layer: str
    rule: str
    ref: str
    check: Callable[[Context], tuple[bool, str]]


def _n(x) -> str:
    return f'{int(x):,}'


def _ordered(df: pd.DataFrame) -> pd.DataFrame:
    """Rows in panel order: by panel, then by when they were observed (mixed timestamp formats, CLAUDE.md §7)."""
    d = df.assign(_ts=pd.to_datetime(df['observed_at'], format='mixed', errors='coerce'))
    return d.sort_values(['data_status'] + PANEL + ['_ts'], kind='stable')


# =========================================================================== raw
def raw_shape(c):
    r = c['raw']
    return len(r) == ROWS and r.shape[1] == RAW_COLS, f'{_n(len(r))} rows x {r.shape[1]} columns'


def raw_key_unique(c):
    dup = int(c['raw'].observation_key.duplicated().sum())
    return dup == 0, f'{_n(dup)} duplicated observation keys'


def raw_composition(c):
    got = c['raw'].groupby(['platform', 'data_status']).size().to_dict()
    off = {f'{p} {s}': f'{_n(got.get((p, s), 0))} (want {_n(want)})' for (p, s), want in COMPOSITION.items()
           if got.get((p, s), 0) != want}
    extra = sorted(f'{p} {s}' for p, s in got if (p, s) not in COMPOSITION)
    ok = not off and not extra
    return ok, 'every platform and label matches the documented count' if ok else f'off: {off}; unexpected: {extra}'


def raw_provenance(c):
    r = c['raw']
    missing = [col for col in PROVENANCE if col not in r.columns]
    if missing:
        return False, f'missing columns: {missing}'
    nulls = {col: int(r[col].isna().sum()) for col in PROVENANCE if r[col].isna().any()}
    return not nulls, f'{len(PROVENANCE)} provenance columns, no nulls' if not nulls else f'nulls: {nulls}'


def raw_labels_agree(c):
    r = c['raw']
    real = r.data_status.eq('REAL')
    bad_status = int((~r.data_status.isin(['REAL', 'SYNTHETIC'])).sum())
    bad_flag = int((r.is_real_observation.eq(1) != real).sum())
    bad_price = int((r.price_provenance.eq('observed') != real).sum())
    ok = bad_status == bad_flag == bad_price == 0
    return ok, (f'{_n(bad_status)} unknown labels, {_n(bad_flag)} flag disagreements, '
                f'{_n(bad_price)} price-provenance disagreements')


def raw_observed_day(c):
    real = c['raw'][c['raw'].data_status.eq('REAL')]
    plats, days = sorted(real.platform.unique()), sorted(real.snapshot_date.astype(str).unique())
    return plats == ['Blinkit'] and days == [OBSERVED_DAY], f'observed rows: platforms {plats}, dates {days}'


def raw_sentinels(c):
    real = c['raw'][c['raw'].data_status.eq('REAL')]
    t = int(real.snapshot_time.ne('NOT_RECORDED').sum())
    h = int(real.hour.ne(-1).sum())
    return t == h == 0, f'{_n(t)} observed rows with an invented time, {_n(h)} with an invented hour'


def raw_schedule(c):
    syn = c['raw'][c['raw'].data_status.eq('SYNTHETIC')]
    hours = sorted(int(x) for x in syn.hour.unique())
    return set(hours) <= CHECK_HOURS, f'simulated checks at hours {hours}'


def raw_prices(c):
    r = c['raw']
    nonpos = int((r.selling_price <= 0).sum())
    below = int((r.mrp < r.selling_price - 1e-9).sum())
    disc = int((~r.discount_percent.between(0, 100, inclusive='left')).sum())
    ok = nonpos == below == disc == 0
    return ok, f'{_n(nonpos)} non-positive prices, {_n(below)} MRP below price, {_n(disc)} discounts outside [0, 100)'


def raw_mrp_source(c):
    r = c['raw']
    unknown = sorted(set(r.mrp_source.dropna().unique()) - MRP_SOURCES)
    filled = r[r.mrp_source.isin(MRP_FILLED)]
    not_equal = int(((filled.mrp - filled.selling_price).abs() > 1e-9).sum())
    return not unknown and not_equal == 0, (f'unknown sources {unknown}; {_n(not_equal)} filled MRPs that differ from '
                                            f'the price (the fill must stay reversible)')


def raw_stock_flag(c):
    r = c['raw']
    odd = sorted(set(r.stock_status.unique()) - {'Available', 'Out of Stock'})
    bad = int((r.in_stock.eq(1) != r.stock_status.eq('Available')).sum())
    return not odd and bad == 0, f'unexpected statuses {odd}; {_n(bad)} rows where in_stock disagrees with the status'


def raw_eta(c):
    r = c['raw']
    bad = int(((r.delivery_eta_min <= 0) | (r.delivery_eta_max < r.delivery_eta_min)).sum())
    return bad == 0, f'{_n(bad)} rows with ETA min <= 0 or max < min (range {r.delivery_eta_min.min()}-{r.delivery_eta_max.max()} min)'


def raw_stores(c):
    r = c['raw']
    per = r.groupby('platform').store_id.nunique().to_dict()
    off = {p: f'{n} (want {STORES[p]})' for p, n in per.items() if n != STORES.get(p)}
    prefix = r.platform.map(STORE_PREFIX)
    pat = r.store_id.str.fullmatch(r'(BLK|INS|FKM|BGB)-BBSR-\d{3}')
    wrong = int((~pat | (r.store_id.str[:3] != prefix)).sum())
    return not off and wrong == 0, (f'{sum(per.values())} stores{f", off: {off}" if off else ""}; '
                                    f'{_n(wrong)} ids off the pattern or on the wrong platform')


# =========================================================================== ML layer
def ml_shape(c):
    m, r = c['ml'], c['raw']
    same = len(m) == len(r) and set(m.observation_key) == set(r.observation_key)
    return same and m.shape[1] == ML_COLS and m.observation_key.is_unique, \
        f'{_n(len(m))} rows x {m.shape[1]} columns, key set {"equals" if same else "differs from"} raw'


def ml_splits(c):
    m = c['ml']
    odd = sorted(set(m.split.unique()) - set(L.SPLITS))
    mism = int((m.split.eq('holdout_real') != m.data_status.eq('REAL')).sum())
    return not odd and mism == 0, f'unknown splits {odd}; {_n(mism)} rows where the holdout and the observed rows differ'


def ml_chronological(c):
    m = c['ml']
    d = m.assign(_d=pd.to_datetime(m.snapshot_date.astype(str), errors='coerce')).groupby('split')._d.agg(['min', 'max'])
    ok = d.loc['train', 'max'] < d.loc['val', 'min'] and d.loc['val', 'max'] < d.loc['test', 'min']
    span = ', '.join(f'{s} {d.loc[s, "min"]:%d %b}-{d.loc[s, "max"]:%d %b}' for s in ('train', 'val', 'test'))
    return bool(ok), span


def ml_past_only(c):
    m = c['ml']
    x = m[m.price_min_to_date.notna() & m.price_max_to_date.notna()]
    lo = int((x.price_min_to_date > x.selling_price + 1e-9).sum())
    hi = int((x.price_max_to_date < x.selling_price - 1e-9).sum())
    return lo == hi == 0, f'{_n(lo)} rows whose to-date minimum is above today\'s price, {_n(hi)} whose maximum is below it'


def ml_no_leaky_names(c):
    back = [col for col in LEAKY_NAMES if col in c['ml'].columns]
    return not back, f'leaky whole-panel columns present: {back}' if back else 'none of the five removed columns is back'


def ml_structural_nulls(c):
    d = _ordered(c['ml'][['observation_key', 'observed_at', 'data_status', 'price_lag_1', 'future_price'] + PANEL])
    g = d.groupby(['data_status'] + PANEL, sort=False, observed=True)
    first = g.cumcount().eq(0)
    last = g.cumcount(ascending=False).eq(0)
    lag_bad = int((d.price_lag_1.isna() != first).sum())
    fut_bad = int((d.future_price.isna() != last).sum())
    return lag_bad == fut_bad == 0, (f'{_n(first.sum())} panels: {_n(lag_bad)} rows where price_lag_1 is null off the '
                                     f'panel start or filled on it, {_n(fut_bad)} likewise for future_price at the end')


# =========================================================================== derived tables
def _derived(name: str, ncols: int):
    """A derived table: keyed on observation_key, `ncols` columns besides the key (the count CLAUDE.md §11 gives)."""
    def check(c):
        t, keys = c[name], c['ml'].observation_key
        unique = t.observation_key.is_unique
        orphans = int((~t.observation_key.isin(keys)).sum())
        return unique and orphans == 0 and t.shape[1] - 1 == ncols, \
            f'{_n(len(t))} rows x {t.shape[1] - 1} columns + key, keys {"unique" if unique else "repeated"}, {_n(orphans)} not in the ML layer'
    return check


CONTRACTS = [
    Contract('raw.shape', 'raw', f'{ROWS:,} rows x {RAW_COLS} columns', 'CLAUDE.md §1, §3.8', raw_shape),
    Contract('raw.key_unique', 'raw', 'observation_key is unique: it is the row key', 'CLAUDE.md §3.3', raw_key_unique),
    Contract('raw.composition', 'raw', 'rows per platform and data label match the documented table', 'CLAUDE.md §2', raw_composition),
    Contract('raw.provenance', 'raw', 'the five provenance columns are on every row', 'CLAUDE.md §2', raw_provenance),
    Contract('raw.labels_agree', 'raw', 'the data label, the observation flag and the price provenance agree on every row',
             'CLAUDE.md §2', raw_labels_agree),
    Contract('raw.observed_day', 'raw', 'observed rows are Blinkit on 2026-07-10 only: there is no observed history',
             'CLAUDE.md §3.1', raw_observed_day),
    Contract('raw.sentinels', 'raw', 'the observed day keeps its unrecorded time and hour (never imputed)',
             'CLAUDE.md §3.6', raw_sentinels),
    Contract('raw.schedule', 'raw', 'simulated checks sit at the published morning and evening hours',
             'data/reference schedule', raw_schedule),
    Contract('raw.prices', 'raw', 'prices are positive, MRP is never below the price, discounts lie in [0, 100)',
             'CLAUDE.md §3.5', raw_prices),
    Contract('raw.mrp_source', 'raw', 'mrp_source is one of six documented values and every filled MRP equals the price',
             'CLAUDE.md §3.5', raw_mrp_source),
    Contract('raw.stock_flag', 'raw', 'in_stock agrees with stock_status', 'docs/DATA_ACCESS.md', raw_stock_flag),
    Contract('raw.eta', 'raw', 'delivery ETA is positive and its minimum never exceeds its maximum', 'docs/DATA_ACCESS.md', raw_eta),
    Contract('raw.stores', 'raw', '30 stores (8 / 10 / 6 / 6 by platform), each id on its own platform\'s pattern',
             'CLAUDE.md §3.8', raw_stores),
    Contract('ml.shape', 'ml', f'the ML layer has the raw rows and keys, {ML_COLS} columns (109 + 7 targets)', 'CLAUDE.md §5', ml_shape),
    Contract('ml.splits', 'ml', 'split is train / val / test / holdout_real, and the holdout is exactly the observed rows',
             'CLAUDE.md §6', ml_splits),
    Contract('ml.chronological', 'ml', 'train ends before val starts, val ends before test starts', 'CLAUDE.md §6', ml_chronological),
    Contract('ml.past_only', 'ml', 'to-date price bounds contain today\'s price: no feature sees t+1', 'CLAUDE.md §3.4', ml_past_only),
    Contract('ml.no_leaky_names', 'ml', 'the five whole-panel columns that leaked stay removed', 'CLAUDE.md §3.4', ml_no_leaky_names),
    Contract('ml.structural_nulls', 'ml', 'price_lag_1 is null exactly at each panel start, future_price exactly at its end',
             'CLAUDE.md §3.6', ml_structural_nulls),
    Contract('derived.stock_clock', 'derived', 'stock-clock table: one row per ML key, 13 columns besides the key',
             'CLAUDE.md §11', _derived('stock_clock', 13)),
    Contract('derived.price_grid', 'derived', 'price-grid table: one row per ML key, 8 columns besides the key',
             'CLAUDE.md §11', _derived('price_grid', 8)),
]


def run(ctx: Context | None = None, only=None) -> list[dict]:
    """Every contract (or those whose id is in `only`) against the context; a check that raises is a broken contract."""
    ctx = ctx or Context()
    out = []
    for k in CONTRACTS:
        if only and k.id not in only:
            continue
        t0 = time.time()
        try:
            ok, seen = k.check(ctx)
        except Exception as e:                                      # a missing column or table breaks the contract
            ok, seen = False, f'could not be checked: {type(e).__name__}: {e}'
        out.append({'id': k.id, 'layer': k.layer, 'rule': k.rule, 'ref': k.ref, 'ok': bool(ok), 'observed': seen,
                    'seconds': round(time.time() - t0, 2)})
    return out


def report(results: list[dict], seconds: float) -> dict:
    return {'checked_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'ok': all(r['ok'] for r in results),
            'passed': sum(r['ok'] for r in results), 'failed': sum(not r['ok'] for r in results),
            'seconds': round(seconds, 1), 'contracts': results}


def main():
    ap = argparse.ArgumentParser(description='Check the data contracts the models rely on.')
    ap.add_argument('--list', action='store_true', help='list the contracts and exit')
    a = ap.parse_args()
    if a.list:
        for k in CONTRACTS:
            print(f'{k.id:<22} {k.rule}   [{k.ref}]')
        return 0
    t0 = time.time()
    results = run()
    doc = report(results, time.time() - t0)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding='utf-8', newline='\n')
    for r in results:
        print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['id']:<22} {r['observed']}")
    print(f"\n{doc['passed']}/{len(results)} contracts hold ({doc['seconds']} s) -> {OUT.relative_to(ROOT)}")
    return 0 if doc['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
