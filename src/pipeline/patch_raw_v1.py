"""
patch_raw_v1.py — two corrections to data/raw/, applied once, fully documented.

STATUS: ARCHIVAL. Applied 2026-09-17, AFTER data/raw/ had been declared frozen
(the shipped project already marked it FROZEN). Current data/raw/ is the post-patch
state and its hashes are pinned in scripts/verify_raw_integrity.py.
Re-running is safe but pointless: every target file already has `store_id_source`,
so the script skips them all (verified by a second run). Running it against a
pre-patch copy to reproduce the pinned hashes has NOT been verified.
See data/raw/PATCH_LOG.md.

Run from the project root:   python -m src.pipeline.patch_raw_v1
Idempotent: re-running is a no-op. Writes a receipt to data/raw/PATCH_LOG.md.
Pre-patch originals: the shipped project archive (quickcommerce-mi.zip).

WHY THIS EDITS "FROZEN" RAW
  The freeze exists so derived layers don't drift, not to preserve known defects.
  Both fixes below are corrections, not reinterpretations, and the original values
  are either preserved in a new column or were fabricated in the first place.

------------------------------------------------------------------------------
FIX 1 — store_id collision between real and synthetic Blinkit  (the serious one)

  Real Blinkit rows use      BBSR-001..008      (from the source)
  Synthetic Blinkit rows use BLK-BBSR-001..008  (assigned during generation)
  Overlap: ZERO. STORES.csv carries only the BLK- form.

  Consequence: all 21,949 REAL rows fail to join STORES.csv, so latitude and
  longitude are unavailable for exactly the rows that matter. Store-level analysis
  also treats Blinkit as 16 stores instead of 8.

  Verified they are the same 8 stores: numeric suffix aligns 1:1, and area and
  pincode match on all 8. Two synthetic names were truncated
  ("Niladri Medical Store" vs "Niladri Medical Store, In Front Of Utsav Enclave").

  Action: unify on the BLK-BBSR-00N form (consistent with INS-/FKM-/BGB- on the
  other three platforms), preserve the original in a new `store_id_source` column,
  and repair the two truncated names to the fuller real versions — in RAW and in
  STORES.csv. CANONICAL_KEY_AUDIT.csv is relabelled the same way so it still joins.
  No observation value changes — this is a key relabel with a verified 1:1 crosswalk.

  observation_key is deliberately NOT rebuilt. It still reads
  'BASELINE_2026-07-10 | BBSR-002 | MASTER-00001' on real rows. It is a row
  identifier, not a join key; rewriting it would break every external reference to
  the original rows. Join stores on store_id, never by parsing observation_key.

------------------------------------------------------------------------------
FIX 2 — fabricated pack fields on the 4 unnamed REAL listings

  MASTER-15606, MASTER-15609, MASTER-16464, MASTER-18803 have no product name in
  the source. During the fill pass they picked up pack_size='1 pc', pack_qty=1.0,
  pack_unit='pc' from a fillna default, and unit_price was then computed from that
  invented pack size. On rows flagged REAL that is a fabrication.

  Action: NULL pack_size, pack_qty, pack_unit and unit_price on those 4 rows.

  NOT changed, deliberately:
    product_name  'UNNAMED LISTING MASTER-15606' is a self-describing label, not
                  an invented product name. Keeping it preserves joinability.
    selling_price copied from the real MRP under the user-approved rule that an
                  item with no separate discount sells at MRP.
    mrp_source    was 'observed_at_mrp', which claims MRP and selling price matched
                  in the source. They did not — selling price was absent. Corrected
                  to 'selling_price_assumed_equal_to_mrp'.

------------------------------------------------------------------------------
SAFETY
  Column dtypes are preserved exactly (RAW is stored as plain strings, not
  categoricals). Every column other than the ones named above is asserted
  byte-identical before the file is written.
"""
from pathlib import Path
from datetime import date
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW, REF = ROOT / 'data' / 'raw', ROOT / 'data' / 'reference'
UNNAMED = ['MASTER-15606', 'MASTER-15609', 'MASTER-16464', 'MASTER-18803']
NAME_FIX = {'Niladri Medical Store': 'Niladri Medical Store, In Front Of Utsav Enclave',
            'Sanjivani Medicine Store': 'Sanjivani Medicine Store, Behera Sahi Rd'}
