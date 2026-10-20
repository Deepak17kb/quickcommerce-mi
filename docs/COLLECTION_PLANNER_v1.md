# Collection planner v1: how much real data would be enough? (SYNTHETIC)

Built 2026-10-13. `python -m src.planner.collection` → `outputs/models/collection_planner/`. A design study, not a model.

## What this is allowed to claim

Every dynamic result in this project rests on a generated panel, because the only REAL data is one snapshot. A real
panel has to be logged by hand. The owner's price logger holds a 128-product watchlist and, on 2026-10-13, no
observations. This study answers one question before anyone starts: for each quantity the project cares about, how
many days and how many products does a panel need before the estimate is worth having?

**It is a planning prior, not a guarantee.** It says what a panel of each shape resolves if the real market is about
as noisy as the generator. Two parts of that noise are calibrated to the REAL snapshot (stock-out level per category,
price-ending grid). Everything else is an assumption (`docs/GENERATOR_v15_PARAMETERS.md`). The right use is: log a
short pilot, then re-run the same cuts on the pilot's own variance.

## Method

The SYNTHETIC common panel has the shape a real panel would have: 2,000 products on all four platforms, 60
snapshots (09:00 and 18:00 for 30 days). A design is (days, products, snapshots per day). For each of 126 designs the
panel is cut down 200 times: a random run of consecutive days, a random set of products, every platform's listing of
each. Each cut is estimated with the plain estimator a first analysis would use and compared with the full panel.

A design **identifies** a quantity when at least 90% of its cuts land within the tolerance, and every longer design
of the same size does too. Tolerances are choices, listed below; the saved grid also holds the 90% half-width of every
cell, so a different tolerance can be read off it.

Effort is observations × 20 seconds, an **assumed** logging speed for one product on one app.

## Results

| Quantity | Full panel | Tolerance | Smallest design that identifies it | With the 128-product watchlist |
|---|---|---|---|---|
| Flipkart Minutes price gap | −5.34% | ±1 pp | 1 day × 250 products (11 h) | 10 days, mornings only (28 h) |
| Flipkart Minutes cheapest-of-4 share | 56.6% | ±3 pp | 2 days × 1,000 products (89 h) | not reached in 30 days |
| Blinkit out-of-stock rate | 5.8% | ±1 pp | 14 days × 128 products (80 h) | 14 days (80 h) |
| Mean out-of-stock spell | 2.58 snapshots | ±0.2 | 30 days × 128 products (171 h) | 30 days (171 h) |
| Stock-out hazard, long run over short run | 5.7 | ±1.5 | 30 days × 1,000 products (1,333 h) | not reached |
| Instamart's response to Blinkit (naive) | 0.220 | ±0.05 | 7 days × 500 products (156 h) | not reached |
| Blinkit evening ETA minus morning | 3.43 min | ±0.5 | 7 days × 10 products (3 h) | 3 days (17 h) |

Four things a planner should take from this.

**1. Days and products buy different things.** With the watchlist, the price gap is known to about ±1.2 pp after one
day and ±0.9 pp after thirty: more days barely help, because the uncertainty is between products. The cheapest-of-4
share behaves the same way (±7 pp to ±5 pp). The evening ETA is the opposite: ±0.9 minutes after one day, ±0.06 after
thirty. The out-of-stock rate sits between (±2.9 pp to ±0.7 pp).

**2. A short panel gives a precise wrong answer about restocking.** A window can only contain spells shorter than
itself. At 1,000 products the mean out-of-stock spell is biased by −1.28 snapshots in a 2-day panel, −0.34 at 7 days,
−0.11 at 14 and −0.05 at 21. The estimate looks tight the whole time (±0.2 with the watchlist at every length).

**3. One snapshot a day keeps the cross-section and loses every dynamic.** Mornings only halves the effort and still
identifies the price gap. It cannot estimate the evening ETA, the restock spell, the hazard or the price response at
any size, because each needs the half-day step.

**4. Two headline results of this project are out of reach of a hand-logged panel.** Duration dependence of the
stock-out hazard needs about 240,000 observations at this tolerance. The price response needs 500 products for a
week, and that is the naive coefficient, which is about half the planted one on rounded prices (deliverable 9). A real
study of either needs automated collection or a much narrower question.

### What the watchlist is worth, by length

At 20 seconds an observation, the full watchlist on four apps twice a day is 1,024 observations: **5.7 hours a day.**

| Plan | Observations | Hours | Identifies |
|---|---|---|---|
| One weekend, watchlist | 2,048 | 11 | nothing at these tolerances |
| One week, watchlist | 7,168 | 40 | price gap, evening ETA |
| Two weeks, watchlist | 14,336 | 80 | + out-of-stock rate |
| Thirty days, watchlist | 30,720 | 171 | + mean out-of-stock spell |
| Two weeks, 25 products | 2,800 | 16 | evening ETA |
| Two weeks, watchlist, mornings only | 7,168 | 40 | price gap |

## One REAL fact that widens the stock-out answer

In the generated panel a product running out on one platform says almost nothing about the others: the chance on
another platform rises by a factor of 1.16. In the REAL snapshot, records of the same product run out together: 6.4
times the rate (`docs/STORE_LABEL_AUDIT_v1.md`). If that holds across real platforms, a fourth app adds less
information about stock-outs than a few more products would, and the out-of-stock sample sizes above are too
optimistic. The generator was not changed.

## What transfers, per quantity

| Quantity | Basis in the real snapshot |
|---|---|
| price gap, cheapest share | The price grid is REAL-calibrated. The size and spread of cross-platform gaps is assumed. |
| out-of-stock rate | The level is REAL-calibrated per category. Persistence is assumed. Real clustering by product is not planted. |
| restock spell, hazard, response, evening ETA | Assumed dynamics throughout. |

## Tests

`tests/test_planner.py`: the estimators on a toy panel, the tolerance table, and the structure of the saved plan
(once-a-day designs, the short-window bias, products against days, the REAL-against-SYNTHETIC clustering gap).
