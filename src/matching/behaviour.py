"""
behaviour.py — behavioural tests of the product matcher: edit real names in ways whose effect on product identity is
known BY CONSTRUCTION, and watch the saved model's score. No labels of any kind (human, AI or rule) are involved.

    python -m src.matching.behaviour        # needs models/product_matcher_v1.txt (python -m src.matching.train)

WHY
  Tier 1 (human labels) is not measurable yet and the AI proxy is one reviewer's opinion. A behavioural test asks a
  narrower question that needs neither: does the model's decision survive an edit that cannot change the product
  (INVARIANCE), and does it flip for an edit that must (DIRECTIONAL)? This is the CheckList idea (Ribeiro et al., 2020)
  applied to entity matching.

THE EDITS (each applied to a REAL catalog record and scored against the unedited record)
  invariance, the product cannot change:
    control       unchanged copy (must score as the original pair with itself)
    markup        '**name**' and '**pack**', the catalog's own markup (rule R4 already treats it as same)
    case          UPPER CASE name
    punctuation   hyphens, commas, slashes, full stops and apostrophes removed
    typo          one adjacent-letter transposition inside one word of 5+ letters
    alias         a local-name bracket appended, as the catalog does ('Amla' / 'Amla (Aula)')
  directional, the product must change:
    pack          pack quantity doubled (500 g -> 1000 g): a different SKU
    number        a number inside the name changed (10 -> 20 vibration patterns, SPF 50 -> 60): a different spec
    colour        a colour word swapped for another (Black -> White)

WHAT IT CAN CLAIM
  The edited names are constructed text, not observations, so rows are labelled SYNTHETIC and the manifest scope is
  SYNTHETIC-DERIVED. A pass rate describes how the MODEL behaves under one kind of edit. It is not accuracy on real
  pairs and not tier 1. "alias" is the one invariance edit that leans on catalog convention: in real data a bracket can
  also name a variant ("(Can)"); here the appended words are local names, never variants.
"""
import json
import re

import numpy as np
import pandas as pd

import src.load as L
from src.matching import blocking as B
from src.matching.features import PairFeaturizer
from src.matching.train import BOOSTER_PATH, FEATS, MODEL_NAME
from src.model_output import MODELS_DIR, save_model_outputs

OUT_NAME = 'product_matcher_behaviour_check'
N_PER_EDIT = 600
SEED = 20260925
INVARIANCE = ('control', 'markup', 'case', 'punctuation', 'typo', 'alias')
DIRECTIONAL = ('pack', 'number', 'colour')
ALIASES = ('Desi', 'Aula', 'Janhii', 'Deshi', 'Local')      # local-name brackets of the kind the REAL catalog uses
COLOURS = ('black', 'white', 'blue', 'red', 'green', 'grey', 'pink', 'yellow', 'brown', 'purple', 'orange', 'cream')
_COLOUR = re.compile(r'\b(' + '|'.join(COLOURS) + r')\b', re.I)
_NUM = re.compile(r'(?<![\d.])(\d+)(?![\d.])')
_PACK = re.compile(r'(\d+(?:\.\d+)?)')


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f'{x:g}'


def edit(name: str, pack: str, kind: str, rng) -> tuple[str, str] | None:
    """(edited name, edited pack), or None when the edit does not apply to this record."""
    if kind == 'control':
        return name, pack
    if kind == 'markup':
        return f'**{name}**', f'**{pack}**'
    if kind == 'case':
        return name.upper(), pack
    if kind == 'punctuation':
        new = re.sub(r"\s*[-,/.']\s*", ' ', name).strip()
        new = re.sub(r'\s+', ' ', new)
        return (new, pack) if new != name else None
    if kind == 'typo':
        words = name.split()
        long_ = [i for i, w in enumerate(words) if len(w) >= 5 and w.isalpha()]
        if not long_:
            return None
        i = long_[int(rng.integers(len(long_)))]
        w = words[i]; k = int(rng.integers(1, len(w) - 2))
        if w[k] == w[k + 1]:
            return None
        words[i] = w[:k] + w[k + 1] + w[k] + w[k + 2:]
        return ' '.join(words), pack
    if kind == 'alias':
        if B.bracket_text(name):
            return None                     # keep it to names with no bracket, so the edit is only the alias
        return f'{name} ({ALIASES[int(rng.integers(len(ALIASES)))]})', pack
    if kind == 'pack':
        m = _PACK.search(str(pack))
        if not m or float(m.group(1)) <= 0:
            return None
        return name, pack[:m.start()] + _fmt(float(m.group(1)) * 2) + pack[m.end():]
    if kind == 'number':
        m = _NUM.search(name)
        if not m or int(m.group(1)) == 0:
            return None
        return name[:m.start()] + str(int(m.group(1)) * 2) + name[m.end():], pack
    if kind == 'colour':
        m = _COLOUR.search(name)
        if not m:
            return None
        others = [c for c in COLOURS if c != m.group(1).lower()]
        new = others[int(rng.integers(len(others)))]
        new = new.capitalize() if m.group(1)[0].isupper() else new
        return name[:m.start()] + new + name[m.end():], pack
    raise ValueError(kind)


