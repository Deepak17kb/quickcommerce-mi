# Deliverable 4 — stock-out classifier v1 (SYNTHETIC)

Built 2026-09-23; retrained the same day after the stock-clock table gained `store_pressure_index`.

```
python -m src.features.stock_clock          # new derived feature table, prints its leakage check
python -m src.models.stockout_classifier    # -> outputs/models/stockout_classifier/
```

## What this is allowed to claim

Every row carrying `future_stock` is SYNTHETIC. These numbers show the pipeline **recovers the v15.1
generator's planted stock-out hazard and restock process** (`docs/GENERATOR_v15_PARAMETERS.md` A, B).
They say nothing about real availability. The category hazard scales are calibrated to a real
stock-out *prevalence*, which cannot separate depletion from replenishment: never "category X sells
out faster".

## New data: the stock-clock table (`src/features/stock_clock.py` → `data/ml/stock_clock.parquet`)

The ML layer had `oos_run_length` (how long a listing has been OUT) but not the clock a
duration-dependent hazard runs on: how long it has been IN stock. It also had no view of the whole store
at t, though the generator drives stock-outs with a latent store demand pressure. 13 past-only columns,
joined on `observation_key`; `data/raw` and the frozen ML files are untouched:

| Column | What |
|---|---|
| `instock_run_length` | consecutive in-stock snapshots up to and including t |
| `instock_clock_censored` | 1 while the run started at the panel start (clock is a lower bound; the generator burns in 60 snapshots) |
| `snapshots_since_restock` | the clock, only when a restock was actually observed |
| `oos_spells_to_date`, `mean_oos_spell_to_date` | spell history (left-censored spells excluded) |
| `store_oos_share`, `_lag_1`, `store_eta_mean`, `store_eta_z`, `store_eta_delta` | store demand-pressure proxies at t |
| `catplat_oos_share` | platform × category OOS share at t |
| `next_snapshot_is_evening` | from the published 09:00/18:00 schedule, not from t+1 data |
| `store_pressure_index` | the store's ETA vs its own same-hour past, in past-sd units: latent demand read off delivery times |

Leakage check (`verify()`, printed on every build): every panel truncated at snapshot 30, rebuilt, and
compared with the full build. 13/13 PASS.

## Method

Two LightGBM heads, because a state change is two processes:

- **depletion**: rows in stock at t, event = OOS at t+1 (base rate 2.6%)
- **restock**: rows OOS at t, event = back at t+1 (base rate 37%)

They are assembled into P(in stock at t+1). 89 features: `L.feature_columns`, the stock clock, and `category`
as a categorical. `platform` and `store_id` are identifiers, refused by the guard, and stay out.
Chronological split from the `split` column; early stopping on val; test scored once.

## Result (test, 107,954 rows)

Persistence is right 95.2% of the time and useless as a probability, so the bar is a transition table
learned on train: **P(change | state, category)**.

| Forecast | log loss | Brier | ROC-AUC |
|---|---|---|---|
| persistence | ∞ | 0.0485 | — |
| markov (state) | 0.1557 | 0.0388 | 0.798 |
| markov × category (**bar**) | 0.1491 | 0.0376 | 0.861 |
| LightGBM without stock clock | 0.1439 | 0.0370 | 0.889 |
| **LightGBM + stock clock** | **0.1425** | **0.0369** | **0.894** |

Beats the bar on every head: log-loss skill +4.4% overall, +5.4% depletion, +1.8% restock.
The stock-clock features improve the depletion head (PR-AUC 0.073 → 0.082, ROC-AUC 0.739 → 0.753) and
do nothing measurable for the restock head, which already had `oos_run_length`. Calibration error
(ECE) 0.003 on the depletion head.

**Stock-out radar**: flagging 1% of in-stock listings catches 6.1% of next-snapshot stock-outs (6.1×
lift, the table gets 2.0×); at 5%, 21.9% (table 12.6%); at 10%, 34.6% (table 25.5%).

## Planted-parameter recovery (pipeline check)

| Planted (🟠 assumption) | Recovered |
|---|---|
| Hazard rises with the in-stock clock, discrete Weibull k = 2 | k̂ = 1.40 ± 0.05 from the model, 1.38 ± 0.06 from observed rates; hazard 0.4% at run 1 → 3.5% at run 25 |
| Evening multiplies the hazard increment 1.4 / 0.7 = 2.0× | counterfactual flip (hour and schedule together) **1.93×** (2.13× before the retrain); observed 1.95× |
| Restock speed Blinkit < Instamart < BigBasket < Flipkart | model-implied mean spell 2.33 < 2.34 < 2.94 < 2.99: **order exact**, Spearman 1.0 |

k̂ < 2 is expected, not a failure: the product frailty (lognormal sd 0.25) and the category/platform scale
mix mean long runs are survived disproportionately by sturdy products, which flattens the pooled curve.
The platform result is notable because `platform` is **not** a model input — the order is recovered
through features that correlate with platform.

**Where deliverable 7 takes over.** k̂ = 1.40 here is the pooled curve. Deliverable 7 shows why it is below 2:
category/platform heterogeneity takes it to 1.81, and a per-listing frailty to 1.98 (`docs/STOCKOUT_SURVIVAL_v1.md`).

## Honest caveats

- The restock head barely beats the table (+1.8%). Restock in the generator is a negative binomial duration
  with little observable signal beyond the spell age and group, so there is little to learn.
- Depletion PR-AUC 0.08 is low in absolute terms, as a 2.6%-base-rate hazard with lognormal frailty
  should be. The honest framing is 3–6× lift, not "predicts stock-outs".
- Nothing transfers to the REAL snapshot, which has one observation per listing and so no clock.

Figure: `outputs/models/stockout_classifier/figures/stockout_classifier.png`.
