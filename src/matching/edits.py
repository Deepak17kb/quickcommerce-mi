"""
edits.py — constructed edits of REAL catalog records, for the product matcher v2.

Each edit changes a real name or pack in a way whose effect on product identity is known BY CONSTRUCTION. v1 used nine
of them only to test the saved model (behaviour.py). v2 also TRAINS on constructed edits, which is a new label source.
It was an open decision for the owner (asked 2026-09-25); the owner's reply of 2026-10-13 to the list of open items,
"whatever is open, start finishing it", was taken as the go-ahead. v2 lives beside v1 and replaces nothing, so the
decision can be reversed by deleting it. The rule that bounds the label source:

    an edit is used only when its effect on identity does not depend on a judgement call.

That is why some plausible edits are absent. Reordering words is not here ('Milk Chocolate' / 'Chocolate Milk'), nor is
adding a variant bracket to one side ('Goggles' / 'Goggles (Black)': the first listing may or may not be the black one).
Pairs like those stay with human review; train_v2 reports them as out of support.

Every constructed pair is labelled SYNTHETIC (the edited text was never observed) with
label_source = CONSTRUCTED_EDIT. It is never a human label and never tier 1.

SAME product (identity-preserving)
  markup, case, punctuation, typo, alias          as in behaviour.py (one implementation, imported from there)
  typo_drop / typo_double                         one inner letter dropped / doubled in a word of 5+ letters
  spacing                                         '250 ml' <-> '250ml', 'Sugar-Free' -> 'SugarFree'
  unit_spelling                                   pack unit respelled: g <-> gm, l <-> ltr <-> litre, pc <-> piece
  and_amp                                         '&' <-> 'and'
  pack_format                                     same quantity in another unit: '1 kg' <-> '1000 g', '500 ml' <-> '0.5 l'

DIFFERENT product (identity-changing)
  pack, number, colour                            as in behaviour.py
  pack_scale                                      pack quantity times 0.5 / 1.5 / 3 / 5
  multipack                                       '180 ml' -> '2 x 180 ml'
  number_shift                                    a number in the name moved by 1, 2, 5 or 10
  size / flavour / audience                       a variant word swapped for another of its lexicon
  word_swap                                       one content word replaced by a random word from another catalog name
"""
import re

import numpy as np

from src.matching.behaviour import edit as _v1_edit
from src.matching.diff_features import AUDIENCE, COLOURS, FLAVOURS, SIZES

SAME = ('markup', 'case', 'punctuation', 'typo', 'typo_drop', 'typo_double', 'spacing', 'unit_spelling', 'and_amp',
        'alias', 'pack_format')
DIFFERENT = ('pack', 'pack_scale', 'multipack', 'number', 'number_shift', 'colour', 'size', 'flavour', 'audience',
             'word_swap')
V1_KINDS = ('control', 'markup', 'case', 'punctuation', 'typo', 'alias', 'pack', 'number', 'colour')
KINDS = SAME + DIFFERENT
EXPECTED = {**{k: 'same' for k in SAME + ('control',)}, **{k: 'different' for k in DIFFERENT}}

_NUM = re.compile(r'(?<![\d.])(\d+)(?![\d.])')
_PACK_NUM = re.compile(r'(\d+(?:\.\d+)?)')
_NAME_QTY = re.compile(r'(\d+(?:\.\d+)?) (ml|g|gm|kg|l|ltr|pcs|pc)\b', re.I)
_NAME_GLUED = re.compile(r'(\d+(?:\.\d+)?)(ml|g|gm|kg|l|ltr|pcs|pc)\b', re.I)
_HYPHEN = re.compile(r'([A-Za-z]{3,})-([A-Za-z]{3,})')
_SIMPLE_PACK = re.compile(r'^(\d+(?:\.\d+)?)\s*(kg|g|l|ltr|ml)$', re.I)
_PACK_UNIT = re.compile(r'\b(gm|g|ltr|litre|l|pcs|pc)$', re.I)
_RESPELL = {'g': 'gm', 'gm': 'g', 'l': 'ltr', 'ltr': 'litre', 'litre': 'l', 'pc': 'piece', 'pcs': 'pieces'}
_CONVERT = {'kg': ('g', 1000.0), 'g': ('kg', 0.001), 'l': ('ml', 1000.0), 'ltr': ('ml', 1000.0), 'ml': ('l', 0.001)}


def _fmt(x: float) -> str:
    return str(int(round(x))) if abs(x - round(x)) < 1e-9 else f'{x:g}'


def _swap_word(name: str, lexicon, rng):
    pat = re.compile(r'\b(' + '|'.join(lexicon) + r')\b', re.I)
    m = pat.search(name)
    if not m:
        return None
    others = [w for w in lexicon if w != m.group(1).lower()]
    new = others[int(rng.integers(len(others)))]
    new = new.upper() if m.group(1).isupper() else new.capitalize() if m.group(1)[0].isupper() else new
    return name[:m.start()] + new + name[m.end():]


def _long_word(name: str, rng):
    words = name.split()
    idx = [i for i, w in enumerate(words) if len(w) >= 5 and w.isalpha()]
    if not idx:
        return None
    i = idx[int(rng.integers(len(idx)))]
    return words, i, int(rng.integers(1, len(words[i]) - 1))


