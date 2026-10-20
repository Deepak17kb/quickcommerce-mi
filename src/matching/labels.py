"""
labels.py — label assembly for the product matcher, with explicit provenance on every row. REAL rows only.

NO LABEL IS EVER GUESSED. A pair gets a label only from one of these sources:

  auto_positive    listing pairs inside a verified CANONICAL_KEY_AUDIT.csv group (verdict SAME_SKU_MULTIPLE_LISTINGS).
                   CAVEAT: every one of these groups has exactly one distinct product_name, pack_size and brand, so
                   every auto_positive pair compares two IDENTICAL catalog records. They teach nothing about name
                   variation.

  auto_positive    R4 markup_only_difference: two DIFFERENT canonical keys whose product names are identical once
                   '**' markup is removed (case and wording kept exactly), AND whose packs are equal (both parse with
                   src.matching.blocking.parse_pack to the same quantity and dimension; if either pack does not parse,
                   the markup-stripped pack strings must be identical), AND brand (markup-stripped, case-insensitive)
                   and category are equal. Same equivalence that fixed the pack_qty parsing: '**' is formatting, not
                   product identity. CAVEAT: features normalise markup away, so R4 pairs are feature-identical to
                   identical records too; they add labels, not name-variation signal.

  auto_negative    product pairs that are different products by an unambiguous rule:
                   R1 different_category_pack_and_name: category differs AND pack_size differs AND
                      ngram_cos_base < negative_max_ngram_cos_base AND jw_base < negative_max_jw_base
                   R2 pack_variant_same_unit: normalised pack_size strings differ, BOTH packs parse cleanly
                      (src.matching.blocking.parse_pack) to the same dimension, and larger/smaller parsed quantity
                      >= pack_variant_min_ratio. The raw pack_qty column is never used: it is 1.0 for every '**...**'
                      pack, which once made '**180 ml**' vs '180 ml' look like a pack variant. Different pack size = different SKU by this project's definition
                      (canonical_product_key = name | pack_size; CLAUDE.md §3.3), e.g. 1 kg vs 5 kg of the same atta.
                   R3 same_pack_different_category_and_name: pack_size strings equal AND category differs AND
                      ngram_cos_base < negative_max_ngram_cos_base AND jw_base < negative_max_jw_base. Added after the
                      first training run learned the shortcut "same pack size => same product" (every positive shares
                      its pack; R1/R2 negatives almost never do). Tested on random pairs sampled WITHIN the same
                      normalised pack size, so negatives exist on both sides of the pack feature.
                   Thresholds: config.yaml :: matching.labels.

  human_reviewed   pairs a person labelled in data/reference/MATCH_REVIEW_PRIORITY.csv or MATCH_REVIEW_QUEUE.csv
                   (label column 1 = same product, 0 = different product). Any other value, or blank, means still
                   unknown. If the two files disagree on a pair, that pair is left unlabelled and reported.

  needs_review     every other candidate pair — above all high-similarity pairs with different canonical keys
                   ('Amla' vs 'Amla (Aula)'). No label. Written to MATCH_REVIEW_QUEUE.csv for a human.

Random product pairs that are NOT blocking candidates are tested against R1/R2 only. If neither rule fires they
get no label and are not queued.
"""
from dataclasses import dataclass, fields
from pathlib import Path

import numpy as np
import pandas as pd

import src.load as L
from src.matching import blocking as B
from src.matching.features import PairFeaturizer, pair_frames

QUEUE_PATH = L.REF / 'MATCH_REVIEW_QUEUE.csv'
PRIORITY_PATH = L.REF / 'MATCH_REVIEW_PRIORITY.csv'
PROVENANCES = ('auto_positive', 'auto_negative', 'human_reviewed', 'needs_review')


