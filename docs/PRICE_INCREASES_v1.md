# Price increases v1: what a raise costs, category and listing (SYNTHETIC)

Built 2026-09-24. This is extension 1 of the post-chain plan (price increases → product unavailable → store adds
products → richer restock objective → company/market/competitor documents).

```
python -m src.simulate.grid              # the what-if grid, now cuts AND raises of 1-10% (161 runs)
python -m src.optimize.price_headroom    # -> outputs/models/optimize_price_headroom/
python -m src.chain.listing --demo       # the listing chain, now with a raise objective
python -m src.analyst "How much headroom does Blinkit have in Beverages?"
python -m src.analyst "If Blinkit raises snacks prices by 5%, what happens?"
```

## What this is allowed to claim

Everything here describes **positioning and availability under the fitted, generated dynamics**.

- "Headroom" means only that a raise costs little cheapest-of-4 share in the generator.
- It never means a raise earns more. No demand, orders, revenue or margin exist in the data, so nothing here can say
  whether a raise pays.
- The analyst refuses "how much more revenue" questions (held-out eval item).
- The link between a shallower promo and fewer stock-outs is a planted generator assumption (deliverable 7's promo
  effect), not a market fact.

## What changed

| Layer | Change |
|---|---|
| What-if grid (`src/simulate/grid.py`) | Raises of 1–10% for every mover, in both views: 161 runs (was 84). Each cell carries `direction`, a positive `cut_pct` (size) and a signed `move_pct`. The cut cells are unchanged, because the seed and the random draws are the same. |
| `src/optimize/price_headroom.py` (new) | Per category: the largest raise within a share-loss budget, raise-vs-cut asymmetry, and a raise taken by withdrawing a promo. |
| Listing chain (`src/chain/listing.py`) | The ladder runs from +30% to −30% on the listing's own grid. Stage 6 has one target and two directions: below the target it finds the smallest cut, at or above it the largest raise that keeps the target. The discount rule is symmetric: with MRP held, a cut deepens a promo and a raise withdraws it. Rungs beyond ±30% (a single step on a coarse grid) are shown but never recommended. |
| Analyst | `simulate_price_move` takes `direction`. The new `price_headroom` tool answers "raise / increase / hike X%" and "headroom / how far can Blinkit raise" questions. |
| What-If Lab | The price slider runs from −10% to +10%, and a headroom tile appears when Blinkit raises. |

## Category level (grid + headroom), all SYNTHETIC

Source: `outputs/models/simulate_grid/metrics.json`, `outputs/models/optimize_price_headroom/metrics.json`.

**The planted structure checks out.**

- **Follower raises.** When a follower raises, the static and responsive views agree exactly (largest gap 0.0 pp).
  Deliverable 9 has followers respond only to Blinkit, so nobody follows a follower.
- **Blinkit raises.** Followers follow Blinkit up, so a static comparison overstates what a raise costs Blinkit, by a
  median 1.42×. That mirrors the 1.76× by which it overstates a cut's gain.

**Blinkit across the whole common panel** (cheapest-of-4 now 17.7%, change in pp, competitors responding / static):

| Move | 1% | 2% | 3% | 5% | 10% |
|---|---|---|---|---|---|
| Raise | −1.71 / −2.74 | −3.27 / −5.08 | −4.74 / −7.07 | −7.06 / −10.11 | −10.90 / −14.01 |
| Cut | +1.79 / +3.10 | +3.87 / +6.53 | +6.08 / +10.47 | +10.72 / +19.05 | +24.83 / +43.54 |

**Raises cost less than cuts buy, and the gap grows with size.** Share lost by raising x%, divided by share gained by
cutting x% (responsive view):

| Size of move | 1% | 5% | 10% |
|---|---|---|---|
| Loss ÷ gain | 0.96 | 0.66 | 0.44 |

Blinkit is cheapest on only 17.7% of SKUs, so a raise can lose at most that much. A cut has the other 82.3% to win.

**There is no free raise.** Even a 1% raise costs 1.4 to 2.4 pp of share in every category (responsive view). The
headroom depends on the loss budget, so all three budgets are reported rather than one picked:

| Budget (share Blinkit may lose) | 1 pp | 2 pp | 5 pp |
|---|---|---|---|
| Categories with any headroom, competitors responding | 0 of 13 | 9 of 13 | 13 of 13 |
| Categories with any headroom, static view | 0 of 13 | 0 of 13 | 13 of 13 |
| Where the response widens headroom | 0 | 9 | 13 |

At the 5 pp budget, the responsive view gives headroom of 2–4% where the static view gives 1–2%. Personal Care has
the most (4% vs 2%). It starts with the lowest share, 13.7%, so it has the least to lose. Snacks (ratio 0.96) and
Bakery (0.94) lose almost as much from a raise as they gain from a cut. The other categories sit between 0.57 and 0.79.

**Withdrawing a promo helps availability, but only slightly.** A 5% raise taken by withdrawing promos (1,313 of 2,479
Blinkit listings have one) changes the stock-out rate by −0.01 to −0.30 pp by category (−0.16 pp panel-wide) and ETA
by about −0.09 min. That is the mirror of the promo frontier, where a 10% promo adds 0.4–1.1 pp. So the generator
asymmetry runs both ways: price moves shift position a lot and availability only a little.

## Listing level (the chain), SYNTHETIC with REAL context

The gallery now has 9 listings: 6 where Blinkit is not the cheapest (the cut question) and 3 where it is cheapest at
the decision snapshot (the raise question). All 9 pass the baseline check.

| Listing | Store | Price, competitors | Hold share | Outcome |
|---|---|---|---|---|
| Wonder Fresh Pocket Air Freshener | BBSR-008 | ₹185; ₹205 / ₹196 / ₹199 | 99.5% | **Raise ₹10 (+5.41%) to ₹195, still cheapest 84.4% with competitors responding** (61.8% static: the response widens the margin). As a promo withdrawal, the stock-out chance within 12 snapshots changes by −1.03 pp and ETA by −0.196 min. |
| Sleepy Owl Cappuccino Premix | BBSR-003 | ₹199; ₹225 / ₹210 / ₹199 | 96.4% | **Hold.** The grid is ₹100 ending 99, so the only raise is ₹299 (+50%), outside the ±30% limit and at 0% share anyway. The grid, not competition, sets the headroom. |
| Boba Bhai Litchi Blood Orange | BBSR-003 | ₹85; ₹85 / ₹85 / ₹89 | 31.9% | **Cut ₹7 (8.24%) with competitors responding, ₹1 static.** Cheapest now only through a three-way tie at ₹85. Holding keeps it cheapest in just 31.9% of snapshots as the tied competitors drift, so "cheapest now" is not "safe to raise". |

## Tests

`tests/test_deliverables.py`:

- raises follow the planted structure (follower views agree, response softens Blinkit's loss, a raise never gains
  share);
- headroom is monotone in the budget and never narrower with the response;
- a promo withdrawal never adds stock-outs;
- the chain's raise objective meets the target;
- no recommended rung lies beyond ±30%.

`tests/test_analyst.py`: raise and headroom routing; answers SYNTHETIC and verified.

Eval: 37/37 tuning (2 added) and 21/21 held-out. The 3 held-out items added here were written before the tools ran,
and were run once.
