"""
diff_features.py — difference-aware pair features for the product matcher v2.

v1's features say HOW MUCH two names differ (Jaro-Winkler, n-gram cosine, token Jaccard). The behavioural test showed
why that cannot work: a typo and a colour swap change a name by about the same amount, yet one keeps the product and the
other changes it (docs/MATCHER_v1.md, AUC 0.42). These features say WHAT differs.

How a pair is read
  1. Both names are tokenised after a stricter normalisation than v1's: markup and case removed, '&' read as 'and',
     punctuation dropped, glued number-units split ('250ml' -> '250', 'ml'), unit spellings unified ('gm' -> 'g').
     Bracket text is kept, and each token remembers whether it sat inside a bracket.
  2. Tokens the two names share are cancelled (as multisets, so word order does not matter here).
  3. Of what is left, a token on one side is paired with a token on the other when they are one edit apart
     (Damerau-Levenshtein) and at least one of them is rare in the catalog: that is what a typo looks like. Two common
     words one edit apart ('mint' / 'mini') are NOT a typo; they stay as a substitution and are counted separately.
  4. What still remains is the residual. Residual on both sides is a SUBSTITUTION (the names contrast); residual on one
     side only is an INSERTION (one name says more).

Features (all prefixed d_, all computed from the two names and packs only)
  d_nothing            nothing differs after steps 1-3 and the word order is the same
  d_order_changed      same tokens, different order
  d_typo_like          token pairs matched as typos in step 3
  d_near_word_subst    one-edit pairs where both tokens are common catalog words
  d_spacing_only       the residuals are equal once spaces are removed ('sugar free' / 'sugarfree')
  d_subst              substituted tokens: min(residual left, residual right)
  d_insert             inserted tokens: |residual left - residual right|
  d_alpha_subst        substituted tokens that are words, not numbers
  d_num_subst          the two residuals both hold numbers (a spec or size contrast)
  d_num_insert         a number is left on one side only
  d_res_base_count     residual tokens outside brackets
  d_res_bracket_share  share of residual tokens that sat inside a bracket
  d_lex_contrast       variant lexicons (colour, size, flavour, audience) with a word left on BOTH sides
  d_lex_insert         a variant-lexicon word left on one side only
  d_res_idf_max        rarity of the rarest residual token (IDF over the REAL catalog names)
  d_res_char_share     residual characters / all characters
  d_pack_equal_qty     both packs parse to the same quantity and dimension, whatever the spelling ('1 kg' / '1000 g')
  d_pack_unparsed      either pack does not parse

`signature` condenses a pair's difference into a small tuple. train_v2 counts signatures in the training pairs, so a
pair whose kind of difference was never taught can be reported as OUT OF SUPPORT instead of being scored with false
confidence.
"""
import math
import re
from collections import Counter

import numpy as np
import pandas as pd
from rapidfuzz.distance import DamerauLevenshtein

from src.matching.blocking import parse_pack

DIFF_FEATS = ['d_nothing', 'd_order_changed', 'd_typo_like', 'd_near_word_subst', 'd_spacing_only', 'd_subst',
              'd_insert', 'd_alpha_subst', 'd_num_subst', 'd_num_insert', 'd_res_base_count', 'd_res_bracket_share',
              'd_lex_contrast', 'd_lex_insert', 'd_res_idf_max', 'd_res_char_share', 'd_pack_equal_qty',
              'd_pack_unparsed']

# variant lexicons: a word from one of these, swapped for another of the same list, names a different product
COLOURS = ('black', 'white', 'blue', 'red', 'green', 'grey', 'pink', 'yellow', 'brown', 'purple', 'orange', 'cream')
SIZES = ('small', 'medium', 'large', 'mini', 'jumbo', 'xl', 'xxl')
FLAVOURS = ('vanilla', 'chocolate', 'strawberry', 'mango', 'lemon', 'mint', 'rose', 'lavender', 'coffee',
            'butterscotch', 'pineapple', 'banana', 'apple', 'grape', 'litchi', 'guava', 'coconut', 'jasmine',
            'sandalwood', 'neem', 'tomato', 'masala', 'onion', 'cheese', 'pudina', 'elaichi', 'kesar', 'ginger',
            'garlic', 'honey', 'caramel', 'hazelnut', 'almond', 'peach', 'blueberry', 'cola', 'jeera', 'tulsi',
            'charcoal', 'saffron')
