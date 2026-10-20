# Deliverable 7 — stockout-hazard survival v1 (SYNTHETIC)

Built 2026-09-23. `python -m src.features.stock_clock` then `python -m src.models.stockout_survival` →
`outputs/models/stockout_survival/`.

## What this is allowed to claim

Every in-stock spell here is SYNTHETIC. Recovering k, the platform and category scales, the evening and promo
multipliers and the frailty sd shows the pipeline recovers the v15.1 generator's planted hazard
(`docs/GENERATOR_v15_PARAMETERS.md` A). It says nothing about real depletion, and the category scales are not
depletion rates: they were calibrated to a real stock-out *prevalence*. This is the honest substitute for demand
forecasting (CLAUDE.md §4), not demand forecasting.

## Model

Discrete-time Weibull proportional hazard with a shared log-normal frailty per listing, fitted by exact maximum
likelihood (24-point Gauss–Hermite quadrature over the frailty, analytic gradients checked to 1e-10 against numerical
ones, L-BFGS, standard errors from a finite-difference Hessian):

```
h = 1 − exp(−exp(η + s·z) · (r^k − (r−1)^k)),    z ~ N(0,1) per listing, shared by its spells
η = a[category] + b[platform] + g·evening(t+1) + log(1 + d·depth(t+1)) + θ·pressure(t+1)
```

`r` is the in-stock clock from the stock-clock table. Only clocks started by an **observed** restock are used:
a clock that began before the panel is a lower bound. `pressure` is the store demand-pressure index, a new past-only
column read off each store's delivery times (`src/features/stock_clock.py`; its lag-1 autocorrelation is 0.44 against
a planted 0.5). `platform` is a 4-level stratum here because the plan's claim for this deliverable **is** the
per-platform scale.

Parameter recovery uses all 271,812 observed-clock transitions (7,794 listings). That's a parameter check, not a
forecast. On train alone most listings have one spell and the frailty sd is not identified (it collapses to 0).

## Result 1: the rising hazard is recovered, and why deliverable 4 missed it

| Planted (🟠 assumption) | Estimate | 95% CI | Covered |
|---|---|---|---|
| Weibull shape k = 2, pooled curve (V0, what deliverable 4 saw) | 1.379 | 1.353–1.406 | no |
| k, with category and platform (V1) | 1.811 | 1.777–1.845 | no |
| **k, with frailty (V2)** | **1.980** | **1.935–2.026** | **yes** |
| k read off free per-clock steps, no Weibull assumed (V3) | 1.994 | 1.978–2.009 | yes |
| frailty sd on the log hazard (k × 0.25 = 0.50) | 0.495 | 0.458–0.543 (profile likelihood) | yes |
| evening multiplier 1.4 / 0.7 = 2.0 | 1.942 | 1.845–2.044 | yes |
| promo d in (1 + d·depth) = 1.5 | 1.838 | 1.219–2.457 | yes |
| platform λ multipliers 0.994 / 1.064 / 1.524 | 0.995 / 1.072 / 1.530 | all covered | yes |
| store pressure θ = 0.30 | 0.263 | 0.241–0.284 | no, attenuated |

The flattening deliverable 4 saw had two causes: **observed** heterogeneity (category and platform scales differ by
up to 8×, which lifts k from 1.38 to 1.81) and **unobserved** frailty (fragile listings run out early, so long clocks
are survived by sturdy ones: 1.81 → 1.98). The frailty term improves the likelihood by LR = 161.6 on 1 df. The 22
category scales correlate 0.991 (log scale) with the planted ones.

θ is attenuated because the pressure index is a noisy estimate of the latent demand. That's errors-in-variables,
and the estimate is correctly signed and roughly 88% of the planted value.

## Result 2: time-to-stock-out forecasts (test, fitted on train only)

`P(out of stock within h snapshots)`. Each listing's frailty posterior is updated with its own history up to t.
A clock that began before the panel has its unknown age integrated out under the fitted model's equilibrium law,
`P(age a | survived o) ∝ S(a + o)`.

| h | Frailty survival | LightGBM (one model per h, every feature) | Life table | ROC-AUC (survival) |
|---|---|---|---|---|
| 1 (½ day) | **0.1098** | 0.1102 | 0.1138 | 0.754 |
| 2 (1 day) | **0.1831** | 0.1838 | 0.1867 | 0.737 |
| 4 (2 days) | **0.2946** | 0.2948 | 0.3003 | 0.738 |
| 6 (3 days) | **0.3744** | 0.3753 | 0.3818 | 0.741 |

(Log loss, lower is better.) A structural model with 30 parameters matches or beats a LightGBM with every feature,
at every horizon. It is stronger on observed-restock clocks (ROC-AUC 0.77) than on pre-panel clocks (0.66–0.69),
where the elapsed time has to be integrated out. The frailty posterior adds nothing to the forecast (V2 ≈ V1):
fitted on the 20 train days, the frailty sd is ~0.

## Caveats

- The forecast frailty is unidentified on train alone. Only the full-panel recovery fit identifies it.
- The equilibrium-age integration for pre-panel clocks assumes a stationary renewal process and a 120-snapshot age
  support. It is not told the generator's 60-snapshot burn-in.
- Nothing transfers to the REAL snapshot, which has no clocks.

Figure: `outputs/models/stockout_survival/figures/stockout_survival.png`. Panel A is the key picture: free per-clock
steps with frailty follow the planted k = 2 curve, while the pooled hazard flattens.