@dataclass
class LabelConfig:
    negative_max_ngram_cos_base: float = 0.3
    negative_max_jw_base: float = 0.7
    pack_variant_min_ratio: float = 1.05
    random_pairs: int = 20000
    random_same_pack_pairs: int = 20000
    seed: int = 20260917

    @classmethod
    def from_yaml(cls, path: Path | None = None, **overrides):
        import yaml
        path = path or (L.ROOT / 'config.yaml')
        raw = (yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}).get('matching', {}).get('labels', {})
        raw.update(overrides)
        unknown = set(raw) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"unknown label config keys: {unknown}")
        return cls(**raw)


def negative_rule(left: pd.DataFrame, right: pd.DataFrame, X: pd.DataFrame, cfg: LabelConfig) -> pd.Series:
    """'' where no rule fires, else the rule name."""
    la, ra = left.reset_index(drop=True), right.reset_index(drop=True)
    r1 = ((la.category.astype(str) != ra.category.astype(str)) & (X.pack_exact == 0)
          & (X.ngram_cos_base < cfg.negative_max_ngram_cos_base) & (X.jw_base < cfg.negative_max_jw_base))
    pa, pb = la.pack_size.map(B.parse_pack), ra.pack_size.map(B.parse_pack)
    qa, qb = pd.Series([p[0] for p in pa]), pd.Series([p[0] for p in pb])
    da, db = pd.Series([p[1] for p in pa]), pd.Series([p[1] for p in pb])
    same_dim = (da == db) & (da != '')
    ratio = np.maximum(qa, qb) / np.minimum(qa, qb)
    r2 = (X.pack_exact == 0) & same_dim & (qa > 0) & (qb > 0) & (ratio >= cfg.pack_variant_min_ratio)
    r3 = ((la.category.astype(str) != ra.category.astype(str)) & (X.pack_exact == 1)
          & (X.ngram_cos_base < cfg.negative_max_ngram_cos_base) & (X.jw_base < cfg.negative_max_jw_base))
    rule = pd.Series('', index=X.index, dtype=object)
    rule[r2] = 'R2_pack_variant_same_unit'
    rule[r1] = np.where(r2[r1], 'R1_different_category_pack_and_name+R2_pack_variant_same_unit',
                        'R1_different_category_pack_and_name')
    rule[r3] = 'R3_same_pack_different_category_and_name'
    return rule


def positive_rule(left: pd.DataFrame, right: pd.DataFrame) -> pd.Series:
    """'' where no rule fires, else 'R4_markup_only_difference'."""
    la, ra = left.reset_index(drop=True), right.reset_index(drop=True)
    name_eq = la.product_name.map(B.strip_markup) == ra.product_name.map(B.strip_markup)
    raw_differs = la.product_name.astype(str) != ra.product_name.astype(str)
    pa, pb = la.pack_size.map(B.parse_pack), ra.pack_size.map(B.parse_pack)
    parsed_ok = pd.Series([bool(x[1]) and bool(y[1]) for x, y in zip(pa, pb)])
    parsed_eq = pd.Series([x[1] == y[1] and np.isclose(x[0], y[0]) if (x[1] and y[1]) else False for x, y in zip(pa, pb)])
    str_eq = la.pack_size.map(B.strip_markup) == ra.pack_size.map(B.strip_markup)
    pack_eq = np.where(parsed_ok, parsed_eq, str_eq)
    brand_eq = la.brand.map(B.strip_markup).str.lower() == ra.brand.map(B.strip_markup).str.lower()
    cat_eq = la.category.astype(str) == ra.category.astype(str)
    fire = name_eq & raw_differs & pack_eq & brand_eq & cat_eq
    return pd.Series(np.where(fire, 'R4_markup_only_difference', ''), dtype=object)


def pair_id(key_a, key_b) -> pd.Series:
    a, b = pd.Series(key_a).astype(str), pd.Series(key_b).astype(str)
    lo, hi = np.where(a <= b, a, b), np.where(a <= b, b, a)
    return pd.Series(lo, dtype=object) + ' || ' + pd.Series(hi, dtype=object)


