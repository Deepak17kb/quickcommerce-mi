# Scenarios v1: product unavailable, store adds products, richer restock objective

Built 2026-09-24. These are extensions 2, 3 and 4 of the post-chain plan. Extension 1 is `docs/PRICE_INCREASES_v1.md`
and extension 5 is `docs/EXTERNAL_SOURCES_v1.md`.

```
python -m src.simulate.unavailable        # -> outputs/models/simulate_unavailable/
python -m src.simulate.store_adds         # -> outputs/models/simulate_store_adds/ (SYNTHETIC) + simulate_store_adds_real/ (REAL)
python -m src.optimize.restock_objective  # -> outputs/models/optimize_restock_objective/
python scripts/build_explorer.py          # -> outputs/showcase/explorer.html (all of it, plus the listing chain)
```

Everything here is SYNTHETIC unless marked REAL: positioning and availability under the fitted, generated dynamics.
There are no orders, shoppers or revenue in the data. A "lost win" is a lost price position, never a lost sale.

## Engine changes (`src/simulate/engine.py`)

- **`StockWorld.simulate(outage=...)`** takes a set of listings out of stock now.
  - The outage lasts a fixed number of snapshots after now, or a spell length drawn from the fitted restock
    distribution (deliverable 8).
  - Outage lengths come from their own random stream, so every other draw stays paired with the no-outage run. A test
    checks that untouched listings follow identical paths.
- **`simulate(active=...)`** simulates listings the operator cannot see or count. That keeps random streams paired when
  listings are added. With every listing active, it is identical to no mask (tested).
- **`simulate(return_states=True)`** returns per-snapshot in-stock paths. `PriceWorld.simulate(return_prices=True)`
  returns each platform's grid price per product and snapshot.
- **`StockWorld.state_from_rows()`** builds a simulation state from any rows. The listing chain uses it to start the
  stock world at its own decision snapshot.
- **Regression checks:** after the refactor, the no-policy baseline reproduces the saved 7,387.25 out-of-stock
  listing-snapshots exactly, and the priority index reproduces 5,425.95.

## 2 · Product unavailable (`src/simulate/unavailable.py`)

**The measure: cheapest-available-of-4.** For each product listed on all four platforms, the winner at a snapshot is
the cheapest platform among those with at least one listing of it in stock. Ties count for each tied platform.
Availability costs every platform a little, but the ranking holds:

| Platform | Cheapest on price alone | Cheapest and in stock |
|---|---|---|
| Blinkit | 17.7% | 18.3% |
| Swiggy Instamart | 24.5% | 25.2% |
| Flipkart Minutes | 56.5% | 53.3% |
| BigBasket | 18.0% | 18.8% |

Shares can rise when stock is counted, because an out-of-stock rival drops out of the comparison.

**Who inherits.** Each platform in turn loses every common-panel listing now. Outage lengths are drawn from the
restock model, over 12 snapshots and 16 paired simulations. Median change in pp (the outlined diagonal is the platform's
own loss):

| Runs out ↓ · changes → | Blinkit | Swiggy Instamart | Flipkart Minutes | BigBasket |
|---|---|---|---|---|
| Blinkit | **−1.55** | +0.37 | +0.60 | +0.38 |
| Swiggy Instamart | +0.54 | **−2.47** | +0.97 | +0.62 |
| Flipkart Minutes | +2.47 | +3.31 | **−8.63** | +2.65 |
| BigBasket | +0.55 | +0.79 | +1.02 | **−3.02** |

Flipkart Minutes loses most because it holds the most wins (planted −6% price level). When Blinkit runs out, Flipkart
Minutes picks up most.

**Duration: what waiting costs.** Blinkit outages lasting 0, 1, 2, 4 and 8 snapshots after now cost +0.84, −0.73, −2.33,
−5.46 and −11.84 pp; the drawn length costs −1.55 pp. The 0 case is not "no outage". The listing comes back before the
next snapshot with a fresh in-stock clock, and under the fitted rising hazard (deliverable 7) that is a small gain: the
same effect as a pre-emptive top-up. An earlier version had "length 1" mean exactly this, which made a one-snapshot
outage look like a gain. The lengths now count snapshots out after now.

