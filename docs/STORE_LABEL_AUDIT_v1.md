# Store-label audit v1 (REAL)

Built 2026-10-13. `python -m src.audit.store_label` → `outputs/models/real_store_label_audit/` (REAL-ONLY) and
`outputs/models/real_store_label_audit_synthetic_control/` (the positive control, kept apart). An audit, not a model.
Raw data verified against the sha256 baseline in `scripts/verify_raw_integrity.py` on the run date.

## The finding

**On the 21,949 REAL Blinkit rows of 2026-07-10, the store label cannot be told apart from a random label.** Ten
permutation tests, 2,000 shuffles each; none departs after Bonferroni correction (threshold 0.005).

| Test (observed against store labels shuffled across rows) | Observed | Shuffled mean | p |
|---|---|---|---|
| ETA: share of variance between stores | 0.00026 | 0.00032 | 0.57 |
| log price: share of variance between stores | 0.00029 | 0.00032 | 0.52 |
| in stock: share of variance between stores | 0.00021 | 0.00032 | 0.71 |
| category × store chi-square | 177.5 | 147.3 | 0.043 |
| subcategory × store chi-square | 336.9 | 308.2 | 0.12 |
| brand × store chi-square | 602.6 | 630.7 | 0.78 |
| ETA value × store chi-square | 42.4 | 41.7 | 0.45 |
| price decile × store chi-square | 60.6 | 63.3 | 0.56 |
| records of one name\|pack that sit in the same store | 21.0% | 21.9% | 0.007 |
| store changes along the source id order | 17,110 | 17,129 | 0.73 |

The clearest single number is the ninth row. The snapshot holds 17,054 pairs of records that share a name and pack.
If the label marked real stores, such a pair would almost never be inside one store, because a store lists a product
once. If the label were independent of the product, the share would be the sum of squared store shares, 21.96%. The
data shows 21.0%. That row is also the closest to a departure (p 0.007), and it departs downwards: slightly fewer
same-store pairs than chance, nowhere near zero.

Two more readings point the same way:

- **ETA follows the product record, not the store.** A real store has one delivery time at a given moment. Here the
  ETA distribution is the same in all eight stores (44% of listings at 8 minutes, 34% at 9, in every store), while
  42% of ETA variance lies between name\|pack keys.
- **A pair inside one store agrees no more often than a pair across stores.** Same price: 41.6% inside a store, 42.3%
  across. Same ETA: 39.2% and 39.7%. Both out of stock given either is: 29.5% and 31.2%.

Deliverable 10 had already found that listing similarity does not follow distance (Spearman −0.09, p 0.65) and read
it as "collection depth". This audit is the direct test of that suspicion.

## Could the tests have seen a store effect?

A null result means nothing unless the test detects an effect that exists. Two positive controls:

- **Planted shift.** An ETA shift is added to the smallest store (1,319 rows), in memory only, and the ETA test is
  re-run 400 times. It detects 0.2 minutes 99% of the time and 0.1 minutes 46% of the time. The eight synthetic
  Blinkit stores differ by up to 4.9 minutes.
- **SYNTHETIC rows**, where the generator planted store ETA effects: the same statistic is 0.73 on the last snapshot
  (median 0.83 over 60 snapshots, minimum 0.59) against 0.00026 on the REAL rows. p 0.002.

The control covers ETA. The generator did not plant store differences in category mix or price level either, so those
tests are null on synthetic rows too and prove nothing there.

## What this does and does not say

It is a property of the data in `data/raw`. **It is not a statement about how the source was collected.**

**The source workbook was checked afterwards (2026-10-13, `docs/audit/AUDIT_2026-10-13.md`).**
`Blinkit_Master_FINAL_Clean_v2.xlsx` (owner's Downloads, sha256 `568313ec…77b696`, read-only) says where the stores
come from: a public store map ("QuickCommerceMap public store listings", `public_web_observation`, accurate to about
50–100 m). Its `STORE_PRODUCT_MAP` sheet pairs each of the 21,949 product rows with one store, but nothing in the
workbook records how: the provenance fields on those rows are the store's own, and there is no method column or notes
sheet. So the source cannot establish that a product was observed in its store. The status is **UNVERIFIED**, and
`src/provenance.py` carries it to the manifests, the analyst and the pages. The person who collected the data can
still settle it; until then:

| | |
|---|---|
| **Affected** | Deliverable 10 (assortment gaps), 12c category coverage, the REAL part of "a store adds products", and the store half of the listing chain's REAL context row. Each reads `store_id` as "this store listed this product". None of them is supported by evidence that the label carries store information. |
| **Unaffected** | Price and stock status per record (verified against the source, 21,949 rows). The product matcher. The REAL anomaly detector. The v15.1 calibration, which is per category. Store names, addresses and coordinates in `STORES*.csv`, which come from a separate public source. |

No existing output was changed or withdrawn. The affected docs now carry a pointer to this page.

## What the snapshot does say, with the store label set aside

15,804 of the REAL records share a name\|pack with at least one other record (6,047 keys, 17,054 pairs).

- **Stock.** 7.4% of those records are out of stock. Given that one record of a product is out, another record of the
  same product is out 47.1% of the time: 6.4 times the rate. Shuffling stock status within category gives 10.1%, so
  category explains little of it (p 0.002). Whatever the records are, the same product in different places or at
  different times, stock-outs in this snapshot are a property of the product more than of the listing.
- **Price.** 57.9% of pairs carry different prices, and the split by category is sharp: 0% of 324 pairs in Personal
  Care, 7.6% in Home & Cleaning and 19% in Sauces, Spreads & Pickles, against 41–92% in the other twelve categories
  with at least 50 pairs, with median gaps of 8–43% where they differ. A split that clean is unusual for one platform
  in one city on one day. It may reflect how the catalog was assembled. It is recorded here as an open question about
  the source, not as a finding about Blinkit's pricing.

The generator plants none of the product-level clustering: in the SYNTHETIC panel a product running out on one
platform raises the chance on another by a factor of 1.16. That gap is carried into the collection planner
(`docs/COLLECTION_PLANNER_v1.md`) and is a candidate for a future generator revision. v15.1 was not re-run.

## Tests

`tests/test_audit.py`: the statistics on a toy table, the saved verdict and scope, and both positive controls.
