# RAW patch v1 — 2026-09-17

> **Status: applied AFTER the raw layer was declared frozen. Script is archival.**
>
> - **Timing.** The project was shipped with `data/raw/` already marked FROZEN
>   (`data/README.md`, `README.md`; archive files dated 2026-09-17 00:19–00:21).
>   This patch ran later the same day, against those frozen files. It is a
>   deliberate, documented exception to the freeze, not part of the original build.
> - **Re-running.** `patch_raw_v1.py` is idempotent: it skips any file that already
>   has `store_id_source`. A second run on 2026-09-17 was verified to change nothing
>   and to leave this log untouched. So re-running it on current data is harmless —
>   but there is no reason to. Treat it as an archival record of what was done.
>   Do not run it against a pre-patch copy of raw expecting to reproduce the frozen
>   hashes; that has not been verified.
> - **Frozen baseline now.** Post-patch parquet hashes are checked by
>   `make verify-raw` (`scripts/verify_raw_integrity.py`).

Script: `src/pipeline/patch_raw_v1.py` (the docstring explains each fix).

- `BigBasket_RAW.parquet`: 0 store_id relabelled, 0 unnamed-listing rows corrected
- `Blinkit_RAW.parquet`: 21,949 store_id relabelled, 4 unnamed-listing rows corrected
- `FlipkartMinutes_RAW.parquet`: 0 store_id relabelled, 0 unnamed-listing rows corrected
- `Instamart_RAW.parquet`: 0 store_id relabelled, 0 unnamed-listing rows corrected
- `STORES.csv`: added `store_id_source`; 0 store_id relabelled; truncated store names repaired
- `CANONICAL_KEY_AUDIT.csv`: added `store_id_source`; 2,419 store_id relabelled

store_id rows relabelled: 21,949
unnamed-listing rows corrected: 4

### Correction to the v1 counts above (added 2026-09-17)

The v1 receipt above under-reports what v1 changed. It counted `store_id` relabels and
unnamed-listing rows only; it did not count the **store_name repair**, which v1 applied
to every platform file, not just Blinkit. A cell-by-cell diff against the pre-patch
parquet (from `quickcommerce-mi.zip`) shows v1 also renamed:

| File | Rows | data_status | Change |
|---|---|---|---|
| `Blinkit_RAW.parquet` | 38,100 | SYNTHETIC | `store_name` repaired: 'Niladri Medical Store' (18,060) and 'Sanjivani Medicine Store' (20,040) → full names |
| `Instamart_RAW.parquet` | 16,620 | SYNTHETIC | `store_name` of `INS-BBSR-007`: 'Niladri Medical Store' → 'Niladri Medical Store, In Front Of Utsav Enclave' |

So the corrected v1 totals are: `Blinkit_RAW.parquet` 60,049 rows changed (21,949 REAL
store_id relabels, 4 of which also had unnamed-listing fixes; 38,100 SYNTHETIC store_name
repairs) and `Instamart_RAW.parquet` 16,620 rows changed, not 0. FlipkartMinutes and
BigBasket: 0 cell changes (new `store_id_source` column only).

The Instamart rename was not intended by v1, but it is accurate: `STORES_Instamart.csv`
gives INS-BBSR-007's address as "Niladri Medical Store, In Front Of Utsav Enclave,
Bhubaneswar, Odisha, 751021". No `selling_price`, `mrp`, `stock_status`, `in_stock` or
`discount_percent` value changed on any row of any platform in v1.

Original store ids preserved in `store_id_source`. `observation_key` intentionally keeps the original BBSR-00N form on real rows.
No observation value was altered by Fix 1; Fix 2 removed fabricated pack fields and corrected one mislabelled `mrp_source`.

---

# RAW patch v2 — 2026-09-17

Script: `src/pipeline/patch_raw_v2.py` (evidence embedded; no external files needed to re-run).
Applied to `Blinkit_RAW.parquet` only, REAL rows only. Idempotent (second run verified: no-op).
Like v1, applied after the raw layer was declared frozen — a documented exception.

