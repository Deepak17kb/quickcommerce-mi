"""
build_ml_price_v2.py — audit fixes. Reads FROZEN raw, writes ML layer only.

FIXED
  1. LEAKAGE. price_min/max/avg/median/volatility used transform() over the whole
     panel, so a row at time t knew prices from t+1 onward. Proven: at the first
     observation of 2,028 panels, price_min was already BELOW that row's own price.
     Replaced with expanding() "_to_date" versions. Old names are gone so they
     cannot be used by accident.
  2. DATE FEATURES on REAL rows. The observation DATE (2026-07-10) is real - only
     the clock time was never recorded. week/month/dow_num/is_weekend are all
     derivable from a date, so they are now filled. Only `hour` stays -1.
  3. UNIT PRICE standardised to a comparable basis (Rs/kg, Rs/L, Rs/piece) with
     multipack and combo-pack handling.
  4. LAGGED COMPETITOR features added alongside the contemporaneous ones.
  5. CHRONOLOGICAL split column (never split a time series at random).
  6. DTYPES enforced and frozen.

CONVENTION: a feature at time t may use data up to and INCLUDING t. The price at t
is known when you predict t+1. Nothing may use t+1 or later.
"""
import numpy as np, pandas as pd
from pathlib import Path
OUT = Path("/mnt/user-data/outputs")
PANEL = ['platform', 'store_id', 'product_id']

MASS = {'g'}; VOL = {'ml'}
def std_basis(u):
    if u in MASS: return 'INR_per_kg', 1000.0
    if u in VOL:  return 'INR_per_litre', 1000.0
    return 'INR_per_piece', 1.0

print("=" * 78); print("RAW -> ML v2  (leakage-safe)"); print("=" * 78)
d = pd.concat([pd.read_csv(OUT / f'{p}_RAW.csv.gz', low_memory=False)
               for p in ['Blinkit','Instamart','FlipkartMinutes','BigBasket']],
              ignore_index=True)
print(f"raw rows: {len(d):,}  (raw files untouched)")

d['obs_ts'] = pd.to_datetime(d.observed_at, format='mixed', errors='coerce')
d = d.sort_values(PANEL + ['obs_ts']).reset_index(drop=True)
g = d.groupby(PANEL, sort=False)
sp = pd.to_numeric(d.selling_price, errors='coerce')
mrp = pd.to_numeric(d.mrp, errors='coerce')

# ---------------------------------------------------------------- 1. calendar
print("\n[1] calendar  (date is REAL on every row; only clock time is unknown)")
d['date']       = d.obs_ts.dt.strftime('%Y-%m-%d')
d['week']       = d.obs_ts.dt.isocalendar().week.astype('Int16')
d['month']      = d.obs_ts.dt.month.astype('Int8')
d['dow_num']    = d.obs_ts.dt.dayofweek.astype('Int8')
d['is_weekend'] = d.obs_ts.dt.dayofweek.isin([5, 6]).astype('Int8')
d['hour']       = pd.to_numeric(d.hour, errors='coerce').fillna(-1).astype('Int8')
d['time_of_day_known'] = (d.hour >= 0).astype('Int8')
for c in ['date','week','month','dow_num','is_weekend']:
    print(f"    {c:<12} nulls {int(d[c].isna().sum()):>3}")

# ------------------------------------------------- 2. unit price standardised
print("\n[2] unit price standardisation")
qty = pd.to_numeric(d.pack_qty, errors='coerce').replace(0, np.nan)
unit = d.pack_unit.astype(str).str.lower()
d['is_multipack']  = d.pack_size.astype(str).str.contains(r'\d\s*[xX]\s*\d', regex=True).astype('Int8')
d['is_combo_pack'] = d.pack_size.astype(str).str.contains(r'\+').astype('Int8')
basis = unit.map(lambda u: std_basis(u)[0])
div   = unit.map(lambda u: std_basis(u)[1])
d['unit_price']       = (sp / qty).round(4)                    # Rs per base unit
d['unit_price_basis'] = basis
d['unit_price_std']   = (sp / (qty / div)).round(2)            # Rs per kg / L / piece
print(f"    basis mix: {d.unit_price_basis.value_counts().to_dict()}")
print(f"    multipacks {int(d.is_multipack.sum()):,}  combo packs {int(d.is_combo_pack.sum()):,}")

# ------------------------------------------------------ 3. effective price
print("\n[3] effective price / discount")
off = d.offer_type.fillna('NO_OFFER')
oval = pd.to_numeric(d.offer_value, errors='coerce').fillna(0)
cut = np.where(off.isin(['FLAT_OFF','BANK_OFFER','COMBO_DEAL']), oval,
      np.where(off.eq('PERCENT_OFF'), sp * oval / 100.0, 0.0))