def edit(name: str, pack: str, kind: str, rng, vocabulary=None) -> tuple[str, str] | None:
    """(edited name, edited pack), or None when the edit does not apply. `vocabulary` (catalog content words) is only
    needed for word_swap."""
    if kind == 'punctuation' and re.search(r'\d\.\d', name):
        return None                 # the v1 edit would turn '3.7' into '3 7': that changes a number, so it is not used
    if kind in V1_KINDS:
        return _v1_edit(name, pack, kind, rng)
    if kind in ('typo_drop', 'typo_double'):
        got = _long_word(name, rng)
        if got is None:
            return None
        words, i, k = got
        w = words[i]
        words[i] = (w[:k] + w[k + 1:]) if kind == 'typo_drop' else (w[:k] + w[k] + w[k:])
        return ' '.join(words), pack
    if kind == 'spacing':
        m = _NAME_QTY.search(name)
        if m:
            return name[:m.start()] + m.group(1) + m.group(2) + name[m.end():], pack
        m = _NAME_GLUED.search(name)
        if m:
            return name[:m.start()] + m.group(1) + ' ' + m.group(2) + name[m.end():], pack
        m = _HYPHEN.search(name)
        if m:
            return name[:m.start()] + m.group(1) + m.group(2) + name[m.end():], pack
        return None
    if kind == 'unit_spelling':
        m = _PACK_UNIT.search(str(pack).replace('*', '').strip())
        if not m or m.group(1).lower() not in _RESPELL:
            return None
        p = str(pack).replace('*', '').strip()
        return name, p[:m.start()] + _RESPELL[m.group(1).lower()] + p[m.end():]
    if kind == 'and_amp':
        if ' & ' in name:
            return name.replace(' & ', ' and ', 1), pack
        if re.search(r' and ', name, re.I):
            return re.sub(r' and ', ' & ', name, count=1, flags=re.I), pack
        return None
    if kind == 'pack_format':
        m = _SIMPLE_PACK.match(str(pack).replace('*', '').strip())
        if not m:
            return None
        unit, factor = _CONVERT[m.group(2).lower()]
        q = float(m.group(1)) * factor
        if q < 0.05 or (unit in ('kg', 'l') and q < 0.1):
            return None
        return name, f'{_fmt(q)} {unit}'
    if kind == 'pack_scale':
        m = _PACK_NUM.search(str(pack))
        if not m or float(m.group(1)) <= 0:
            return None
        f = (0.5, 1.5, 3.0, 5.0)[int(rng.integers(4))]
        return name, pack[:m.start()] + _fmt(float(m.group(1)) * f) + pack[m.end():]
    if kind == 'multipack':
        p = str(pack).replace('*', '').strip()
        if 'x' in p.lower() or '+' in p or not _PACK_NUM.match(p):
            return None
        return name, f'{int(rng.integers(2, 7))} x {p}'
    if kind == 'number_shift':
        m = _NUM.search(name)
        if not m:
            return None
        n = int(m.group(1)) + (1, 2, 5, 10)[int(rng.integers(4))]
        return name[:m.start()] + str(n) + name[m.end():], pack
    if kind == 'size':
        new = _swap_word(name, SIZES, rng)
        return (new, pack) if new else None
    if kind == 'flavour':
        new = _swap_word(name, FLAVOURS, rng)
        return (new, pack) if new else None
    if kind == 'audience':
        new = _swap_word(name, AUDIENCE, rng)
        return (new, pack) if new else None
    if kind == 'word_swap':
        if vocabulary is None or len(vocabulary) == 0:
            raise ValueError('word_swap needs the catalog vocabulary')
        words = re.sub(r'[\(\[][^\)\]]*[\)\]]', ' ', name).split()
        idx = [i for i, w in enumerate(words) if i > 0 and len(w) >= 4 and w.isalpha()]
        if not idx:
            return None
        old = words[idx[int(rng.integers(len(idx)))]]
        for _ in range(20):
            new = str(vocabulary[int(rng.integers(len(vocabulary)))])
            if new.lower() != old.lower() and new.lower() not in name.lower() and abs(len(new) - len(old)) >= 2:
                break
        else:
            return None
        new = new.capitalize() if old[0].isupper() else new.lower()
        return re.sub(r'\b' + re.escape(old) + r'\b', new, name, count=1), pack
    raise ValueError(kind)


def catalog_vocabulary(product_names, min_len: int = 4, min_df: int = 5) -> np.ndarray:
    """Content words that appear in at least min_df catalog names: the pool word_swap draws from."""
    from collections import Counter
    df = Counter()
    for n in product_names:
        df.update({w.lower() for w in re.sub(r'[^A-Za-z ]', ' ', str(n)).split() if len(w) >= min_len})
    return np.array(sorted(w for w, c in df.items() if c >= min_df))


def build(rec, kinds=KINDS, per_kind: int | None = None, seed: int = 0):
    """Constructed pairs: every record that an edit applies to, up to per_kind records per edit kind.
    Returns a frame with the original record's key and the edited name / pack."""
    import pandas as pd
    rng = np.random.default_rng(seed)
    vocab = catalog_vocabulary(rec.product_name)
    order = rec.sample(frac=1, random_state=seed).reset_index(drop=True)
    rows = []
    for kind in kinds:
        got = 0
        for r in order.itertuples():
            out = edit(str(r.product_name), str(r.pack_size), kind, rng, vocab)
            if out is None or (out[0] == str(r.product_name) and out[1] == str(r.pack_size) and kind != 'control'):
                continue
            rows.append({'edit': kind, 'expected': EXPECTED[kind], 'canonical_product_key': r.canonical_product_key,
                         'observation_key': r.rep_observation_key, 'name_edited': out[0], 'pack_edited': out[1]})
            got += 1
            if per_kind and got >= per_kind:
                break
    return pd.DataFrame(rows)
