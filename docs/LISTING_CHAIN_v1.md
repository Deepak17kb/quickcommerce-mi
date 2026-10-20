# Product × store chain v1 — one listing, seven stages (SYNTHETIC, with REAL context rows)

Built 2026-09-24.

```
python -m src.chain.listing --demo                                   # gallery: 6 cut + 3 raise listings
python -m src.chain.listing --product "frooti" --store BLK-BBSR-008  # one listing
python -m src.analyst "explain this listing"                         # the analyst's explain_listing tool
python -m src.analyst "why is Frooti risky at BBSR-008"
```

## What this is allowed to claim

Deliverables 2–13 were built and tested one at a time. The chain runs all of them on **one** listing, so each layer has
to agree with the next. It is an integration test, and a worked example of the whole loop.

- **REAL:** the 2026-07-10 Blinkit row of the same product in the same store, its REAL anomaly score, and any store where
  the product is a REAL assortment gap. The REAL row is **context only**: one snapshot has no history, so no model uses it.
  Its price and stock status are verified against the source; that it belongs to *this store* is not supported
  (`docs/STORE_LABEL_AUDIT_v1.md`, 2026-10-13: the store label on the REAL rows cannot be told apart from a random one).
- **SYNTHETIC:** the listing's generated panel, every other prediction, every simulation and the optimisation. They
  describe the fitted, generated dynamics, never the market.
- **METHOD:** the assumptions, stored in full in each record.
- No demand, sales, revenue or profit, anywhere. The objective is price position (cheapest-of-4 share), and the cost is
  availability and ETA.

## The seven stages

Each record on disk (`outputs/models/listing_chain/chains/<listing>.json`) has exactly these keys, in this order. A test
enforces it.

