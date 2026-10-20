"""
build_v13.py — canonical mapping review

Finding: the collisions are NOT variants. Inside all 2,419 collision groups,
product_name, pack_size and brand are identical in 100% of groups, no canonical
key covers more than one pack_size, and no embedded size differs. The only
identity attribute that varies is category/subcategory - and that variation is
a LABELLING INCONSISTENCY in the source (67 groups are 'Energy Bar' vs
'Energy Bars'), not a product difference.

So the fix is to NORMALISE the inconsistent labels, not to split the key.
Splitting on subcategory would wrongly separate one product into two because
of a plural.
"""
import re, numpy as np, pandas as pd
from pathlib import Path

OUT = Path("/mnt/user-data/outputs")
FILES = ['Blinkit', 'Instamart', 'FlipkartMinutes', 'BigBasket']
KEY = ['snapshot_id', 'store_id', 'canonical_product_key']


def modal_labels(df):
    """One category/subcategory per canonical product, by majority vote."""
    out = {}
    for col in ['category', 'subcategory']:
        m = (df.groupby(['canonical_product_key', col]).size()
               .reset_index(name='n')
               .sort_values(['canonical_product_key', 'n', col],
                            ascending=[True, False, True])
               .drop_duplicates('canonical_product_key')
               .set_index('canonical_product_key')[col])
        out[col] = m
    return out


def audit_sheet(r):
    """One row per collision group, with the evidence for why it is not a variant."""
    g = r[r.duplicated(KEY, keep=False)].groupby(KEY)
    rows = []
    for key, grp in g:
        ident = {c: int(grp[c].nunique(dropna=False)) for c in
                 ['product_name', 'pack_size', 'brand', 'subcategory']}
        obs = {c: int(grp[c].nunique(dropna=False)) for c in
               ['selling_price', 'delivery_eta_min', 'stock_status']}
        identity_differs = any(v > 1 for k, v in ident.items() if k != 'subcategory')
        rows.append(dict(
            snapshot_id=key[0], store_id=key[1], canonical_product_key=key[2],
            n_listings=len(grp),
            product_ids=', '.join(sorted(grp.product_id.astype(str))),
            distinct_product_name=ident['product_name'],
            distinct_pack_size=ident['pack_size'],
            distinct_brand=ident['brand'],
            distinct_selling_price=obs['selling_price'],
            distinct_eta=obs['delivery_eta_min'],
            distinct_stock=obs['stock_status'],
            verdict=('SEPARATE_SKU_SPLIT_KEY' if identity_differs
                     else 'SAME_SKU_MULTIPLE_LISTINGS'),
            reason=('identity attribute differs' if identity_differs else
                    'product_name, pack_size and brand all identical; only '
                    'observed price/ETA/stock differ, which are observations '
                    'not identity')))
    return pd.DataFrame(rows)


def main():
    print("=" * 78); print("BUILD v13 - canonical mapping review"); print("=" * 78)

    # label map is built from the real Blinkit rows, then applied everywhere
    bl = pd.read_excel(OUT / 'Blinkit_FINAL_v12.xlsx', sheet_name='OBSERVATIONS')
    maps = modal_labels(bl[bl.data_status == 'REAL'])
    print(f"\nLabel map built over {bl[bl.data_status=='REAL'].canonical_product_key.nunique():,} "
          f"canonical products")

    audit = None
    for f in FILES:
        src = OUT / f"{f}_FINAL_v12.xlsx"
        sheets = {s: pd.read_excel(src, sheet_name=s) for s in pd.ExcelFile(src).sheet_names}
        d = sheets['OBSERVATIONS']
        print(f"\n{f}:")

        for col in ['category', 'subcategory']:
            new = d.canonical_product_key.map(maps[col])
            changed = int((new.notna() & (new != d[col])).sum())
            d[col] = new.where(new.notna(), d[col])
            print(f"    {col:<12} normalised on {changed:>6,} rows")

        # after normalising, how many keys still carry inconsistent labels?
        inc = int((d.groupby('canonical_product_key').subcategory.nunique() > 1).sum())
        print(f"    canonical keys with inconsistent subcategory: {inc}")

        if f == 'Blinkit':
            r = d[d.data_status == 'REAL']
            audit = audit_sheet(r)
            vc = audit.verdict.value_counts()
            print(f"    collision audit: " + " | ".join(f"{k} {v}" for k, v in vc.items()))
            sheets['CANONICAL_KEY_AUDIT'] = audit

        # catalog sheet gets the same normalisation
        mc = sheets['MASTER_CATALOG']
        for col in ['category', 'subcategory']:
            new = mc.canonical_product_key.map(maps[col])
            mc[col] = new.where(new.notna(), mc[col])
        sheets['MASTER_CATALOG'] = mc
        sheets['OBSERVATIONS'] = d

        with pd.ExcelWriter(OUT / f"{f}_FINAL_v13.xlsx", engine='xlsxwriter') as w:
            order = ['_READ_ME_FIRST', 'OBSERVATIONS', 'CANONICAL_KEY_AUDIT',
                     'SNAPSHOT_SCHEDULE', 'MASTER_CATALOG', 'STORES']
            for s in [x for x in order if x in sheets] + \
                     [x for x in sheets if x not in order]:
                sheets[s].to_excel(w, sheet_name=s, index=False)
        print(f"    -> {f}_FINAL_v13.xlsx")

    print("\n" + "=" * 78); print("CANONICAL MAPPING VERDICT"); print("=" * 78)
    print(audit.verdict.value_counts().to_string())
    print(f"\nGroups needing a key split: "
          f"{int((audit.verdict=='SEPARATE_SKU_SPLIT_KEY').sum())}")
    print("\nEvidence across all collision groups:")
    for c, lbl in [('distinct_product_name','product_name'),
                   ('distinct_pack_size','pack_size'),
                   ('distinct_brand','brand')]:
        print(f"   groups where {lbl:<14} differs: {int((audit[c]>1).sum()):>5} / {len(audit)}")
    for c, lbl in [('distinct_selling_price','selling price'),
                   ('distinct_eta','ETA'), ('distinct_stock','stock')]:
        print(f"   groups where {lbl:<14} differs: {int((audit[c]>1).sum()):>5} / {len(audit)}"
              f"   <- observation, not identity")


if __name__ == '__main__':
    main()
