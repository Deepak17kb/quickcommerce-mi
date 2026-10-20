"""
build_v14_panel.py — make price intelligence computable.

PROBLEM: only 9 canonical products existed on all four platforms, because each
platform sampled the catalog independently. A cross-platform price gap needs the
same SKU on 2+ platforms, so 99.9% of the catalog was uncomparable.

FIX: define a COMMON PANEL of products and ensure every platform carries all of
them across all 60 snapshots. Existing rows are NEVER touched - product names and
prices stay exactly as they are. Only the missing (platform x product) pairs are
generated, using the same generator and the same per-platform price positioning.

ALSO: brand extraction from product names, data-driven (leading n-grams that recur
across many distinct products), never guessed.
"""
import re, numpy as np, pandas as pd
from pathlib import Path

RNG = np.random.default_rng(20260916)
OUT = Path("/mnt/user-data/outputs")
FILES = ['Blinkit', 'Instamart', 'FlipkartMinutes', 'BigBasket']
PANEL_SIZE = 2000

PERSONAS = {
    'Blinkit':          dict(gap= 0.000, promo=0.52, da=2., db=5., dmax=0.33, eta=(8,15),
                             fees=[0,0,0,15,20,25], movs=[99,99,149], offer=0.31,
                             bs=0.11, sp=0.08, oos=0.060, pfx='BLI'),
    'Swiggy Instamart': dict(gap=-0.015, promo=0.58, da=2., db=5., dmax=0.35, eta=(8,16),
                             fees=[0,0,0,15,20,25], movs=[99,99,149], offer=0.34,
                             bs=0.11, sp=0.09, oos=0.065, pfx='INS'),
    'Flipkart Minutes': dict(gap=-0.060, promo=0.72, da=2., db=4., dmax=0.42, eta=(10,22),
                             fees=[0,0,0,0,19,29], movs=[0,49,99], offer=0.45,
                             bs=0.09, sp=0.14, oos=0.085, pfx='FKM'),
    'BigBasket':        dict(gap=-0.005, promo=0.46, da=2., db=6., dmax=0.28, eta=(12,28),
                             fees=[0,25,30,35,40], movs=[199,199,249], offer=0.28,
                             bs=0.12, sp=0.07, oos=0.055, pfx='BGB'),
}
PLAT_OF_FILE = {'Blinkit':'Blinkit','Instamart':'Swiggy Instamart',
                'FlipkartMinutes':'Flipkart Minutes','BigBasket':'BigBasket'}
OFFERS = np.array(['FLAT_OFF','PERCENT_OFF','BUY_X_GET_Y','COMBO_DEAL','BANK_OFFER'])
OFFER_W = np.array([0.26,0.34,0.16,0.12,0.12])
FRESH = {'Fruits & Vegetables','Dairy, Bread & Eggs','Meat, Fish & Eggs','Bakery','Fruits'}

GENERIC = {'fresh','organic','premium','natural','pure','indian','assorted','mixed','whole',
           'raw','dried','frozen','baby','kids','men','women','classic','special','regular',
           'green','red','black','white','yellow','sweet','salted','plain','the','a','an',
           'combo','pack','gift','no','new','desi','country','local','loose','farm','home',
           'hot','cold','soft','hard','light','extra','super','mini','large','small','big'}


def psych_vec(x):
    x = np.asarray(x, float); out = np.empty_like(x)
    m1, m2 = x < 20, (x >= 20) & (x < 100)
    m3, m4 = (x >= 100) & (x < 500), x >= 500
    out[m1] = np.round(x[m1], 1)
    v = np.floor(x[m2]); out[m2] = np.where(np.isin(v % 10, [0,1]), v-1, v)
    out[m3] = np.round(x[m3]/10.)*10 - 1
    out[m4] = np.round(x[m4]/50.)*50 - 1
    return np.maximum(out, 1.0)


