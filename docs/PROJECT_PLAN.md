# Project plan — 13 deliverables

Planning only, except where marked BUILT. Built so far: the data foundation (raw layer, ML layer,
`src/load.py`, `src/model_output.py`) and deliverable 1 v1 (product matcher). Last updated 2026-09-17, after the v15.1 real-calibrated generator.

**Standing rule.** REAL = the 21,949 Blinkit rows from one observed snapshot (2026-07-10) plus real
reference data (catalog names/brands/categories/pack sizes, the 30 store records: names, addresses,
coordinates, pincodes). Everything with a time dimension, and every non-Blinkit price, stock and ETA,
is SYNTHETIC (`SIMULATED_GENERATOR_v15.1`; `docs/GENERATOR_v15_PARAMETERS.md` marks which generator parameters are 🟢 real-calibrated and which are 🟠 assumptions). A result computed from synthetic rows demonstrates that a
method works, for example by recovering a parameter planted in `docs/GENERATOR_v15_PARAMETERS.md`.
It is never a market finding.

Every model saves through `src/model_output.py` (`docs/MODEL_OUTPUT_CONTRACT.md`) and loads through
`src/load.py` (`docs/DATA_ACCESS.md`).

## Data scope: not buildable, and not planned

No customers, orders, transactions, quantities sold, revenue, inventory levels or ratings exist.
So demand forecasting, price elasticity, reorder prediction, recommendation-to-customer and
order → AOV → GMV → revenue are out of scope. Deliverables 7–10 are the honest substitutes.

## The 13 deliverables

