"""
build_v12.py
  1. MASTER_CATALOG: brand / pack_qty / pack_unit filled (same parser as OBSERVATIONS).
  2. Duplicates: diagnosed, not deleted. Adds listing_class + is_preferred_listing
     + observation_key. Nothing is removed; dedup becomes a one-line filter.
  3. Blinkit baseline timestamp: explicit NOT_RECORDED / -1 sentinels, no invented time.
"""
import sys, numpy as np, pandas as pd
from pathlib import Path
sys.path.insert(0, '/tmp/claude-0/-home-claude/3798d455-625a-503b-bf70-c7237fb22bb7/scratchpad')
from build_v11 import parse_pack           # extended parser: count units + "N x M unit"

OUT = Path("/mnt/user-data/outputs")
FILES = ['Blinkit', 'Instamart', 'FlipkartMinutes', 'BigBasket']
KEY = ['snapshot_id', 'store_id', 'canonical_product_key']
SUBSTANTIVE = ['selling_price', 'mrp', 'stock_status', 'delivery_eta_min']


def fix_catalog(mc):
    before = dict(brand=int(mc.brand.isna().sum()),
                  pack_qty=int(mc.pack_qty.isna().sum()),
                  pack_unit=int(mc.pack_unit.isna().sum()))
    parsed = mc.pack_size.map(parse_pack)
    q = parsed.map(lambda t: t[0]).astype(float)
    u = parsed.map(lambda t: t[1])
    mc['pack_qty'] = pd.to_numeric(mc.pack_qty, errors='coerce')
    mc['pack_qty'] = mc.pack_qty.where(mc.pack_qty.notna(), q).fillna(1.0).replace(0, 1.0)
    mc['pack_unit'] = mc.pack_unit.where(mc.pack_unit.notna(), u).fillna('pc')
    mc['brand'] = mc.brand.fillna('UNBRANDED').replace({'': 'UNBRANDED'})
    for c in ['product_name', 'original_product_name', 'category', 'subcategory']:
        if c in mc: mc[c] = mc[c].fillna('UNKNOWN')
    after = int(mc.isna().sum().sum())
    print(f"    MASTER_CATALOG nulls  brand {before['brand']:,} -> 0 | "
          f"pack_qty {before['pack_qty']} -> 0 | pack_unit {before['pack_unit']} -> 0 "
          f"| total remaining {after}")
    return mc


def classify(d):
    """Why does the same product/store/snapshot appear more than once?"""
    d = d.copy()
    g = d.groupby(KEY, sort=False)
    size = g['product_id'].transform('size').to_numpy()
    differs = np.zeros(len(d), dtype=bool)
    for f in SUBSTANTIVE:
        differs |= g[f].transform('nunique').to_numpy() > 1

    d['listing_class'] = np.where(
        size == 1, 'single_listing',
        np.where(differs, 'distinct_listing', 'identical_repeat'))

    # keep everything; mark one row per identical_repeat group as the preferred one
    first_in_grp = ~d.duplicated(KEY, keep='first')
    d['is_preferred_listing'] = np.where(
        d.listing_class.eq('identical_repeat') & ~first_in_grp, 0, 1).astype(int)

    d['observation_key'] = (d.snapshot_id.astype(str) + ' | ' + d.store_id.astype(str)
                            + ' | ' + d.product_id.astype(str))
    return d


