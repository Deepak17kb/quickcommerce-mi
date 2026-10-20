# Generator v15.1 — planted and calibrated parameters

> **Recovering these parameters with a model proves the MODELING PIPELINE works — exactly like the
> Flipkart Minutes −6% recovery check proves the cross-platform join works. It is NOT a market finding.
> No result computed from SYNTHETIC rows may ever be reported as one.**

Script: `src/pipeline/build_v15_dynamics.py`. Its `PARAMS` dict is the single source of truth, and this file is generated from it. Seed `20260917`. Realized random draws: `docs/GENERATOR_v15_realized.json`. Input: `data/archive/v14_pre_regen/` (hash-checked). Run 2026-09-17.

Applies to SYNTHETIC rows only (`source = SIMULATED_GENERATOR_v15.1`, `price_provenance = simulated_v15.1_dynamics_around_v14_panel_level_from_blinkit_median_reference_real_calibrated_endings`). The 21,949 REAL Blinkit rows are untouched.

**Versions.** v15.0 planted the dynamics (A–D) with assumed levels. v15.1 (current) calibrated two parts of the generator against the REAL Blinkit 2026-07-10 snapshot: per-category stock-out levels and price-ending styles. Everything else is unchanged from v15.0. v15.0 state: `data/archive/v15_0_pre_calibration/`.

## Provenance at a glance

| Parameter | Provenance | Source |
|---|---|---|
| `hazard.scale_lam_by_category` | 🟢 **REAL-CALIBRATED** | REAL Blinkit per-category stock-out rate, 2026-07-10 (shrunk targets) |
| `price.ending_style_probs_by_band` | 🟢 **REAL-CALIBRATED** | REAL Blinkit selling-price endings, 2026-07-10 |
| `hazard.shape_k` | 🟠 **ASSUMPTION** (not real-derived) | k = 2 depletion shape (v15.0 design choice) |
| `hazard.scale_mult_by_platform` | 🟠 **ASSUMPTION** (not real-derived) | v14 persona stock-out ratios between platforms |
| `hazard.m_hour` | 🟠 **ASSUMPTION** (not real-derived) | time-of-day multipliers (real clock time was never recorded) |
| `hazard.scale_product_frailty_lognormal_sd` | 🟠 **ASSUMPTION** (not real-derived) | v15.0 design choice |
| `hazard.m_promo_depth, hazard.m_store_demand` | 🟠 **ASSUMPTION** (not real-derived) | v15.0 design choice |
| `restock.*` | 🟠 **ASSUMPTION** (not real-derived) | group means FAST/MEDIUM/SLOW and platform multipliers (v15.0 assumptions) |
| `store_demand.*` | 🟠 **ASSUMPTION** (not real-derived) | v15.0 design choice |
| `price.* except ending_style_probs_by_band` | 🟠 **ASSUMPTION** (not real-derived) | leader/follower, rho, sigma, wave, style persistence |
| `eta.*` | 🟠 **ASSUMPTION** (not real-derived) | v15.0 design choice; platform base means from v14 personas |

🟢 = fitted so the SIMULATED data reproduces an observable property of the REAL Blinkit snapshot. 🟠 = a design choice carried over from v14/v15.0; no real data supports or contradicts it (a single snapshot has no time dimension, no clock time and no other platform).

## ⚠ Identifiability — read before using any hazard value

The per-category hazard scales are calibrated so that the **simulated stock-out rate** matches the **real observed stock-out rate**, *given the restock-duration assumptions below*. A stock-out rate from a single snapshot is a prevalence: roughly (how often an item runs out) × (how long it stays out). **One snapshot cannot separate depletion speed from replenishment speed**. A category with a high real stock-out rate may deplete fast, restock slowly, or both.

Therefore these hazard scales are **NOT depletion rates**, and **must never be reported as "category X sells out faster than category Y"**. Had the restock assumptions been different, the calibration would have produced different hazard scales for the same real data. The only real-data statement they support is: *on 2026-07-10, the share of Blinkit listings out of stock differed by category as in the target table.*