**Verified by cell-by-cell diff against the pre-v2 parquet:** 37 rows changed, all REAL,
all Blinkit. Columns changed: `mrp_source` (37 rows), `delivery_eta_min` (4), `delivery_eta_max` (4).
No other column, row or platform file changed. No dtype changed.
`mrp`, `selling_price`, `discount_percent`, `stock_status` unchanged on every row.

| Fix | Rows | Column(s) | Before → after | Confidence |
|---|---|---|---|---|
| 2a | 4 (unnamed listings) | `mrp_source` | `selling_price_assumed_equal_to_mrp` → `assumed_equal_to_selling_price` | **Inferred** (high confidence, not proven) |
| 2b | same 4 | `delivery_eta_min`, `delivery_eta_max` | 9/9 → 8/8, 8/8, 11/11, 11/11 | **Confirmed** against source |
| 2c | 33 | `mrp_source` | `assumed_equal_to_selling_price` → `invalid_source_mrp_below_selling_price_set_to_selling_price` | **Label-only** correction, no value change |

### 2a — evidence (inferred)
The 4 unnamed listings (MASTER-15606, -15609, -16464, -18803) are **not present in
`Blinkit_REAL_v7.xlsx`**, so which of MRP / selling price was observed cannot be proven for
these specific rows. The relabel is inferred from `Blinkit_Master_FINAL_Clean_v2.xlsx ::
MASTER_PRODUCTS`, where these rows carry a Selling Price, and where across the other real rows
Selling Price matches v7 on 21,945/21,945 and MRP equals Selling Price on all 20,892 rows whose
v7 MRP was absent — i.e. that source filled MRP *from* selling price. The 4 rows now carry the
same label as the other 20,892 filled rows. Values (100, 100, 150, 499) are unchanged.

### 2b — evidence (confirmed)
`Blinkit_Master_FINAL_Clean_v2.xlsx` gives ETA '8 mins', '8 mins', '11 mins', '11 mins' for
these 4 rows in both `MASTER_PRODUCTS` and the 2026-07-10 rows of `PRODUCT_SNAPSHOTS`. The same
source's ETA equals raw `delivery_eta_min` on all 21,945 other real rows, so it is the same
observation source. Real-row rule unchanged: a point ETA, so `delivery_eta_max = delivery_eta_min`.

### 2c — evidence (label-only)
On these 33 rows `Blinkit_REAL_v7.xlsx` carried an MRP **lower** than the selling price
(e.g. MRP 80 vs selling price 370; all 33 listed in the script). The fill pass set
`mrp = selling_price` and labelled them `assumed_equal_to_selling_price`, which claims MRP was
absent. It was present but invalid. Only the label changed; `mrp` still equals `selling_price`
and `discount_percent` is still 0.

### Hashes (first 16 hex chars of sha256)
| File | after v1 | after v2 |
|---|---|---|
| `Blinkit_RAW.parquet` | 1f3258cac3b25c37 | **4e04dffcac84b821** |
| `Instamart_RAW.parquet` | 42433edfe5aaffde | 42433edfe5aaffde |
| `FlipkartMinutes_RAW.parquet` | 3b693b724ed785d2 | 3b693b724ed785d2 |
| `BigBasket_RAW.parquet` | dcb4f7ba0c826bbd | dcb4f7ba0c826bbd |

Baseline updated in `scripts/verify_raw_integrity.py`. `verify-raw` PASS and 14/14 tests pass
after v2 (2026-09-17).

**Propagated 2026-09-17:** `data/ml/` and `data/reference/ML_SCHEMA_v2.xlsx` were rebuilt from
post-v2 raw with `python -m src.pipeline.build_features`. Only `Blinkit_ML_price.parquet` changed;
ML matches raw on all three patched columns (0 mismatches); leakage checks PASS; 14/14 tests pass.

---

# After patch v2: v15.0 dynamics regeneration and v15.1 calibration (2026-09-17)

The SYNTHETIC rows of all four raw files were regenerated by `src/pipeline/build_v15_dynamics.py` (v15.0, then v15.1 calibrated to the real snapshot).
That is a generator run, not a patch, and it is logged in `data/raw/GENERATOR_LOG.md`. REAL rows,
including every v1 and v2 correction above, are cell-for-cell identical (verified against
`data/archive/v14_pre_regen/`). Current hash baseline: `scripts/verify_raw_integrity.py`.