**By category, the planted restock groups reappear.** Categories where the generator planted FAST restocking lose least:
Dairy, Bread & Eggs 0.00 pp, and Fruits & Vegetables +0.35 pp, since its outages end before the next snapshot. SLOW
categories lose most: Home & Cleaning −2.66 and Other / General Merchandise −2.97. Deliverable 8 found these groups
from spell lengths. Here they come back from price positions, a second route to the same planted structure. A test
guards the ordering.

**Store ETA.** A whole category out in one Blinkit store raises the store's out-of-stock share. Deliverable 5's store-OOS
term turns that into minutes. The term is confounded with latent demand, so all three values are shown: planted 8, state
space 19.2 and naive 56 minutes per 100% OOS share. The largest case is Other / General Merchandise, with a mean extra
OOS share of 0.047: 0.38 / 0.90 / 2.62 minutes.

**Negative control: is there substitution?** If shoppers switched platforms, a competitor listing of the same product
would run out faster while Blinkit is out. The check is a logistic regression over 330,702 competitor listing-snapshots
(8,223 stock-outs), with category, platform, in-stock clock, store pressure and time of day as controls and errors
clustered by product. It gives an odds ratio of 0.949 (95% CI 0.867 to 1.038, p = 0.25): no substitution, consistent
with the generator, which planted none.

History, kept in the output: the first version left out time of day and found a small negative association (odds ratio
0.909, p = 0.04). Of snapshots where Blinkit is out, 53.6% come before a morning snapshot, against 48.6% of the others,
and every hazard is lower overnight. Time of day is a known driver of the fitted hazard and belonged in from the start;
with it, the association vanishes, and snapshot fixed effects agree. Real substitution cannot be measured here at all:
there is no demand.

**In the listing chain.** Stage 5 now simulates the listing itself going out of stock now: its expected spell, P(back
within h), the cost in cheapest-available share, who picks it up, and the value of restoring it at once. Stage 6 turns
that into an "if it goes out" action with its deliverable-12b priority index. The gallery shows the principle: an
outage can only cost a win the listing was going to have.
- **Wonder Fresh Pocket Air Freshener** is in stock and cheapest in 85.9% of the next 12 snapshots. An outage now costs it
  −13.65 pp, and restoring it at once recovers 16.05 pp: expedite.
- **Sleepy Owl Cappuccino Premix**: 83.0%, an outage costs −5.0 pp, and expediting recovers 7.23 pp.
- **Frooti**: an outage costs only −0.83 pp and nobody inherits much, because Flipkart Minutes already wins that product.
- **Chana Dal Namkeen** and **Frozen Sweet Corn** are almost never the cheapest (0.8% and 1.2%): no urgency.

The richer restock objective below generalises exactly this.

## 3 · A store adds products (`src/simulate/store_adds.py`)

Each Blinkit store adds its top 10, 25 or 50 assortment gaps from deliverable 10 (REAL): products similar stores list and
it was not seen listing. There are two outputs, one per provenance: the REAL part (`simulate_store_adds_real`, REAL-ONLY
manifest) and the SYNTHETIC parts (`simulate_store_adds`).

> **Read with `docs/STORE_LABEL_AUDIT_v1.md` (2026-10-13).** The two REAL results below read `store_id` on the REAL
> rows as "this store listed this product". On ten permutation tests that label cannot be told apart from a random
> one, so both describe an arbitrary split of the catalog until the source's store column is explained.

**REAL: the category mix barely moves.** At 50 additions, 4 of the 8 stores move closer to their peers' category mix
(total-variation distance to the median of the other seven stores), and the median distance rises from 0.0458 to 0.0507.
The gap recommender works product by product, from what similar stores carry. It is not a category rebalancer.

**REAL: the additions are cheaper items.** In all 8 stores, the median REAL price of the 50 additions (in the stores that
list them) is below the store's current median, for example ₹81.5 against ₹167 at BBSR-006 and ₹116 against ₹195 at
BBSR-002. A gap is still "not seen in the listing", which is not the same as "not stocked".

