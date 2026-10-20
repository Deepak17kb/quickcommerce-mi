"""
blocking.py — candidate-pair generation for the product matcher (model 1). REAL Blinkit rows only.

The unit is the catalog product (one canonical_product_key). Every catalog attribute a feature can use (name,
pack, brand, category) is identical across the listings of one key (verified in CANONICAL_KEY_AUDIT.csv), so
listing pairs of two different keys are exact duplicates of the key pair. Listing pairs of the SAME key are
generated separately (`same_key_listing_pairs`).

Methods (union of those enabled in config.yaml :: matching.blocking):
  char_ngram            TF-IDF character n-grams of the normalised name; top-k cosine neighbours above a threshold.
                        Finds 'Amla' ~ 'Amla (Aula)', typos, reordered words.
  token                 shared informative tokens (rare enough to be discriminative), minimum shared count and Jaccard.
  sorted_neighbourhood  neighbours within a window after sorting by normalised base name.

The old strategy (exact base name + pack size, 364 pairs) could not generate pairs whose names differ, which are
exactly the hard cases.
"""
from dataclasses import dataclass, field, fields
from pathlib import Path
import re

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer

import src.load as L

UNNAMED_PREFIX = 'UNNAMED LISTING'
_BRACKETS = re.compile(r'\s*[\(\[][^\)\]]*[\)\]]')
_MARKUP = re.compile(r'\*+')
_TOKEN = re.compile(r"[a-z0-9][a-z0-9'&.\-]*")


@dataclass
class BlockingConfig:
    methods: tuple = ('char_ngram', 'token')
    ngram_field: str = 'base'           # 'base' (brackets stripped) or 'full'
    ngram_min: int = 3
    ngram_max: int = 3
    ngram_top_k: int = 10
    ngram_min_cosine: float = 0.6
    token_max_df: int = 50              # ignore tokens appearing in more than this many products
    token_min_shared: int = 2
    token_min_jaccard: float = 0.5
    snm_window: int = 3
    chunk: int = 2000

    @classmethod
    def from_yaml(cls, path: Path | None = None, **overrides):
        import yaml
        path = path or (L.ROOT / 'config.yaml')
        raw = (yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}).get('matching', {}).get('blocking', {})
        raw.update(overrides)
        known = {f.name for f in fields(cls)}
        unknown = set(raw) - known
        if unknown:
            raise ValueError(f"unknown blocking config keys: {unknown}")
        if 'methods' in raw:
            raw['methods'] = tuple(raw['methods'])
        return cls(**raw)


# --------------------------------------------------------------------------- normalisation
def strip_markup(s: str) -> str:
    """Remove '**' markup and collapse whitespace. Case is kept (stricter than normalize_name)."""
    return re.sub(r'\s+', ' ', _MARKUP.sub('', str(s))).strip()


def normalize_name(s: str) -> str:
    s = _MARKUP.sub('', str(s)).lower()
    return re.sub(r'\s+', ' ', s).strip()


def base_name(s: str) -> str:
    """Normalised name with every (...) / [...] group removed: 'Amla (Aula)' -> 'amla'."""
    return re.sub(r'\s+', ' ', _BRACKETS.sub('', normalize_name(s))).strip()


def bracket_text(s: str) -> str:
    return ' '.join(m.strip('()[] ') for m in re.findall(r'[\(\[][^\)\]]*[\)\]]', normalize_name(s)))


def tokens(s: str) -> list[str]:
    return [t for t in _TOKEN.findall(s) if len(t) >= 2 and not t.replace('.', '').isdigit()]


# --------------------------------------------------------------------------- pack parsing
# The raw pack_qty column is NOT trusted by the matcher: it is 1.0 for every '**...**' pack string and sometimes
# stores the single-unit size of a multipack ('2 x 180 ml' -> 180). See docs/MATCHER_v1.md.
_UNIT = {
    'mg': ('mass', 0.001), 'g': ('mass', 1.0), 'gm': ('mass', 1.0), 'gms': ('mass', 1.0), 'kg': ('mass', 1000.0),
    'ml': ('volume', 1.0), 'l': ('volume', 1000.0), 'ltr': ('volume', 1000.0), 'litre': ('volume', 1000.0),
    'liter': ('volume', 1000.0),
}
_COUNT = ('pc', 'pcs', 'piece', 'pieces', 'set', 'sets', 'pack', 'packs', 'pair', 'pairs', 'pull', 'pulls',
          'wipe', 'wipes', 'tab', 'tabs', 'tablet', 'tablets', 'roll', 'rolls', 'sheet', 'sheets', 'sachet',
          'sachets', 'strip', 'strips', 'unit', 'units', 'bag', 'bags', 'capsule', 'capsules', 'pod', 'pods')
