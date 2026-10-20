"""
priority.py — the small human-labelling batch that makes tier 1 measurable.

    python -m src.matching.priority            # build data/reference/MATCH_REVIEW_PRIORITY.csv (refuses to overwrite labels)
    python -m src.matching.priority --status   # how many same / different labels the batch has so far

WHY NOT "TEST-SPLIT PAIRS ONLY"
  A pair is a test pair only if BOTH canonical keys are test keys: with a 25% key share that is ~6% of pairs. True
  same-product pairs with different keys are rare in one catalog: 157 heuristic "likely same" pairs exist across all
  11,834 needs_review pairs, and only 9 of them have both keys in the hash test split. That cannot yield 30 positives.

  So the batch is drawn from ALL needs_review pairs, and every key in the batch becomes a RESERVED EVALUATION KEY:
  train.group_split forces it into test, so no batch key ever appears in a training pair. The reservation is fixed
  by this file, before any label exists, and is chosen from similarity features only (never from label values).
  Consequence to keep in mind: tier 1 measures performance on review-selected, harder-than-random pairs, not on
  random catalog pairs.

STRATA (selection uses similarity features only)
  L_likely_same   same pack AND (identical after markup/case normalisation, OR same base name with bracket text on
                  one side only e.g. 'Amla (Aula)', OR identical token set, OR Jaro-Winkler >= 0.97 without two
                  different bracket texts). All of them are taken: this is where the positives are.
  M_ambiguous     same pack, not L, not a bracket-variant pattern, char n-gram cosine in [0.75, 0.97): stratified
                  over four cosine bins, at most one pair per key.
  N_hard_contrast bracket-variant pattern ('(Rose)' vs '(Citrus)') or different pack with cosine >= 0.8: at most one
                  pair per key. Guarantees hard negatives on both sides of the pack feature.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

import src.load as L
from src.matching import blocking as B
from src.matching import labels as LB

PRIORITY_PATH = L.REF / 'MATCH_REVIEW_PRIORITY.csv'
SEED = 20260917
M_PER_BIN = 25
M_BINS = [0.75, 0.80, 0.85, 0.90, 0.97]
N_PER_KIND = 20


def _signals(pairs: pd.DataFrame, rec: pd.DataFrame) -> pd.DataFrame:
    r = rec.set_index('canonical_product_key')
    p = pairs.copy()
    p['formatting_only'] = r.name_norm.reindex(p.key_a).to_numpy() == r.name_norm.reindex(p.key_b).to_numpy()
    p['same_base'] = r.name_base.reindex(p.key_a).to_numpy() == r.name_base.reindex(p.key_b).to_numpy()
    ka, kb = r.bracket.reindex(p.key_a).to_numpy(), r.bracket.reindex(p.key_b).to_numpy()
    p['alias_bracket'] = p.same_base & (p.bracket_one == 1)
    p['variant_bracket'] = p.same_base & (p.bracket_both == 1) & (ka != kb)
    p['same_tokens'] = p.tokjac_full == 1
    return p


def _one_per_key(df: pd.DataFrame, used: set, limit: int) -> pd.DataFrame:
    take = []
    for row in df.itertuples():
        if row.key_a in used or row.key_b in used:
            continue
        take.append(row.Index); used.update((row.key_a, row.key_b))
        if len(take) >= limit:
            break
    return df.loc[take]


def select_batch(labels: pd.DataFrame, rec: pd.DataFrame, seed: int = SEED) -> pd.DataFrame:
    nr = _signals(labels[labels.provenance == 'needs_review'], rec)
    rng = np.random.default_rng(seed)
    nr = nr.iloc[rng.permutation(len(nr))]          # deterministic tie-breaking inside strata

    L_mask = (nr.pack_exact == 1) & (nr.formatting_only | nr.alias_bracket | nr.same_tokens
                                     | ((nr.jw_full >= 0.97) & ~nr.variant_bracket))
    parts = [nr[L_mask].assign(stratum='L_likely_same', selection_reason=np.select(
        [nr[L_mask].formatting_only, nr[L_mask].alias_bracket, nr[L_mask].same_tokens],
        ['identical after markup/case normalisation', 'bracket text on one side only', 'identical token set'],
        'Jaro-Winkler >= 0.97'))]
    used = set(parts[0].key_a) | set(parts[0].key_b)

    rest = nr[~L_mask]
    m_pool = rest[(rest.pack_exact == 1) & ~rest.variant_bracket]
    for lo, hi in zip(M_BINS[:-1], M_BINS[1:]):
        b = m_pool[(m_pool.ngram_cos_full >= lo) & (m_pool.ngram_cos_full < hi)]
        parts.append(_one_per_key(b, used, M_PER_BIN).assign(stratum='M_ambiguous',
                                                             selection_reason=f'same pack, cosine {lo:.2f}-{hi:.2f}'))
    variants = rest[(rest.pack_exact == 1) & rest.variant_bracket].sort_values('ngram_cos_full', ascending=False)
    parts.append(_one_per_key(variants, used, N_PER_KIND).assign(stratum='N_hard_contrast',
                                                                 selection_reason='same base name, different bracket text'))
    diffpack = rest[(rest.pack_exact == 0) & (rest.ngram_cos_full >= 0.8)].sort_values('ngram_cos_full', ascending=False)
    parts.append(_one_per_key(diffpack, used, N_PER_KIND).assign(stratum='N_hard_contrast',
                                                                 selection_reason='different pack (no rule fired), cosine >= 0.80'))
    batch = pd.concat(parts)

    r = rec.set_index('canonical_product_key')
    out = pd.DataFrame({
        'pair_id': batch.pair_id.to_numpy(), 'stratum': batch.stratum.to_numpy(),
        'selection_reason': batch.selection_reason.to_numpy(),
        'name_a': r.product_name.reindex(batch.key_a).to_numpy(), 'name_b': r.product_name.reindex(batch.key_b).to_numpy(),
        'pack_a': r.pack_size.reindex(batch.key_a).to_numpy(), 'pack_b': r.pack_size.reindex(batch.key_b).to_numpy(),
        'brand_a': r.brand.reindex(batch.key_a).to_numpy(), 'brand_b': r.brand.reindex(batch.key_b).to_numpy(),
        'category_a': r.category.reindex(batch.key_a).to_numpy(), 'category_b': r.category.reindex(batch.key_b).to_numpy(),
        'jw_full': batch.jw_full.round(4).to_numpy(), 'ngram_cos_full': batch.ngram_cos_full.round(4).to_numpy(),
        'ngram_cos_base': batch.ngram_cos_base.round(4).to_numpy(), 'tokjac_full': batch.tokjac_full.round(4).to_numpy(),
        'key_a': batch.key_a.to_numpy(), 'key_b': batch.key_b.to_numpy(),
    })
    order = {'L_likely_same': 0, 'M_ambiguous': 1, 'N_hard_contrast': 2}
    out = out.assign(_o=out.stratum.map(order)).sort_values(['_o', 'ngram_cos_full'], ascending=[True, False])
    out = out.drop(columns='_o').reset_index(drop=True)
    out.insert(0, 'batch_row', np.arange(1, len(out) + 1))
    out['label'] = ''
    out['reviewer_note'] = ''
    return out


def reserved_test_keys(path: Path = PRIORITY_PATH) -> set:
    """Every canonical key in the priority batch. train.group_split forces these into test."""
    if not Path(path).exists():
        return set()
    b = pd.read_csv(path, dtype=str)
    return set(b.key_a) | set(b.key_b)


def status(path: Path = PRIORITY_PATH) -> dict:
    b = pd.read_csv(path, dtype=str).fillna('')
    lab = b.label.str.strip()
    return {'rows': len(b), 'labelled_same_1': int((lab == '1').sum()), 'labelled_different_0': int((lab == '0').sum()),
            'unlabelled': int((~lab.isin(['1', '0'])).sum()),
            'by_stratum': b.assign(l=lab).groupby(['stratum', 'l']).size().unstack(fill_value=0).to_dict('index'),
            'tier1_needs': '>= 30 labelled 1 and >= 30 labelled 0'}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--force', action='store_true', help='overwrite even if labels exist (never needed normally)')
    args = ap.parse_args(argv)
    if args.status:
        import json
        print(json.dumps(status(), indent=1)); return
    if PRIORITY_PATH.exists() and not args.force:
        old = pd.read_csv(PRIORITY_PATH, dtype=str).fillna('')
        if (old.label.str.strip() != '').any() or (old.reviewer_note.str.strip() != '').any():
            raise SystemExit(f"{PRIORITY_PATH.name} already has labels or notes; refusing to overwrite (use --status).")
    labels, rec, _ = LB.build()
    batch = select_batch(labels, rec)
    batch.to_csv(PRIORITY_PATH, index=False)
    keys = set(batch.key_a) | set(batch.key_b)
    print(f"wrote {len(batch)} pairs -> {PRIORITY_PATH.relative_to(L.ROOT)} | reserved evaluation keys: {len(keys)}")
    print(batch.groupby(['stratum', 'selection_reason']).size().to_string())


if __name__ == '__main__':
    main()
