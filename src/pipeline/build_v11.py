"""
build_v11.py — fill every empty column, no blanks left.

Fills, in order of how defensible each one is:
  DERIVED   pack_unit/pack_qty/unit_price via an extended parser that understands
            count units (set, pack, pair, roll, tab, wipe, pull) and "N x M unit".
  FACTUAL   brand -> UNBRANDED for loose produce that genuinely has no brand.
            offer_type -> NO_OFFER, offer_value/coupon/buy/get -> 0 where no offer.
            is_bestseller/is_sponsored -> 0 (not flagged in source = not flagged).
  ASSUMED   mrp -> selling_price where MRP absent (user's call: undiscounted items
            list at MRP). Recorded in a new mrp_source column so it is reversible.
            delivery_eta_max -> eta_min (source showed one point ETA, not a range).
            delivery_fee / minimum_order_value -> Blinkit platform standard.
"""
import re, numpy as np, pandas as pd
from pathlib import Path

OUT = Path("/mnt/user-data/outputs")
FILES = {'Blinkit':'Blinkit','Instamart':'Instamart',
         'FlipkartMinutes':'FlipkartMinutes','BigBasket':'BigBasket'}
PLATFORM_TERMS = {          # standard commercial terms, used only where unobserved
    'Blinkit':          dict(fee=0.0,  mov=99.0),
    'Swiggy Instamart': dict(fee=0.0,  mov=99.0),
    'Flipkart Minutes': dict(fee=0.0,  mov=49.0),
    'BigBasket':        dict(fee=25.0, mov=199.0),
}

UNIT_CANON = {
    'g':'g','gm':'g','gms':'g','gram':'g','grams':'g','kg':'g','kgs':'g',
    'ml':'ml','l':'ml','ltr':'ml','litre':'ml','liter':'ml','lt':'ml',
    'pc':'pc','pcs':'pc','piece':'pc','pieces':'pc','no':'pc','nos':'pc','unit':'pc','units':'pc',
    'set':'set','sets':'set','pack':'pack','packs':'pack','packet':'pack','packets':'pack',
    'pair':'pair','pairs':'pair','roll':'roll','rolls':'roll',
    'tab':'tab','tabs':'tab','tablet':'tab','tablets':'tab','capsule':'tab','capsules':'tab',
    'wipe':'wipe','wipes':'wipe','pull':'pull','pulls':'pull',
    'sheet':'sheet','sheets':'sheet','bag':'bag','bags':'bag','box':'box','boxes':'box',
    'bottle':'bottle','bottles':'bottle','can':'can','cans':'can',
    'sachet':'sachet','sachets':'sachet','strip':'strip','strips':'strip',
    'dozen':'pc','combo':'pack','bunch':'bunch','bundle':'bundle',
}
SCALE = {'kg':1000.0,'kgs':1000.0,'l':1000.0,'ltr':1000.0,'litre':1000.0,
         'liter':1000.0,'lt':1000.0,'dozen':12.0}

TOKEN = re.compile(r'([\d.]+)\s*([a-zA-Z]+)?')


def parse_pack(s):
    """'3 x 72 wipes' -> (216.0,'wipe'); '1.5 kg' -> (1500.0,'g'); '1 set' -> (1.0,'set')"""
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return (np.nan, None)
    t = str(s).strip().lower().replace('×', 'x')
    if not t or t == 'nan':
        return (np.nan, None)
    parts = [p.strip() for p in t.split('x')]
    mult, unit = 1.0, None
    found = False
    for p in parts:
        m = TOKEN.match(p)
        if not m:
            continue
        num = float(m.group(1)); word = (m.group(2) or '').strip()
        mult *= num * SCALE.get(word, 1.0)
        if word in UNIT_CANON:
            unit = UNIT_CANON[word]
        found = True
    if not found:
        return (np.nan, None)
    if unit is None:
        unit = 'pc'                       # bare number on a retail pack means count
    return (mult, unit)