| # | Deliverable | Data it uses | REAL / SYNTHETIC | Can legitimately claim | Cannot claim |
|---|---|---|---|---|---|
| 1 | **Product matcher** — same product or not ("Amla" vs "Amla (Aula)"). **v1 BUILT 2026-09-17** (`docs/MATCHER_v1.md`); tier 1 not yet measurable | REAL Blinkit listings; `CANONICAL_KEY_AUDIT.csv`; human labels in `data/reference/MATCH_REVIEW_QUEUE.csv` | **REAL** | Blocking recall (100% audit, 99.7% stress test); negative discrimination; and, once humans label the queue, precision/recall/F1/PR-AUC on real name variation | Any real name-variation accuracy today (0 human labels; audit positives are identical records); that LightGBM beats the string baseline; cross-platform matching accuracy (other platforms' names are byte copies) |
| 2 | **Next-price forecast** (`future_price`). **v1 BUILT 2026-09-19** (`docs/PRICE_FORECAST_v1.md`) | ML layer train/val/test | SYNTHETIC | The pipeline beats both baselines (naive "tomorrow = today" and `price_avg_to_date`) and recovers the planted AR / leader-follower dynamics | Any statement about how real prices move |
| 3 | **Price direction** (`future_price_direction`). **v1 BUILT 2026-09-23** (`docs/PRICE_DIRECTION_v1.md`) | ML layer | SYNTHETIC | Classifier skill vs a majority/persistence baseline on generated series | Real up/down behaviour of any platform |
| 4 | **Stock-out classifier** (`future_stock`). **v1 BUILT 2026-09-23** (`docs/STOCKOUT_CLASSIFIER_v1.md`) | ML layer | SYNTHETIC | Recovers planted run-length, category, time-of-day and promo effects | Real availability rates or causes |
| 5 | **ETA prediction** (`future_eta`). **v1 BUILT 2026-09-23** (`docs/ETA_FORECAST_v1.md`) | ML layer | SYNTHETIC | Recovers planted store, peak and demand-pressure terms | Real delivery performance of any platform or store |
| 6 | **Price / discount anomaly detection**. **v1 BUILT 2026-09-23** (`docs/ANOMALY_v1.md`) | REAL snapshot for cross-sectional anomalies; ML layer for temporal ones | REAL (cross-sectional) + SYNTHETIC (temporal) | Real rows: listings that are unusual *within the 2026-07-10 snapshot* (e.g. invalid MRP, outlier unit price) | That a real anomaly is an error or a deal without checking the source; any temporal anomaly on real data (no history exists) |
| 7 | **Stockout-hazard survival** (time until OOS; substitute for demand forecasting). **v1 BUILT 2026-09-23** (`docs/STOCKOUT_SURVIVAL_v1.md`) | ML layer, in-stock spells | SYNTHETIC | Recovers the planted discrete-Weibull shape (k = 2) and the category/platform scales | Real depletion rates or demand. The category scales are calibrated to real stock-out *prevalence* and cannot separate depletion from replenishment, so never "category X sells out faster than Y" |
| 8 | **Restock-interval model** (substitute for reorder prediction). **v1 BUILT 2026-09-23** (`docs/RESTOCK_INTERVAL_v1.md`) | ML layer, OOS spells | SYNTHETIC | Recovers planted restock means by group × platform and their spread | Real replenishment performance |
| 9 | **Competitive price-response** (VAR + impulse response; substitute for elasticity). **v1 BUILT 2026-09-23** (`docs/PRICE_RESPONSE_v1.md`) | ML layer, 2,000-product common panel | SYNTHETIC | Recovers the planted leader (Blinkit) and follower lags; on observed (rounded) prices the coefficients are attenuated to ~50% (0.22 / 0.15 / 0.18 vs planted 0.45 / 0.30 / 0.35). Correcting for grid rounding and recovering the planted values is the method demonstration | Who actually leads real pricing; any elasticity or demand effect; an unattenuated pass-through number from rounded prices |
| 10 | **Assortment-gap recommender** (store × product implicit MF; substitute for customer recommendation). **v1 BUILT 2026-09-23** (`docs/ASSORTMENT_GAPS_v1.md`) | Store × product carry matrix | SYNTHETIC (which products each synthetic store carries was generated); REAL only for the Blinkit snapshot's carry matrix | On the real Blinkit snapshot: products a real store does not list that similar real stores do | Customer preference or sales uplift; synthetic stores' assortment as fact |
| 11 | **SIMULATE** — competitive-positioning what-ifs. **v1 BUILT 2026-09-23** (`docs/SIMULATE_OPTIMIZE_v1.md`) | Outputs of 2, 4, 5, 9 via the contract; ML layer | SYNTHETIC | What-ifs on **price rank, cheapest-of-4 share, availability and ETA** ("if Blinkit cuts SKU X by 3%, its cheapest-share on the panel moves from a to b under the fitted response") | **Demand, orders, GMV or revenue** — no order data exists; any real-market forecast |
| 12 | **OPTIMIZE** | see sub-rows | mixed | see sub-rows | see sub-rows |
| 12a | — minimum price cut to reach a target cheapest-share. **v1 BUILT 2026-09-23** | Deliverable 11 + 9 outputs | SYNTHETIC | The smallest cut that reaches the target *under the generated dynamics* | Profit-optimal or revenue-optimal prices |
| 12b | — restock priority minimising out-of-stock exposure. **v1 BUILT 2026-09-23** | Outputs of 4, 7, 8 | SYNTHETIC | A ranking that minimises expected OOS snapshots under the fitted hazard/restock models | Lost sales, revenue or real stock-out cost |
| 12c | — **store coverage gaps** | The 30-store master (`data/reference/STORES*.csv`: real names, addresses, coordinates, pincodes) + area/pincode geography | **REAL** | Areas/pincodes of Bhubaneswar farther than X km from any *listed* store of a platform — a real-data deliverable | Complete platform coverage: the 30 stores are the stores in this dataset, not a verified census of all dark stores |
| 13 | **RAG + AI analyst**. **v1 BUILT 2026-09-23** (`docs/AI_ANALYST_v1.md`) | Docs, manifests and `predictions.parquet` of 1–12, the REAL snapshot | mixed — labelled per claim | Answers grounded in cited files, **every claim labelled by source provenance** (REAL / SYNTHETIC, with file and date). Synthetic-derived answers say so **unprompted** | Presenting any synthetic-derived number as market fact; answering demand/revenue questions (it must refuse and say why) |

## After the 13: the product x store chain (BUILT 2026-09-24, `docs/LISTING_CHAIN_v1.md`)

One listing through every layer, in seven explicit stages: **observe -> applicability -> prediction record -> price grid
-> simulation -> optimization -> explanation**. SYNTHETIC listing; the REAL 2026-07-10 row of the same product and store is
context only. Can claim: that the layers agree on one listing (baseline check, cross-check with deliverable 7) and the
smallest grid-feasible cut to a cheapest-share target under the generated dynamics. Cannot claim: anything about the real
listing's future, demand, sales or profit.

Then, in this order, all BUILT 2026-09-24: price increases (`docs/PRICE_INCREASES_v1.md`) -> product unavailable
scenario -> store adds products scenario -> richer restock objective (`docs/SCENARIOS_v1.md`) -> company / market /
competitor documents for the analyst (`docs/EXTERNAL_SOURCES_v1.md`, a fourth provenance label, EXTERNAL). Gaps 1 and 2 of the architecture review (no real
history of demand, price or stock) are a data limitation, not a software problem, and are not being modelled around.

## Build order (when modelling starts)

1 → 2 → 4 → 7 → 8 → 9 → 5 → 3 → 6 → 10 → 11 → 12 → 13.
The real-data deliverables (1, 12c) come first or early. SIMULATE and OPTIMIZE need the fitted outputs
of 2, 4, 5, 7, 8 and 9. The analyst comes last because it consumes everything through the contract.

## Change from the previous plan

The previous plan listed 10 models, dropped SIMULATE and OPTIMIZE, and treated the AI analyst as
optional. That plan predated the v15 generator: on v14 data, deliverables 7–9 could only have
reported "constant rate" or "no effect". v15 plants recoverable structure, so all 13 are in scope,
with the claim limits above.