def load_scorer(rec: pd.DataFrame):
    """The saved booster and a featurizer fitted exactly as the trainer fits it (on the REAL catalog names)."""
    import lightgbm as lgb
    cfg = B.BlockingConfig.from_yaml()
    fz = PairFeaturizer(cfg.ngram_min, cfg.ngram_max).fit(rec.product_name)
    booster = lgb.Booster(model_file=str(BOOSTER_PATH))
    params = json.loads((MODELS_DIR / MODEL_NAME / 'params.json').read_text(encoding='utf-8'))

    def score(left: pd.DataFrame, right: pd.DataFrame) -> pd.DataFrame:
        X = fz.transform(left, right)
        return pd.DataFrame({'proba_lightgbm': booster.predict(L.select_features(X, FEATS)),
                             'baseline_score': X[params['baseline']['feature']].to_numpy()})
    return score, params


def parity(rec: pd.DataFrame, score, n: int = 2000) -> dict:
    """Re-score saved pairs; the reloaded booster + refitted featurizer must reproduce the trainer's probabilities."""
    saved = pd.read_parquet(MODELS_DIR / MODEL_NAME / 'predictions.parquet').sample(n, random_state=SEED)
    r = rec.set_index('canonical_product_key')
    s = score(r.loc[saved.key_a].reset_index(), r.loc[saved.key_b].reset_index())
    d_m = np.abs(s.proba_lightgbm.to_numpy() - saved.proba_lightgbm.to_numpy())
    d_b = np.abs(s.baseline_score.to_numpy() - saved.baseline_score.to_numpy())
    return {'pairs': n, 'max_abs_diff_lightgbm': float(d_m.max()), 'max_abs_diff_baseline': float(d_b.max()),
            'ok': bool(d_m.max() < 1e-6 and d_b.max() < 1e-6)}


def separability(ed: pd.DataFrame) -> dict:
    """AUC that a real identity-preserving edit (punctuation, typo, alias) outscores an identity-changing NAME edit
    (number, colour). Threshold-free: 0.5 means no threshold can separate them, whatever it is tuned to. Pack edits are
    left out because the name-only baseline cannot see packs by design."""
    from sklearn.metrics import roc_auc_score
    sub = ed[ed.edit.isin(['punctuation', 'typo', 'alias', 'number', 'colour'])]
    y = sub.expected.eq('same').astype(int)
    return {'pairs': int(len(sub)), 'lightgbm_auc': float(roc_auc_score(y, sub.proba_lightgbm)),
            'baseline_auc': float(roc_auc_score(y, sub.baseline_score)),
            'by_pair_of_edits_baseline': {f'{a} vs {b}': float(roc_auc_score(
                sub.edit[sub.edit.isin([a, b])].eq(a).astype(int), sub.baseline_score[sub.edit.isin([a, b])]))
                for a in ['punctuation', 'typo', 'alias'] for b in ['number', 'colour']}}