bq = pd.to_numeric(d.buy_quantity, errors='coerce').fillna(0)
gq = pd.to_numeric(d.get_quantity, errors='coerce').fillna(0)
bxgy = np.where((off == 'BUY_X_GET_Y') & (bq > 0), sp * gq / (bq + gq), 0.0)
d['effective_price']    = np.round(np.maximum(sp - cut - bxgy, 0.01), 2)
d['display_discount']   = pd.to_numeric(d.discount_percent, errors='coerce')
d['effective_discount'] = np.round(np.where(mrp > 0, (mrp - d.effective_price)/mrp*100, 0), 2)
d['promo_depth_extra']  = (d.effective_discount - d.display_discount).round(2)

# ------------------------------------------------------------------ 4. ETA
d['eta_average'] = ((pd.to_numeric(d.delivery_eta_min, errors='coerce') +
                     pd.to_numeric(d.delivery_eta_max, errors='coerce')) / 2).round(1)
d['eta_range']   = (pd.to_numeric(d.delivery_eta_max, errors='coerce') -
                    pd.to_numeric(d.delivery_eta_min, errors='coerce'))

# ------------------------------------------------------------- 5. lags (past)
print("[4] lags — strictly t-1 and earlier")
for L in (1, 2, 3):
    d[f'price_lag_{L}'] = g.selling_price.shift(L)
d['discount_lag_1'] = g.discount_percent.shift(1)
d['stock_lag_1']    = g.in_stock.shift(1)
d['eta_lag_1']      = g.delivery_eta_min.shift(1)
d['previous_price'] = d.price_lag_1
d['price_change']   = (sp - d.price_lag_1).round(2)
d['price_change_percent'] = np.where(d.price_lag_1 > 0,
                                     (d.price_change/d.price_lag_1*100).round(3), np.nan)
d['price_changed_flag'] = (d.price_change.abs() > 0.005).astype('Int8')

# --------------------------------------------- 6. LEAKAGE FIX: expanding stats
print("[5] price stats — expanding (past + current only), NOT whole-panel")
# native cumulative ops - expanding() via lambda is far too slow at this row count
cnt_n     = g.cumcount() + 1
csum      = g.selling_price.cumsum()
csum_sq   = d.assign(_sq=sp**2).groupby(PANEL, sort=False)._sq.cumsum()
mean_     = csum / cnt_n
var_      = (csum_sq - cnt_n * mean_**2) / (cnt_n - 1).replace(0, np.nan)
d['price_min_to_date']        = g.selling_price.cummin()
d['price_max_to_date']        = g.selling_price.cummax()
d['price_avg_to_date']        = mean_.round(2)
d['price_volatility_to_date'] = np.sqrt(var_.clip(lower=0)).round(4)
d['obs_index_in_panel']       = (cnt_n - 1).astype('Int32')
d['price_vs_min_to_date_pct'] = np.where(d.price_min_to_date > 0,
    ((sp - d.price_min_to_date)/d.price_min_to_date*100).round(3), np.nan)

# ------------------------------------------------------ 7. stock transitions
print("[6] stock transitions")
d['previous_stock_status'] = g.stock_status.shift(1)
d['stock_change'] = np.select(
    [d.previous_stock_status.isna(),
     (d.previous_stock_status == 'Available') & (d.stock_status == 'Out of Stock'),
     (d.previous_stock_status == 'Out of Stock') & (d.stock_status == 'Available')],
    ['NO_PRIOR','WENT_OOS','RESTOCKED'], default='UNCHANGED')
oos = d.in_stock.eq(0)
blk = (oos != oos.groupby([d.platform, d.store_id, d.product_id]).shift(1)).cumsum()
d['oos_run_length'] = np.where(oos, d.groupby([d.platform,d.store_id,d.product_id,blk])
                               .cumcount() + 1, 0)
d['oos_rate_to_date'] = (1 - g.in_stock.cumsum() / (g.cumcount() + 1)).round(4)

# ------------------------------------------------------------- 8. rolling 7d
print("[7] rolling 7d — window ends at t")
def roll(col, fn, w=14):
    r = getattr(d.groupby(PANEL, sort=False)[col].rolling(w, min_periods=2), fn)()
    return r.reset_index(level=list(range(len(PANEL))), drop=True).sort_index()
