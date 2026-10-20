"""
features.py — pairwise similarity features for the product matcher (model 1).

Input: two aligned frames of product records (left row n is compared with right row n), each with
product_name, pack_size, brand, category, subcategory. Pack quantity and dimension are parsed from the pack_size
text by src.matching.blocking.parse_pack; the raw pack_qty / pack_unit columns are not used (they are wrong for
every '**...**' pack and for some multipacks). Output: a frame of feature
columns only. The column list used for training is `FEATS` in src/matching/train.py; every feature set is
passed through src.load.check_feature_set, so no identifier or target column can enter it.

Features
  jw_full / jw_base               Jaro-Winkler similarity, full normalised name / name with bracket text removed
  tokjac_full / tokjac_base       token Jaccard
  ngram_cos_full / ngram_cos_base char 3-gram TF-IDF cosine (vectoriser fitted on the REAL catalog names)
  token_set_base                  token-set ratio (order-insensitive)
  bracket_both / bracket_one      both / exactly one name carries bracket text
  bracket_jac                     token Jaccard of the bracket texts (0 when either has none)
  len_ratio_base                  shorter / longer base-name length
  pack_exact                      normalised pack_size strings equal
  pack_qty_ratio                  smaller / larger parsed base-unit quantity (NaN when not comparable)
  unit_compatible                 same parsed pack dimension (mass / volume / count:<unit>)
  brand_match / brand_known_both  brands equal (case-insensitive) / neither is UNBRANDED
  category_match / subcategory_match

Brands come from the v14 extraction, which has known errors (data/reference/BRAND_REVIEW.csv). With the
current blocking brand is nearly constant within candidate pairs, so it carries little weight today.
"""
import numpy as np
import pandas as pd
from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler
from sklearn.feature_extraction.text import TfidfVectorizer

from src.matching.blocking import base_name, bracket_text, normalize_name, parse_pack, tokens


def _jac(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a or b) else 0.0


class PairFeaturizer:
    """Fit once on the REAL catalog names, then featurise any aligned record pairs."""

    def __init__(self, ngram_min: int = 3, ngram_max: int = 3):
        self.ngram = (ngram_min, ngram_max)
        self.vec_full = None
        self.vec_base = None

    def fit(self, product_names) -> 'PairFeaturizer':
        names = pd.Series(product_names).astype(str)
        self.vec_full = TfidfVectorizer(analyzer='char_wb', ngram_range=self.ngram).fit(names.map(normalize_name))
        self.vec_base = TfidfVectorizer(analyzer='char_wb', ngram_range=self.ngram).fit(names.map(base_name))
        return self

    @staticmethod
    def _cos(vec, a, b):
        A, B = vec.transform(a), vec.transform(b)
        return np.asarray(A.multiply(B).sum(axis=1)).ravel()

    def transform(self, left: pd.DataFrame, right: pd.DataFrame) -> pd.DataFrame:
        if self.vec_full is None:
            raise RuntimeError("PairFeaturizer.fit must be called first")
        if len(left) != len(right):
            raise ValueError("left and right must be aligned and the same length")
        la, ra = left.reset_index(drop=True), right.reset_index(drop=True)
        fa, fb = la.product_name.map(normalize_name), ra.product_name.map(normalize_name)
        ba, bb = la.product_name.map(base_name), ra.product_name.map(base_name)
        ka, kb = la.product_name.map(bracket_text), ra.product_name.map(bracket_text)
        tfa, tfb = fa.map(lambda s: set(tokens(s))), fb.map(lambda s: set(tokens(s)))
        tba, tbb = ba.map(lambda s: set(tokens(s))), bb.map(lambda s: set(tokens(s)))

        X = pd.DataFrame(index=la.index)
        X['jw_full'] = [JaroWinkler.normalized_similarity(x, y) for x, y in zip(fa, fb)]
        X['jw_base'] = [JaroWinkler.normalized_similarity(x, y) for x, y in zip(ba, bb)]
        X['tokjac_full'] = [_jac(x, y) for x, y in zip(tfa, tfb)]
        X['tokjac_base'] = [_jac(x, y) for x, y in zip(tba, tbb)]
        X['ngram_cos_full'] = self._cos(self.vec_full, fa, fb)
        X['ngram_cos_base'] = self._cos(self.vec_base, ba, bb)
        X['token_set_base'] = [fuzz.token_set_ratio(x, y) / 100.0 for x, y in zip(ba, bb)]
        has_a, has_b = ka.str.len() > 0, kb.str.len() > 0
        X['bracket_both'] = (has_a & has_b).astype(int)
        X['bracket_one'] = (has_a ^ has_b).astype(int)
        X['bracket_jac'] = [_jac(set(tokens(x)), set(tokens(y))) if (x and y) else 0.0 for x, y in zip(ka, kb)]
        la_len, lb_len = ba.str.len(), bb.str.len()
        X['len_ratio_base'] = np.minimum(la_len, lb_len) / np.maximum(np.maximum(la_len, lb_len), 1)
        X['pack_exact'] = (la.pack_size.map(normalize_name) == ra.pack_size.map(normalize_name)).astype(int)
        pa, pb = la.pack_size.map(parse_pack), ra.pack_size.map(parse_pack)
        qa, qb = pd.Series([p[0] for p in pa]), pd.Series([p[0] for p in pb])
        da, db = pd.Series([p[1] for p in pa]), pd.Series([p[1] for p in pb])
        unit_same = (da == db) & (da != '')
        ratio = np.minimum(qa, qb) / np.maximum(qa, qb)
        X['pack_qty_ratio'] = ratio.where(unit_same & (qa > 0) & (qb > 0))
        X['unit_compatible'] = unit_same.astype(int)
        br_a, br_b = la.brand.astype(str).str.lower(), ra.brand.astype(str).str.lower()
        X['brand_match'] = (br_a == br_b).astype(int)
        X['brand_known_both'] = ((br_a != 'unbranded') & (br_b != 'unbranded')).astype(int)
        X['category_match'] = (la.category.astype(str) == ra.category.astype(str)).astype(int)
        X['subcategory_match'] = (la.subcategory.astype(str) == ra.subcategory.astype(str)).astype(int)
        return X


def pair_frames(rec: pd.DataFrame, i, j):
    """Aligned left/right record frames for index arrays i, j into rec."""
    return rec.iloc[np.asarray(i)].reset_index(drop=True), rec.iloc[np.asarray(j)].reset_index(drop=True)