def main():
    print("=" * 78); print("BUILD v12"); print("=" * 78)
    frames = {}
    for f in FILES:
        src = OUT / f"{f}_FINAL_v11.xlsx"
        sheets = {s: pd.read_excel(src, sheet_name=s) for s in pd.ExcelFile(src).sheet_names}
        print(f"\n{f}:")
        sheets['MASTER_CATALOG'] = fix_catalog(sheets['MASTER_CATALOG'])

        d = classify(sheets['OBSERVATIONS'])

        # ---- Blinkit baseline timestamp: sentinel, never an invented clock time ----
        base = d.data_status.eq('REAL')
        if base.any():
            d['snapshot_time'] = d.snapshot_time.astype(object)
            d.loc[base, 'snapshot_time'] = 'NOT_RECORDED'
            d['hour'] = pd.to_numeric(d.hour, errors='coerce')
            d.loc[base, 'hour'] = -1
            print(f"    baseline timestamp   {int(base.sum()):,} real rows -> "
                  f"snapshot_time='NOT_RECORDED', hour=-1")
        d['hour'] = pd.to_numeric(d.hour, errors='coerce').fillna(-1).astype(int)
        d['snapshot_time'] = d.snapshot_time.fillna('NOT_RECORDED')

        cols = list(d.columns)
        for c in ['observation_key', 'listing_class', 'is_preferred_listing']:
            cols.remove(c)
        d = d[['observation_key'] + cols[:cols.index('listing_seq') + 1]
              + ['listing_class', 'is_preferred_listing']
              + cols[cols.index('listing_seq') + 1:]]

        vc = d.listing_class.value_counts()
        print(f"    listing_class        " + " | ".join(f"{k} {v:,}" for k, v in vc.items()))
        print(f"    is_preferred_listing 1 -> {int(d.is_preferred_listing.eq(1).sum()):,}   "
              f"0 -> {int(d.is_preferred_listing.eq(0).sum()):,}")
        print(f"    empty cells          {int(d.isna().sum().sum())}")

        sheets['OBSERVATIONS'] = d
        frames[f] = d
        with pd.ExcelWriter(OUT / f"{f}_FINAL_v12.xlsx", engine='xlsxwriter') as w:
            for s, sd in sheets.items():
                sd.to_excel(w, sheet_name=s, index=False)

    allp = pd.concat(frames.values(), ignore_index=True)
    allp.to_csv(OUT / 'ALL_PLATFORMS_FINAL_v12.csv.gz', index=False, compression='gzip')
    mc = pd.read_excel(OUT / 'FlipkartMinutes_FINAL_v12.xlsx', sheet_name='MASTER_CATALOG')

    summary = (allp.groupby(['platform', 'data_status'])
               .agg(rows=('selling_price', 'size'), preferred=('is_preferred_listing', 'sum'),
                    listings=('product_id', 'nunique'), snapshots=('snapshot_id', 'nunique'),
                    days=('snapshot_date', 'nunique')).reset_index())
    with pd.ExcelWriter(OUT / 'ALL_PLATFORMS_FINAL_v12.xlsx', engine='xlsxwriter') as w:
        summary.to_excel(w, sheet_name='SUMMARY', index=False)
        allp.to_excel(w, sheet_name='ALL_OBSERVATIONS', index=False)
        mc.to_excel(w, sheet_name='MASTER_CATALOG', index=False)

    print("\n" + "=" * 78); print("SUMMARY"); print("=" * 78)
    print(summary.to_string(index=False))

    print("\n" + "=" * 78); print("VALIDATION"); print("=" * 78)
    pref = allp[allp.is_preferred_listing == 1]
    chk = [
      ("observation_key unique", int(allp.observation_key.duplicated().sum())),
      ("MASTER_CATALOG empty cells", int(mc.isna().sum().sum())),
      ("OBSERVATIONS empty cells", int(allp.isna().sum().sum())),
      ("dup on (snapshot,store,product_id)",
       int(allp.duplicated(['snapshot_id','store_id','product_id']).sum())),
      ("dup on KEY after is_preferred filter, excl. distinct_listing",
       int(pref[pref.listing_class != 'distinct_listing'].duplicated(KEY).sum())),
      ("selling_price > mrp", int((allp.selling_price > allp.mrp + 1e-9).sum())),
      ("Blinkit real listings != 21949",
       int(allp[(allp.platform=='Blinkit') & (allp.data_status=='REAL')].product_id.nunique()-21949)),
      ("real rows with an invented clock time",
       int(((allp.data_status=='REAL') & (allp.snapshot_time != 'NOT_RECORDED')).sum())),
    ]
    for l, v in chk:
        print(f"  {'PASS' if v == 0 else 'FAIL'}  {l:<52} {v}")


if __name__ == '__main__':
    main()