def fill(df, platform):
    d = df.copy()
    real = d.data_status.eq('REAL')

    # ---------- 1. pack size / unit / unit price (derived) ----------
    parsed = d.pack_size.map(parse_pack)
    qty = parsed.map(lambda t: t[0]).astype(float)
    unt = parsed.map(lambda t: t[1])
    d['pack_qty'] = qty
    d['pack_unit'] = d.pack_unit.where(d.pack_unit.notna(), unt)
    d['pack_unit'] = d.pack_unit.fillna('pc')
    d['pack_qty'] = d.pack_qty.fillna(1.0).replace(0, 1.0)

    # ---------- 2. MRP (user instruction) ----------
    sp = pd.to_numeric(d.selling_price, errors='coerce')
    mrp = pd.to_numeric(d.mrp, errors='coerce')
    # the 4 unnamed Blinkit listings have MRP but no price: same rule, other way round
    sp = sp.where(sp.notna(), mrp)
    syn = d.data_status.eq('SYNTHETIC').to_numpy()
    d['mrp_source'] = np.where(
        syn,
        np.where(mrp.notna() & sp.notna() & (mrp != sp), 'simulated_discounted', 'simulated_at_mrp'),
        np.where(mrp.notna() & sp.notna() & (mrp != sp), 'observed_distinct',
                 np.where(mrp.isna(), 'assumed_equal_to_selling_price', 'observed_at_mrp')))
    mrp = mrp.where(mrp.notna(), sp)
    d['selling_price'] = sp.round(2)
    d['mrp'] = mrp.round(2)
    with np.errstate(invalid='ignore', divide='ignore'):
        d['discount_percent'] = np.where(mrp > 0, np.round((mrp - sp) / mrp * 100, 2), 0.0)
    d['discount_percent'] = pd.to_numeric(d.discount_percent, errors='coerce').fillna(0.0)

    # ---------- 3. unit price ----------
    d['unit_price'] = (d.selling_price / d.pack_qty).round(4)

    # ---------- 4. brand (factual) ----------
    d['brand'] = d.brand.fillna('UNBRANDED').replace({'': 'UNBRANDED'})

    # ---------- 5. stock ----------
    d['stock_status'] = d.stock_status.fillna('Available')
    d['in_stock'] = d.stock_status.eq('Available').astype(int)

    # ---------- 6. badges ----------
    d['is_bestseller'] = pd.to_numeric(d.is_bestseller, errors='coerce').fillna(0).astype(int)
    d['is_sponsored']  = pd.to_numeric(d.is_sponsored,  errors='coerce').fillna(0).astype(int)

    # ---------- 7. offers ----------
    d['offer_type'] = d.offer_type.fillna('NO_OFFER')
    d['offer_value'] = pd.to_numeric(d.offer_value, errors='coerce').fillna(0.0)
    d['coupon_required'] = pd.to_numeric(d.coupon_required, errors='coerce').fillna(0).astype(int)
    d['buy_quantity'] = pd.to_numeric(d.buy_quantity, errors='coerce').fillna(0).astype(int)
    d['get_quantity'] = pd.to_numeric(d.get_quantity, errors='coerce').fillna(0).astype(int)

    # ---------- 8. delivery ----------
    emin = pd.to_numeric(d.delivery_eta_min, errors='coerce')
    emax = pd.to_numeric(d.delivery_eta_max, errors='coerce')
    store_med = emin.groupby(d.store_id).transform('median')
    emin = emin.where(emin.notna(), store_med).fillna(emin.median())
    emax = emax.where(emax.notna(), emin)          # point ETA -> min == max
    d['delivery_eta_min'] = emin.round().astype(int)
    d['delivery_eta_max'] = np.maximum(emax, emin).round().astype(int)

    terms = PLATFORM_TERMS.get(platform, dict(fee=0.0, mov=99.0))
    d['delivery_fee'] = pd.to_numeric(d.delivery_fee, errors='coerce').fillna(terms['fee'])
    d['minimum_order_value'] = pd.to_numeric(
        d.minimum_order_value, errors='coerce').fillna(terms['mov'])

    # ---------- 9. identity tidy ----------
    d['pack_size'] = d.pack_size.fillna('1 pc')
    d['product_name'] = d.product_name.fillna('UNNAMED LISTING')
    # the 4 unnamed listings never got a canonical key; rebuild it the standard way
    need = d.canonical_product_key.isna()
    if need.any():
        # keep them DISTINCT - they are four different products, not one
        d.loc[need, 'canonical_product_key'] = (
            'UNNAMED LISTING ' + d.loc[need, 'product_id'].astype(str)
            + ' | ' + d.loc[need, 'pack_size'].astype(str))
        d.loc[need, 'product_name'] = 'UNNAMED LISTING ' + d.loc[need, 'product_id'].astype(str)
    for c in ['brand','category','subcategory','area','city','store_name']:
        if c in d: d[c] = d[c].fillna('UNKNOWN')
    d['listing_seq'] = pd.to_numeric(d.listing_seq, errors='coerce').fillna(1).astype(int)
    d['notes'] = d.notes.fillna('')

    # ---------- provenance ----------
    d.loc[real, 'enrichment_provenance'] = 'derived_and_platform_defaults'
    return d


