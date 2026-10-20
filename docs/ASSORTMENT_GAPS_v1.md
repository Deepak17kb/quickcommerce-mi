# Deliverable 10 — assortment-gap recommender v1 (REAL)

Built 2026-09-23. `python -m src.models.assortment_gaps` → `outputs/models/assortment_gaps/`.

## What this is allowed to claim

Input: which products each of the 8 REAL Blinkit stores listed on 2026-07-10. A "gap" is a product similar real
stores list that this store's listing did not show that day. It is **not** proof the store does not stock it. Two
stores have ~5,600 listed products and six have ~1,300, which says more about how deeply each store was collected than
about its range. Nothing here is customer preference or sales uplift. The 22 SYNTHETIC stores are never used, because
their assortment was generated.

Overlap is thin: of 12,192 products, 7,058 are listed by one store only, 3,899 by two, and 4 by seven.

> **Read with `docs/STORE_LABEL_AUDIT_v1.md` (2026-10-13).** On ten permutation tests the store label on the REAL rows
> cannot be told apart from a random label: products that share a name and pack fall in the same store at the rate a
> label independent of the product would give (21.0% against 21.9%), and ETA, price and stock do not vary by store.
> Until the source's store column is explained, a "gap" here is not supported by evidence that the label carries
> store information. The method and its evaluation stand as a method; the store-level reading does not.

## Methods

| Method | Score for "store s should list product i" |
|---|---|
| popularity | how many other stores list it |
| store_knn | other stores' listings weighted by Jaccard similarity to s |
| mf_svd | rank-3 truncated SVD of the store × product matrix (implicit matrix factorisation) |
| brand_affinity | share of the product's brand range that s lists (the product itself left out) |
| **hybrid_ranker** | LightGBM on all of the above + subcategory/category affinity, brand size, price position, store size |

## Evaluation: hide and recover, leave-one-store-out

For each store, 20% of its listed products that another store also lists are hidden. Every method ranks all products
the masked store does not list. Averaged over 3 masks; the ranker scoring store s is trained only on the other 7
stores' masks.

| Method | recall@20 | recall@100 | recall@250 | NDCG@100 |
|---|---|---|---|---|
| brand_affinity | 0.003 | 0.016 | 0.043 | 0.061 |
| mf_svd | 0.005 | 0.018 | 0.035 | 0.059 |
| popularity | 0.007 | 0.025 | 0.050 | 0.096 |
| store_knn | 0.007 | 0.025 | 0.055 | 0.103 |
| **hybrid_ranker** | **0.011** | **0.065** | **0.155** | **0.199** |

The hybrid recovers 2.6× as many hidden REAL listings as popularity in the top 100. Absolute recall is modest because
the matrix is 8 stores wide and mostly single-store products. Pure MF has little to factorise at that width, which is
why the ranker leans on brand and subcategory affinity.

**Listing similarity does not follow geography.** Across the 28 store pairs, Jaccard similarity vs straight-line
distance gives Spearman ρ = −0.09, p = 0.65. The two deeply collected stores look "most similar" to everyone. That's
more evidence that the matrix reflects collection depth.

## Output

Top 50 gaps per store with a reason in words, e.g. "listed by 5 of 7 other REAL stores, incl. the most similar listing
BLK-BBSR-003; this store lists 33% of the RiteBite range and 36% of the subcategory". Every row carries the claim
"may be a collection gap, not an assortment gap".

Figure: `outputs/models/assortment_gaps/figures/assortment_gaps.png`.
