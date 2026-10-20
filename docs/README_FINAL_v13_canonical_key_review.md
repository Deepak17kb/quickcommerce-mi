# Canonical mapping review — FINAL v13

## I tested your hypothesis. The data says the mapping is already correct.

Your reasoning was sound and worth checking, so I ran it properly against all 2,419
collision groups. Four checks:

**A. Does one canonical key ever cover different pack sizes?**
`0` keys. Your 500 ml / 1 L case cannot occur — `pack_size` is already part of the key,
so `Product A | 500 ml` and `Product A | 1 L` are already separate keys.

**B. Is a size hiding inside the product name, unsplit?**
`0` groups. No collision group has a differing product name at all, and none has an
embedded size that differs.

**C. Do colliding rows differ on any identity attribute?**

| Attribute | Groups where it differs |
|---|---|
| `product_name` | **0** / 2,419 |
| `pack_size` | **0** / 2,419 |
| `brand` | **0** / 2,419 |

**D. So what does differ?**

| Attribute | Groups | |
|---|---|---|
| selling price | 1,572 | observation |
| ETA | 1,592 | observation |
| stock status | 202 | observation |

Those are all **observations, not identity**. A product's canonical key must not change
when it goes on sale — otherwise the same SKU splits into a new "variant" every time the
price moves, and cross-platform matching collapses.

**Verdict: 0 of 2,419 groups need a key split.** They are the same SKU listed more than
once in the same store — which is real, and which `product_id` + `listing_seq` already
represent correctly.

---

## The one real defect this surfaced — and it wasn't the key

`subcategory` differed in 106 groups, which looked like variant evidence. It wasn't:

| Count | Values | |
|---|---|---|
| 67 | `Energy Bar` vs `Energy Bars` | singular/plural |
| 12 | `Dates &Seeds` vs `Indian Sweets` | same product, two labels |
| 6 | `Dates &Seeds` vs `Dry Fruit` | same product, two labels |
| 4 | `Dry Fruit` vs `Indian Sweets` | same product, two labels |

Same product name, same pack size, same brand, same price — categorised inconsistently by
the source. **Splitting the key on subcategory would have been the wrong fix**: it would
have torn one protein bar into two products because of a plural `s`.

The right fix was to normalise the labels. Each canonical product now carries one category
and one subcategory, assigned by majority vote across its listings:

- `category` normalised on **73** rows
- `subcategory` normalised on **197** rows
- canonical keys with inconsistent labels: **0** (was 106)

Applied to `OBSERVATIONS` and `MASTER_CATALOG` in all four workbooks.

---

## New sheet: `CANONICAL_KEY_AUDIT`

In `Blinkit_FINAL_v13.xlsx` — one row per collision group, 2,419 rows, with the evidence:

```
canonical_product_key · n_listings · product_ids · distinct_product_name
distinct_pack_size · distinct_brand · distinct_selling_price · distinct_eta
distinct_stock · verdict · reason
```

Every row reads `SAME_SKU_MULTIPLE_LISTINGS`. If the source is ever re-scraped and a real
variant does appear, that group will come back `SEPARATE_SKU_SPLIT_KEY` and the key should
then be split.

---

## The data model, stated plainly

| Key | Grain | Unique? |
|---|---|---|
| `canonical_product_key` | the SKU — `name \| pack_size` | No, by design. Cross-platform matching |
| `product_id` | one catalog listing | Yes, 21,949 |
| `listing_seq` | which listing of that SKU in that store | 1–6 |
| `observation_key` | `snapshot \| store \| product_id` | **Yes — 285,949 / 285,949** |

Point any duplicate audit at `observation_key`. A duplicate on
`snapshot_id + store_id + canonical_product_key` is expected behaviour, not a defect — it
means a store carries that SKU as more than one listing.

If you want one row per SKU per store per snapshot:
```python
one_per_sku = df.sort_values('listing_seq').drop_duplicates(
    ['snapshot_id','store_id','canonical_product_key'])
```
That is a *choice about aggregation*, not a data fix — you would be discarding a real
second listing at a different price.

---

285,949 rows · 0 empty cells · 0 keys with inconsistent labels · 0 keys spanning multiple pack sizes