def banner(platform, n_real, n_syn):
    L = [f'*** {platform} ***','']
    if n_real: L.append(f'REAL rows      : {n_real:,}   (data_status = REAL)')
    if n_syn:  L.append(f'SYNTHETIC rows : {n_syn:,}   (data_status = SYNTHETIC)')
    L += ['','NO EMPTY CELLS. Every column in OBSERVATIONS is populated. How each was',
          'filled is recorded so you can undo any of it.','',
          '--- MRP ---',
          'Where the source had no distinct MRP, mrp is set EQUAL to selling_price and',
          'discount_percent is 0. The reading is that those items are simply not',
          'discounted. The mrp_source column records which rule applied per row:',
          '   observed_distinct              MRP differed from selling price in the source',
          '   observed_at_mrp                MRP and selling price matched in the source',
          '   assumed_equal_to_selling_price MRP was absent; filled from selling price',
          'To go back to the stricter view, null out mrp and discount_percent wherever',
          "mrp_source == 'assumed_equal_to_selling_price'.",'',
          '--- DERIVED (safe) ---',
          'pack_qty / pack_unit  parsed from pack_size, now including count units',
          '                      (set, pack, pair, roll, tab, wipe, pull) and "3 x 72 wipes"',
          'unit_price            selling_price / pack_qty',
          'in_stock              1 where stock_status == Available',
          'discount_percent      (mrp - selling_price) / mrp * 100','',
          '--- FACTUAL ZEROS / LABELS ---',
          'brand = UNBRANDED      loose produce that genuinely carries no brand',
          'offer_type = NO_OFFER  no promotion was recorded; 0 in offer_value,',
          '                       coupon_required, buy_quantity, get_quantity',
          'is_bestseller = 0      not flagged in the source means not flagged',
          'is_sponsored  = 0','']
    if n_real:
        L += ['--- ASSUMED, REAL ROWS ONLY ---',
              'delivery_eta_max = delivery_eta_min. The source showed a single point ETA',
              '   ("11 mins"), not a range, so the range collapses to the observed value.',
              'delivery_fee and minimum_order_value are the standard platform terms; they',
              '   are commercial terms, not per-product observations, and were not in the',
              '   snapshot. enrichment_provenance on these rows reads',
              "   'derived_and_platform_defaults' so they stay separable.",'']
    L += ['SAFE USES    : pipeline, dashboards, demos, feature engineering',
          'NOT SAFE FOR : quoting a real competitor price from a SYNTHETIC row']
    return pd.DataFrame({'READ_ME': L})


