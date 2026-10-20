"""
audit_data_quality.py — read-only data-quality audit of data/raw/ and data/reference/.

    python scripts/audit_data_quality.py

Writes:
    outputs/audit/consistency_checks.csv   one row per rule: violations total / REAL / per platform
    outputs/audit/text_artifacts.csv       rows whose product_name or brand carry markup / stray dashes
    data/reference/BRAND_REVIEW.csv        catalog products whose brand needs a human decision (only if absent —
                                           an existing file may already carry decisions, never overwritten)

Never writes to data/raw/ or data/ml/. Findings are written up in docs/DATA_AUDIT.md.
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.load import load_raw, load_stores, load_catalog   # noqa: E402

OUT = ROOT / 'outputs' / 'audit'
BRAND_REVIEW = ROOT / 'data' / 'reference' / 'BRAND_REVIEW.csv'

# a brand that is also an ordinary word used mid-name this often is suspect
GENERIC_MID_USES = 20


def consistency(d: pd.DataFrame) -> pd.DataFrame:
    sp, mrp = d.selling_price, d.mrp
    ot = d.offer_type.astype(str)
    ts = pd.to_datetime(d.observed_at.astype(str), format='mixed', errors='coerce')
    disc = np.where(mrp > 0, (mrp - sp) / mrp * 100, 0)
    stores = load_stores()
    ref_name = d.store_id.map(stores.set_index('store_id').store_name)

    rules = {
        'selling_price > mrp':                        sp > mrp + .005,
        'selling_price <= 0 or null':                 (sp <= 0) | sp.isna(),
        'discount_percent != formula (>0.6pt)':       (d.discount_percent - disc).abs() > .6,
        'unit_price != selling_price / pack_qty':     ((d.unit_price - sp / d.pack_qty).abs()
                                                       > .01 * d.unit_price.abs().clip(lower=1)) & d.pack_qty.notna(),
        'in_stock disagrees with stock_status':       d.in_stock.astype(int).ne(d.stock_status.eq('Available').astype(int)),
        'delivery_eta_min > delivery_eta_max':        d.delivery_eta_min > d.delivery_eta_max,
        'NO_OFFER with non-zero offer fields':        ot.eq('NO_OFFER') & ((d.offer_value != 0) | (d.buy_quantity != 0)
                                                       | (d.get_quantity != 0) | (d.coupon_required != 0)),
        'BUY_X_GET_Y with buy or get == 0':           ot.eq('BUY_X_GET_Y') & ((d.buy_quantity == 0) | (d.get_quantity == 0)),
        'PERCENT_OFF value outside (0,100)':          ot.eq('PERCENT_OFF') & ~d.offer_value.between(.01, 99.99),
        'flat/bank/combo offer_value >= selling_price': ot.isin(['FLAT_OFF', 'BANK_OFFER', 'COMBO_DEAL']) & (d.offer_value >= sp),
        'observed_at unparseable':                    ts.isna(),
        'observed_at date != snapshot_date':          ts.dt.strftime('%Y-%m-%d') != d.snapshot_date.astype(str),
        'day_of_week != observed_at weekday':         ts.dt.day_name() != d.day_of_week.astype(str),
        'is_real_observation disagrees with data_status': d.is_real_observation.astype(int).ne(d.data_status.eq('REAL').astype(int)),
        'pack fields null':                           d.pack_size.isna() | d.pack_qty.isna() | d.pack_unit.isna(),
        'store_id not in STORES*.csv':                ref_name.isna(),
        'store_name differs from STORES*.csv':        ref_name.notna() & d.store_name.astype(str).ne(ref_name.astype(str)),
        'product_name has ** or stray dash/space':    _artifact(d.product_name),
        'brand has ** or stray dash/space':           _artifact(d.brand),
    }
    real = d.data_status.eq('REAL')
    rows = []
    for name, mask in rules.items():
        mask = pd.Series(mask, index=d.index).fillna(False).astype(bool)
        rows.append({'rule': name, 'violations': int(mask.sum()), 'real_rows': int((mask & real).sum()),
                     **{f'n_{p}': int((mask & d.platform.eq(p)).sum()) for p in sorted(d.platform.unique())}})
    return pd.DataFrame(rows)


def _artifact(s: pd.Series) -> pd.Series:
    s = s.astype(str)
    return (s != s.str.strip()) | s.str.contains(r'\*\*') | s.str.contains(r'\s-$')


def brand_review(cat: pd.DataFrame) -> pd.DataFrame:
    """One row per catalog product whose brand needs a human look. Nothing is applied.

    flag                meaning                                              suggestion
    NAME_SAYS_BY        name ends 'by X' and brand != X                      X
    OVER_EXTENDED       brand is another brand plus extra words              the shorter brand
                        ('Amul Kool' when 'Amul' exists)                     (only if it has more products)
    GENERIC_WORD        one-word brand that is an ordinary word elsewhere    none — human call
                        ('Banana', 'Honey', 'Set')
    TEXT_ARTIFACT       brand carries ** or a trailing ' -'                  cleaned string
    """
    names = cat.product_name.astype(str)
    brands = cat.brand.astype(str)
    by_brand = names.str.extract(r"\bby\s+([A-Z][\w'&.]*(?:\s+[A-Z][\w'&.]*){0,3})\s*$")[0]
    n_products = brands.value_counts()
    known = set(n_products.index) - {'UNBRANDED'}

    shorter = {}
    for b in known:
        parts = b.split()
        for k in range(len(parts) - 1, 0, -1):
            cand = ' '.join(parts[:k])
            if cand in known and n_products[cand] > n_products[b]:
                shorter[b] = cand
                break

    generic = {}
    for b in known:
        if len(b.split()) != 1:
            continue
        # ordinary use = the word inside some OTHER product's name, not as its leading brand, not after 'by'
        pat = re.compile(r"(?<!\bby )(?<!^)\b" + re.escape(b) + r"\b", re.I)
        mid = sum(1 for n in names if pat.search(n) and not n.lower().startswith(b.lower()))
        if mid >= GENERIC_MID_USES:
            generic[b] = mid

    rows = []
    for i, name, brand in zip(cat.index, names, brands):
        flags, suggestion = [], ''
        by = by_brand.get(i)
        if isinstance(by, str) and by != brand:
            flags.append('NAME_SAYS_BY')
            suggestion = by
        if brand in shorter:
            flags.append(f'OVER_EXTENDED({shorter[brand]})')
            suggestion = suggestion or shorter[brand]
        if brand in generic and not flags:
            flags.append(f'GENERIC_WORD(mid_name_uses={generic[brand]})')
        if brand != 'UNBRANDED' and _artifact(pd.Series([brand])).iat[0]:
            flags.append('TEXT_ARTIFACT')
            suggestion = suggestion or re.sub(r'[\s\-*]+$', '', brand.replace('**', '')).strip()
        if flags:
            rows.append({'canonical_product_key': cat.at[i, 'canonical_product_key'],
                         'product_name': name, 'brand': brand, 'flags': '; '.join(flags),
                         'suggested_brand': suggestion, 'decision': ''})
    cols = ['canonical_product_key', 'product_name', 'brand', 'flags', 'suggested_brand', 'decision']
    return pd.DataFrame(rows, columns=cols).sort_values(['flags', 'brand', 'product_name'])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    d = load_raw()
    print(f"raw {len(d):,} rows")

    c = consistency(d)
    c.to_csv(OUT / 'consistency_checks.csv', index=False)
    with pd.option_context('display.width', 200):
        print(c.to_string(index=False))

    art = d[_artifact(d.product_name) | _artifact(d.brand)]
    (art.drop_duplicates('canonical_product_key')[['canonical_product_key', 'product_name', 'brand', 'data_status']]
        .to_csv(OUT / 'text_artifacts.csv', index=False))
    print(f"\ntext artifacts: {art.canonical_product_key.nunique():,} products -> outputs/audit/text_artifacts.csv")

    br = brand_review(load_catalog())
    print(f"catalog products whose brand needs review: {len(br):,}  "
          f"{br['flags'].str.extract(r'^([A-Z_]+)')[0].value_counts().to_dict()}")
    if BRAND_REVIEW.exists():
        br.to_csv(OUT / 'brand_review_latest.csv', index=False)
        print(f"  {BRAND_REVIEW.relative_to(ROOT)} exists (may hold decisions) — "
              f"fresh copy written to outputs/audit/brand_review_latest.csv instead")
    else:
        br.to_csv(BRAND_REVIEW, index=False)
        print(f"  -> {BRAND_REVIEW.relative_to(ROOT)}  (fill `decision`: KEEP / USE_SUGGESTED / <brand>)")


if __name__ == '__main__':
    main()