REAL_ID = r'BBSR-\d{3}'
TOUCHED = {'store_id', 'store_name', 'pack_size', 'pack_qty', 'pack_unit',
           'unit_price', 'mrp_source'}


def _relabel(s: pd.Series) -> tuple[pd.Series, int]:
    s = s.astype(str)
    m = s.str.fullmatch(REAL_ID)
    return s.mask(m, 'BLK-' + s), int(m.sum())


def patch_raw(f: Path, log: list) -> tuple[int, int]:
    orig = pd.read_parquet(f)
    if 'store_id_source' in orig.columns:
        print(f"  {f.name}: already patched, skipping")
        return 0, 0
    d = orig.copy()

    # ---- FIX 1 ----
    d['store_id_source'] = d.store_id
    d['store_id'], n = _relabel(d.store_id)
    d['store_name'] = d.store_name.replace(NAME_FIX)

    # ---- FIX 2 ----
    um = d.product_id.isin(UNNAMED) & d.data_status.eq('REAL')
    d.loc[um, ['pack_size', 'pack_unit']] = None
    d.loc[um, ['pack_qty', 'unit_price']] = float('nan')
    d.loc[um, 'mrp_source'] = 'selling_price_assumed_equal_to_mrp'
    k = int(um.sum())

    # ---- verify before writing ----
    assert len(d) == len(orig), "row count changed — aborting"
    assert d.observation_key.is_unique, "observation_key no longer unique — aborting"
    for c in orig.columns:
        assert d[c].dtype == orig[c].dtype, f"dtype changed on {c} — aborting"
        if c not in TOUCHED:
            assert d[c].equals(orig[c]), f"untouched column {c} changed — aborting"

    d.to_parquet(f, compression='zstd', index=False)
    print(f"  {f.name}: store_id relabelled on {n:,} rows, pack fields nulled on {k} rows")
    log.append(f"- `{f.name}`: {n:,} store_id relabelled, {k} unnamed-listing rows corrected")
    return n, k


def patch_csv(path: Path, fix_names: bool, log: list):
    s = pd.read_csv(path)
    if 'store_id_source' in s.columns:
        return
    s['store_id_source'] = s.store_id.astype(str).str.replace('^BLK-', '', regex=True)
    s['store_id'], n = _relabel(s.store_id)
    if fix_names:
        s['store_name'] = s.store_name.replace(NAME_FIX)
    s.to_csv(path, index=False)
    log.append(f"- `{path.name}`: added `store_id_source`; {n:,} store_id relabelled"
               + ("; truncated store names repaired" if fix_names else ""))


def main():
    files = sorted(RAW.glob('*_RAW.parquet'))
    if not files:
        raise SystemExit(f"No parquet in {RAW}")

    log = [f"# RAW patch v1 — {date.today()}", "",
           "Script: `src/pipeline/patch_raw_v1.py` (the docstring explains each fix).", ""]
    total_store = total_pack = 0
    for f in files:
        n, k = patch_raw(f, log)
        total_store += n
        total_pack += k

    patch_csv(REF / 'STORES.csv', fix_names=True, log=log)
    patch_csv(REF / 'CANONICAL_KEY_AUDIT.csv', fix_names=False, log=log)

    if len(log) == 4:
        print("nothing to do — already patched. PATCH_LOG.md left as is.")
        return

    log += ["", f"store_id rows relabelled: {total_store:,}",
            f"unnamed-listing rows corrected: {total_pack}", "",
            "Original store ids preserved in `store_id_source`. `observation_key` "
            "intentionally keeps the original BBSR-00N form on real rows.",
            "No observation value was altered by Fix 1; Fix 2 removed fabricated "
            "pack fields and corrected one mislabelled `mrp_source`."]
    (RAW / 'PATCH_LOG.md').write_text("\n".join(log) + "\n", encoding='utf-8')
    print("\nreceipt -> data/raw/PATCH_LOG.md")


if __name__ == '__main__':
    main()
