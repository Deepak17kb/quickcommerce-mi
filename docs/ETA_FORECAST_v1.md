# Deliverable 5 — delivery ETA v1 (SYNTHETIC)

Built 2026-09-23. `python -m src.features.stock_clock` then `python -m src.models.eta_forecast` →
`outputs/models/eta_forecast/`.

## What this is allowed to claim

Every row with a `future_eta` (the next snapshot's `delivery_eta_min`) is SYNTHETIC. Recovering the ETA equation and
beating the baselines show the pipeline recovers the generator's planted delivery dynamics
(`docs/GENERATOR_v15_PARAMETERS.md` D). None of it describes the real delivery performance of any platform or store.

## Part 1 — structural recovery (whole panel; a parameter check)

Planted: `eta_min = round(base[platform] + store_eff + 3.5·[18:00] + 1.6·D + 4.0·depth + 8.0·(store OOS share −
platform mean) + N(0,1))`, with a latent store demand `D ~ AR(1)`, φ = 0.5, sd 1.

| Term | Planted | Recovered | How |
|---|---|---|---|
| evening peak (min) | 3.5 | **3.44** (3.32–3.56) | store × snapshot intercepts on store dummies + evening |
| discount effect (min per 100% depth) | 4.0 | 3.88 (3.84–3.93) | within store × snapshot; slightly low because observed discounts come from ceil-rounded MRPs |
| listing noise sd | 1.0 | 1.03 | stage-1 residual (includes rounding to whole minutes) |
| store effect sd | 1.5 | 1.60 | from only 30 stores |
| **store OOS-share effect** | **8.0** | **56.0 naive → 19.2 state-space** | see below |
| latent demand effect | 1.6 | 1.29 naive → 1.38 state-space | sd of the store residual |
| latent demand persistence φ | 0.5 | 0.34 naive → 0.44 state-space | residual autocorrelation |

**The confounding finding.** The same latent demand drives stock-outs (deliverable 7's hazard carries exp(0.3·D)) and
delivery time. So a regression of ETA on the store's OOS share credits demand's effect to stock-outs: 56 minutes per
100% instead of 8. A two-series state-space model has D as an AR(1) state read by the OOS share and by ETA, fitted by
Kalman-filter maximum likelihood. It uses the part of the OOS share that demand does not explain, and brings the
estimate to 19. Full recovery needs a joint model of the stock process with its many lags of D. The transferable
lesson: "stock-outs slow deliveries", estimated from observational data, is confounded by demand.

## Part 2 — next-snapshot forecast (test, 107,954 rows)

LightGBM (L1) on the ETA change, early-stopped on val.

| Method | Test MAE (min) |
|---|---|
| naive (ETA now) | 3.530 |
| seasonal naive (ETA one snapshot ago, same hour as the next) | 1.984 |
| listing's same-hour mean to date | 1.550 |
| **LightGBM** | **1.519** |

It beats every baseline (+2.0% vs the best), and on every platform (MAE 1.43–1.63 vs 3.44–3.63 naive). The top
features are the schedule (`hour`, `next_snapshot_is_evening`) and the store-level signals from the stock-clock table
(`store_eta_delta`, `store_eta_mean`, `store_eta_z`).

## Part 3 — a promise you can keep: conformal intervals

Quantile LightGBMs (5/95 and 10/90) alone cover only 48.7% and 62.8% on val. Split-conformal calibration on val (CQR)
widens them by 1.18 and 1.41 minutes, and on the untouched test split:

| Target | Test coverage (shipped, marginal CQR) | Mean width | Worst platform × hour cell | Mondrian CQR worst cell |
|---|---|---|---|---|
| 80% | **80.3%** | 4.95 min | 72.2% (Blinkit 18:00) | 70.3% |
| 90% | **90.1%** | 6.26 min | 85.0% | 81.2% |

`promise_eta_90` in the predictions is the rounded-up upper bound: the ETA a platform could show and keep about 90% of
the time.

**The per-cell calibration that didn't work, and why.** Coverage is exact on average but uneven by cell. Group-
conditional ("Mondrian") calibration, one correction per platform × hour, made the worst cell *worse*. The diagnostic
explains it. Misses cluster by store × snapshot: one store's demand shock moves every listing's ETA at once. 34% of
the variance of the miss indicator sits between the 330 store × snapshot clusters in test, and cluster coverage ranges
from 1% to 100%. Each cell therefore holds only a few dozen independent units, and a per-cell correction fitted on val
is noise. Conformal guarantees assume exchangeable units; here the unit is the store-snapshot, not the listing.
Marginal CQR is shipped; a cluster-level conformal method is the principled next step.

Figure: `outputs/models/eta_forecast/figures/eta_forecast.png`.
