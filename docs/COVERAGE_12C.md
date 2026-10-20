# Deliverable 12c — store coverage gaps (REAL)

Built 2026-09-19. `python -m src.coverage.store_coverage` (read-only on `data/raw/`,
`data/reference/STORES*.csv`, `data/reference/MASTER_CATALOG.parquet`).

Outputs, both saved through `src/model_output.py`, both `data_status = REAL`,
both `claim_scope = REAL-ONLY`:

```
outputs/models/store_category_coverage/     176 rows = 8 stores x 22 categories
outputs/models/store_coverage_geography/  1,237 rows = city grid cells
```

## 1. The scope limit that shaped this

The deliverable was asked for "each of the 30 real stores". **Category coverage is reported for 8
of them, not 30.** Only the 8 Blinkit stores have a REAL carry matrix — which products a store
actually lists. The other 22 stores have REAL names, addresses and coordinates, but every
observation row of theirs is SYNTHETIC and their assortment was generated
(`docs/PROJECT_PLAN.md`, deliverable 10). A per-category table for those 22 would describe the
generator, not any store.

Geography uses all 30, because the coordinates are real: `public_web_observation`,
`last_verified 2026-07-10`, in `STORES*.csv`.

> **Read with `docs/STORE_LABEL_AUDIT_v1.md` (2026-10-13).** On ten permutation tests the store label on the REAL rows
> cannot be told apart from a random label, so the category coverage table in section 2 is not supported by evidence
> that the label carries store information. The geography output is unaffected: it uses store coordinates from a
> separate public source and no listing rows.

## 2. Category coverage — 8 REAL Blinkit stores

Carry = distinct `canonical_product_key` observed in that store on the REAL 2026-07-10 snapshot.
Measured against what the 8 stores carry **between them**, never against a platform assortment
claim. That union is exactly the 12,188-product `MASTER_CATALOG` — the catalog was derived from
this same snapshot — so "chain universe" and "catalog" coincide category by category here. The 4
unnamed listings (CLAUDE.md §3.7) are not in `MASTER_CATALOG` and are excluded.

Two stores are broad (BLK-BBSR-003: 5,585 keys; BLK-BBSR-008: 5,608) and six are narrow
(1,259–1,394). So raw counts would call every narrow store sparse everywhere. The metric instead is

```
coverage_index = store_carried / (chain_category_keys * store_breadth_share)
```

— observed over what the store's own breadth predicts. 1.0 = in line with itself.
`sparse` < 0.60, `covered` 0.60–1.40, `strong` > 1.40, `missing` = 0.

Result: 131 covered, 25 sparse, 20 strong, **0 missing** — every store carries something in all 22
categories. BLK-BBSR-003 and BLK-BBSR-008, the two broad stores, have no sparse category at all.

Sparse, by store (worst first):

| Store | Sparse categories |
|---|---|
| BLK-BBSR-001 | Health & Wellness (idx 0.18), Electronics & Stationery, Frozen Foods, Kitchen & Dining, Pet Supplies, Baby Care |
| BLK-BBSR-002 | Fashion & Lifestyle, Electronics & Stationery, Kitchen & Dining, Frozen Foods, Baby Care |
| BLK-BBSR-005 | Fashion & Lifestyle, Electronics & Stationery, Health & Wellness, Pet Supplies |
| BLK-BBSR-006 | Pet Supplies (0.28), Sauces/Spreads/Pickles, Fashion & Lifestyle, Kitchen & Dining |
| BLK-BBSR-004 | Health & Wellness, Electronics & Stationery, Kitchen & Dining |
| BLK-BBSR-007 | Electronics & Stationery, Fashion & Lifestyle, Frozen Foods |

The pattern across the six narrow stores is consistent: they concentrate in Snacks, Bakery &
Biscuits, Dry Fruits & Nuts and Tea/Coffee (the `strong` band) and thin out in the non-grocery
long tail — Electronics & Stationery, Fashion & Lifestyle, Kitchen & Dining, Health & Wellness.

**Can claim:** these 8 real stores' listed assortment on 2026-07-10, relative to each other.
**Cannot claim:** that a sparse category is a lost sale, a demand signal, or a stocking error — no
demand data exists (CLAUDE.md §4); nor anything about the other three platforms' assortment.

## 3. Geographic coverage — all 30 REAL store locations

Haversine distances over a ~0.42 km grid (0.004°) across the store bounding box, keeping the 1,237
cells within 5 km of some store. A platform is in a **relative gap** at a cell if its nearest store
is > 3 km away while some competitor is within 1.5 km.

| Platform | Stores | Relative-gap cells | Share | Median km to nearest |
|---|---|---|---|---|
| Flipkart Minutes | 6 | 95 | 7.7% | 2.61 |
| BigBasket | 6 | 89 | 7.2% | 2.69 |
| Blinkit | 8 | 38 | 3.1% | 2.29 |
| Swiggy Instamart | 10 | 5 | 0.4% | 2.23 |

Where:

- **Flipkart Minutes** — the South West Zone / Surya Nagar / North Zone band (lat 20.269–20.377,
  lon 85.796–85.844), 95 cells, the largest single relative gap in the city.
- **BigBasket** — Patrapada and the western North Zone (lat 20.225–20.337, lon 85.744–85.832).
- **Blinkit** — Patrapada only (38 cells, lat 20.225–20.245), where Flipkart Minutes and Instamart
  both have a store within 1.26 km of each other and Blinkit's nearest is over 3 km.
- **Swiggy Instamart** — effectively none (5 cells, Surya Nagar). With 10 of the 30 stores it is the
  most evenly spread in this dataset.

Most isolated stores (km to nearest competitor of any platform): BGB-BBSR-003 Surya Nagar (2.18),
then FKM-BBSR-006 and INS-BBSR-008, both Patrapada, 1.26 apart from each other.

230 cells have no platform within 3 km, ranging 3.0–4.96 km from the nearest store. **These are
mostly bounding-box fringe**, not verified unserved neighbourhoods — the grid is defined by where
stores are, so its edges are far from stores by construction. Do not report them as underserved
areas without street-level geography this repo does not have.

**Can claim:** distance from a point to the nearest *listed* store of each platform, for the 30
stores in this dataset, as of 2026-07-10.
**Cannot claim:** complete platform coverage (these are this dataset's stores, not a verified dark
store census); unserved demand or population (no demand or population data — CLAUDE.md §4); service
areas or delivery reach (a dark store's radius is not in the data).

## 4. Contract deviations, stated on purpose

`predictions.parquet` requires `observation_key`. Neither output is at observation grain:

- category rows use a **representative** REAL `observation_key` for that store (first by key) — the
  same convention model 1 used for pair rows. The row is a store × category aggregate.
- geography rows use `GEO_GRID | <lat> | <lon>`, which is **not joinable** to `data/ml`. A grid cell
  is not a listing.

Both are recorded in each manifest's `notes`. A consumer joining these on `observation_key` and
expecting a listing will get the wrong thing.
