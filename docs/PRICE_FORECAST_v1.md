# Deliverable 2 — next-price forecast v1 (SYNTHETIC)

Built 2026-09-19. `python -m src.models.price_forecast` → `outputs/models/price_forecast_lgbm/`.

## What this is allowed to claim

Every row carrying `future_price` is SYNTHETIC — the 30-day panel is generated (CLAUDE.md §2).
These numbers show the **modelling pipeline recovers the v15.1 generator's planted price dynamics**.
They say nothing about how real quick-commerce prices move. The manifest's `claim_scope` carries
this automatically; keep it attached to every number below.

## Method

LightGBM (`objective: l1`) on the price **change**, `future_price - selling_price`, folded back to a
level before scoring. Predicting the level would spend the model's capacity relearning "tomorrow ≈
today"; on the delta the naive baseline is a constant zero and every gain is real signal.

Split from the pipeline's own `split` column via `L.splits` — train 15 Sep–4 Oct (392,560 rows),
val 5–8 Oct (78,512), test 9–14 Oct (107,954). Never random. Features from `L.feature_columns`:
75 numeric columns, identifiers and targets refused by the guard. Early stopping on val
(best iteration 629 of 3,000); test scored once.

`holdout_real` is absent by construction — the single REAL snapshot has no next observation, so
`future_price` is null there (CLAUDE.md §3.6).

## Result — beats both mandated baselines

| Split | Model MAE | naive | price_avg_to_date | Skill vs naive |
|---|---|---|---|---|
| val | 9.613 | 10.466 | 11.332 | +8.2% |
| test | **9.661** | 10.563 | 11.410 | **+8.5%** |

The bar in CLAUDE.md §6 is to beat **both** baselines or report the model as useless. It beats both:
−8.5% MAE against naive (the stronger one) and −15.3% against `price_avg_to_date`. Verdict recorded
in `metrics.json` is computed, not asserted.

Per platform on test:

| Platform | Model MAE | naive MAE | Skill |
|---|---|---|---|
| BigBasket | 9.360 | 10.415 | +10.1% |
| Swiggy Instamart | 9.210 | 10.290 | +10.5% |
| Flipkart Minutes | 8.134 | 8.929 | +8.9% |
| Blinkit | 11.876 | 12.550 | +5.4% |

Blinkit is the hardest to forecast, and that is the expected shape: v15.1 plants Blinkit as the
price **leader** and the other three as followers with a lagged response. A leader's next move has
less to predict it from; a follower's is partly determined by what the leader already did. The
model recovering that asymmetry is a sign the pipeline works — not a finding about Blinkit.

## Where the signal sits

Top features by gain: `price_vs_7d_avg_pct` (by far the largest), `price_vs_min_to_date_pct`,
`price_7d_volatility`, `price_volatility_to_date`, then the competitor block — `price_gap_vs_avg`,
`price_gap_vs_avg_pct`, `price_gap_vs_avg_pct_lag_1`.

That is the planted structure showing through: mean-reversion toward the recent average, scaled by
volatility, plus a lagged competitor-gap response. Quantifying the leader/follower lags properly is
deliverable 9 (VAR + impulse response), not this model.

## Honest caveats

- +8.5% skill over naive is a **modest** gain, and that is the right order of magnitude. A large
  jump here would more likely mean leakage than a good model. All leakage tests pass.
- The v15.1 price grid is coarse (real-calibrated endings), which attenuates measurable price
  response to ~50% of the planted value (CLAUDE.md §2). The same attenuation caps what this model
  can extract.
- Nothing here transfers to the REAL snapshot: it has no history to forecast from.