_PART = re.compile(r'^(?:(\d+(?:\.\d+)?)\s*x\s*)?(\d+(?:\.\d+)?)\s*([a-z]+)$')


def parse_pack(s) -> tuple[float, str]:
    """'2 x 180 ml' -> (360.0, 'volume'); '1 kg' -> (1000.0, 'mass'); '3 x 72 wipes' -> (216.0, 'count:wipe').
    Components joined by '+' are summed when they share a dimension. Returns (nan, '') when not parseable
    or when components mix dimensions."""
    txt = normalize_name(s)
    if not txt:
        return float('nan'), ''
    total, dim = 0.0, None
    for part in [p.strip() for p in txt.split('+')]:
        m = _PART.match(part)
        if not m:
            return float('nan'), ''
        mult, qty, unit = float(m.group(1) or 1), float(m.group(2)), m.group(3)
        if unit in _UNIT:
            d, f = _UNIT[unit]
        elif unit in _COUNT:
            d, f = 'count:' + unit.rstrip('s').replace('piece', 'pc').replace('tablet', 'tab'), 1.0
        else:
            return float('nan'), ''
        if dim is not None and d != dim:
            return float('nan'), ''
        dim, total = d, total + mult * qty * f
    return total, dim


# --------------------------------------------------------------------------- records
def real_listings() -> pd.DataFrame:
    """REAL Blinkit listings with a usable name and pack (the 4 unnamed listings are excluded)."""
    r = L.real_only(L.load_raw())
    assert r.data_status.eq('REAL').all()
    keep = ~r.product_name.astype(str).str.startswith(UNNAMED_PREFIX) & r.pack_size.notna()
    cols = ['observation_key', 'product_id', 'store_id', 'canonical_product_key', 'product_name', 'brand',
            'category', 'subcategory', 'pack_size', 'pack_qty', 'pack_unit', 'data_status']
    return r.loc[keep, cols].reset_index(drop=True)


def product_records(listings: pd.DataFrame) -> pd.DataFrame:
    """One row per canonical_product_key, with its listings."""
    g = listings.groupby('canonical_product_key', sort=True)
    rec = g.agg(product_name=('product_name', 'first'), brand=('brand', 'first'), category=('category', 'first'),
                subcategory=('subcategory', 'first'), pack_size=('pack_size', 'first'),
                pack_qty=('pack_qty', 'first'), pack_unit=('pack_unit', 'first'),
                n_listings=('product_id', 'size'), rep_observation_key=('observation_key', 'first'),
                data_status=('data_status', 'first')).reset_index()
    rec['name_norm'] = rec.product_name.map(normalize_name)
    rec['name_base'] = rec.product_name.map(base_name)
    rec['bracket'] = rec.product_name.map(bracket_text)
    parsed = rec.pack_size.map(parse_pack)
    rec['pack_qty_parsed'] = [p[0] for p in parsed]
    rec['pack_dim_parsed'] = [p[1] for p in parsed]
    return rec


# --------------------------------------------------------------------------- methods
def _pairs_frame(i, j, method):
    i, j = np.asarray(i), np.asarray(j)
    a, b = np.minimum(i, j), np.maximum(i, j)
    keep = a != b
    return pd.DataFrame({'i': a[keep], 'j': b[keep], 'method': method})


def char_ngram_pairs(rec, cfg: BlockingConfig):
    text = rec.name_base if cfg.ngram_field == 'base' else rec.name_norm
    X = TfidfVectorizer(analyzer='char_wb', ngram_range=(cfg.ngram_min, cfg.ngram_max)).fit_transform(text)
    n = X.shape[0]
    k = min(cfg.ngram_top_k + 1, n)
    I, J = [], []
    for s in range(0, n, cfg.chunk):
        S = (X[s:s + cfg.chunk] @ X.T).toarray()
        idx = np.argpartition(-S, k - 1, axis=1)[:, :k]
        rows = np.repeat(np.arange(s, s + S.shape[0]), k)
        cols = idx.ravel()
        ok = S[rows - s, cols] >= cfg.ngram_min_cosine
        I.append(rows[ok]); J.append(cols[ok])
    return _pairs_frame(np.concatenate(I), np.concatenate(J), 'char_ngram')