## A. Stock-out hazard (duration-dependent)

`h(r) = 1 - exp(-m * ((r/lam)^k - ((r-1)/lam)^k)),  r = consecutive in-stock snapshots so far` — discrete Weibull. 🟠 Shape **k = 2.0**: k > 1 means the hazard rises with consecutive in-stock snapshots, and the run counter resets on restock.

Scale λ (snapshots) = category scale × platform multiplier × product frailty `lognormal(0, 0.25)` 🟠.

### 🟢 Category scales — REAL-CALIBRATED (not depletion rates; see Identifiability)

Target = REAL Blinkit 2026-07-10 stock-out rate per category, shrunk toward the overall real rate (6.17%) with 200 pseudo-rows, so small categories are not fitted to noise. Method: dry runs of the generator; λ_c ← λ_c × (simulated Blinkit rate_c / target_c), iterated to convergence. Achieved: mean absolute error 0.22 pts, correlation 0.99 with target and 0.93 with the raw real rates.

| Category | REAL rows | REAL OOS % | Target % (shrunk) | λ (Blinkit) | Simulated Blinkit OOS % | Restock group 🟠 |
|---|---|---|---|---|---|---|
| Snacks & Munchies | 1,303 | 14.27 | 13.20 | 15.28 | 13.22 | MEDIUM |
| Dry Fruits & Nuts | 342 | 15.79 | 12.24 | 18.88 | 12.22 | MEDIUM |
| Staples & Grains | 538 | 14.13 | 11.97 | 19.98 | 11.97 | MEDIUM |
| Fruits & Vegetables | 2,126 | 9.50 | 9.21 | 16.29 | 9.18 | FAST |
| Bakery & Biscuits | 1,245 | 7.71 | 7.50 | 28.73 | 7.37 | MEDIUM |
| Instant & Ready to Eat | 160 | 8.75 | 7.32 | 37.71 | 7.50 | MEDIUM |
| Masala, Oil & More | 1,684 | 7.30 | 7.18 | 33.69 | 7.37 | MEDIUM |
| Tea, Coffee & More | 240 | 5.42 | 5.76 | 35.62 | 5.76 | MEDIUM |
| Sauces, Spreads & Pickles | 267 | 5.24 | 5.64 | 47.73 | 6.87 | MEDIUM |
| Electronics & Stationery | 27 | 0.00 | 5.43 | 50.24 | 5.83 | SLOW |
| Other / General Merchandise | 5,479 | 5.35 | 5.38 | 71.54 | 5.37 | SLOW |
| Kitchen & Dining | 120 | 3.33 | 5.11 | 65.94 | 5.07 | SLOW |
| Frozen Foods | 75 | 1.33 | 4.85 | 46.78 | 3.33 | MEDIUM |
| Health & Wellness | 63 | 0.00 | 4.69 | 41.21 | 4.62 | MEDIUM |
| Sweets & Chocolates | 1,880 | 4.47 | 4.63 | 50.54 | 4.46 | MEDIUM |
| Baby Care | 392 | 3.83 | 4.62 | 48.80 | 4.74 | MEDIUM |
| Personal Care | 1,141 | 4.12 | 4.42 | 55.96 | 4.42 | MEDIUM |
| Fashion & Lifestyle | 129 | 1.55 | 4.36 | 95.53 | 4.60 | SLOW |
| Dairy, Bread & Eggs | 2,062 | 3.69 | 3.90 | 45.09 | 3.92 | FAST |
| Pet Supplies | 177 | 0.56 | 3.54 | 83.03 | 3.68 | MEDIUM |
| Home & Cleaning | 1,022 | 2.64 | 3.22 | 111.07 | 3.48 | SLOW |
| Beverages | 1,473 | 1.77 | 2.29 | 116.67 | 2.43 | MEDIUM |

### 🟠 Platform multipliers — ASSUMPTION