def learn_brands(names, known):
    """Leading 1-2 token n-grams that recur across many DISTINCT products."""
    vocab = {str(b).strip().lower() for b in known if isinstance(b, str) and b.strip()
             and b != 'UNBRANDED'}
    tok = lambda s: re.findall(r"[A-Za-z0-9&'.\-]+", str(s))
    c1, c2 = {}, {}
    for n in set(names):
        t = tok(n)
        if t:
            c1.setdefault(t[0].lower(), set()).add(n)
        if len(t) > 1:
            c2.setdefault(' '.join(t[:2]).lower(), set()).add(n)

    def ok(key, bag, minn):
        if key in vocab: return True
        parts = key.split()
        if any(p in GENERIC for p in parts): return False
        if len(key) < 3 or key.isdigit(): return False
        return len(bag) >= minn

    learned2 = {k for k, v in c2.items() if ok(k, v, 6)}
    learned1 = {k for k, v in c1.items() if ok(k, v, 4)}

    def infer(n):
        t = tok(n)
        if not t: return 'UNBRANDED'
        two = ' '.join(t[:2]).lower() if len(t) > 1 else None
        if two and two in learned2:
            return ' '.join(t[:2])
        if t[0].lower() in learned1 or t[0].lower() in vocab:
            return t[0]
        return 'UNBRANDED'
    return infer


def gen_rows(plat, cfg, prods, stores, grid, ref, seq0):
    """Generate the missing (platform x product) panel rows. Same model as v10."""
    P = len(prods)
    sids = stores.store_id.to_numpy()
    si = RNG.integers(0, len(sids), size=P)
    lvl   = np.clip(RNG.normal(1 + cfg['gap'], 0.045, P), 0.78, 1.22)
    promo = RNG.random(P) < cfg['promo']
    depth = RNG.beta(cfg['da'], cfg['db'], P) * cfg['dmax']
    bs    = RNG.random(P) < cfg['bs']
    spon  = RNG.random(P) < cfg['sp']
    offon = RNG.random(P) < cfg['offer']
    otyp  = RNG.choice(OFFERS, size=P, p=OFFER_W)

    base    = prods.ref_price.to_numpy()
    isfresh = np.isin(prods.category.to_numpy(), list(FRESH))
    qty     = pd.to_numeric(prods.pack_qty, errors='coerce').fillna(1.0).to_numpy()
    punit   = prods.pack_unit.fillna('pc').to_numpy()

    S = len(grid); N = P * S
    wave = np.repeat(RNG.normal(0, 0.012, S), P)
    hour = np.repeat(grid.hour.to_numpy(), P)
    T = lambda a: np.tile(a, S)

    sell = psych_vec(np.maximum(T(base) * T(lvl) * (1 + wave) * RNG.normal(1., .018, N), 1.))
    dep  = np.clip(T(depth) * RNG.uniform(.75, 1.15, N), .02, .60)
    mrp  = np.where(T(promo), psych_vec(sell / (1 - dep)), sell)
    mrp  = np.maximum(np.where((mrp <= sell) & T(promo),
                               np.round(sell * (1 + np.maximum(dep, .05)), 2), mrp), sell)
    disc = np.round((mrp - sell) / np.where(mrp > 0, mrp, 1) * 100, 2)

    q = T(qty)
    unit = np.round(sell / np.where(q > 0, q, 1), 4)

    p_oos = np.minimum(cfg['oos'] * np.where(T(isfresh), 1.9, 1.) *
                       np.where(hour == 18, 1.35, 1.), .45)
    instock = (RNG.random(N) >= p_oos).astype(int)

    lo, hi = cfg['eta']
    eta_lo = RNG.integers(lo, lo + 4, N) + np.where(hour == 18, 4, 0)
    eta_hi = eta_lo + RNG.integers(4, 11, N)

    ot = np.where(T(offon) & (instock == 1), T(otyp), 'NO_OFFER')
    oval = np.zeros(N); bq = np.zeros(N); gq = np.zeros(N); coup = np.zeros(N)
    for t, vals, cp in [('FLAT_OFF', [10,20,25,30,50,75,100], .35),
                        ('PERCENT_OFF', [5,10,15,20,25,30], .30),
                        ('COMBO_DEAL', [15,25,40,60], 0.), ('BANK_OFFER', [10,50,75,100], 1.)]:
        m = ot == t
        if m.any():
            oval[m] = RNG.choice(vals, size=int(m.sum()))
            coup[m] = (RNG.random(int(m.sum())) < cp).astype(float) if cp not in (0., 1.) else cp
    mb = ot == 'BUY_X_GET_Y'
    if mb.any(): bq[mb] = RNG.choice([1,2,2,3], size=int(mb.sum())); gq[mb] = 1.

    st = stores.set_index('store_id'); sid_f = T(sids[si])
    pid = T(np.array([f"{cfg['pfx']}-{seq0+i:06d}" for i in range(P)]))
    d = pd.DataFrame({
        'snapshot_id': np.repeat(grid.snapshot_id.to_numpy(), P),
        'observed_at': np.repeat(grid.planned_at.to_numpy(), P),
        'snapshot_date': np.repeat(grid.snapshot_date.to_numpy(), P),
        'snapshot_time': np.repeat(grid.snapshot_time.to_numpy(), P),
        'hour': hour, 'day_of_week': np.repeat(grid.day_of_week.to_numpy(), P),
        'platform': plat, 'store_id': sid_f,
        'store_name': st.store_name.reindex(sid_f).to_numpy(),
        'area': st.area.reindex(sid_f).to_numpy(),
        'pincode': st['pin'].reindex(sid_f).to_numpy(),
        'city': st.city.reindex(sid_f).to_numpy(),
        'product_id': pid,
        'canonical_product_key': T(prods.canonical_product_key.to_numpy()),
        'listing_seq': 1, 'listing_class': 'single_listing', 'is_preferred_listing': 1,
        'product_name': T(prods.product_name.to_numpy()),
        'brand': T(prods.brand.to_numpy()), 'category': T(prods.category.to_numpy()),
        'subcategory': T(prods.subcategory.to_numpy()),
        'pack_size': T(prods.pack_size.to_numpy()), 'pack_qty': q, 'pack_unit': T(punit),
        'mrp': mrp, 'mrp_source': np.where(mrp > sell, 'simulated_discounted', 'simulated_at_mrp'),
        'selling_price': sell, 'discount_percent': disc, 'unit_price': unit,
        'stock_status': np.where(instock == 1, 'Available', 'Out of Stock'), 'in_stock': instock,
        'is_bestseller': np.where(instock == 1, T(bs).astype(int), 0),
        'is_sponsored': T(spon).astype(int),
        'delivery_eta_min': eta_lo, 'delivery_eta_max': eta_hi,
        'delivery_fee': RNG.choice(cfg['fees'], N).astype(float),
        'minimum_order_value': RNG.choice(cfg['movs'], N).astype(float),
        'offer_type': ot, 'offer_value': oval, 'coupon_required': coup.astype(int),
        'buy_quantity': bq.astype(int), 'get_quantity': gq.astype(int),
        'notes': 'SYNTHETIC ROW - common-panel fill so cross-platform price gaps are computable',
        'source': 'SIMULATED_GENERATOR_v14_panel',
        'price_provenance': 'simulated_from_blinkit_median_reference',
        'enrichment_provenance': 'simulated',
        'data_status': 'SYNTHETIC', 'is_real_observation': 0,
    })
    d['observation_key'] = d.snapshot_id + ' | ' + d.store_id + ' | ' + d.product_id
    return d