def token_pairs(rec, cfg: BlockingConfig):
    toks = rec.name_base.map(lambda s: set(tokens(s)))
    vocab = pd.Series([t for ts in toks for t in ts]).value_counts()
    vocab = vocab[vocab <= cfg.token_max_df]
    pos = {t: n for n, t in enumerate(vocab.index)}
    rows, cols = [], []
    for r_, ts in enumerate(toks):
        for t in ts:
            if t in pos:
                rows.append(r_); cols.append(pos[t])
    T = sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(rec), len(pos)))
    C = sparse.triu(T @ T.T, k=1).tocoo()
    ok = C.data >= cfg.token_min_shared
    i, j, shared = C.row[ok], C.col[ok], C.data[ok]
    size = np.array([len(ts) for ts in toks])
    jac = shared / (size[i] + size[j] - shared)
    keep = jac >= cfg.token_min_jaccard
    return _pairs_frame(i[keep], j[keep], 'token')


def sorted_neighbourhood_pairs(rec, cfg: BlockingConfig):
    order = np.argsort(rec.name_base.to_numpy(), kind='stable')
    I, J = [], []
    for w in range(1, cfg.snm_window + 1):
        I.append(order[:-w]); J.append(order[w:])
    return _pairs_frame(np.concatenate(I), np.concatenate(J), 'sorted_neighbourhood')


METHODS = {'char_ngram': char_ngram_pairs, 'token': token_pairs, 'sorted_neighbourhood': sorted_neighbourhood_pairs}


def candidate_pairs(rec: pd.DataFrame, cfg: BlockingConfig | None = None) -> pd.DataFrame:
    """Candidate PRODUCT pairs (different canonical keys), i < j, with the methods that proposed each."""
    cfg = cfg or BlockingConfig.from_yaml()
    unknown = set(cfg.methods) - set(METHODS)
    if unknown:
        raise ValueError(f"unknown blocking methods {unknown}")
    parts = [METHODS[m](rec, cfg) for m in cfg.methods]
    allp = pd.concat(parts, ignore_index=True)
    out = (allp.groupby(['i', 'j']).method.agg(lambda s: '+'.join(sorted(set(s)))).reset_index())
    out['key_a'] = rec.canonical_product_key.to_numpy()[out.i]
    out['key_b'] = rec.canonical_product_key.to_numpy()[out.j]
    return out


def same_key_listing_pairs(listings: pd.DataFrame) -> pd.DataFrame:
    """All listing pairs that share a canonical key (identical catalog attributes)."""
    rows = []
    for key, g in listings.groupby('canonical_product_key', sort=False):
        ids = g.product_id.to_numpy()
        if len(ids) < 2:
            continue
        a, b = np.triu_indices(len(ids), 1)
        rows.append(pd.DataFrame({'product_id_a': ids[a], 'product_id_b': ids[b], 'canonical_product_key': key}))
    return pd.concat(rows, ignore_index=True)


# --------------------------------------------------------------------------- evaluation of blocking
def audit_pairs() -> pd.DataFrame:
    """Listing pairs inside the verified CANONICAL_KEY_AUDIT groups (SAME_SKU_MULTIPLE_LISTINGS)."""
    a = pd.read_csv(L.REF / 'CANONICAL_KEY_AUDIT.csv')
    a = a[a.verdict == 'SAME_SKU_MULTIPLE_LISTINGS']
    rows = []
    for r in a.itertuples():
        ids = sorted(x.strip() for x in r.product_ids.split(','))
        for x in range(len(ids)):
            for y in range(x + 1, len(ids)):
                rows.append((ids[x], ids[y], r.canonical_product_key, r.store_id, r.snapshot_id))
    return pd.DataFrame(rows, columns=['product_id_a', 'product_id_b', 'canonical_product_key', 'store_id', 'snapshot_id'])


def audit_recall(listings, cand, audit=None) -> dict:
    """Share of verified audit listing pairs present among candidates (same-key pairs + product candidate pairs)."""
    audit = audit_pairs() if audit is None else audit
    key_of = listings.set_index('product_id').canonical_product_key
    ka, kb = audit.product_id_a.map(key_of), audit.product_id_b.map(key_of)
    missing_listing = ka.isna() | kb.isna()
    same_key = ka == kb
    cand_set = set(zip(cand.key_a, cand.key_b)) | set(zip(cand.key_b, cand.key_a))
    cross = [(x, y) in cand_set for x, y in zip(ka, kb)]
    found = (same_key | pd.Series(cross, index=audit.index)) & ~missing_listing
    return {'audit_pairs': len(audit), 'found': int(found.sum()), 'recall': float(found.mean()),
            'pairs_with_listing_not_in_matching_set': int(missing_listing.sum()),
            'audit_pairs_with_identical_name_and_pack': int(same_key.sum())}