AUDIENCE = ('men', 'women', 'boys', 'girls', 'kids')
LEXICONS = {'colour': frozenset(COLOURS), 'size': frozenset(SIZES), 'flavour': frozenset(FLAVOURS),
            'audience': frozenset(AUDIENCE)}

UNIT_CANON = {'gm': 'g', 'gms': 'g', 'gram': 'g', 'grams': 'g', 'kgs': 'kg', 'ltr': 'l', 'ltrs': 'l', 'litre': 'l',
              'litres': 'l', 'liter': 'l', 'liters': 'l', 'mls': 'ml', 'pcs': 'pc', 'piece': 'pc', 'pieces': 'pc'}
COMMON_DF = 3                      # a token in at least this many catalog names counts as a common word
TYPO_MIN_LEN = 4

_MARKUP = re.compile(r'\*+')
_BRACKET = re.compile(r'[\(\[]([^\)\]]*)[\)\]]')
_DECIMAL = re.compile(r'(?<=\d)\.(?=\d)')
_APOS = re.compile(r"['’`]")
_PUNCT = re.compile(r'[^a-z0-9§\s]')
_GLUE_A = re.compile(r'(\d)([a-z])')
_GLUE_B = re.compile(r'([a-z])(\d)')
_NUM = re.compile(r'\d+(?:\.\d+)?')


def _segment_tokens(text: str) -> list[str]:
    s = text.replace('&', ' and ')
    s = _APOS.sub('', _DECIMAL.sub('§', s))
    s = _PUNCT.sub(' ', s)
    s = _GLUE_B.sub(r'\1 \2', _GLUE_A.sub(r'\1 \2', s))
    return [UNIT_CANON.get(t, t) for t in s.replace('§', '.').split()]


def name_tokens(name) -> list[tuple[str, bool]]:
    """[(token, inside_bracket)] in reading order."""
    s = _MARKUP.sub('', str(name)).lower()
    out, pos = [], 0
    for m in _BRACKET.finditer(s):
        out += [(t, False) for t in _segment_tokens(s[pos:m.start()])]
        out += [(t, True) for t in _segment_tokens(m.group(1))]
        pos = m.end()
    return out + [(t, False) for t in _segment_tokens(s[pos:])]


def is_number(tok: str) -> bool:
    return bool(_NUM.fullmatch(tok))


def _residual(a: list, b: list) -> tuple[list, list]:
    """Tokens of a not cancelled by b, and of b not cancelled by a (multiset difference, bracket flag kept)."""
    ca, cb = Counter(t for t, _ in a), Counter(t for t, _ in b)
    shared = ca & cb

    def left(seq):
        need, keep = dict(shared), []
        for t, br in seq:
            if need.get(t, 0) > 0:
                need[t] -= 1
            else:
                keep.append((t, br))
        return keep
    return left(a), left(b)


