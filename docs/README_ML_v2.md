# ML layer v2 — audit fixes

Raw files were not touched *by this ML v2 build*. They were later corrected by patches v1 and
v2 (2026-09-17, `data/raw/PATCH_LOG.md`); the current raw baseline is at the bottom and in
`scripts/verify_raw_integrity.py`.

**Scope of "verified against source"** (last checked 2026-09-17): `selling_price` and
`stock_status` on the 21,949 REAL Blinkit rows only — 21,945 matched against
`Blinkit_REAL_v7.xlsx` (0 mismatches), plus the 4 unnamed listings matched against
`Blinkit_Master_FINAL_Clean_v2.xlsx`. Neither file ships in this repo. The PASS tables below
verify feature *logic* (leakage, joins, dtypes), not source values.

## 1. Temporal leakage — CONFIRMED and fixed

This was a real defect, not a false alarm. Five features used `transform()` over the
whole panel, so a row at time *t* already knew prices from *t+1* onward.

**Proof, before the fix** — at the **first** observation of each panel, a past-only
minimum must equal that row's own price:

```
price_min BELOW own price at t=0 : 2,028 panels
price_max ABOVE own price at t=0 : 2,176 panels
```

A worked row: first observation priced ₹279, but `price_min` already read ₹259 — a price
that does not occur until later in the series. Any backtest using these would have been
optimistic for reasons that vanish in production.

**Fixed** by replacing them with expanding (past + current) versions under new names, so
the leaky ones cannot be used by accident:

| Removed | Replaced by |
|---|---|
| `price_min` | `price_min_to_date` |
| `price_max` | `price_max_to_date` |
| `price_avg` | `price_avg_to_date` |
| `price_median` | dropped — no cheap past-only form; use avg/min/max |
| `price_volatility` | `price_volatility_to_date` |

**Convention now enforced:** a feature at time *t* may use data up to and **including** *t*
— the current price is known when you predict *t+1* — and nothing may use *t+1* or later.

### Verified clean

```
PASS  price_min_to_date below own price at t=0        0
PASS  price_max_to_date above own price at t=0        0
PASS  price_avg_to_date != own price at t=0           0
PASS  price_7d_min below expanding min                0
PASS  lag_1 present at t=0                            0
PASS  price_min_to_date never increases               0
```

`price_7d_*` (rolling window ending at *t*), `oos_rate_to_date` (expanding) and the
competitor block were already clean — I checked rather than assumed.

## 2. Competitor features — clean, plus lagged copies

They are computed within a single `snapshot_id`, so they are contemporaneous, never
forward-looking. That is legitimate for forecasting *t+1* from *t*.

Added explicit lagged copies for strictly-past modelling:
`competitor_avg_price_lag_1`, `price_gap_vs_avg_pct_lag_1`, `is_cheapest_lag_1`,
`price_rank_lag_1`.

## 3. Date/time features — filled

I had been over-cautious and nulled these on the real rows. The observation **date**
(2026-07-10) is real — only the clock time was never recorded. Date-derived features are
therefore perfectly legitimate.

`date`, `week`, `month`, `dow_num`, `is_weekend` — **0 nulls on all four platforms.**
`hour` stays `-1` on real rows, with a new `time_of_day_known` flag (0/1).

## 4. Unit price — standardised

`unit_price` (₹ per base unit) is now joined by:

- `unit_price_std` — a comparable basis: **₹/kg**, **₹/litre**, or **₹/piece**
- `unit_price_basis` — which of the three applies
- `is_multipack` — 36,414 rows (`2 x 10 tabs` → 20 tab)
- `is_combo_pack` — 13,752 rows (`177 g + 1 set`; the measured component is used)

Sanity check: median ₹745/kg, ₹699/L, ₹259/piece.

## 5. Chronological split

Never random on a time series. Split by date, no date in two splits:

| split | rows | dates |
|---|---|---|
| train | 392,560 | 2026-09-15 → 2026-10-04 |
| val | 78,512 | 2026-10-05 → 2026-10-08 |
| test | 117,768 | 2026-10-09 → 2026-10-14 |
| holdout_real | 21,949 | the real Blinkit snapshot |

