# Deliverables 11, 12a, 12b — SIMULATE and OPTIMIZE v1 (SYNTHETIC)

Built 2026-09-23.

```
python -m src.simulate.whatif              # 11   -> outputs/models/simulate_whatif/
python -m src.optimize.price_cut           # 12a  -> outputs/models/optimize_price_cut/
python -m src.optimize.restock_priority    # 12b  -> outputs/models/optimize_restock_priority/
```

## What these may claim

"Under the fitted, generated dynamics, X moves from a to b." Positioning only: price rank, cheapest-of-4 share,
availability, ETA. **Never demand, orders, GMV, revenue or profit.** There is no order or cost data, so no price
here is "profit-optimal" and no stock-out has a rupee cost.

## The engine (`src/simulate/engine.py`)

Every parameter is read from a fitted model's saved outputs through `src/model_output.py`, never retyped:

| World | From | What it simulates |
|---|---|---|
| PriceWorld | price_response (9) | the corrected leader/follower response with bootstrap parameter draws; prices snapped to each listing's inferred grid at its latent level |
| StockWorld | stockout_survival (7), restock_interval (8), eta_forecast (5) | the frailty hazard (k, category, platform, evening, promo, store pressure AR(1)); negative-binomial restock times; ETA terms |

A scenario's price move is a persistent shift of the platform's latent price, which others respond to via the
fitted response. That's the model's definition of a response, not an observed fact.

**Validation first.** With no scenario, the engine reproduces the status quo:

- cheapest-of-4 shares 17.7 / 24.6 / 56.4 / 17.9% against 17.5 / 24.6 / 56.6 / 18.0% in the data (CLAUDE.md §6);
- the test period's out-of-stock path, including the morning/evening zig-zag, to within 0.50 pp mean absolute gap.

A clock that began before the panel starts at its expected age under the fitted hazard's equilibrium law. Without
that, simulated stock-outs dropped from 7.2% to 5.6% in the first step.

## 11 — SIMULATE (30 simulations × 12 snapshots each)

| Scenario | View | Blinkit cheapest-of-4 share | Change (90% band) |
|---|---|---|---|
| P1 Blinkit −3% on every common-panel SKU | static (competitors frozen) | 17.7% → 28.1% | +10.4 pp (10.1–10.7) |
| | **strategic (fitted response)** | 17.7% → **23.7%** | **+6.0 pp** (5.6–6.3) |
| P2 Blinkit −5% on Snacks & Munchies only | static / strategic | 17.7% → 18.3% / 18.0% | +0.6 / +0.3 pp (panel-wide) |
| P3 Swiggy Instamart −3% everywhere | static = strategic | Blinkit 17.7% → 15.1%; Instamart 24.6% → **37.4%** | Instamart +12.9 pp |

- **The static view overstates a leader's gain by 1.7×.** Under the fitted response Instamart follows 1.59% of
  Blinkit's 3% cut within 12 snapshots, Flipkart 1.24% and BigBasket 1.33%.
- **Asymmetry:** a follower's cut draws no response, because the leader follows no one (deliverable 9's negative
  control), so it keeps the whole gain.

| Stock scenario | Segment | Out-of-stock rate | ETA |
|---|---|---|---|
| S1 promo depth +10 points | Blinkit × Snacks & Munchies (88 listings) | 12.06% → 13.24% (+1.18 pp) | +0.39 min on the promoted listings (discount term, 3.88 min per 100% depth) |
| S2 demand surge +2 sd for 2 snapshots | one Blinkit store (334 listings) | 6.19% → 6.65% (+0.46 pp over 12 snapshots) | +0.09 min via OOS share (state-space estimate, still partly confounded) plus the direct demand term (~1.4 min per sd) while the surge lasts |

## 12a — the smallest Blinkit cut that makes it cheapest-of-4 on 40% of a category's SKUs

Bisection on the engine for all 13 categories with ≥30 common-panel SKUs at once (categories never interact).
Common random numbers keep the share monotone in the cut.

| Category | SKUs | Cheapest now | Min cut, static | **Min cut, strategic** |
|---|---|---|---|---|
| Staples & Grains | 39 | 21.8% | 4.7% | **7.6%** |
| Baby Care | 55 | 16.7% | 5.1% | 8.1% |
| Sweets & Chocolates | 135 | 16.6% | 5.6% | 8.4% |
| Home & Cleaning | 119 | 19.3% | 5.3% | 8.5% |
| Other / General Merchandise | 636 | 18.1% | 5.5% | 9.0% |
| Fruits & Vegetables | 155 | 18.7% | 5.7% | 9.2% |
| Dairy, Bread & Eggs | 177 | 17.5% | 6.1% | 9.3% |
| Masala, Oil & More | 126 | 16.4% | 5.6% | 9.6% |
| Bakery & Biscuits | 77 | 20.5% | 5.7% | 10.1% |
| Pet Supplies | 30 | 14.0% | 6.3% | 10.1% |
| Personal Care | 123 | 13.5% | 6.7% | 10.6% |
| Beverages | 125 | 17.2% | 6.2% | 10.7% |
| Snacks & Munchies | 66 | 19.4% | 5.7% | 10.7% |

**Ignoring competitor response understates the cut needed by a median of 1.62×.** The answer is a positioning
optimum. What the cut would cost cannot be computed.

## 12b — restock priority under a capacity limit

Each snapshot, each store may act on 1% of its listings: expedite an out-of-stock item, or top up an in-stock one so
that its in-stock clock resets. A policy sees only what an operator could see: stock state, time out so far, in-stock
clock, category, platform. It never sees the simulator's hidden remaining durations. 20 simulations × 12 snapshots,
same random streams across policies.

| Policy | OOS listing-snapshots | Reduction vs none (90% band) | Saved per action |
|---|---|---|---|
| none | 7,404 | — | — |
| random | 6,258 | 15.5% (12.0–19.5) | 1.14 |
| longest-out-first | 6,364 | 14.0% (10.5–17.7) | 1.03 |
| **priority index** | **5,426** | **26.7%** (25.5–27.6) | **1.96** |

The priority index scores each listing by expected out-of-stock snapshots saved within the remaining horizon:
`E[min(D − a, H_left) | D ≥ a]` for an out-of-stock item (deliverable 8), and the drop in `P(out within H_left)` from
resetting the clock times the expected capped spell for an in-stock item (deliverables 7 and 8).

**The "sensible" rule is worse than random.** Restock times have dispersion n ≈ 2, so an item that has been out a long
time is usually about to come back anyway, and expediting it wastes capacity. Meanwhile the in-stock items with long
clocks are the ones about to run out (k ≈ 2), which only the priority index sees.

Figures: `outputs/models/simulate_whatif/figures/simulate_whatif.png`,
`outputs/models/optimize_price_cut/figures/price_cut.png`,
`outputs/models/optimize_restock_priority/figures/restock_priority.png`.