class DiffFeaturizer:
    """Fit once on the REAL catalog names (token document frequencies), then describe any aligned record pairs."""

    def __init__(self):
        self.df_ = None
        self.n_docs_ = 0

    def fit(self, product_names) -> 'DiffFeaturizer':
        df = Counter()
        n = 0
        for name in product_names:
            df.update({t for t, _ in name_tokens(name)})
            n += 1
        self.df_, self.n_docs_ = df, n
        return self

    def idf(self, tok: str) -> float:
        return math.log((self.n_docs_ + 1) / (self.df_.get(tok, 0) + 1)) + 1.0

    def describe(self, name_a, name_b) -> dict:
        ta, tb = name_tokens(name_a), name_tokens(name_b)
        ra, rb = _residual(ta, tb)
        typo = near = 0
        used = set()
        keep_a = []
        for t, br in ra:
            hit = None
            if not is_number(t) and len(t) >= TYPO_MIN_LEN:
                for j, (u, _) in enumerate(rb):
                    if j in used or is_number(u) or len(u) < TYPO_MIN_LEN:
                        continue
                    if DamerauLevenshtein.distance(t, u, score_cutoff=1) <= 1:
                        hit = j
                        break
            if hit is None:
                keep_a.append((t, br))
                continue
            u = rb[hit][0]
            if self.df_.get(t, 0) >= COMMON_DF and self.df_.get(u, 0) >= COMMON_DF:
                near += 1                              # two real words one edit apart: a substitution, not a typo
                keep_a.append((t, br))
            else:
                typo += 1
                used.add(hit)
        ra = keep_a
        rb = [x for j, x in enumerate(rb) if j not in used]
        spacing = bool(ra and rb) and ''.join(t for t, _ in ra) == ''.join(t for t, _ in rb)
        if spacing:
            ra, rb = [], []
        res = ra + rb
        na, nb = len(ra), len(rb)
        num_a, num_b = [t for t, _ in ra if is_number(t)], [t for t, _ in rb if is_number(t)]
        wa, wb = {t for t, _ in ra}, {t for t, _ in rb}
        lex_contrast = sum(1 for L_ in LEXICONS.values() if wa & L_ and wb & L_)
        lex_insert = int(any(bool(wa & L_) != bool(wb & L_) for L_ in LEXICONS.values()))
        chars = sum(len(t) for t, _ in ta) + sum(len(t) for t, _ in tb)
        same_seq = [t for t, _ in ta] == [t for t, _ in tb]
        return {
            'd_nothing': int(not res and not typo and same_seq),
            'd_order_changed': int(not res and not typo and not same_seq and not spacing),
            'd_typo_like': typo, 'd_near_word_subst': near, 'd_spacing_only': int(spacing),
            'd_subst': min(na, nb), 'd_insert': abs(na - nb),
            'd_alpha_subst': min(na - len(num_a), nb - len(num_b)),
            'd_num_subst': int(bool(num_a) and bool(num_b)),
            'd_num_insert': int(bool(num_a) != bool(num_b)),
            'd_res_base_count': sum(1 for _, br in res if not br),
            'd_res_bracket_share': (sum(1 for _, br in res if br) / len(res)) if res else 0.0,
            'd_lex_contrast': lex_contrast, 'd_lex_insert': lex_insert,
            'd_res_idf_max': max((self.idf(t) for t, _ in res), default=0.0),
            'd_res_char_share': (sum(len(t) for t, _ in res) / chars) if chars else 0.0,
        }

    def transform(self, left: pd.DataFrame, right: pd.DataFrame) -> pd.DataFrame:
        if self.df_ is None:
            raise RuntimeError('DiffFeaturizer.fit must be called first')
        if len(left) != len(right):
            raise ValueError('left and right must be aligned and the same length')
        la, ra = left.reset_index(drop=True), right.reset_index(drop=True)
        X = pd.DataFrame([self.describe(a, b) for a, b in zip(la.product_name, ra.product_name)], index=la.index)
        pa, pb = la.pack_size.map(parse_pack), ra.pack_size.map(parse_pack)
        ok = np.array([bool(x[1]) and bool(y[1]) for x, y in zip(pa, pb)])
        eq = np.array([x[1] == y[1] and bool(x[1]) and math.isclose(x[0], y[0], rel_tol=1e-9) for x, y in zip(pa, pb)])
        X['d_pack_equal_qty'] = (ok & eq).astype(int)
        X['d_pack_unparsed'] = (~ok).astype(int)
        return X[DIFF_FEATS]


def signature(X: pd.DataFrame) -> pd.Series:
    """The kind of difference, as a short string. Pairs with the same signature differ in the same way."""
    pack = np.where(X.pack_exact == 1, 'pack=', np.where(X.d_pack_equal_qty == 1, 'pack~',
                    np.where(X.d_pack_unparsed == 1, 'pack?', 'pack!')))
    parts = [np.where(X.d_nothing == 1, 'none', ''), np.where(X.d_order_changed == 1, 'order', ''),
             np.where(X.d_typo_like > 0, 'typo', ''), np.where(X.d_near_word_subst > 0, 'nearword', ''),
             np.where(X.d_spacing_only == 1, 'spacing', ''),
             np.where(X.d_subst > 1, 'subst2+', np.where(X.d_subst == 1, 'subst1', '')),
             np.where(X.d_insert > 1, 'ins2+', np.where(X.d_insert == 1, 'ins1', '')),
             np.where((X.d_num_subst == 1) | (X.d_num_insert == 1), 'num', ''),
             np.where(X.d_lex_contrast > 0, 'lexswap', ''), np.where(X.d_lex_insert == 1, 'lexins', ''),
             np.where((X.d_res_bracket_share == 1), 'inbracket', '')]
    sig = pd.Series(pack, index=X.index, dtype=object)
    for p in parts:
        sig = sig + np.where(p != '', '|', '') + p
    return sig