def _read_one(path: Path) -> pd.DataFrame:
    if not Path(path).exists():
        return pd.DataFrame(columns=['pair_id', 'label'])
    q = pd.read_csv(path, dtype={'label': str})
    lab = q['label'].astype(str).str.strip().str.lower()
    q['label_value'] = lab.map({'1': 1, '0': 0, '1.0': 1, '0.0': 0})
    return q.loc[q.label_value.notna(), ['pair_id', 'label_value']].rename(columns={'label_value': 'label'})


def read_human_labels(path: Path | None = None, priority_path: Path | None = None) -> pd.DataFrame:
    """Human labels from the review queue and the priority batch. Pairs labelled differently in the two files are
    dropped (left unlabelled) with a warning. Passing only `path` reads just that file."""
    if path is not None and priority_path is None:
        return _read_one(path)
    both = pd.concat([_read_one(path or QUEUE_PATH), _read_one(priority_path or PRIORITY_PATH)], ignore_index=True)
    n = both.groupby('pair_id').label.nunique()
    conflict = n[n > 1].index
    if len(conflict):
        print(f"WARNING: {len(conflict)} pairs labelled differently in queue and priority files - left unlabelled")
    return both[~both.pair_id.isin(conflict)].drop_duplicates('pair_id')


def build(listings: pd.DataFrame | None = None, rec: pd.DataFrame | None = None, cand: pd.DataFrame | None = None,
          featurizer: PairFeaturizer | None = None, cfg: LabelConfig | None = None,
          block_cfg: B.BlockingConfig | None = None, queue_path: Path = QUEUE_PATH,
          priority_path: Path = PRIORITY_PATH):
    """Returns (labels, rec, featurizer). labels: one row per labelled or reviewable pair, with provenance,
    rule, label (1 / 0 / NaN) and every feature column."""
    cfg = cfg or LabelConfig.from_yaml()
    listings = B.real_listings() if listings is None else listings
    assert listings.data_status.eq('REAL').all(), "matcher labels must come from REAL rows only"
    rec = B.product_records(listings) if rec is None else rec
    cand = B.candidate_pairs(rec, block_cfg) if cand is None else cand
    featurizer = featurizer or PairFeaturizer().fit(rec.product_name)
    idx = pd.Series(np.arange(len(rec)), index=rec.canonical_product_key)

    # ---- auto_positive: verified audit groups (identical catalog records)
    aud = B.audit_pairs()
    key_of = listings.set_index('product_id').canonical_product_key
    aud = aud[aud.product_id_a.isin(key_of.index) & aud.product_id_b.isin(key_of.index)].copy()
    assert (aud.product_id_a.map(key_of) == aud.canonical_product_key).all()
    ii = idx.reindex(aud.canonical_product_key).to_numpy()
    Xp = featurizer.transform(*pair_frames(rec, ii, ii))
    pos = pd.concat([pd.DataFrame({
        'pair_id': aud.product_id_a.to_numpy() + ' || ' + aud.product_id_b.to_numpy(),
        'pair_level': 'listing', 'key_a': aud.canonical_product_key.to_numpy(), 'key_b': aud.canonical_product_key.to_numpy(),
        'i': ii, 'j': ii, 'label': 1.0, 'provenance': 'auto_positive',
        'rule': 'CANONICAL_KEY_AUDIT verified SAME_SKU_MULTIPLE_LISTINGS', 'blocking_method': 'same_key'}), Xp], axis=1)

    # ---- candidate product pairs: rules, human labels, needs_review
    left, right = pair_frames(rec, cand.i, cand.j)
    Xc = featurizer.transform(left, right)
    rule = negative_rule(left, right, Xc, cfg)
    prule = positive_rule(left, right)
    both = (rule != '') & (prule != '')
    assert not both.any(), f"{int(both.sum())} pairs match a positive AND a negative rule - rules are inconsistent"
    rule = rule.where(prule == '', prule)
    label = np.where(prule != '', 1.0, np.where(rule != '', 0.0, np.nan))
    prov = np.where(prule != '', 'auto_positive', np.where(rule != '', 'auto_negative', 'needs_review'))
    cp = pd.concat([pd.DataFrame({
        'pair_id': pair_id(cand.key_a, cand.key_b).to_numpy(), 'pair_level': 'product',
        'key_a': cand.key_a.to_numpy(), 'key_b': cand.key_b.to_numpy(), 'i': cand.i.to_numpy(), 'j': cand.j.to_numpy(),
        'label': label, 'provenance': prov, 'rule': rule.to_numpy(), 'blocking_method': cand.method.to_numpy()}), Xc], axis=1)

    # ---- random non-candidate product pairs: rules only, otherwise dropped (never queued, never labelled)
    rng = np.random.default_rng(cfg.seed)
    ri, rj = rng.integers(0, len(rec), cfg.random_pairs), rng.integers(0, len(rec), cfg.random_pairs)
    # plus random pairs WITHIN the same normalised pack size (R3 can only fire there)
    pack_groups = [g for g in rec.groupby(rec.pack_size.map(B.normalize_name)).indices.values() if len(g) > 1]
    sizes = np.array([len(g) for g in pack_groups], float)
    gsel = rng.choice(len(pack_groups), size=cfg.random_same_pack_pairs, p=sizes ** 2 / (sizes ** 2).sum())
    si = np.array([rng.choice(pack_groups[g]) for g in gsel])
    sj = np.array([rng.choice(pack_groups[g]) for g in gsel])
    ri, rj = np.r_[ri, si], np.r_[rj, sj]
    keep = ri != rj
    ri, rj = np.minimum(ri, rj)[keep], np.maximum(ri, rj)[keep]
    in_cand = pd.MultiIndex.from_arrays([ri, rj]).isin(pd.MultiIndex.from_arrays([cand.i, cand.j]))
    ri, rj = ri[~in_cand], rj[~in_cand]
    rl, rr = pair_frames(rec, ri, rj)
    Xr = featurizer.transform(rl, rr)
    rrule = negative_rule(rl, rr, Xr, cfg)
    rnd = pd.concat([pd.DataFrame({
        'pair_id': pair_id(rec.canonical_product_key.to_numpy()[ri], rec.canonical_product_key.to_numpy()[rj]).to_numpy(),
        'pair_level': 'product', 'key_a': rec.canonical_product_key.to_numpy()[ri],
        'key_b': rec.canonical_product_key.to_numpy()[rj], 'i': ri, 'j': rj, 'label': 0.0,
        'provenance': 'auto_negative', 'rule': rrule.to_numpy(), 'blocking_method': 'random_pair'}), Xr], axis=1)
    rnd = rnd[rrule.to_numpy() != ''].drop_duplicates('pair_id')

    labels = pd.concat([pos, cp, rnd[~rnd.pair_id.isin(cp.pair_id)]], ignore_index=True)

    # ---- human labels override needs_review (never override auto rules silently: report conflicts)
    human = read_human_labels(queue_path, priority_path)
    if len(human):
        h = labels.pair_id.map(human.set_index('pair_id').label)
        conflict = h.notna() & labels.provenance.isin(['auto_negative', 'auto_positive']) & (h != labels.label)
        if conflict.any():
            print(f"WARNING: {int(conflict.sum())} human labels contradict auto rules - kept as human_reviewed")
        take = h.notna() & (labels.provenance.isin(['needs_review']) | conflict)
        labels.loc[take, 'label'] = h[take]
        labels.loc[take, 'provenance'] = 'human_reviewed'
        labels.loc[take, 'rule'] = 'human label in MATCH_REVIEW_QUEUE.csv'
    labels['data_status'] = 'REAL'
    labels['rep_observation_key_a'] = rec.rep_observation_key.to_numpy()[labels.i]
    labels['rep_observation_key_b'] = rec.rep_observation_key.to_numpy()[labels.j]
    return labels, rec, featurizer


