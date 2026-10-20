# Deliverable 6 — price / discount anomaly detection v1 (REAL + SYNTHETIC, never mixed)

Built 2026-09-23. `python -m src.models.anomaly` → `outputs/models/anomaly_real/` (REAL only) and
`outputs/models/anomaly_temporal/` (SYNTHETIC only).

## What this is allowed to claim

A flag means **unusual within the REAL 2026-07-10 snapshot**. It is never "an error" and never "a deal" until someone
checks the source. No temporal statement is made about REAL data, which has one snapshot.

## Part A — REAL, cross-sectional (21,949 listings)

Unsupervised detectors. None of them sees the pack text or the label:

| Detector | What it compares |
|---|---|
| `unit_price_z` | log unit price vs subcategory × pack-unit peers (robust z: median / MAD) |
| `price_z` | log price vs subcategory peers |
| `cross_store_z` | log price vs the same SKU in the other REAL stores |
| `discount_z` | discount vs subcategory peers (plus the 33 recorded invalid-MRP rows) |
| `isolation_forest` | all of the above together |
| `combined` | the largest absolute z of the listing |

**Tested against a real, known data error.** The raw `pack_qty` defect (CLAUDE.md §10) gives ground truth. A REAL
listing is defective when its pack text parses to a quantity that disagrees with the stored `pack_qty`. That's 819 of
21,797 labellable REAL rows, the same 819 CLAUDE.md records, so the base rate is 3.8%.

| Detector | PR-AUC | ROC-AUC | Precision@100 | Recall in top 5% |
|---|---|---|---|---|
| **unit_price_z** | **0.231** | 0.715 | **0.70** | 0.34 |
| combined | 0.196 | 0.659 | 0.62 | 0.31 |
| isolation_forest | 0.117 | 0.630 | 0.33 | 0.22 |
| cross_store_z | 0.041 | 0.521 | 0.01 | 0.08 |
| discount_z | 0.038 | 0.500 | 0.00 | 0.02 |
| price_z | 0.030 | 0.404 | 0.00 | 0.03 |

The unit-price detector finds a real error it was never told about: 70% of its top 100 are genuine defects (18× the
base rate). Of the top 500 combined flags that are known defects, 125 are `**…**` packs stored as 1 and 45 are combo
packs. The flag rule (|z| ≥ 5, or a recorded invalid MRP) marks 282 listings. 138 of them are known defects, and the
other 144 are reported as unusual only, each with a reason in words. Two real examples from the output:
"**Hommade Coconut Milk** 200 ml: unit price 200x its subcategory-unit median" (a confirmed `**…**` defect), and
"Raw Pressery Mixed Fruit Juice 1 ltr at Rs 56: price 0.242x the same SKU in other stores". The second is not a known
defect. It is exactly the kind of listing that has to be checked at source before anyone calls it an error or a deal.
Price, discount and cross-store detectors find nothing about the pack defect. That's expected: the defect corrupts
quantity, not price.

## Part B — SYNTHETIC, temporal (injection test)

1% of test rows (1,177) get a known anomaly: a spike (price × 1.3–2.0) or a crash (× 0.5–0.75). The detector compares
log price with the median of the listing's previous 14 prices, scaled by the larger of the past MAD of log changes and
**half a grid step**.

| Threshold on \|z\| | Recall | Precision | Normal rows flagged |
|---|---|---|---|
| 3 | 0.924 | 0.445 | 1.16% |
| **5** | **0.842** | **0.890** | **0.11%** |
| 8 | 0.698 | 0.993 | 0.005% |

PR-AUC 0.903, ROC-AUC 0.988. Spikes and crashes are caught about equally (82% and 86% at 5).

**Why the grid floor matters.** Without it, the same detector at |z| ≥ 5 flags 8.2% of normal rows and its precision
collapses to 11%. On a Rs 10 grid, a Rs 10 jump is how prices normally move.

Figure: `outputs/models/anomaly_real/figures/anomaly.png`.