def run(save: bool = True) -> dict:
    listings = B.real_listings()
    rec = B.product_records(listings)
    assert rec.data_status.eq('REAL').all()
    score, params = load_scorer(rec)
    par = parity(rec, score)
    print('PARITY', json.dumps(par))
    if not par['ok']:
        raise RuntimeError(f'reloaded model does not reproduce the saved scores: {par}')

    rng = np.random.default_rng(SEED)
    order = rec.sample(frac=1, random_state=SEED).reset_index(drop=True)
    rows = []
    for kind in INVARIANCE + DIRECTIONAL:
        got = 0
        for _, r in order.iterrows():
            out = edit(str(r.product_name), str(r.pack_size), kind, rng)
            if out is None:
                continue
            rows.append({'edit': kind, 'canonical_product_key': r.canonical_product_key,
                         'observation_key': r.rep_observation_key, 'name_edited': out[0], 'pack_edited': out[1]})
            got += 1
            if got == N_PER_EDIT:
                break
    ed = pd.DataFrame(rows)
    left = rec.set_index('canonical_product_key').loc[ed.canonical_product_key].reset_index()
    right = left.copy()
    right['product_name'], right['pack_size'] = ed.name_edited.to_numpy(), ed.pack_edited.to_numpy()
    s = score(left, right)
    thr_m, thr_b = params['threshold_lightgbm'], params['baseline']['threshold']
    ed = ed.assign(name_original=left.product_name.to_numpy(), pack_original=left.pack_size.to_numpy(),
                   expected=np.where(ed.edit.isin(INVARIANCE), 'same', 'different'),
                   proba_lightgbm=s.proba_lightgbm.to_numpy(), baseline_score=s.baseline_score.to_numpy())
    ed['lightgbm_same'] = ed.proba_lightgbm >= thr_m
    ed['baseline_same'] = ed.baseline_score >= thr_b
    ed['lightgbm_pass'] = ed.lightgbm_same == (ed.expected == 'same')
    ed['baseline_pass'] = ed.baseline_same == (ed.expected == 'same')

    table = (ed.groupby('edit', sort=False)
             .agg(expected=('expected', 'first'), pairs=('edit', 'size'),
                  lightgbm_pass_rate=('lightgbm_pass', 'mean'), baseline_pass_rate=('baseline_pass', 'mean'),
                  lightgbm_median_proba=('proba_lightgbm', 'median'), baseline_median_score=('baseline_score', 'median'))
             .round(4))
    inv, dirn = ed[ed.edit.isin(INVARIANCE[1:])], ed[ed.edit.isin(DIRECTIONAL)]
    worst = (ed[~ed.lightgbm_pass].sort_values('proba_lightgbm', ascending=False)
             .groupby('edit').head(3)[['edit', 'name_original', 'pack_original', 'name_edited', 'pack_edited',
                                       'proba_lightgbm']].to_dict(orient='records'))
    result = {
        'NOTE': 'BEHAVIOURAL TEST, NOT TIER 1: edits of REAL catalog names whose effect on identity is known by '
                'construction. Pass rates describe model behaviour under each edit, not accuracy on real pairs.',
        'parity_with_saved_model': par,
        'thresholds': {'lightgbm': thr_m, 'baseline': params['baseline']},
        'by_edit': table.to_dict(orient='index'),
        'summary': {
            'invariance_pass_lightgbm': float(inv.lightgbm_pass.mean()),
            'invariance_pass_baseline': float(inv.baseline_pass.mean()),
            'directional_pass_lightgbm': float(dirn.lightgbm_pass.mean()),
            'directional_pass_baseline': float(dirn.baseline_pass.mean()),
            'excluding_edits_removed_by_normalisation': {
                'edits': ['punctuation', 'typo', 'alias'],
                'lightgbm': float(ed[ed.edit.isin(['punctuation', 'typo', 'alias'])].lightgbm_pass.mean()),
                'baseline': float(ed[ed.edit.isin(['punctuation', 'typo', 'alias'])].baseline_pass.mean())}},
        'separability_NO_THRESHOLD': separability(ed),
        'failure_examples': worst,
    }
    print(json.dumps({k: result[k] for k in ['summary', 'separability_NO_THRESHOLD']}, indent=1, default=str))
    if not save:
        return result
    out = ed.assign(data_status='SYNTHETIC', original_data_status='REAL',
                    label_source='CONSTRUCTED_EDIT_NOT_A_LABEL')
    save_model_outputs(OUT_NAME, out, {'evaluates': MODEL_NAME, 'n_per_edit': N_PER_EDIT, 'seed': SEED,
                                       'invariance_edits': INVARIANCE, 'directional_edits': DIRECTIONAL,
                                       'aliases': ALIASES, 'colours': COLOURS},
                       result, training_data=out,
                       split={'fit': 'nothing (saved booster reloaded; parity-checked)',
                              'evaluated_on': 'constructed edits of REAL catalog records'},
                       target='behaviour under identity-preserving / identity-changing edits (NOT a label)',
                       training_source='models/product_matcher_v1.txt + REAL catalog records via src.load',
                       notes='Behavioural (CheckList-style) test of model 1. Edited names are constructed, so rows are '
                             'SYNTHETIC. Not tier 1, not accuracy.')
    return result


if __name__ == '__main__':
    run()
