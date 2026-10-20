"""
patch_raw_v2.py — three corrections to data/raw/Blinkit_RAW.parquet (REAL rows only), applied once.

Run from the project root:   python -m src.pipeline.patch_raw_v2
Idempotent: if every target cell already holds its corrected value, nothing is written.
Aborts without writing if any target row is not in the exact state this patch expects.
No other platform file is opened. Receipt and reasoning: data/raw/PATCH_LOG.md (v2 section).

All evidence is embedded below, so the patch does not depend on files outside the repo.

------------------------------------------------------------------------------
FIX 2a — mrp_source on the 4 unnamed REAL listings            confidence: INFERRED (high)

  MASTER-15606, MASTER-15609, MASTER-16464, MASTER-18803.
  v1 labelled them 'selling_price_assumed_equal_to_mrp' (selling price copied from MRP).
  These 4 rows are NOT in Blinkit_REAL_v7.xlsx, so the direction cannot be proven for them.
  The inference comes from Blinkit_Master_FINAL_Clean_v2.xlsx :: MASTER_PRODUCTS, where these
  rows do carry a Selling Price, and where — across the other 21,945 real rows — Selling Price
  matches v7 on 21,945/21,945 while MRP equals Selling Price on all 20,892 rows whose v7 MRP was
  absent. I.e. in that source MRP was filled FROM selling price. Relabelled to the same value
  the other filled rows carry: 'assumed_equal_to_selling_price'. No value changes.

FIX 2b — delivery_eta_min / delivery_eta_max on the same 4 rows   confidence: CONFIRMED

  Raw had 9/9 on all four. Blinkit_Master_FINAL_Clean_v2.xlsx (MASTER_PRODUCTS and the
  2026-07-10 rows of PRODUCT_SNAPSHOTS) gives ETA '8 mins', '8 mins', '11 mins', '11 mins'.
  The same source's ETA equals raw delivery_eta_min on all 21,945 other real rows.
  Real-row rule (unchanged): the source shows a point ETA, so eta_max = eta_min.

FIX 2c — mrp_source on 33 REAL rows with an invalid source MRP  confidence: LABEL-ONLY

  Blinkit_REAL_v7.xlsx carried an MRP on these rows, but it was LOWER than the selling price
  (e.g. MRP 80, selling price 370). The fill pass set mrp = selling_price and labelled them
  'assumed_equal_to_selling_price', which claims MRP was absent. It was present but invalid.
  Relabelled to 'invalid_source_mrp_below_selling_price_set_to_selling_price'.
  mrp, selling_price and discount_percent are NOT changed.
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
FILE = ROOT / 'data' / 'raw' / 'Blinkit_RAW.parquet'

OLD_2A = 'selling_price_assumed_equal_to_mrp'
NEW_2A = 'assumed_equal_to_selling_price'
OLD_2C = 'assumed_equal_to_selling_price'
NEW_2C = 'invalid_source_mrp_below_selling_price_set_to_selling_price'

# observation_key -> source ETA in minutes (Blinkit_Master_FINAL_Clean_v2.xlsx :: MASTER_PRODUCTS)
UNNAMED_ETA = {
    'BASELINE_2026-07-10 | BBSR-003 | MASTER-15606': 8,
    'BASELINE_2026-07-10 | BBSR-003 | MASTER-15609': 8,
    'BASELINE_2026-07-10 | BBSR-007 | MASTER-16464': 11,
    'BASELINE_2026-07-10 | BBSR-007 | MASTER-18803': 11,
}

# observation_key -> (source MRP, source selling_price) from Blinkit_REAL_v7.xlsx :: OBSERVATIONS
INVALID_MRP = {
    'BASELINE_2026-07-10 | BBSR-001 | MASTER-19857': (155, 189),
    'BASELINE_2026-07-10 | BBSR-002 | MASTER-19867': (159, 249),
    'BASELINE_2026-07-10 | BBSR-002 | MASTER-19896': (60, 180),
    'BASELINE_2026-07-10 | BBSR-002 | MASTER-19905': (165, 405),
    'BASELINE_2026-07-10 | BBSR-003 | MASTER-19849': (90, 249),
    'BASELINE_2026-07-10 | BBSR-003 | MASTER-19865': (80, 370),
    'BASELINE_2026-07-10 | BBSR-003 | MASTER-19907': (165, 311),
    'BASELINE_2026-07-10 | BBSR-003 | MASTER-19910': (150, 450),
    'BASELINE_2026-07-10 | BBSR-003 | MASTER-19929': (130, 135),
    'BASELINE_2026-07-10 | BBSR-004 | MASTER-01866': (20, 40),
    'BASELINE_2026-07-10 | BBSR-004 | MASTER-19820': (70, 80),
    'BASELINE_2026-07-10 | BBSR-004 | MASTER-19840': (80, 370),
    'BASELINE_2026-07-10 | BBSR-004 | MASTER-19848': (249, 370),
    'BASELINE_2026-07-10 | BBSR-005 | MASTER-01863': (25, 30),
    'BASELINE_2026-07-10 | BBSR-005 | MASTER-19844': (70, 269),
    'BASELINE_2026-07-10 | BBSR-005 | MASTER-19899': (180, 405),
    'BASELINE_2026-07-10 | BBSR-005 | MASTER-19909': (450, 1280),
    'BASELINE_2026-07-10 | BBSR-007 | MASTER-19901': (249, 370),
    'BASELINE_2026-07-10 | BBSR-007 | MASTER-19913': (120, 198),
    'BASELINE_2026-07-10 | BBSR-008 | MASTER-01862': (20, 30),
    'BASELINE_2026-07-10 | BBSR-008 | MASTER-19846': (70, 370),
    'BASELINE_2026-07-10 | BBSR-008 | MASTER-19850': (53, 90),
    'BASELINE_2026-07-10 | BBSR-008 | MASTER-19853': (215, 265),
    'BASELINE_2026-07-10 | BBSR-008 | MASTER-19859': (189, 370),
    'BASELINE_2026-07-10 | BBSR-008 | MASTER-19861': (215, 370),
    'BASELINE_2026-07-10 | BBSR-008 | MASTER-19870': (45, 265),
    'BASELINE_2026-07-10 | BBSR-008 | MASTER-19873': (149, 409),
    'BASELINE_2026-07-10 | BBSR-008 | MASTER-19881': (265, 295),
    'BASELINE_2026-07-10 | BBSR-008 | MASTER-19885': (99, 249),
    'BASELINE_2026-07-10 | BBSR-008 | MASTER-19892': (150, 399),
    'BASELINE_2026-07-10 | BBSR-008 | MASTER-19902': (60, 249),
    'BASELINE_2026-07-10 | BBSR-008 | MASTER-19912': (198, 249),
    'BASELINE_2026-07-10 | BBSR-008 | MASTER-19927': (135, 360),
}

TOUCHED = {'mrp_source', 'delivery_eta_min', 'delivery_eta_max'}


def main():
    orig = pd.read_parquet(FILE)
    d = orig.copy()
    key = d.observation_key.astype(str)

    ua = key.isin(UNNAMED_ETA)
    ic = key.isin(INVALID_MRP)
    assert int(ua.sum()) == 4 and int(ic.sum()) == 33, "target rows not found — aborting"
    assert not (ua & ic).any()
    assert d.loc[ua | ic, 'data_status'].eq('REAL').all(), "a target row is not REAL — aborting"

    want_eta = key[ua].map(UNNAMED_ETA)
    done = (d.loc[ua, 'mrp_source'].eq(NEW_2A).all()
            and d.loc[ua, 'delivery_eta_min'].eq(want_eta).all()
            and d.loc[ua, 'delivery_eta_max'].eq(want_eta).all()
            and d.loc[ic, 'mrp_source'].eq(NEW_2C).all())
    if done:
        print("patch v2 already applied — nothing to do")
        return

    # ---- preconditions: exactly the state v1 left behind ----
    assert d.loc[ua, 'mrp_source'].eq(OLD_2A).all(), "2a precondition failed"
    assert d.loc[ua, ['delivery_eta_min', 'delivery_eta_max']].eq(9).all().all(), "2b precondition failed"
    assert d.loc[ic, 'mrp_source'].eq(OLD_2C).all(), "2c precondition failed"
    src = pd.DataFrame(INVALID_MRP, index=['src_mrp', 'src_sp']).T.reindex(key[ic]).to_numpy()
    assert (d.loc[ic, 'selling_price'].to_numpy() == src[:, 1]).all(), "2c selling_price != source"
    assert (src[:, 0] < src[:, 1]).all(), "2c source MRP not below selling price"
    assert d.loc[ic, 'mrp'].eq(d.loc[ic, 'selling_price']).all(), "2c mrp != selling_price"

    # ---- apply ----
    d.loc[ua, 'mrp_source'] = NEW_2A
    d.loc[ua, 'delivery_eta_min'] = want_eta.astype(orig.delivery_eta_min.dtype)
    d.loc[ua, 'delivery_eta_max'] = want_eta.astype(orig.delivery_eta_max.dtype)
    d.loc[ic, 'mrp_source'] = NEW_2C

    # ---- verify before writing ----
    assert len(d) == len(orig) and list(d.columns) == list(orig.columns)
    for c in orig.columns:
        assert d[c].dtype == orig[c].dtype, f"dtype changed on {c}"
        if c not in TOUCHED:
            assert d[c].equals(orig[c]), f"untouched column {c} changed"
        else:
            changed = ~(d[c].astype(str) == orig[c].astype(str))
            assert not (changed & ~(ua | ic)).any(), f"{c} changed outside target rows"

    d.to_parquet(FILE, compression='zstd', index=False)
    print(f"{FILE.name}: 2a mrp_source relabelled on {int(ua.sum())} rows, "
          f"2b ETA corrected on {int(ua.sum())} rows, 2c mrp_source relabelled on {int(ic.sum())} rows")


if __name__ == '__main__':
    main()