**SYNTHETIC: price position.** Few additions are in the four-platform panel (4 to 14 of the 50 per store). Where they are, Blinkit
is cheapest-of-4 on them in a median 18.2% of snapshots, against 17.4% on current products: no different.

**SYNTHETIC: restock effort spread thinner.** The store's generated listings (about 300) get the additions as fresh
in-stock listings of their categories. The priority index (12b) runs at a fixed 2% of today's listings per snapshot
(6 or 7 actions), against capacity that grows with the assortment:
- at +50 products with the same actions, the existing listings' out-of-stock exposure rises by a median +2.30% across
  stores (+0.78% to +5.66%);
- with one more action per snapshot (capacity scaled), it falls by a median −3.91%.

The dilution grows with the number added: at +10 it is under +1.1% in every store. The added listings are simulated in
every run and are only invisible in the "before" run, so the comparison is paired.

Two flaws were found and fixed before these numbers:
- The first version let the added listings change the length of every random draw. The noise swamped the effect (−13%
  to +13%, both signs).
- At 1% capacity, "scaled" rounded back to the same 3 actions.

The generated store is a sample of about 300 listings of a REAL store's 1,259 to 5,608 products, so adding 50 is a far
bigger relative change than it would be for the real store.

## 4 · A richer restock objective (`src/optimize/restock_objective.py`)

Deliverable 12b minimises out-of-stock listing-snapshots (J1): every listing counts the same. In positioning terms, a
stock-out only costs something if the listing would have won, meaning in stock and the cheapest. J2 counts
cheapest-available wins lost to stock-outs, summed over products, snapshots and platforms. J3, the store ETA from
stock-outs, is reported but not optimised.

**The weighted index.** Score = the 12b index × [α + (1 − α) × wᵢ / mean(w)], where wᵢ is the chance that the listing's
platform is cheapest on its product, divided by that platform's number of listings of it. Sweeping α from 1 (plain 12b)
to 0 (fully win-weighted) traces the trade-off. Settings: 24 paired simulations, capacity 1% of each store per snapshot,
12 snapshots, 8,000 common-panel listings. With no action, 221.8 wins are lost per run.

| α | Out-of-stock cut (J1) | Lost-wins cut (J2) |
|---|---|---|
| 1 (12b's index) | 26.9% | 19.9% |
| 0.75 | 25.6% | 26.6% |
| 0.5 | 23.0% | 29.0% |
| 0.25 | 20.2% | 29.5% |
| 0 | 18.5% | 29.0% (beaten by 0.25 on both) |
| clairvoyant benchmark | 23.0% | 37.1% |
| random / longest out first | 16.3% / 15.1% | 12.3% / 9.7% |

The knee is at α = 0.75: it gives up 1.3 pp of the out-of-stock cut for 6.7 pp more of the lost-wins cut.
The average gain is clearly positive: 6.7 pp, with a 90% confidence interval for the mean of 4.3 to 9.1 pp (and 1.2 to
1.4 pp for the cost). Single 12-snapshot windows vary far more: the gain was positive in 79% of paired runs at α = 0.75, and
in 83 to 88% at lower α. The win-weighted index at α = 0 gets 78% of the clairvoyant benchmark's lost-wins cut.

**Reading it.** The operator's objective is a choice the data cannot make. Minimising stock-outs and protecting price
positions pull apart, and the frontier shows by how much. Under the generated dynamics, the plain index is the right
choice if every listing matters alike; a mild weighting (α around 0.75) is the cheap improvement if positions are the
goal.

## Tests and eval

`tests/test_deliverables.py` checks:
- outage structure: own loss, nobody else loses, a longer outage costs more, restoring at once beats waiting, and the
  FAST categories lose less than the SLOW ones;
- no substitution;
- store additions: REAL-ONLY vs SYNTHETIC manifests, scaled capacity never worse than fixed, a positive median dilution;
- the restock frontier: 12b best on J1, weighting better on J2, the oracle on top, weighting always costs J1;
- engine pairing.

`tests/test_analyst.py` covers the routing and verified answers of the new tools (`outage_impact`, `store_adds`,
`restock_objective`).