def provenance_counts(labels: pd.DataFrame) -> dict:
    out = labels.groupby('provenance').size().reindex(PROVENANCES, fill_value=0).to_dict()
    out['by_rule'] = labels[labels.provenance.isin(['auto_positive', 'auto_negative'])].rule.value_counts().to_dict()
    out['trainable'] = int(labels.label.notna().sum())
    out['positives'] = int((labels.label == 1).sum())
    out['negatives'] = int((labels.label == 0).sum())
    return {k: (int(v) if isinstance(v, (int, np.integer)) else v) for k, v in out.items()}


def write_review_queue(labels: pd.DataFrame, rec: pd.DataFrame, path: Path = QUEUE_PATH) -> pd.DataFrame:
    """needs_review pairs -> CSV with an empty `label` column. Existing human labels and notes are preserved."""
    q = labels[labels.provenance == 'needs_review'].copy()
    r = rec.set_index('canonical_product_key')
    out = pd.DataFrame({
        'pair_id': q.pair_id.to_numpy(),
        'name_a': r.product_name.reindex(q.key_a).to_numpy(), 'name_b': r.product_name.reindex(q.key_b).to_numpy(),
        'pack_a': r.pack_size.reindex(q.key_a).to_numpy(), 'pack_b': r.pack_size.reindex(q.key_b).to_numpy(),
        'brand_a': r.brand.reindex(q.key_a).to_numpy(), 'brand_b': r.brand.reindex(q.key_b).to_numpy(),
        'category_a': r.category.reindex(q.key_a).to_numpy(), 'category_b': r.category.reindex(q.key_b).to_numpy(),
        'jw_base': q.jw_base.round(4).to_numpy(), 'ngram_cos_base': q.ngram_cos_base.round(4).to_numpy(),
        'ngram_cos_full': q.ngram_cos_full.round(4).to_numpy(), 'tokjac_base': q.tokjac_base.round(4).to_numpy(),
        'pack_exact': q.pack_exact.to_numpy(), 'blocking_method': q.blocking_method.to_numpy(),
        'key_a': q.key_a.to_numpy(), 'key_b': q.key_b.to_numpy(),
    })
    # names and packs identical once '**' markup, case and spacing are normalised: the only difference is formatting
    out.insert(1, 'formatting_only_difference', (
        (r.name_norm.reindex(q.key_a).to_numpy() == r.name_norm.reindex(q.key_b).to_numpy())
        & (r.pack_size.reindex(q.key_a).map(B.normalize_name).to_numpy()
           == r.pack_size.reindex(q.key_b).map(B.normalize_name).to_numpy())).astype(int))
    # review order: formatting-only first, then same pack, then most similar full names
    out = out.sort_values(['formatting_only_difference', 'pack_exact', 'ngram_cos_full', 'jw_base'],
                          ascending=False).reset_index(drop=True)
    out.insert(1, 'review_priority', np.arange(1, len(out) + 1))
    out['label'] = ''
    out['reviewer_note'] = ''
    if Path(path).exists():
        old = pd.read_csv(path, dtype=str).fillna('')
        keep_old = old[(old.label.str.strip() != '') | (old.reviewer_note.str.strip() != '')]
        out = out.set_index('pair_id')
        for col in ('label', 'reviewer_note'):
            out.loc[out.index.intersection(keep_old.pair_id), col] = keep_old.set_index('pair_id')[col]
        extra = keep_old[~keep_old.pair_id.isin(out.index)]   # labelled pairs no longer generated: never dropped
        out = pd.concat([out.reset_index(), extra], ignore_index=True)
    out.to_csv(path, index=False)
    return out


if __name__ == '__main__':
    import json
    labels, rec, _ = build()
    print(json.dumps(provenance_counts(labels), indent=1))
    q = write_review_queue(labels, rec)
    print(f"review queue: {len(q):,} pairs -> {QUEUE_PATH.relative_to(L.ROOT)}")