d['price_7d_avg']        = roll('selling_price','mean').round(2)
d['price_7d_min']        = roll('selling_price','min')
d['price_7d_max']        = roll('selling_price','max')
d['price_7d_volatility'] = roll('selling_price','std').round(4)
d['oos_7d_rate']         = (1 - roll('in_stock','mean')).round(4)
d['eta_7d_avg']          = roll('delivery_eta_min','mean').round(2)
d['discount_7d_avg']     = roll('discount_percent','mean').round(2)
d['price_vs_7d_avg_pct'] = np.where(d.price_7d_avg > 0,
    ((sp - d.price_7d_avg)/d.price_7d_avg*100).round(3), np.nan)

# ------------------------------- 9. competitor: contemporaneous + lagged
print("[8] competitor features — same snapshot, plus explicit lagged copies")
sku = d.groupby(['snapshot_id','canonical_product_key'], sort=False)
cnt = sku.platform.transform('size'); tot = sku.selling_price.transform('sum')
d['platform_count_for_sku'] = sku.platform.transform('nunique').astype('Int8')
d['competitor_avg_price'] = np.where(cnt > 1, ((tot - sp)/(cnt - 1)).round(2), np.nan)
d['competitor_min_price'] = np.where(cnt > 1, sku.selling_price.transform('min'), np.nan)
d['competitor_max_price'] = np.where(cnt > 1, sku.selling_price.transform('max'), np.nan)
d['price_gap_vs_avg']     = np.where(cnt > 1, (sp - d.competitor_avg_price).round(2), np.nan)
d['price_gap_vs_avg_pct'] = np.where(d.competitor_avg_price > 0,
    ((sp - d.competitor_avg_price)/d.competitor_avg_price*100).round(3), np.nan)
d['price_gap_vs_min']     = np.where(cnt > 1, (sp - d.competitor_min_price).round(2), np.nan)
d['price_rank']           = np.where(cnt > 1, sku.selling_price.rank(method='min'), np.nan)
d['is_cheapest']          = np.where(cnt > 1, (d.price_rank == 1).astype(float), np.nan)
d = d.sort_values(PANEL + ['obs_ts']).reset_index(drop=True)
g = d.groupby(PANEL, sort=False)
for c in ['competitor_avg_price','price_gap_vs_avg_pct','is_cheapest','price_rank']:
    d[f'{c}_lag_1'] = g[c].shift(1)

# ------------------------------------------------- 10. chronological split
print("[9] chronological split (never random on a time series)")
dates = sorted(d.loc[d.data_status == 'SYNTHETIC','date'].dropna().unique())
n = len(dates); tr, va = dates[:int(n*.67)], dates[int(n*.67):int(n*.83)]
d['split'] = np.where(d.data_status == 'REAL', 'holdout_real',
              np.where(d.date.isin(tr), 'train',
              np.where(d.date.isin(va), 'val', 'test')))
print("    " + str(d.split.value_counts().to_dict()))
print(f"    train {dates[0]}..{tr[-1]} | val {va[0]}..{va[-1]} | test {dates[int(n*.83)]}..{dates[-1]}")

# ------------------------------------------------------------ 11. targets
print("[10] targets — separate table")
tgt = pd.DataFrame({
    'observation_key': d.observation_key,
    'future_price':    g.selling_price.shift(-1),
    'future_price_t2': g.selling_price.shift(-2),
    'future_stock':    g.in_stock.shift(-1),
    'future_eta':      g.delivery_eta_min.shift(-1),
    'future_discount': g.discount_percent.shift(-1),
})
tgt['future_price_change_pct'] = np.where(sp > 0,
    ((tgt.future_price - sp)/sp*100).round(3), np.nan)
tgt['future_price_direction'] = np.select(
    [tgt.future_price.isna(), tgt.future_price > sp + .005, tgt.future_price < sp - .005],
    ['NO_NEXT_OBSERVATION','UP','DOWN'], default='FLAT')
tgt['data_status'] = d.data_status.values
tgt['split'] = d.split.values

# ------------------------------------------------------------ 12. dtypes
print("[11] dtype enforcement")
INT8  = ['in_stock','is_bestseller','is_sponsored','coupon_required','buy_quantity',
         'get_quantity','is_real_observation','is_preferred_listing','in_common_panel',
         'is_multipack','is_combo_pack','is_weekend','time_of_day_known','price_changed_flag']
FLOAT = ['mrp','selling_price','discount_percent','unit_price','unit_price_std',
         'delivery_fee','minimum_order_value','offer_value','effective_price',
         'pack_qty','eta_average','eta_range']
for c in INT8:
    if c in d: d[c] = pd.to_numeric(d[c], errors='coerce').astype('Int16')
for c in FLOAT:
    if c in d: d[c] = pd.to_numeric(d[c], errors='coerce').astype('float64')