def old_strategy_recall(rec, cand) -> dict:
    """The widened blocking must be a superset of the old exact base-name + pack blocking."""
    old = rec.assign(b=rec.name_base + '|' + rec.pack_size.astype(str)).groupby('b').canonical_product_key.agg(list)
    pairs = {(x, y) for keys in old if len(keys) > 1 for n, x in enumerate(keys) for y in keys[n + 1:]}
    cand_set = set(zip(cand.key_a, cand.key_b)) | set(zip(cand.key_b, cand.key_a))
    hit = sum((x, y) in cand_set for x, y in pairs)
    return {'old_strategy_pairs': len(pairs), 'found': hit, 'recall': hit / max(len(pairs), 1)}


PERTURBATIONS = ('strip_brackets', 'add_alias_bracket', 'markup', 'drop_last_token', 'swap_tokens', 'typo')


def perturbation_recall(rec, cfg: BlockingConfig | None = None, n: int = 1500, seed: int = 0) -> dict:
    """BLOCKING STRESS TEST ONLY — never used as training labels.

    Takes n real product names, applies one realistic name variation each (strip bracket text, add an alias in
    brackets, ** markup, drop the last word, swap two words, one-character typo), adds the variants as extra
    records, re-runs blocking and reports how often the (original, variant) pair is generated. This is the only
    way to measure blocking recall on DIFFERING names without human labels: the audit pairs all have identical names.
    """
    cfg = cfg or BlockingConfig.from_yaml()
    rng = np.random.default_rng(seed)
    base = rec.sample(n=min(n, len(rec)), random_state=seed).reset_index(drop=True)
    kinds = rng.choice(PERTURBATIONS, size=len(base))

    def perturb(name, kind):
        words = normalize_name(name).split()
        if kind == 'strip_brackets':
            return base_name(name) if bracket_text(name) else base_name(name) + ' (pack)'
        if kind == 'add_alias_bracket':
            return normalize_name(name) + ' (desi)'
        if kind == 'markup':
            return '**' + str(name) + '**'
        if kind == 'drop_last_token' and len(words) > 2:
            return ' '.join(words[:-1])
        if kind == 'swap_tokens' and len(words) > 2:
            w = list(words); k = int(rng.integers(0, len(w) - 1)); w[k], w[k + 1] = w[k + 1], w[k]
            return ' '.join(w)
        s = normalize_name(name)
        if len(s) > 4:
            k = int(rng.integers(1, len(s) - 1))
            return s[:k] + s[k + 1] + s[k] + s[k + 2:]
        return s + 'x'

    var = base.copy()
    var['product_name'] = [perturb(nm, kd) for nm, kd in zip(base.product_name, kinds)]
    var['canonical_product_key'] = '__variant__' + base.canonical_product_key
    var['name_norm'] = var.product_name.map(normalize_name)
    var['name_base'] = var.product_name.map(base_name)
    var['bracket'] = var.product_name.map(bracket_text)
    both = pd.concat([rec, var], ignore_index=True)
    cand = candidate_pairs(both, cfg)
    cand_set = set(zip(cand.key_a, cand.key_b)) | set(zip(cand.key_b, cand.key_a))
    hit = np.array([(k, '__variant__' + k) in cand_set for k in base.canonical_product_key])
    by_kind = pd.Series(hit).groupby(kinds).mean().round(4).to_dict()
    return {'variants': len(base), 'recall': float(hit.mean()), 'recall_by_variation': by_kind}


def report(cfg: BlockingConfig | None = None, stress: bool = True) -> dict:
    cfg = cfg or BlockingConfig.from_yaml()
    listings = real_listings()
    rec = product_records(listings)
    cand = candidate_pairs(rec, cfg)
    same = same_key_listing_pairs(listings)
    n_list = rec.set_index('canonical_product_key').n_listings
    listing_equiv = int((n_list.reindex(cand.key_a).to_numpy() * n_list.reindex(cand.key_b).to_numpy()).sum())
    out = {
        'config': cfg.__dict__,
        'real_listings_used': len(listings),
        'products': len(rec),
        'candidate_product_pairs': len(cand),
        'candidate_pairs_by_method': cand.method.value_counts().to_dict(),
        'candidate_listing_pairs_equivalent': listing_equiv + len(same),
        'same_key_listing_pairs': len(same),
        'audit_recall': audit_recall(listings, cand),
        'old_strategy_recall': old_strategy_recall(rec, cand),
    }
    if stress:
        out['perturbation_stress_recall'] = perturbation_recall(rec, cfg)
    return out


if __name__ == '__main__':
    import json
    print(json.dumps(report(), indent=1, default=str))
