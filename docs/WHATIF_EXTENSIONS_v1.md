# SIMULATE, OPTIMIZE and analyst extensions v1 (SYNTHETIC)

Built 2026-09-24. Four additions on top of deliverables 11, 12 and 13.

```
python -m src.simulate.grid               # the what-if grid            -> outputs/models/simulate_grid/
python -m src.optimize.promo_frontier     # price vs availability        -> outputs/models/optimize_promo_frontier/
python -m src.optimize.restock_lab        # capacity + optimality gap    -> outputs/models/optimize_restock_lab/
python scripts/build_whatif_lab.py        # the interactive What-If Lab  -> outputs/showcase/whatif_lab.html
python -m src.analyst "If Blinkit cuts snacks by 5%, what happens?"   # the analyst runs the experiment
```

Everything here is **SYNTHETIC**: what the fitted models imply about the generated market. Positioning and
availability only, never demand, orders or revenue.

## 1. The what-if grid (`src/simulate/grid.py`)

4 movers × cuts of 1–10% × {competitors frozen, fitted response}, over 12 snapshots and 12 simulations each. Products
of different categories never interact in the engine, so one run that cuts every category gives each category's
answer at once: 84 runs (161 since raises were added, docs/PRICE_INCREASES_v1.md; the cut cells are unchanged) cover 1,120 scenario cells (13 categories + the whole panel). A scenario and its baseline
share every random draw (common random numbers), so change bands are paired.

Across the whole panel, the static view overstates Blinkit's gain by a median **1.76×** over the ten cut sizes. A
follower's cut draws no response (only Blinkit is followed), so both views agree there.

## 2. The analyst runs experiments

Three tools join the analyst's four (`src/analyst/tools.py`), in both engines:

| Tool | Answers |
|---|---|
| `simulate_price_move` | a platform cuts one category or all by 1–10%: cheapest-of-4 share before and after for all four platforms, 90% band, both views |
| `promo_frontier` | a category's share gain vs the stock-outs and delivery minutes a promo adds |
| `restock_capacity` | the capacity curve and the index's share of the clairvoyant benchmark |

The offline engine routes what-if questions to them ("If Blinkit cuts snacks by 5%…", "Would a promo on Dairy hurt
availability?", "How much does restock capacity buy?"). Claude mode gets them as strict tools. Answers go through the
same verifier: every number must appear in the tool output, and every claim is SYNTHETIC. Example: *If Blinkit cuts
prices 5% in Snacks & Munchies (66 SKUs), with the fitted competitor response, its cheapest-of-4 share moves from 19.9%
to 28.2%: +8.5 pp (90% band +5.4 to +10.5). The static view gives +17.2 pp.* "…what happens to sales?" is refused, since
"sales" was added to the refusal policy.

Two evaluation expectations were widened when the tools arrived. A tuning-set question about a 3% Blinkit cut now
accepts the grid as a source. A held-out question about promotions and stock-outs
now routes to the promo frontier, which is a correct and better answer, so that tool was added to its accepted
sources. New questions: 5 in the tuning set and 3 held-out, the held-out ones written after the tools were tuned and
run once.

## 3. Price position vs availability (`src/optimize/promo_frontier.py`)

Blinkit can make a category cheaper by a **promo** (selling price falls, MRP stays: the discount deepens) or a
**list-price cut** (both fall: discount unchanged). Both buy the same cheapest-of-4 share (deliverable 9). But discount
depth raises the stock-out hazard (deliverable 7, promo effect 1.84) and delivery time (deliverable 5, 3.88 min per 100%
depth). A listing that is out of stock cannot win the comparison, so the joint measure is **available-and-cheapest**
share = share cheapest × share in stock (the two worlds share no random driver in the fitted models).

| Finding | Value |
|---|---|
| Share a 10% cut buys | +19.5 to +30.1 pp by category |
| Stock-outs a 10% promo adds | +0.38 to +1.15 pp |
| Delivery time a 10% promo adds | ~0.37 min |
| Stock-out cost per pp of share | 0.014 (Baby Care) to 0.059 (Snacks & Munchies) |
| Categories where a promo breaks a 1 pp stock-out budget before 10% | 1: Snacks & Munchies, beyond a 7% promo |
| Interior optimum of available-and-cheapest share? | none: it rises with the cut in every category |

**The honest reading:** the trade-off is real but small under the fitted dynamics. The price gain dominates, so there
is no sweet spot inside 0–10%. The ranking is the useful part: the high-stock-out category (Snacks, 11.6% out of stock
now) pays about 4× what Baby Care pays. "Cut list prices, not promos" is a statement about the generator's planted
promo-depletion assumption, not about the market.

## 4. Restock capacity and the optimality gap (`src/optimize/restock_lab.py`)

Five policies at 0.25–4% capacity per store per snapshot, 8 simulations each. Two are new benchmarks: the index
restricted to outages (**restock only**, no pre-emptive top-ups), and a **clairvoyant oracle** that knows every
outage's true remaining length (information no operator has), ranking everything in expected out-of-stock snapshots
saved.

| Capacity | Random | Longest out first | Index, restock only | **Priority index** | Clairvoyant oracle | Index / oracle |
|---|---|---|---|---|---|---|
| 0.25% | 4.4% | 3.7% | 10.5% | **10.5%** | 16.7% | 63% |
| 0.5% | 5.8% | 4.9% | 12.8% | **12.8%** | 19.7% | 65% |
| 1% | 15.4% | 13.7% | 26.3% | **26.4%** | 35.8% | 74% |
| 2% | 34.0% | 33.1% | 43.9% | **45.7%** | 52.6% | 87% |
| 4% | 51.9% | 52.1% | 55.1% | **63.8%** | 65.5% | **97%** |

(Out-of-stock listing-snapshots removed vs no action.)

- **Information is worth most when capacity is scarce.** Knowing true outage lengths adds 6–9 pp at low capacity. At
  4% the simple index is within 2 pp of clairvoyance.
- **Top-ups only pay once there is spare capacity.** They add 0.1 pp at 1% and 8.7 pp at 4%. With little capacity,
  every action is best spent on an outage.
- **Diminishing returns.** Each extra action saves 2.34 → 1.74 → 1.21 → 0.57 out-of-stock snapshots as capacity grows
  from 0.5% to 4%.
- "Longest out first" is worse than random up to 2%, and only catches up at 4%, when there's enough capacity to fix
  nearly everything.

## 5. The What-If Lab (`scripts/build_whatif_lab.py`)

An interactive page with three tabs: price move (platform, category, cut and response toggle; before/after for all
four platforms, the path over 12 snapshots, the band), promo vs list price (per category), and restock capacity (all
five policies). It embeds only saved results and computes nothing new. Built from the three model folders above.