Tuned only to keep the v14 persona ordering of platform stock-out rates relative to Blinkit (BigBasket 0.055 < Blinkit 0.060 < Instamart 0.065 < Flipkart 0.085). The real snapshot has no data for the other platforms.

| Platform | λ multiplier | Resulting synthetic OOS % |
|---|---|---|
| Blinkit | 1.0 | 5.79 |
| Swiggy Instamart | 0.9943 | 6.25 |
| Flipkart Minutes | 1.0637 | 8.22 |
| BigBasket | 1.5239 | 5.28 |

### 🟠 Multipliers on the hazard increment `m` — ASSUMPTION

- time of day: 09:00 × 0.7, 18:00 × 1.4 (real clock time was never recorded)
- E. promo depletion: `m *= 1 + 1.5 * discount_depth`
- store demand pressure: `m *= exp(0.30 * D[store, t])`

Measured (corrected estimator, `src/diagnostics.py`, left-censored runs excluded): hazard rises at every run length 1→10, run-10/run-1 ratio **15.1**. The estimator returns 0.994 on memoryless stock and 0.845 on v14 (downward selection bias under heterogeneity), so this is a conservative figure.

## 🟠 B. Restock duration — ASSUMPTION

Out-of-stock spells last `D = 1 + NegativeBinomial(n=2, mean=mu - 1)` snapshots (n = 2.0). Mean μ = group mean × platform multiplier. The FAST/MEDIUM/SLOW groups are assumptions, and the real stock-out rates show they are **not** a turnover ranking (e.g. real Dairy 3.7% is below the overall 6.2%). They are used only for restock means.

| Group \ Platform | Blinkit | Swiggy Instamart | Flipkart Minutes | BigBasket |
|---|---|---|---|---|
| FAST (μ=1.6) | 1.360 | 1.440 | 2.000 | 1.840 |
| MEDIUM (μ=2.5) | 2.125 | 2.250 | 3.125 | 2.875 |
| SLOW (μ=4.0) | 3.400 | 3.600 | 5.000 | 4.600 |

FAST: Fruits & Vegetables, Dairy, Bread & Eggs. SLOW: Home & Cleaning, Kitchen & Dining, Electronics & Stationery, Fashion & Lifestyle, Other / General Merchandise. MEDIUM: all other categories.

## 🟠 Store demand pressure (shared by A and D) — ASSUMPTION

`D[s,t] = phi * D[s,t-1] + sqrt(1 - phi^2) * N(0,1)` with φ = 0.5, one series per store, stationary sd 1.

## C. Cross-platform price response (leader / follower)