| # | Stage | What it does |
|---|---|---|
| 1 | **Observe** | The Blinkit listing at the decision snapshot, plus the three competitors' prices for the product and the REAL row. The decision snapshot is the last test snapshot that still has a next one, so every prediction sits next to what actually happened. |
| 2 | **Applicability** | Models 1–10. For each: applies or not, and why. This is checked against the saved outputs, not assumed. 7 applies only in stock and 8 only out of stock. 10 cannot apply, because the store already lists the product (the REAL stores where it *is* a gap are listed instead). 1 is not used, because the panel carries the cross-platform key. |
| 3 | **Prediction record** | The saved predictions of every applicable model, joined on `observation_key`: next price (2), direction (3), next-snapshot stock (4), next ETA with its conformal interval (5), anomaly scores (6, REAL and temporal), P(out of stock within h) (7) and the follower βs (9). |
| 4 | **Price grid** | The listing's grid (step, remainder) is inferred from its **own past prices only**, so nothing from after the decision snapshot is used. The ladder is every grid point from a 30% raise down to a 30% cut (a ₹1 grid is thinned to about 13 rungs each way; a grid coarser than 30% gets one rung each way, shown but never recommended). |
| 5 | **Simulation** | **Baseline check first.** The status quo runs from the last validation snapshot over the 11 test snapshots. Then every rung runs for 12 snapshots, with competitors responding (9's fitted response, bootstrap draws) and without (static). Each rung also gets its stock-out and ETA cost if it is run as a promo. Finally the chain's own stock projection is cross-checked against 7's saved forecast. |
| 6 | **Optimization** | One target, a mean cheapest-of-4 share over 12 snapshots of at least 50% (ties count as cheapest), checked at the posted price. Below the target, it finds the smallest rupee cut that reaches it. At or above it, it finds the largest rupee **raise** that keeps it (added with `docs/PRICE_INCREASES_v1.md`). Both views are shown, with the promo cost or the promo-withdrawal gain, and a verdict. **If the baseline check failed, nothing is recommended.** |
| 7 | **Explanation** | Labelled claims, stage by stage, built only from stages 1–6. The analyst's tool returns stages 1–6 as evidence and **not** the stored explanation, so the verifier checks each number against the value it was built from, not against itself. |

## Baseline check rule (changed in v1)

The check passes when both of these hold:

- **(a) Prices:** each platform has at least 70% of its observed prices inside the simulated 90% band.
- **(b) Cheapest share:** the observed Blinkit cheapest-of-4 share falls inside the simulated 2.5–97.5% range, endpoints
  included.

The first version of (b) was a percentile test. It failed two listings (Chana Dal Namkeen, Frozen Sweet Corn) whose
price coverage was 100% on every platform, because the observed share was 0 and every simulated share was 0 as well.
Identical zeros are agreement, not a miss. `tests/test_deliverables.py::test_validate_counts_a_degenerate_tie_as_agreement`
guards the rule. With it, **6 of 6** gallery listings pass.

## Gallery (SYNTHETIC; REAL price shown for context only)

Each listing is in stock and is not currently the cheapest of the four platforms. There is one listing per category.

| Listing | Store | REAL 07-10 | Decision price | Grid | Status quo share | Cut, competitors respond | Cut, static | Promo: + pp OOS in 12 |
|---|---|---|---|---|---|---|---|---|
| Whole Farm Grocery Sugar (5 kg) | BBSR-003 | ₹375 | ₹399 | ₹100, ends 99 | 9.7% | ₹299 (25.06%) | ₹299 (25.06%) | 9.03 |
| Fruit Chaat Mix | BBSR-003 | ₹116 | ₹105 | ₹1 | 38.7% | ₹96 (8.57%) | ₹96 (8.57%) | 4.1 |
| Let's Try Signature Chana Dal Namkeen | BBSR-007 | ₹51 | ₹69 | ₹1 | 0.0% | ₹49 (28.99%) | ₹60 (13.04%) | 5.6 |
| Frooti Mango Drink 2 L | BBSR-008 | ₹122 | ₹105 | ₹10, ends 5 | 12.6% | ₹95 (9.52%) | ₹95 (9.52%) | 1.58 |
| SPT American Frozen Sweet Corn | BBSR-003 | ₹141 | ₹180 | ₹10, ends 0 | 0.2% | ₹140 (22.22%) | ₹160 (11.11%) | 8.77 |
| Derm Ease Sunscreen Spray | BBSR-007 | ₹1,199 | ₹1,249 | ₹50, ends 49 | 16.1% | ₹1,149 (8.01%) | ₹1,199 (4.0%) | 2.65 |

Source: `outputs/models/listing_chain/metrics.json` and the six chain files, run 2026-09-24.

**What the gallery shows (all SYNTHETIC):**

- **Response doubles the cut on three of six listings.** For Chana Dal, Sweet Corn and Derm Ease, followers track
  Blinkit's move, so the static view understates the needed cut by 2× (₹20 vs ₹9, ₹40 vs ₹20, ₹100 vs ₹50). On the
  other three, a single grid rung clears the target either way. This matches deliverable 12a's category-level finding
  (1.62×), seen here one listing at a time.
- **Grids create cliffs.** On Chana Dal, Instamart sits at ₹50 on a ₹10 grid, and with competitors responding it stays
  there. From ₹60 down to ₹51, Blinkit's share stays at about 6%. At ₹49, the first rung below Instamart, it jumps to
  about 100%. The optimum is a threshold rather than a smooth trade-off, which is why the ladder uses the listing's own
  grid rather than percentages.
- **Coarse grids force large cuts.** Sugar's ₹100 grid means the smallest possible move is 25%.
- **Increases never help on these six.** Each one's +1-step rung gives a cheapest share of 0.0% with competitors
  responding. Where Blinkit is already cheapest, a raise can be affordable: see the update below.
- **Promo cost scales with depth.** Running the optimum as a promo adds 1.58 pp (Frooti, 9.5%) up to 9.03 pp (Sugar,
  25%) to the chance of a stock-out within 12 snapshots. As a list-price cut it adds nothing, by assumption.

## Cross-check between layers

The chain's own single-listing stock projection (7's hazard, 8's restock and the store-pressure AR) is compared with
deliverable 7's saved forecast for the same observation. Both give P(out of stock within 6 snapshots):

| Listing | Deliverable 7 | Chain |
|---|---|---|
| Sugar | 0.207 | 0.249 |
| Fruit Chaat Mix | 0.363 | 0.380 |
| Chana Dal Namkeen | 0.733 | 0.711 |
| Frooti | 0.047 | 0.053 |
| Sweet Corn | 0.397 | 0.390 |
| Derm Ease | 0.154 | 0.176 |

The largest gap is 4.2 pp, on Sugar. Two known differences explain small gaps:

- **Censored clock (Sugar only).** Sugar is the only gallery listing whose in-stock clock started before the panel. The
  chain plugs in the expected equilibrium age; deliverable 7 integrates over the unknown age
  (`src/models/stockout_survival.py`).
- **Frailty.** The chain draws the listing's frailty from its prior; deliverable 7 conditions it on the listing's own
  history.

## Analyst integration

- **Tool:** `explain_listing(product, store)` matches a saved chain by how much of the query the product name covers.
  If no saved chain covers every query word, it runs the chain live.
- **Routing:** offline, "explain … listing", or a store id with "why / risky / what should", routes to the tool.
- **Output:** claims are printed with their stage.
- **Eval:** 35/35 tuning (2 chain questions added) and 18/18 held-out (3 added).
- **Held-out caveat:** the held-out sugar question first "passed" on the wrong listing. The old matcher scored overlap
  against the name length and fell through to a sugar-free lassi, and the grader only checked for the word "Sugar". The
  matcher now scores query coverage, the check was tightened, and a regression test covers it. That item is therefore no
  longer a clean held-out question.

## Honest caveats

- The chain uses only listings where Blinkit's product is on all four platforms and has a REAL row in the same store:
  414 candidates.
- The REAL price often differs from the generated one (Chana Dal: ₹51 REAL vs ₹69 generated). This is expected: the
  generator only calibrated price endings and stock-out levels to the snapshot, not listing-level prices. It is also why
  the REAL row stays context.
- The price response acts on the product's mean price per platform. Blinkit's other stores for the product keep their
  status-quo paths.
- Stock-outs and ETA move only through discount depth. A list-price cut costs nothing in availability by assumption
  (deliverables 7, 8 and 5 have no price-level term).

## Update: price increases (2026-09-24)

The gallery now has 9 listings. Three more were picked where Blinkit is the cheapest at the decision snapshot, and all
9 pass the baseline check. The six cut listings above keep the same results.

Results for the three new listings, and the full rule changes, are in `docs/PRICE_INCREASES_v1.md`. In short:

- **Wonder Fresh Pocket Air Freshener** can rise ₹10 (+5.41%) and stay cheapest in 84.4% of snapshots with competitors
  responding.
- **Sleepy Owl Cappuccino Premix** has to hold, because its ₹100 grid has no raise within 30%.
- **Boba Bhai Litchi Blood Orange** is "cheapest now" only through a three-way tie, and in fact needs a ₹7 cut.

## Update: the product-unavailable scenario (2026-09-24)

Stage 5 also simulates the listing going out of stock now. It reports:
- the expected spell (deliverable 8) and P(back within 1, 2 or 4 snapshots);
- the cost in cheapest-available-of-4 share over 12 snapshots, and who picks it up;
- the value of restoring it before the next snapshot.

Stage 6 adds an "if it goes out" action with the listing's deliverable-12b priority index. An outage only costs a win the
listing would have had: Wonder Fresh Pocket Air Freshener (in stock and cheapest 85.9% of the time) loses 13.65 pp and
restoring it at once recovers 16.05 pp, while Chana Dal Namkeen and Frozen Sweet Corn (about 1%) need no urgency. All 9
listings still pass the baseline check. Details: `docs/SCENARIOS_v1.md`.
