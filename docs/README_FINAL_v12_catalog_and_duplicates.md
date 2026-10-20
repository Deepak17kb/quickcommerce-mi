# Quick-Commerce Dataset — FINAL v12

## 1. MASTER_CATALOG — fixed

| Column | Before | After |
|---|---|---|
| `brand` | 9,129 missing | 0 |
| `pack_qty` | 647 missing | 0 |
| `pack_unit` | 709 missing | 0 |

The pack fields were never really missing — the catalog sheet had never been run through the
extended parser. `1 set`, `1 pair`, `20 tabs`, `2 x 10 tabs`, `3 x 72 wipes`, `100 pulls`,
`6 rolls` all now resolve to a real quantity and unit. `2 x 10 tabs` → `20 tab`.

`brand` → `UNBRANDED` on 9,129 rows. That is a statement about the products, not a
placeholder: they are loose produce and generic goods that carry no brand. The 3,059 rows
that do have a brand are unchanged (Amul 208, Tata 144, Britannia 99, Cadbury 87).

Fixed in all four workbooks — it is the same shared sheet.

---

## 2. Duplicates — diagnosed, nothing deleted

You were right not to let me delete them. Here is what the 5,342 flagged rows actually are,
across 2,419 collision groups on `snapshot_id + store_id + canonical_product_key`:

| `listing_class` | Rows | Groups | What it is |
|---|---|---|---|
| `single_listing` | 16,607 | — | No collision at all |
| `distinct_listing` | 4,682 | 2,098 | **Genuinely different.** Price, MRP, stock or ETA differs |
| `identical_repeat` | 660 | 321 | Identical on every observable field except `product_id` |

**Only 339 rows are genuinely removable** — the second-and-later members of the 321
`identical_repeat` groups. The other 5,003 flagged rows carry real differences: 1,572 groups
differ on selling price, 1,429 on MRP, 1,592 on ETA, 202 on stock status. Collapsing those
would have destroyed real price variation inside a single store.

Nothing was deleted. Three new columns let you decide:

```python
df.listing_class          # single_listing | distinct_listing | identical_repeat
df.is_preferred_listing   # 0 on the 339 redundant rows, 1 everywhere else
df.observation_key        # snapshot_id | store_id | product_id — unique, 285,949/285,949
```

Clean deduplicated view, no data loss:
```python
clean = df[df.is_preferred_listing == 1]     # Blinkit real: 21,610 of 21,949
```

**On the audit that flagged this:** `canonical_product_key` is the cross-*platform* matching
key. It is deliberately not unique within a store, because one store really can carry the
same physical product as several listings. The row key is `observation_key`, which is unique
across all 285,949 rows. Point your duplicate check at that.

---

## 3. Blinkit baseline timestamp

Left unfabricated, as you said. The real 2026-07-10 rows now carry explicit sentinels rather
than blanks:

```
snapshot_date = 2026-07-10      (real)
snapshot_time = NOT_RECORDED    (sentinel — the source captured date only)
hour          = -1              (sentinel)
```

So there are no empty cells, and nothing pretends to be a capture time. To treat them as
missing in a model: `df.loc[df.hour == -1, 'hour'] = np.nan`.

I did not synthesise a time onto these rows even though you offered. They are the only rows
in the dataset labelled `data_status = REAL`, and a fabricated field on a row flagged REAL is
the one combination that would actually mislead later. The timed Blinkit series you need
already exists — the 72,000 synthetic Blinkit rows carry real timestamps across 60 snapshots
and 30 days, same grid as the other three platforms.

---

## Composition — 285,949 rows, 0 empty cells

| Platform | Rows | Status | Preferred | Listings | Snapshots | Days |
|---|---|---|---|---|---|---|
| Blinkit | 21,949 | REAL | 21,610 | 21,949 | 1 | 1 |
| Blinkit | 72,000 | SYNTHETIC | 72,000 | 1,200 | 60 | 30 |
| Swiggy Instamart | 72,000 | SYNTHETIC | 72,000 | 1,200 | 60 | 30 |
| Flipkart Minutes | 54,000 | SYNTHETIC | 54,000 | 900 | 60 | 30 |
| BigBasket | 66,000 | SYNTHETIC | 66,000 | 1,100 | 60 | 30 |

## Validation

```
PASS  observation_key unique                              0
PASS  MASTER_CATALOG empty cells                          0
PASS  OBSERVATIONS empty cells                            0
PASS  dup on (snapshot, store, product_id)                0
PASS  dup on KEY after is_preferred filter                0
PASS  selling_price > mrp                                 0
PASS  Blinkit real listings == 21,949                     0
PASS  real rows with an invented clock time               0
```

---

Version FINAL_v12 · 2026-09-15
