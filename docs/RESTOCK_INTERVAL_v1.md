# Deliverable 8 — restock interval v1 (SYNTHETIC)

Built 2026-09-23. `python -m src.models.restock_interval` → `outputs/models/restock_interval/`.

## What this is allowed to claim

Every out-of-stock spell is SYNTHETIC. Recovering the spell-length distribution, the platform multipliers and the
hidden FAST / MEDIUM / SLOW grouping shows the pipeline recovers the generator's planted restock process
(`docs/GENERATOR_v15_PARAMETERS.md` B, all 🟠 assumptions). It says nothing about real replenishment. This is the
honest substitute for reorder prediction (CLAUDE.md §4).

## Model

A stock-out lasts `D ≥ 1` snapshots: `D − 1 ~ NegBin(n, mean μ − 1)`, `log μ = a[category] + b[platform]`, exact
maximum likelihood with right-censoring (a spell still running at the end contributes `P(D ≥ observed)`). Spells that
began before the panel are dropped. That leaves 14,025 spells, 634 of them censored.

## Result 1: recovery

| Planted | Recovered |
|---|---|
| NegBin dispersion n = 2 | **1.94** (1.82–2.06) |
| memoryless (geometric) restock? | rejected, LR = 557.4 |
| FAST / MEDIUM / SLOW groups, **never given to the model** | K = 3 chosen by BIC; **adjusted Rand = 1.000** against the planted partition |
| 22 categories vs 3 groups × platform | LR = 14.6 on 19 df, p = 0.75: the 3-group model is enough (best AIC 43,112.5) |
| 12 group × platform mean spells | 10 of 12 inside their 95% CI |
| platform ratios to Blinkit 1.059 / 1.471 / 1.353 | 1.066 / 1.469 / **1.411** (BigBasket misses) |

**How the groups were found.** The 22 fitted category effects `a[c]` go into a 1-D Gaussian mixture that accounts
for each estimate's own standard error (EM with known measurement variance plus a shared within-group variance).
BIC picks the number of groups. The result matches the generator's assignment exactly.

**The two misses are one miss.** Both failing cells are BigBasket, and they share the single BigBasket multiplier
(estimate 1.411 vs planted 1.353, z ≈ 2.5). With 15 comparisons that is within chance (Bonferroni p ≈ 0.18).

**Negative control.** Hour, promo depth and store pressure at the moment of stock-out were *not* planted in restock
times. The model estimates all three near 0 (0.0024, 0.0136, −0.0030), every interval covers 0, and the joint test
gives LR = 0.41, p = 0.94. The model does not invent structure that isn't there.

## Result 2: "when will it be back?" (test, fitted on train spells)

`P(back in stock within h | out for a snapshots so far) = [F(a+h−1) − F(a−1)] / [1 − F(a−1)]`

| h | NegBin | LightGBM | Deliverable 4 restock head | Memoryless | Life table |
|---|---|---|---|---|---|
| 1 | **0.6115** | 0.6158 | 0.6166 | 0.6183 | 0.6255 |
| 2 | **0.6072** | 0.6142 | — | 0.6150 | 0.6246 |
| 4 | **0.3779** | 0.3860 | — | 0.3898 | 0.3920 |

(Test log loss.) A 26-parameter structural model beats a LightGBM with every feature at every horizon. It also
improves on deliverable 4's restock head at h = 1. Each out-of-stock listing gets a median return snapshot, translated
into a readable time (`back_by`, e.g. "Thu 15 Oct 09:00"), and an expected remaining duration.

Figure: `outputs/models/restock_interval/figures/restock_interval.png`.
