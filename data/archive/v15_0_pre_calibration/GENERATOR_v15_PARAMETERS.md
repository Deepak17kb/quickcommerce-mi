# Generator v15 — planted parameters

> **Recovering these parameters with a model proves the MODELING PIPELINE works — exactly like the
> Flipkart Minutes −6% recovery check proves the cross-platform join works. It is NOT a market finding.
> No result computed from SYNTHETIC rows may ever be reported as one.**

Script: `src/pipeline/build_v15_dynamics.py` (values below are generated from its `PARAMS` dict — that dict is the single source of truth). Seed `20260917`. Realized random draws: `docs/GENERATOR_v15_realized.json`. Run 2026-09-17.

Applies to SYNTHETIC rows only (`source = SIMULATED_GENERATOR_v15`, `price_provenance = simulated_v15_dynamics_around_v14_panel_level_from_blinkit_median_reference`). The 21,949 REAL Blinkit rows are untouched.

## Category groups

| Group | Categories |
|---|---|
| FAST | Fruits & Vegetables, Dairy, Bread & Eggs |
| SLOW | Home & Cleaning, Kitchen & Dining, Electronics & Stationery, Fashion & Lifestyle, Other / General Merchandise |
| MEDIUM | every other category |

Panels per group: {'MEDIUM': 4318, 'SLOW': 3861, 'FAST': 1635}.

## A. Stock-out hazard (duration-dependent)

`h(r) = 1 - exp(-m * ((r/lam)^k - ((r-1)/lam)^k)),  r = consecutive in-stock snapshots so far` — discrete Weibull, shape **k = 2.0** (k > 1 ⇒ hazard rises with consecutive in-stock snapshots; the run counter resets to 1 on restock).

Scale λ (snapshots) = group scale × platform multiplier × product frailty `lognormal(0, 0.25)`:

| Group \ Platform | Blinkit | Swiggy Instamart | Flipkart Minutes | BigBasket |
|---|---|---|---|---|
| FAST (λ=15.0) | 15.00 | 14.25 | 12.75 | 16.50 |
| MEDIUM (λ=27.0) | 27.00 | 25.65 | 22.95 | 29.70 |
| SLOW (λ=38.0) | 38.00 | 36.10 | 32.30 | 41.80 |

Platform multipliers: {'Blinkit': 1.0, 'Swiggy Instamart': 0.95, 'Flipkart Minutes': 0.85, 'BigBasket': 1.1}.

Multipliers on the hazard increment `m`:

- time of day: 09:00 × 0.7, 18:00 × 1.4
- **E. promo depletion:** `m *= 1 + 1.5 * discount_depth` (depth = that snapshot's discount fraction; 0 for non-promo panels)
- store demand pressure: `m *= exp(0.30 * D[store, t])`

## B. Restock duration

When an item goes out of stock it stays out for `D = 1 + NegativeBinomial(n=2, mean=mu - 1)` snapshots (n = 2.0).

Mean μ (snapshots) = group mean × platform multiplier:

| Group \ Platform | Blinkit | Swiggy Instamart | Flipkart Minutes | BigBasket |
|---|---|---|---|---|
| FAST (μ=1.6) | 1.360 | 1.440 | 2.000 | 1.840 |
| MEDIUM (μ=2.5) | 2.125 | 2.250 | 3.125 | 2.875 |
| SLOW (μ=4.0) | 3.400 | 3.600 | 5.000 | 4.600 |

Platform multipliers: {'Blinkit': 0.85, 'Swiggy Instamart': 0.9, 'Flipkart Minutes': 1.25, 'BigBasket': 1.15}.

## Store demand pressure (shared by A and D)

`D[s,t] = phi * D[s,t-1] + sqrt(1 - phi^2) * N(0,1)` with **φ = 0.5**, one series per store, stationary sd 1.

## C. Cross-platform price response (leader / follower)

- Price level per panel: panel mean of v14 selling_price (keeps each platform's positioning).
- `selling_price = round(level * exp(x + wave[platform, t]))`; rounding nearest 0.10 below Rs 20, nearest Rs 1 otherwise.
- Leader: **Blinkit** — `x[t] = rho_leader * x[t-1] + N(0, sigma_leader)`, ρ = 0.6, σ = 0.03.
- Followers — `x[t] = rho_follower * x[t-1] + beta * (x_leader[t-lag] - x[t-1]) + N(0, sigma_follower)`, ρ = 0.6, σ = 0.02:

| Follower | β (adjustment toward leader) | lag (snapshots) |
|---|---|---|
| Swiggy Instamart | 0.45 | 1 |
| Flipkart Minutes | 0.3 | 1 |
| BigBasket | 0.35 | 2 |

- beta = 0 when the product is not carried by Blinkit (1,335 follower panels).
- Platform-wide time wave: `N(0, 0.005)` per platform × snapshot.
- MRP: promo panels: mrp = ceil(price / (1 - depth * U(0.75, 1.15))), depth clipped to [0.02, 0.60]; else mrp = price. `mrp_source` (promo status) is unchanged per panel.
- Because x has mean 0 and each panel keeps its v14 level, each platform's mean positioning is unchanged. Equivalent regression form: `x_f[t] = (ρ − β)·x_f[t−1] + β·x_leader[t−lag] + ε`.

## D. Delivery ETA

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
| BGB-BBSR-001 | +0.106 |
| BGB-BBSR-002 | +0.300 |
| BGB-BBSR-003 | +1.927 |
| BGB-BBSR-004 | -0.299 |
| BGB-BBSR-005 | +1.743 |
| BGB-BBSR-006 | +1.418 |
| BLK-BBSR-001 | -1.424 |
| BLK-BBSR-002 | +0.816 |
| BLK-BBSR-003 | -1.804 |
| BLK-BBSR-004 | +0.988 |
| BLK-BBSR-005 | +0.108 |
| BLK-BBSR-006 | -0.332 |
| BLK-BBSR-007 | +1.603 |
| BLK-BBSR-008 | +1.043 |
| FKM-BBSR-001 | +1.195 |
| FKM-BBSR-002 | +1.176 |
| FKM-BBSR-003 | -0.452 |
| FKM-BBSR-004 | +1.176 |
| FKM-BBSR-005 | -0.329 |
| FKM-BBSR-006 | +0.974 |
| INS-BBSR-001 | +0.719 |
| INS-BBSR-002 | +0.140 |
| INS-BBSR-003 | +2.238 |
| INS-BBSR-004 | +2.673 |
| INS-BBSR-005 | -0.056 |
| INS-BBSR-006 | -0.398 |
| INS-BBSR-007 | -1.093 |
| INS-BBSR-008 | +1.913 |
| INS-BBSR-009 | +0.406 |
| INS-BBSR-010 | +0.083 |

## Other re-simulated fields

- `is_bestseller` = the panel's v14 flag when in stock, 0 when out of stock.
- Offers cleared (`NO_OFFER`, zeros) when out of stock (68,594 rows) and when a FLAT/BANK/COMBO offer value ≥ the selling price (7,282 rows — fixes the v14 defect that clipped effective_price to ₹0.01 on 8,432 rows).
- `unit_price = selling_price / pack_qty`; `stock_status` follows `in_stock`.
- Burn-in: 60 snapshots simulated before the grid and discarded, so the first grid snapshot is not a cold start.

## Unchanged from v14

Identifiers, the 60-snapshot grid, stores, catalog fields, listing fields, the 2,000-product common panel, `mrp_source`, `is_sponsored`, `delivery_fee`, `minimum_order_value`, `enrichment_provenance`, `data_status`, `is_real_observation`, `in_common_panel`, `store_id_source`.

## Recovery checks (tests/test_generator_dynamics.py)

| Planted | Check | Documented range |
|---|---|---|
| A | hazard rises over run length 1..10 | Spearman ≥ 0.8 and h(10)/h(1) ≥ 1.8 |
| B | restock spread | single-snapshot spells < 60%, sd ≥ 1, mean FAST < MEDIUM < SLOW |
| C | follower β at its documented lag, OLS on log deviation | within ±30% of β, and |β̂| > 0.1 |
| D | ETA pressure | corr(ETA residual, store OOS share) ≥ 0.2, corr with discount ≥ 0.05, 18:00 − 09:00 ≥ 2 min, store-mean sd ≥ 0.5 min |