🟠 Leader **Blinkit**: `x[t] = rho_leader * x[t-1] + N(0, sigma_leader)`, ρ = 0.6, σ = 0.03. Followers: `x[t] = rho_follower * x[t-1] + beta * (x_leader[t-lag] - x[t-1]) + N(0, sigma_follower)`, ρ = 0.6, σ = 0.02. Price level per panel: panel mean of v14 selling_price (keeps each platform's positioning). Platform wave N(0, 0.005). beta = 0 when the product is not carried by Blinkit (1,335 follower panels).

### Planted vs expected-measured coefficients

| Follower | lag | 🟠 PLANTED β (latent, continuous price) | EXPECTED MEASURED β̂ (observed, rounded price) | measured / planted |
|---|---|---|---|---|
| Swiggy Instamart | 1 | 0.45 | 0.22 | 0.49 |
| Flipkart Minutes | 1 | 0.3 | 0.154 | 0.51 |
| BigBasket | 2 | 0.35 | 0.181 | 0.52 |

β̂ = OLS of the follower's log price deviation (from its panel mean) at t on its own deviation at t−1 and Blinkit's at t−lag, common panel, observed prices. Measured on the generated v15.1 data with seed 20260917. `tests/test_generator_dynamics.py` enforces β̂ within ±30% of the expected measured value.

### Methodological finding: rounding attenuation

Snapping prices to coarse, psychological grids (₹10 steps for x9/x0/x5 endings, ₹50 for x49/x99 and x50/x00, ₹100 for x99) **attenuates the measured price-response coefficient to about 50% of the true planted value** (0.49–0.52 here). v15.0, which rounded to ₹1, measured 0.44 / 0.30 / 0.35 against planted 0.45 / 0.30 / 0.35. The only difference is the price grid. Two mechanisms produce it: small adjustments round to zero, so the follower appears not to respond; and each rounding jump is noise in both the regressor and the outcome, which biases OLS toward zero.

**This is not a synthetic artefact to be engineered away.** Real Indian retail prices are similarly discretised: 75% of real Blinkit prices end in 0, 5 or 9, and 52% of real ₹500+ prices end in 49 or 99. So **any real-world pass-through or price-response estimate computed from observed shelf prices is likely attenuated in the same way**, and would understate how strongly platforms actually respond. Correct for it (e.g. model the latent price, use interval regression, or restrict to actual grid moves) or report it as a known downward bias. The v15.1 data can be used to demonstrate and quantify this.

Side effect, stated plainly: the latent volatility parameters are unchanged from v15.0, but rounding to coarse grids raises the observed price dispersion around each panel's mean from 2.9% (v15.0) to 4.3% (v15.1).

### 🟢 Price endings — REAL-CALIBRATED

empirical endings: whole rupees; one pricing style per panel drawn from the REAL Blinkit style shares of its price band; price snapped to that style's grid. drawn once per panel from the band of its v14 price level; fixed over time (assumption: one real snapshot cannot show whether a product keeps its ending style).

Style shares = share of REAL Blinkit 2026-07-10 selling prices in each band with that ending:

| Band | x9 | x0 | x5 | x99 | x49_x99 | x50_x00 | rupee | REAL prices in band |
|---|---|---|---|---|---|---|---|---|
| <20 | 0.3046 | 0.1126 | 0.1589 | — | — | — | 0.4238 | 151 |
| 20-99 | 0.1284 | 0.3147 | 0.1868 | — | — | — | 0.3701 | 6,520 |
| 100-499 | 0.1672 | 0.3190 | 0.1731 | 0.1208 | — | — | 0.2199 | 11,357 |
| 500+ | 0.0367 | 0.0977 | 0.0865 | — | 0.5210 | 0.1303 | 0.1278 | 3,921 |

Grids [step, remainder]: x9 [10, 9], x0 [10, 0], x5 [10, 5], x99 [100, 99], x49_x99 [50, 49], x50_x00 [50, 0], rupee [1, 0]. `x9` excludes prices counted under `x99` / `x49_x99` in their bands, and `x0` excludes `x50_x00`. The <20 band rests on 151 real prices, so treat its shares as rough.

Achieved: last-digit distance to real 8.67/100 (v15.0: 44.5, v14: 51.5), 83.7% of synthetic prices end in 0/5/9 (real 75.1%), 100% whole rupees. Realized styles per panel: {'x0': 2520, 'rupee': 2307, 'x5': 1502, 'x49_x99': 1304, 'x9': 1253, 'x99': 624, 'x50_x00': 304}.

Consequence for regression values: coarser grids create more cheapest-price ties (14.0% of common-panel snapshots, vs 5.7% in v15.0 and 27.9% in v14), which moves the cheapest-of-4 shares; see `tests/test_regression_cheapest.py`.

🟠 MRP: promo panels: mrp = ceil_to_rupee(price / (1 - depth * U(0.75, 1.15))), depth clipped to [0.02, 0.60], at least price + 1; else mrp = price (MRP endings are not calibrated).

## 🟠 D. Delivery ETA — ASSUMPTION

`eta_min = round(base[platform] + store_eff[store] + peak*[hour==18] + b_demand*D[s,t] + b_discount*discount_depth + b_store_oos*(store OOS share - platform mean) + N(0, noise_sd)), >= 5`

| Term | Value |
|---|---|
| base by platform (minutes) | {'Blinkit': 9.5, 'Swiggy Instamart': 9.5, 'Flipkart Minutes': 11.5, 'BigBasket': 13.5} |
| store effect | N(0, 1.5), fixed per store (realized values below) |
| peak slot 18:00 | +3.5 |
| store demand pressure D | +1.6 per sd |
| discount depth (fraction) | +4.0 × depth |
| store OOS share minus platform mean | +8.0 × difference |
| noise | N(0, 1.0) |
| eta_max | eta_min + U{4..10} |

Realized store effects (minutes):

| store_id | effect |
|---|---|
| BGB-BBSR-001 | -0.298 |
| BGB-BBSR-002 | +0.444 |
| BGB-BBSR-003 | +0.661 |
| BGB-BBSR-004 | -2.584 |
| BGB-BBSR-005 | +0.851 |
| BGB-BBSR-006 | +1.219 |
| BLK-BBSR-001 | -2.438 |
| BLK-BBSR-002 | -1.542 |
| BLK-BBSR-003 | -1.022 |
| BLK-BBSR-004 | +2.413 |
| BLK-BBSR-005 | +0.292 |
| BLK-BBSR-006 | -2.296 |
| BLK-BBSR-007 | -0.348 |
| BLK-BBSR-008 | +1.606 |
| FKM-BBSR-001 | -1.496 |
| FKM-BBSR-002 | -0.397 |
| FKM-BBSR-003 | -2.058 |
| FKM-BBSR-004 | -1.132 |
| FKM-BBSR-005 | +2.967 |
| FKM-BBSR-006 | -2.269 |
| INS-BBSR-001 | -1.561 |
| INS-BBSR-002 | -0.550 |
| INS-BBSR-003 | +0.633 |
| INS-BBSR-004 | -0.979 |
| INS-BBSR-005 | -1.590 |
| INS-BBSR-006 | -2.105 |
| INS-BBSR-007 | +0.619 |
| INS-BBSR-008 | +0.558 |
| INS-BBSR-009 | +0.229 |
| INS-BBSR-010 | +1.508 |

## Other re-simulated fields

- `is_bestseller` = the panel's v14 flag when in stock, 0 when out of stock.
- Offers cleared (`NO_OFFER`) on out-of-stock rows (37,499) and where a FLAT/BANK/COMBO value ≥ the selling price (8,030).
- `unit_price = selling_price / pack_qty`; `stock_status` follows `in_stock`.
- Burn-in: 60 snapshots simulated before the grid and discarded.

## Unchanged from v14

Identifiers, the 60-snapshot grid, stores, catalog and listing fields, the 2,000-product common panel, `mrp_source`, `is_sponsored`, `delivery_fee`, `minimum_order_value`, `enrichment_provenance`, `data_status`, `is_real_observation`, `in_common_panel`, `store_id_source`.

## Checks (tests/test_generator_dynamics.py)

| Planted / calibrated | Check | Threshold |
|---|---|---|
| estimator | corrected hazard estimator on memoryless stock | ratio in [0.9, 1.1] |
| A | corrected hazard (left-censored runs excluded) over run 1..10 | Spearman ≥ 0.9 and h(10)/h(1) ≥ 5 |
| B | restock spread | single-snapshot spells < 60%, sd ≥ 1, mean FAST < MEDIUM < SLOW |
| 🟢 stock level | Blinkit synthetic re-weighted to the real category mix vs REAL 6.17% | within ±0.5 pts; category corr with target ≥ 0.9, MAE ≤ 1 pt; platform ordering BigBasket < Blinkit < Instamart < Flipkart |
| 🟢 price endings | last-digit distance to REAL; share ending 0/5/9; whole rupees | ≤ 15; within ±12 pts of real; 100% |
| C | follower β̂ at documented lag, observed prices | within ±30% of EXPECTED MEASURED β̂, > 0.08, and below planted β |
| D | ETA pressure | corr with store OOS share ≥ 0.2, with discount ≥ 0.05, 18:00 − 09:00 ≥ 2 min, store-mean sd ≥ 0.5 min |
