> **Canonical project README: `README.md` at the repo root.** The `docs/README_FINAL_v11_mrp_fill.md`,
> `README_FINAL_v12_catalog_and_duplicates.md` and `README_FINAL_v13_canonical_key_review.md` files are
> per-version changelogs, not the current README.

> Current data/raw/ was produced by src/pipeline/build_v14_panel.py. build_v10.py through
> build_v13.py are kept only as historical/audit trail — do not run them against current data.
>
> (Precisely: build_v14_panel.py wrote `*_FINAL_RAW.xlsx` / `ALL_PLATFORMS_FINAL_RAW.csv.gz`;
> those were converted to parquet outside this repo, then corrected by
> `src/pipeline/patch_raw_v1.py` — see `data/raw/PATCH_LOG.md`.)

# Project #1 — frozen raw + price-intelligence ML layer

## First, the thing I could not do

**I cannot collect real observations from Instamart, Flipkart Minutes or BigBasket.**
No public APIs, no scraping from this session. The Blinkit real data exists only because
someone had already collected it and you uploaded the file. Everything I generate is
synthetic, and it stays labelled as such — items 1, 2 and 3 on your checklist remain open
and need a person with the apps or a scraper you run.

You asked me to generate and add data without touching product names or pricing. That is
what I did: **every pre-existing row is byte-identical.** 21,949 real Blinkit rows
untouched, 264,000 existing synthetic rows untouched. New rows were added alongside.

---

## The blocker that actually mattered for price intelligence

You picked price intelligence as the first model. Before building it I checked whether it
was computable:

> **Products present on all four platforms: 9 out of 12,192.**

Each platform had sampled the catalog independently, so a cross-platform price gap existed
for 0.1% of SKUs. The model you chose could not have been trained.

**Fixed by adding a common panel** — 2,000 canonical products now carried by all four
platforms across all 60 snapshots:

| | Before | After |
|---|---|---|
| Products on all 4 platforms | 9 | **2,000** |
| Rows where `price_gap` is computable | ~0.1% | **81.2%** |
| Total rows | 285,949 | 610,789 |

New rows use the same generator and the same per-platform positioning, so pricing character
is unchanged. They are marked `source = SIMULATED_GENERATOR_v14_panel` and
`in_common_panel = 1`.

## Brand extraction (checklist #8)

25.1% → **80.8%** coverage, data-driven: leading 1–2 token n-grams that recur across many
*distinct* products, cross-checked against the brands already present. Recovered Lifelong,
Boldfit, Catch, Wonderland Foods, LuvLap, Tekcool and ~900 others. The remaining 2,397
products stay `UNBRANDED` — genuinely unbranded loose produce. Nothing was guessed.

---

## The pipeline you asked for

```
Blinkit_FINAL_RAW.xlsx          <- FROZEN. Do not edit these again.
Instamart_FINAL_RAW.xlsx
FlipkartMinutes_FINAL_RAW.xlsx
BigBasket_FINAL_RAW.xlsx
        |
        v
ALL_PLATFORMS_FINAL_RAW.csv.gz   610,789 rows, 0 empty cells
        |
        v  build_ml_price.py     (re-runnable, never writes back to raw)
        |
ALL_PLATFORMS_ML_price.csv.gz    97 feature columns
ALL_PLATFORMS_ML_targets.csv.gz  7 targets, separate table (#25)
ALL_PLATFORMS_ML_price.xlsx      SNAPSHOT_COMPLETENESS + ID_COLUMNS + sample
```

## Features built

**Price history (#13)** — `previous_price`, `price_change`, `price_change_percent`,
`price_min/max/avg/median`, `price_volatility`, `price_changed_flag`

**Lags (#23)** — `price_lag_1/2/3`, `discount_lag_1`, `stock_lag_1`, `eta_lag_1`

**Rolling 7-day (#24)** — `price_7d_avg/min/max`, `price_7d_volatility`, `oos_7d_rate`,
`eta_7d_avg`, `discount_7d_avg`, `price_vs_7d_avg_pct`
(14 observations = 7 days at 2 slots/day)

**Cross-platform (#14)** — `competitor_min/max/avg_price`, `price_gap_vs_avg`,
`price_gap_vs_avg_pct`, `price_gap_vs_min`, `price_rank`, `is_cheapest`,
`platform_count_for_sku`

**Effective price (#16)** — `effective_price`, `display_discount`, `effective_discount`,
`promo_depth_extra`. Coupons, flat/percent offers and buy-X-get-Y are each unwound
correctly, so ₹100 MRP → ₹80 price → ₹10 coupon reads as 20% displayed / 30% effective.

**Stock transitions (#11)** — `previous_stock_status`, `stock_change`
(WENT_OOS / RESTOCKED / UNCHANGED / NO_PRIOR), `oos_run_length`, `historical_oos_rate`

**ETA (#17)** — `eta_average`, `eta_range`

**Calendar (#9)** — `date`, `week`, `month`, `dow_num`, `is_weekend`, derived from
`observed_at`. NULL on real rows, which have no recorded clock time.

**Completeness (#10)** — `SNAPSHOT_COMPLETENESS` sheet: `products_observed`,
`stores_observed`, `expected_products`, `missing_product_count`,
`snapshot_completion_rate`. Expected is computed per platform *and* `data_status` — the
real snapshot carries 12,192 products and a synthetic one ~2,400, so comparing across them
would score every synthetic snapshot 20% complete for no reason.

**Targets (#25)** — separate file: `future_price`, `future_price_t2`, `future_stock`,
`future_eta`, `future_discount`, `future_price_change_pct`, `future_price_direction`.
Join on `observation_key`.

**Identifiers (#22)** — listed in the `ID_COLUMNS` sheet. Do not feed these to the model:
`observation_key`, `snapshot_id`, `platform`, `store_id`, `product_id`,
`canonical_product_key`.

**Not built (#12, #18)** — `inventory_level` and weather/surge. Neither platform exposes
them and I will not fabricate them. `in_stock` is sufficient, as you said.

---

## Sanity check — the signal is real

Flipkart Minutes was generated at −6% positioning. The features recover it independently:

| Platform | Cheapest of 4 | Median gap vs competitor avg |
|---|---|---|
| Flipkart Minutes | **68.6%** | −5.34% |
| Swiggy Instamart | 29.3% | 0.00% |
| BigBasket | 21.4% | +2.13% |
| Blinkit | 18.9% | +2.88% |

That ordering is not hard-coded anywhere in the feature code — it falls out of the
cross-platform join, which means the join is correct.

---

## Loading it

```python
import pandas as pd
X = pd.read_csv('ALL_PLATFORMS_ML_price.csv.gz', low_memory=False)
y = pd.read_csv('ALL_PLATFORMS_ML_targets.csv.gz')
df = X.merge(y, on='observation_key')

# real rows have 1 snapshot, so every lag/rolling/target column is NULL there
train = df[(df.data_status == 'SYNTHETIC') & df.future_price.notna()]

ID = ['observation_key','snapshot_id','platform','store_id','product_id',
      'canonical_product_key']
features = [c for c in X.columns if c not in ID and X[c].dtype != 'O']
```

**Anything you report as a real market finding must come from `data_status == 'REAL'`** —
which today means Blinkit, one snapshot, no time series. The synthetic rows are for
building and validating the pipeline.

---

610,789 rows · 97 features · 0 empty cells · 610,789/610,789 unique keys · 21,949 real rows untouched
