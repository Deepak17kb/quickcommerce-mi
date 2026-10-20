# Deliverable 3 — price direction v1 (SYNTHETIC)

Built 2026-09-23. `python -m src.features.price_grid` then `python -m src.models.price_direction` →
`outputs/models/price_direction/`.

## What this is allowed to claim

Every row with a next observation is SYNTHETIC. Skill here shows the pipeline extracts the generator's planted mean
reversion and leader/follower response through real-style price grids. It says nothing about real up/down behaviour.

## New data: the price-grid table (`src/features/price_grid.py` → `data/ml/price_grid.parquet`)

On a coarse grid a price moves only when the underlying price crosses a grid boundary. None of that was in the ML
layer. Eight past-only columns: `grid_step_to_date` (the coarsest grid consistent with every price so far),
`grid_step_pct`, `n_distinct_prices_to_date`, `snapshots_at_price`, `share_time_at_price`, `price_level_rank_to_date`,
`steps_above_min_to_date` and `steps_below_max_to_date`. Leakage check: panels truncated at 30 snapshots and rebuilt,
8/8 PASS.

## Result (test, 107,954 rows; FLAT 49%, UP 26%, DOWN 25%)

Baselines are lookup tables learned on train, so they give calibrated probabilities:

| Method | Log loss | Macro-F1 | Balanced accuracy |
|---|---|---|---|
| class prior | 1.0448 | 0.220 | 0.333 |
| persistence (last move) | 0.9265 | 0.563 | 0.562 |
| reversion (vs 7-snapshot mean) | 0.9070 | 0.517 | 0.583 |
| rule_combo (last move × reversion × grid), **the bar** | 0.7917 | 0.606 | 0.607 |
| LightGBM without the grid table | 0.7135 | 0.627 | 0.622 |
| **LightGBM + grid table** | **0.6974** | **0.634** | **0.629** |

It beats the bar on both measures. The grid table cuts log loss 2.3% and carries 71% of the model's gain; the top
features are `grid_step_pct` and `share_time_at_price`.

**Grids make prices sticky.** The share of snapshots where the price moves falls from 94% when one grid step is ≤1% of
the price to 10% when it is >12%.

**"Wait, it will drop" radar.** Flagging the 5% of listings with the highest P(DOWN) is right 78% of the time (base
rate 25%, 3.1× lift; the rule gets 60%).

**Two models, one story.** Reading deliverable 2's price forecast as a direction (a move only beyond half a grid
step) agrees with this classifier on 79.5% of rows. The dedicated classifier is the more accurate on direction
(67.4% vs 62.7%).

Figure: `outputs/models/price_direction/figures/price_direction.png`.
