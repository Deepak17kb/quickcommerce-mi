# Quick-Commerce Dataset — FINAL v11

**285,949 rows. No empty cells in any column you asked about.**

## The MRP change you asked for

Where the source had no distinct MRP, `mrp` is now set **equal to `selling_price`** and
`discount_percent` is **0**. Your reading — that those items simply aren't discounted — is
a reasonable one, and it removes 20,925 missing values from the real Blinkit rows.

A new **`mrp_source`** column records which rule produced each row's MRP, so the decision is
reversible:

| `mrp_source` | Rows | Meaning |
|---|---|---|
| `observed_distinct` | 1,020 | MRP differed from selling price in the source |
| `observed_at_mrp` | 4 | MRP and selling price matched in the source |
| `assumed_equal_to_selling_price` | 20,925 | **MRP was absent; filled from selling price** |
| `simulated_discounted` | 150,240 | Generated, on promo |
| `simulated_at_mrp` | 113,760 | Generated, listed at MRP |

To go back to the stricter view:
```python
mask = df.mrp_source == 'assumed_equal_to_selling_price'
df.loc[mask, ['mrp','discount_percent']] = None
```

The same rule ran in reverse for the four unnamed Blinkit listings, which had a real MRP but
no price: `selling_price = mrp`, discount 0.

---

## What filled each column

**Derived — safe, computed from data already present**

| Column | Rule |
|---|---|
| `pack_qty`, `pack_unit` | Parsed from `pack_size`, now including count units |
| `unit_price` | `selling_price / pack_qty` |
| `discount_percent` | `(mrp - selling_price) / mrp × 100` |
| `in_stock` | 1 where `stock_status == 'Available'` |

The parser was the real bug behind your "5–6% missing unit_price". It only knew g/ml/pc, so
`1 set`, `20 tabs`, `3 x 72 wipes`, `100 pulls`, `6 rolls` all fell through. It now handles
count units and multiplier packs, so **`unit_price` is 100% populated** — by fixing the
parser, not by inventing numbers.

**Factual labels and zeros**

`brand` → `UNBRANDED` for loose produce that genuinely carries no brand (15,602 real rows —
things like Amla, Arvi, Aak Flower Garland). `offer_type` → `NO_OFFER` where no promotion was
recorded, with 0 in `offer_value`, `coupon_required`, `buy_quantity`, `get_quantity`.
`is_bestseller` and `is_sponsored` → 0, since not flagged in the source means not flagged.

**Assumed — real Blinkit rows only, flagged**

`delivery_eta_max` = `delivery_eta_min`. The source showed a single point ETA ("11 mins"),
not a range, so the range collapses onto the observed value rather than inventing a spread.
`delivery_fee` and `minimum_order_value` are standard platform terms (Blinkit ₹0 / ₹99) —
commercial terms, not per-product observations, and absent from the snapshot. These rows
carry `enrichment_provenance = 'derived_and_platform_defaults'`.

---

## Two columns I left empty, deliberately

`snapshot_time` and `hour` on the 21,949 real Blinkit rows. They weren't on your list, and
they're the one case where filling would do real damage: the source recorded the **date
only**, so any clock time would be invented and would then look like a genuine observation
timestamp. Every other column is populated.

Say the word if you want them stamped `NOT_RECORDED` instead of blank — that gets you zero
empty cells without pretending to know the time.

---

## Composition

| Platform | Rows | Status | Listings | Snapshots | Days | Discounted |
|---|---|---|---|---|---|---|
| Blinkit | 21,949 | REAL | 21,949 | 1 | 1 | 4.6% |
| Blinkit | 72,000 | SYNTHETIC | 1,200 | 60 | 30 | 54.8% |
| Swiggy Instamart | 72,000 | SYNTHETIC | 1,200 | 60 | 30 | 58.7% |
| Flipkart Minutes | 54,000 | SYNTHETIC | 900 | 60 | 30 | 71.7% |
| BigBasket | 66,000 | SYNTHETIC | 1,100 | 60 | 30 | 45.3% |

`data_status` still separates real from generated. Filter before reporting numbers.

## Validation

```
PASS  selling_price > mrp                        0
PASS  duplicate (snapshot, store, product_id)    0
PASS  discount_percent mismatch                  0
PASS  unit_price != selling_price / pack_qty     0
PASS  eta_max < eta_min                          0
PASS  in_stock vs stock_status mismatch          0
PASS  Blinkit real listings == 21,949            0
PASS  pack_qty <= 0                              0
```

---

Version FINAL_v11 · 2026-09-15