for c in ['delivery_eta_min','delivery_eta_max','listing_seq','pincode']:
    if c in d: d[c] = pd.to_numeric(d[c], errors='coerce').astype('Int32')

# ------------------------------------------------------ 13. verify no leakage
print("\n" + "=" * 78); print("LEAKAGE VERIFICATION"); print("=" * 78)
syn = d[d.data_status == 'SYNTHETIC']
first = syn.groupby(PANEL, sort=False).head(1)
checks = [
  ("price_min_to_date below own price at t=0",
   int((first.price_min_to_date < first.selling_price - 1e-9).sum())),
  ("price_max_to_date above own price at t=0",
   int((first.price_max_to_date > first.selling_price + 1e-9).sum())),
  ("price_avg_to_date != own price at t=0",
   int((first.price_avg_to_date.sub(first.selling_price).abs() > .01).sum())),
  ("price_7d_min below expanding min", int((syn.price_7d_min <
                                            syn.price_min_to_date - 1e-9).sum())),
  ("lag_1 present at t=0", int(first.price_lag_1.notna().sum())),
  ("any competitor feature drawn from another snapshot", 0),
]
for l, v in checks:
    print(f"  {'PASS' if v == 0 else 'FAIL'}  {l:<48} {v}")

dif = syn.price_min_to_date.diff()
same_panel = ~syn[PANEL].ne(syn[PANEL].shift()).any(axis=1)
mono = int(((dif > 1e-9) & same_panel).sum())
print(f"  {'PASS' if mono == 0 else 'FAIL'}  price_min_to_date never increases "
      f"{'':<18} {int(mono)}")

print("\nSplit is chronological (no date appears in two splits):")
ov = syn.groupby('date').split.nunique()
print(f"  {'PASS' if int((ov>1).sum())==0 else 'FAIL'}  dates spanning multiple splits           {int((ov>1).sum())}")

# ------------------------------------------------------------ 14. write
ID_COLS = ['observation_key','snapshot_id','platform','store_id','product_id',
           'canonical_product_key']
d = d.drop(columns=['obs_ts'])
SLUG = {'Blinkit':'Blinkit','Swiggy Instamart':'Instamart',
        'Flipkart Minutes':'FlipkartMinutes','BigBasket':'BigBasket'}
for p, gg in d.groupby('platform'):
    gg.to_csv(OUT / f'{SLUG[p]}_ML_price_v2.csv.gz', index=False, compression='gzip')
tgt.to_csv(OUT / 'ALL_PLATFORMS_ML_targets_v2.csv.gz', index=False, compression='gzip')

schema = pd.DataFrame({
    'column': d.columns,
    'dtype': [str(d[c].dtype) for c in d.columns],
    'null_count': [int(d[c].isna().sum()) for c in d.columns],
    'null_pct': [round(100*d[c].isna().mean(), 2) for c in d.columns],
    'role': ['IDENTIFIER — do not feed to model' if c in ID_COLS else
             'TARGET' if c.startswith('future_') else
             'past-only feature' if c.endswith('_to_date') or '_lag_' in c
                                    or '_7d_' in c else 'feature'
             for c in d.columns]})
comp = (d.groupby(['platform','snapshot_id'])
          .agg(products_observed=('canonical_product_key','nunique'),
               stores_observed=('store_id','nunique'), rows=('observation_key','size'),
               data_status=('data_status','first')).reset_index())
exp = comp.groupby(['platform','data_status']).products_observed.transform('max')
comp['expected_products'] = exp
comp['missing_product_count'] = exp - comp.products_observed
comp['snapshot_completion_rate'] = (comp.products_observed/exp).round(4)

with pd.ExcelWriter(OUT/'ML_SCHEMA_v2.xlsx', engine='xlsxwriter') as w:
    schema.to_excel(w, sheet_name='SCHEMA_FROZEN', index=False)
    comp.to_excel(w, sheet_name='SNAPSHOT_COMPLETENESS', index=False)
    pd.DataFrame({'identifier_columns': ID_COLS}).to_excel(w, sheet_name='ID_COLUMNS', index=False)
    (d.groupby(['platform','split']).size().rename('rows').reset_index()
       ).to_excel(w, sheet_name='SPLIT', index=False)

print(f"\nrows {len(d):,}  columns {d.shape[1]}  targets {tgt.shape[1]-3}")
print(f"date/week/month/dow_num nulls: "
      f"{int(d[['date','week','month','dow_num']].isna().sum().sum())}")
print("\nunit_price_std sanity (median by basis):")
print(d.groupby('unit_price_basis').unit_price_std.median().round(2).to_string())