## 6. Standardisation across all four

```
PASS  canonical_product_key identical across platforms
PASS  category inconsistent for a canonical key          0
PASS  subcategory inconsistent for a canonical key       0
PASS  unit_price_std matches its own formula             0
PASS  targets join 1:1 on observation_key                0
PASS  future_* columns absent from the feature table     0
PASS  dtype drift on numeric columns                     0
```

Targets stay in their own file: `ALL_PLATFORMS_ML_targets_v2.csv.gz`.

## 7. NULLs kept where they are legitimate

| Column | Nulls | Why |
|---|---|---|
| `price_lag_1` | 31,763 (5.2%) | first observation of each panel |
| `price_7d_avg` | 31,763 (5.2%) | needs ≥2 observations |
| `competitor_avg_price` | 114,985 (18.8%) | SKU on only one platform |
| `competitor_avg_price_lag_1` | 138,789 (22.7%) | above, plus first observation |
| `future_price` | 31,763 | last observation of each panel |

Do not impute these. A null here means "unknowable at this point", which is information.

## 8. Schema frozen

`data/reference/ML_SCHEMA_v2.xlsx` (last regenerated 2026-09-17 by `build_features`, from raw
after the v15.1 calibration) → `SCHEMA_FROZEN` lists all 109 columns with dtype, null count and a
role tag (`IDENTIFIER — do not feed to model` / `past-only feature` / `feature` / `TARGET`).
Also `SNAPSHOT_COMPLETENESS`, `ID_COLUMNS`, `SPLIT`.

109 = 51 raw + 58 ML-layer. The original freeze had 108: `split` was already part of it.
The one added column is `store_id_source`, which patch v1 (2026-09-17) added to raw and
which therefore flows through to the ML layer. See `data/raw/PATCH_LOG.md`.

---

## Signal survived the fixes

Flipkart Minutes was generated at −6%. Still recovered, with no hard-coding. (Values at the ML v2 build on v14 data; after the v15.1 calibration they are 56.6 / 24.6 / 18.0 / 17.5 — see CLAUDE.md §6.)

| Platform | Cheapest of 4 | Median gap vs competitor avg |
|---|---|---|
| Flipkart Minutes | 68.6% | −5.34% |
| Swiggy Instamart | 29.3% | 0.00% |
| BigBasket | 21.4% | +2.13% |
| Blinkit | 18.9% | +2.88% |

## Load

```python
import pandas as pd, glob
X = pd.concat([pd.read_csv(f, low_memory=False)
               for f in glob.glob('*_ML_price_v2.csv.gz')], ignore_index=True)
y = pd.read_csv('ALL_PLATFORMS_ML_targets_v2.csv.gz')
df = X.merge(y, on='observation_key')

train = df[(df.split == 'train') & df.future_price.notna()]
val   = df[(df.split == 'val')   & df.future_price.notna()]
test  = df[(df.split == 'test')  & df.future_price.notna()]

ID = ['observation_key','snapshot_id','platform','store_id','product_id',
      'canonical_product_key']
features = [c for c in X.columns if c not in ID and X[c].dtype != 'O']
```

## Raw integrity

Historical — hashes of the original `*_RAW.csv.gz` files. The repo now ships parquet,
so these no longer correspond to anything in `data/raw/`:

```
Blinkit_RAW.csv.gz           cec0bf040481bf11
Instamart_RAW.csv.gz         59e39c95a77abdf9
FlipkartMinutes_RAW.csv.gz   bb3b35107e1f1049
BigBasket_RAW.csv.gz         27ddf91b32d81c70
```

Current baseline — `data/raw/*.parquet` after the v15.1 calibration (2026-09-17), checked by
`make verify-raw` (`scripts/verify_raw_integrity.py`, which also lists every earlier baseline):

```
Blinkit_RAW.parquet          d9d87056baace107
Instamart_RAW.parquet        65f0b5d368a30150
FlipkartMinutes_RAW.parquet  5e8ee620ec72ed09
BigBasket_RAW.parquet        68d8d15cc5ea1d0a
```

610,789 rows · 109 columns · 7 targets · 0 leakage failures