def main():
    print("=" * 78); print("BUILD v14 - common panel + brand extraction"); print("=" * 78)
    sheets = {f: {s: pd.read_excel(OUT / f"{f}_FINAL_v13.xlsx", sheet_name=s)
                  for s in pd.ExcelFile(OUT / f"{f}_FINAL_v13.xlsx").sheet_names} for f in FILES}
    obs = {f: sheets[f]['OBSERVATIONS'] for f in FILES}
    grid = sheets['Blinkit']['SNAPSHOT_SCHEDULE']
    cat = sheets['Blinkit']['MASTER_CATALOG'].copy()

    # ---------- brand extraction ----------
    print("\nBRAND EXTRACTION")
    infer = learn_brands(cat.product_name.tolist(), cat.brand.tolist())
    miss = cat.brand.eq('UNBRANDED')
    cat.loc[miss, 'brand'] = cat.loc[miss, 'product_name'].map(infer)
    got = int((cat.brand != 'UNBRANDED').sum())
    print(f"  catalog: branded {int((~miss).sum()):,} -> {got:,} of {len(cat):,} "
          f"({100*got/len(cat):.1f}%)   still UNBRANDED {len(cat)-got:,}")
    print("  newly inferred examples:",
          ', '.join(cat.loc[miss & cat.brand.ne('UNBRANDED'), 'brand'].value_counts().head(8).index))
    bmap = cat.set_index('canonical_product_key').brand

    # ---------- common panel ----------
    print("\nCOMMON PANEL")
    blk_real = obs['Blinkit'][obs['Blinkit'].data_status == 'REAL']
    ref = blk_real.groupby('canonical_product_key').selling_price.median()
    have = {f: set(obs[f][obs[f].data_status == 'SYNTHETIC'].canonical_product_key) for f in FILES}
    union = set().union(*have.values())
    # prefer products already carried by the most platforms, then by real-price availability
    score = pd.Series({k: sum(k in have[f] for f in FILES) for k in union})
    elig = [k for k in score.sort_values(ascending=False).index if k in ref.index]
    panel = elig[:PANEL_SIZE]
    if len(panel) < PANEL_SIZE:
        extra = [k for k in ref.index if k not in set(panel)]
        panel += list(RNG.choice(extra, PANEL_SIZE - len(panel), replace=False))
    panel = set(panel)
    print(f"  union of current synthetic products : {len(union):,}")
    print(f"  panel size                          : {len(panel):,}")

    cat_idx = cat.set_index('canonical_product_key')
    for f in FILES:
        plat = PLAT_OF_FILE[f]; cfg = PERSONAS[plat]
        missing = sorted(panel - have[f])
        print(f"  {f:<16} has {len(panel & have[f]):>5,} of panel, generating {len(missing):>5,}")
        if not missing:
            continue
        prods = cat_idx.loc[missing].reset_index()
        prods['ref_price'] = prods.canonical_product_key.map(ref)
        prods = prods[prods.ref_price.notna() & (prods.ref_price > 0)]
        seq0 = 900001
        new = gen_rows(plat, cfg, prods, sheets[f]['STORES'], grid, ref, seq0)
        cur = obs[f]
        new = new.reindex(columns=cur.columns, fill_value=np.nan)
        obs[f] = pd.concat([cur, new], ignore_index=True)

    # ---------- apply brands + panel flag, write ----------
    print("\nWRITING")
    for f in FILES:
        d = obs[f]
        nb = d.canonical_product_key.map(bmap)
        upd = int((d.brand.eq('UNBRANDED') & nb.notna() & nb.ne('UNBRANDED')).sum())
        d['brand'] = np.where(d.brand.eq('UNBRANDED') & nb.notna(), nb, d.brand)
        d['in_common_panel'] = d.canonical_product_key.isin(panel).astype(int)
        d = d.drop_duplicates(subset=['observation_key'], keep='first')
        sheets[f]['OBSERVATIONS'] = d
        sheets[f]['MASTER_CATALOG'] = cat
        obs[f] = d
        with pd.ExcelWriter(OUT / f"{f}_FINAL_RAW.xlsx", engine='xlsxwriter') as w:
            for s, sd in sheets[f].items():
                sd.to_excel(w, sheet_name=s, index=False)
        print(f"  {f:<16} {len(d):>7,} rows  (+{len(d)-len(sheets[f]['OBSERVATIONS']) if False else 0}) "
              f"brand filled on {upd:,} rows -> {f}_FINAL_RAW.xlsx")

    allp = pd.concat(obs.values(), ignore_index=True)
    allp.to_csv(OUT / 'ALL_PLATFORMS_FINAL_RAW.csv.gz', index=False, compression='gzip')
    print(f"\n  ALL_PLATFORMS_FINAL_RAW.csv.gz  {len(allp):,} rows")

    # ---------- verify ----------
    print("\n" + "=" * 78); print("CROSS-PLATFORM OVERLAP AFTER FIX"); print("=" * 78)
    sets = {p: set(g.canonical_product_key) for p, g in allp.groupby('platform')}
    for p, s in sets.items(): print(f"  {p:<18} {len(s):>6,}")
    print(f"  on ALL FOUR platforms: {len(set.intersection(*sets.values())):,}  (was 9)")
    print(f"\n  empty cells: {int(allp.isna().sum().sum())}")
    print(f"  observation_key unique: {len(allp) - allp.observation_key.duplicated().sum():,}/{len(allp):,}")
    print(f"  REAL rows untouched: {int((allp.data_status=='REAL').sum()):,}")
    print(f"  brand coverage: {100*(allp.brand!='UNBRANDED').mean():.1f}%")


if __name__ == '__main__':
    main()