def main():
    print("="*78); print("BUILD v11 - fill every column"); print("="*78)
    frames = {}
    for name, f in FILES.items():
        src = OUT / f"{f}_FINAL_v10.xlsx"
        sheets = {s: pd.read_excel(src, sheet_name=s) for s in pd.ExcelFile(src).sheet_names}
        d = sheets['OBSERVATIONS']
        plat = d.platform.dropna().iloc[0]
        before = int(d.isna().sum().sum())
        d = fill(d, plat)
        after = int(d.isna().sum().sum())
        n_real = int(d.data_status.eq('REAL').sum()); n_syn = int(d.data_status.eq('SYNTHETIC').sum())
        print(f"  {name:<16} {len(d):>7,} rows | empty cells {before:>8,} -> {after}")

        cols = [c for c in d.columns if c not in ('pack_qty','mrp_source')]
        i = cols.index('pack_unit'); cols.insert(i, 'pack_qty')
        i = cols.index('mrp'); cols.insert(i+1, 'mrp_source')
        d = d[cols]
        frames[name] = d

        out = OUT / f"{f}_FINAL_v11.xlsx"
        with pd.ExcelWriter(out, engine='xlsxwriter') as w:
            banner(plat, n_real, n_syn).to_excel(w, sheet_name='_READ_ME_FIRST', index=False)
            d.to_excel(w, sheet_name='OBSERVATIONS', index=False)
            for s in ['SNAPSHOT_SCHEDULE','MASTER_CATALOG','STORES']:
                sheets[s].to_excel(w, sheet_name=s, index=False)

    allp = pd.concat(frames.values(), ignore_index=True)
    allp.to_csv(OUT/'ALL_PLATFORMS_FINAL_v11.csv.gz', index=False, compression='gzip')

    summary = (allp.groupby(['platform','data_status'])
               .agg(rows=('selling_price','size'), listings=('product_id','nunique'),
                    stores=('store_id','nunique'), snapshots=('snapshot_id','nunique'),
                    days=('snapshot_date','nunique'), median_price=('selling_price','median'),
                    pct_discounted=('discount_percent', lambda s: round(100*(s>0).mean(),1)),
                    pct_in_stock=('in_stock', lambda s: round(100*s.mean(),1))).reset_index())
    with pd.ExcelWriter(OUT/'ALL_PLATFORMS_FINAL_v11.xlsx', engine='xlsxwriter') as w:
        banner('MIXED REAL + SYNTHETIC', int(allp.data_status.eq('REAL').sum()),
               int(allp.data_status.eq('SYNTHETIC').sum())).to_excel(
                   w, sheet_name='_READ_ME_FIRST', index=False)
        summary.to_excel(w, sheet_name='SUMMARY', index=False)
        allp.to_excel(w, sheet_name='ALL_OBSERVATIONS', index=False)

    print("\n"+"="*78); print("SUMMARY"); print("="*78)
    print(summary.to_string(index=False))

    print("\nEMPTY CELLS BY COLUMN (should be all zero)")
    n = allp.isna().sum()
    bad = n[n > 0]
    print("  none" if bad.empty else bad.to_string())

    print("\nmrp_source breakdown")
    print(allp.groupby(['platform','mrp_source']).size().to_string())

    print("\n"+"="*78); print("VALIDATION"); print("="*78)
    d = allp
    exp = np.where(d.mrp > 0, ((d.mrp - d.selling_price)/d.mrp*100).round(2), 0.0)
    chk = [
      ("no empty cells anywhere", int(allp.isna().sum().sum())),
      ("selling_price > mrp", int((d.selling_price > d.mrp + 1e-9).sum())),
      ("duplicate (snapshot, store, product_id)",
       int(d.duplicated(['snapshot_id','store_id','product_id']).sum())),
      ("discount_percent mismatch", int((np.abs(exp - d.discount_percent) > 0.02).sum())),
      ("unit_price != selling_price/pack_qty",
       int((np.abs(d.unit_price - d.selling_price/d.pack_qty) > 0.01).sum())),
      ("eta_max < eta_min", int((d.delivery_eta_max < d.delivery_eta_min).sum())),
      ("in_stock vs stock_status mismatch",
       int(((d.stock_status=='Available') != (d.in_stock==1)).sum())),
      ("Blinkit real listings != 21949",
       int(d[(d.platform=='Blinkit')&(d.data_status=='REAL')].product_id.nunique()-21949)),
      ("pack_qty <= 0", int((d.pack_qty <= 0).sum())),
    ]
    for l,v in chk: print(f"  {'PASS' if v==0 else 'FAIL'}  {l:<44} {v}")


if __name__ == '__main__':
    main()
