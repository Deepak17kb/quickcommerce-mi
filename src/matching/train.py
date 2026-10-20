"""
train.py — product matcher v1 (model 1): LightGBM on REAL Blinkit pairs, three-tier evaluation, saved through
the model output contract.

    python -m src.matching.train

Pipeline: blocking (src/matching/blocking.py) -> features (features.py) -> labels with provenance (labels.py,
writes data/reference/MATCH_REVIEW_QUEUE.csv) -> GROUP split by canonical_product_key -> LightGBM vs a
string-similarity threshold baseline -> three separate evaluation tiers -> outputs/models/.

TRAINING DATA: REAL rows only (data_status == 'REAL'). Synthetic rows are used for evaluation tiers 2 and 3 only
and are saved to a separate output directory, so their provenance can never blend into the real-data result.

THE THREE TIERS (never blended into one number)
  1 MAIN    real Blinkit name variation. Measured ONLY on human_reviewed pairs, because auto_positive pairs are
            identical catalog records and teach/test nothing about name variation. With no human labels this tier
            is reported as NOT MEASURABLE. The auto-label held-out scores are reported separately as a pipeline
            check, not as tier 1.
  2 SANITY  cross-platform pairs of the SAME canonical key in the synthetic catalogs. Their names are byte copies
            of Blinkit names, so ~100% is expected. Proves no bug; NOT evidence of cross-platform matching ability.
  3 NEGATIVE DISCRIMINATION  cross-platform pairs of DIFFERENT keys: false-positive rate at scale (random pairs),
            on hard rule-certain negatives (pack variants), and the predicted-match rate on unlabelled hard pairs
            (an upper bound, since some of those may truly be the same product).
"""
import json
from dataclasses import dataclass, fields
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score

import src.load as L
from src.matching import blocking as B
from src.matching import labels as LB
from src.matching.features import PairFeaturizer
from src.model_output import save_model_outputs

MODEL_NAME = 'product_matcher'
CHECKS_NAME = 'product_matcher_crossplatform_checks'
BOOSTER_PATH = L.ROOT / 'models' / 'product_matcher_v1.txt'

# Single source of truth for model inputs. Discovered and guarded by tests/test_id_columns_excluded.py.
FEATS = ['jw_full', 'jw_base', 'tokjac_full', 'tokjac_base', 'ngram_cos_full', 'ngram_cos_base', 'token_set_base',
         'bracket_both', 'bracket_one', 'bracket_jac', 'len_ratio_base', 'pack_exact', 'pack_qty_ratio',
         'unit_compatible', 'brand_match', 'brand_known_both', 'category_match', 'subcategory_match']

LGBM_PARAMS = dict(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=20,
                   subsample=0.9, subsample_freq=1, colsample_bytree=0.9, random_state=20260917, verbose=-1)
MIN_HUMAN_PER_CLASS = 30


@dataclass
class TrainConfig:
    test_share: float = 0.25
    seed: int = 20260917
    baseline_feature: str = 'ngram_cos_full'
    tier3_random_pairs: int = 200000

    @classmethod
    def from_yaml(cls, path: Path | None = None, **overrides):
        import yaml
        path = path or (L.ROOT / 'config.yaml')
        raw = (yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}).get('matching', {}).get('train', {})
        raw.update(overrides)
        unknown = set(raw) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"unknown train config keys: {unknown}")
        return cls(**raw)


# --------------------------------------------------------------------------- split
def is_test_key(keys, test_share: float, seed: int) -> np.ndarray:
    """Stable key-level assignment: a canonical_product_key is a test key iff md5(seed:key) falls below
    test_share. It does not depend on which pairs are labelled, so adding human labels never reshuffles the split,
    and pairs chosen for labelling as test pairs stay test pairs."""
    import hashlib
    keys = pd.Series(keys).astype(str)
    h = keys.map(lambda k: int(hashlib.md5(f'{seed}:{k}'.encode()).hexdigest()[:12], 16) / float(16 ** 12))
    return (h < test_share).to_numpy()


def group_split(labels: pd.DataFrame, test_share: float, seed: int, reserved_test_keys: set | None = None):
    """Assign canonical_product_keys (not rows) to train or test: stable hash (is_test_key) plus any reserved
    evaluation keys (every key of the human-labelling priority batch). A pair is kept only if all of its keys are
    on the same side; pairs straddling the split are dropped. Returns (role Series, info dict)."""
    keys = pd.unique(pd.concat([labels.key_a, labels.key_b]))
    reserved = set(reserved_test_keys or ())
    test_keys = set(pd.Series(keys)[is_test_key(keys, test_share, seed)]) | (reserved & set(keys))
    a_test, b_test = labels.key_a.isin(test_keys), labels.key_b.isin(test_keys)
    role = pd.Series(np.select([a_test & b_test, ~a_test & ~b_test], ['test', 'train'], 'straddle_dropped'),
                     index=labels.index)
    info = split_integrity(labels, role)
    info.update({'keys_total': int(len(keys)), 'test_keys': int(len(test_keys)), 'test_share': test_share, 'seed': seed,
                 'assignment': 'md5(seed:canonical_product_key) < test_share, plus reserved evaluation keys',
                 'reserved_evaluation_keys': len(reserved)})
    return role, info


def split_integrity(labels: pd.DataFrame, role: pd.Series) -> dict:
    tr = labels[role == 'train']; te = labels[role == 'test']
    k_tr = set(tr.key_a) | set(tr.key_b)
    k_te = set(te.key_a) | set(te.key_b)
    overlap = k_tr & k_te
    return {'train_pairs': int(len(tr)), 'test_pairs': int(len(te)),
            'straddling_pairs_dropped': int((role == 'straddle_dropped').sum()),
            'train_keys': len(k_tr), 'test_keys_used': len(k_te), 'keys_in_both_train_and_test': len(overlap)}


# --------------------------------------------------------------------------- metrics
def scores(y, s, threshold) -> dict:
    y = np.asarray(y).astype(int); s = np.asarray(s, float); p = (s >= threshold).astype(int)
    out = {'n': int(len(y)), 'positives': int(y.sum()), 'negatives': int(len(y) - y.sum()),
           'threshold': float(threshold)}
    if len(y) == 0:
        return out
    out['precision'] = float(precision_score(y, p, zero_division=0))
    out['recall'] = float(recall_score(y, p, zero_division=0))
    out['f1'] = float(f1_score(y, p, zero_division=0))
    out['pr_auc'] = float(average_precision_score(y, s)) if 0 < y.sum() < len(y) else None
    out['predicted_match_rate'] = float(p.mean())
    return out


def best_threshold(y, s) -> float:
    grid = np.unique(np.round(np.asarray(s, float), 4))
    if len(grid) > 400:
        grid = np.quantile(grid, np.linspace(0, 1, 400))
    f1s = [f1_score(y, (s >= t).astype(int), zero_division=0) for t in grid]
    return float(grid[int(np.argmax(f1s))])


def degeneracy(labels: pd.DataFrame) -> dict:
    pos = labels[labels.provenance == 'auto_positive']
    neg = labels[labels.provenance == 'auto_negative']
    return {
        'auto_positive_pairs': int(len(pos)),
        'auto_positive_by_rule': pos.rule.value_counts().to_dict(),
        'auto_positive_distinct_feature_vectors': int(len(pos[FEATS].round(6).drop_duplicates())),
        'auto_positive_share_identical_base_name': float((pos.jw_base == 1).mean()) if len(pos) else None,
        'auto_positive_share_identical_full_name': float((pos.jw_full == 1).mean()) if len(pos) else None,
        'auto_negative_share_identical_full_name': float((neg.jw_full == 1).mean()) if len(neg) else None,
        'human_reviewed_pairs': int((labels.provenance == 'human_reviewed').sum()),
    }


# --------------------------------------------------------------------------- synthetic cross-platform records
def synthetic_platform_records() -> pd.DataFrame:
    s = L.synthetic_only(L.load_raw())
    assert s.data_status.eq('SYNTHETIC').all()
    cols = ['platform', 'canonical_product_key', 'product_name', 'pack_size', 'brand', 'category', 'subcategory',
            'observation_key', 'data_status']
    return s[cols].drop_duplicates(['platform', 'canonical_product_key']).reset_index(drop=True)


def main(cfg: TrainConfig | None = None, save: bool = True) -> dict:
    import lightgbm as lgb
    cfg = cfg or TrainConfig.from_yaml()
    L.check_feature_set(FEATS)
    block_cfg = B.BlockingConfig.from_yaml()

    # ---------------- data, blocking, labels (REAL only)
    listings = B.real_listings()
    assert listings.data_status.eq('REAL').all()
    rec = B.product_records(listings)
    cand = B.candidate_pairs(rec, block_cfg)
    blocking_report = {
        'config': block_cfg.__dict__, 'products': len(rec), 'real_listings_used': len(listings),
        'candidate_product_pairs': len(cand), 'audit_recall': B.audit_recall(listings, cand),
        'old_strategy_recall': B.old_strategy_recall(rec, cand),
        'perturbation_stress_recall': B.perturbation_recall(rec, block_cfg),
    }
    print('BLOCKING', json.dumps(blocking_report, default=str))
    fz = PairFeaturizer(block_cfg.ngram_min, block_cfg.ngram_max).fit(rec.product_name)
    labels, rec, fz = LB.build(listings=listings, rec=rec, cand=cand, featurizer=fz)
    assert set(FEATS) <= set(labels.columns), "features.py and FEATS are out of sync"
    queue = LB.write_review_queue(labels, rec)
    label_counts = LB.provenance_counts(labels)
    degen = degeneracy(labels)
    print('LABELS', json.dumps(label_counts), '\nDEGENERACY', json.dumps(degen))

    # ---------------- group split + fit
    lab = labels[labels.label.notna()].copy()
    from src.matching.priority import reserved_test_keys
    role, split_info = group_split(lab, cfg.test_share, cfg.seed, reserved_test_keys())
    assert split_info['keys_in_both_train_and_test'] == 0, "group split leaked a canonical_product_key"
    print('SPLIT', json.dumps(split_info))
    tr, te = lab[role == 'train'], lab[role == 'test']
    Xtr = L.select_features(tr, FEATS)
    model = lgb.LGBMClassifier(**LGBM_PARAMS).fit(Xtr, tr.label.astype(int))
    thr_model = 0.5
    thr_base = best_threshold(tr.label.astype(int).to_numpy(), tr[cfg.baseline_feature].to_numpy())

    def predict(df):
        return model.predict_proba(L.select_features(df, FEATS))[:, 1]

    te = te.assign(proba=predict(te))

    # ---------------- tier 1: MAIN (human labels) and the auto-label pipeline check
    human_te = te[te.provenance == 'human_reviewed']
    hum_pos, hum_neg = int((human_te.label == 1).sum()), int((human_te.label == 0).sum())
    if min(hum_pos, hum_neg) >= MIN_HUMAN_PER_CLASS:
        tier1_status = 'MEASURED'
    elif len(human_te) == 0:
        tier1_status = ('NOT MEASURABLE: 0 human-reviewed pairs. auto_positive pairs are identical catalog records, '
                        'so no labelled example of real name variation exists yet. Label data/reference/MATCH_REVIEW_QUEUE.csv.')
    else:
        tier1_status = f'TOO FEW HUMAN LABELS IN TEST: {hum_pos} same / {hum_neg} different (need >= {MIN_HUMAN_PER_CLASS} each)'
    tier1 = {'status': tier1_status}
    if tier1_status == 'MEASURED':
        tier1['lightgbm'] = scores(human_te.label, human_te.proba, thr_model)
        tier1['baseline'] = scores(human_te.label, human_te[cfg.baseline_feature], thr_base)
    auto_te = te[te.provenance.isin(['auto_positive', 'auto_negative'])]
    hard_neg_te = auto_te[(auto_te.provenance == 'auto_negative') & auto_te.rule.str.contains('R2')
                          & (auto_te.blocking_method != 'random_pair')]
    pipeline_check = {
        'NOTE': 'NOT tier 1. Held-out auto labels: positives are identical records, negatives are rule-certain. '
                'High scores here only show the pipeline works.',
        'lightgbm': scores(auto_te.label, auto_te.proba, thr_model),
        'baseline': scores(auto_te.label, auto_te[cfg.baseline_feature], thr_base),
        'hard_negatives_pack_variants_in_candidates': {
            'n': int(len(hard_neg_te)),
            'lightgbm_false_positive_rate': float((hard_neg_te.proba >= thr_model).mean()) if len(hard_neg_te) else None,
            'baseline_false_positive_rate': float((hard_neg_te[cfg.baseline_feature] >= thr_base).mean()) if len(hard_neg_te) else None,
        },
    }

    def comparison(block):
        m, b = block.get('lightgbm'), block.get('baseline')
        if not m or not b or m.get('pr_auc') is None:
            return 'not comparable'
        better = m['f1'] > b['f1'] + 1e-9 and (m['pr_auc'] or 0) >= (b['pr_auc'] or 0) - 1e-9
        tie = abs(m['f1'] - b['f1']) <= 1e-9
        return ('LightGBM beats the baseline' if better else
                'TIE: LightGBM does not beat the string-similarity baseline' if tie else
                'LightGBM does NOT beat the string-similarity baseline')

    pipeline_check['lightgbm_vs_baseline_on_auto_labels'] = (
        comparison(pipeline_check) + ' on auto labels - NOT a valid comparison: positives are identical records')
    if tier1_status == 'MEASURED':
        tier1['lightgbm_vs_baseline'] = comparison(tier1)

    review = labels[labels.provenance == 'needs_review']
    review_scored = review.assign(proba=predict(review))
    unlabelled = {
        'needs_review_pairs': int(len(review)),
        'lightgbm_predicted_match_rate': float((review_scored.proba >= thr_model).mean()),
        'baseline_predicted_match_rate': float((review_scored[cfg.baseline_feature] >= thr_base).mean()),
        'NOTE': 'No labels exist for these pairs; rates describe model behaviour, not accuracy.',
    }

    # ---------------- tiers 2 and 3: synthetic cross-platform
    sp = synthetic_platform_records()
    plats = sorted(sp.platform.unique())
    by_key = sp.groupby('canonical_product_key')
    t2_rows = []
    for key, g in by_key:
        if len(g) < 2:
            continue
        idx = g.index.to_numpy()
        a, b = np.triu_indices(len(idx), 1)
        t2_rows.append(np.c_[idx[a], idx[b]])
    t2 = np.vstack(t2_rows)
    L2, R2 = sp.iloc[t2[:, 0]].reset_index(drop=True), sp.iloc[t2[:, 1]].reset_index(drop=True)
    X2 = fz.transform(L2, R2)
    p2 = model.predict_proba(L.select_features(X2, FEATS))[:, 1]
    tier2 = {
        'NOTE': 'SANITY CHECK ONLY. Synthetic catalog names are byte copies of Blinkit names; ~100% expected. '
                'NOT evidence of cross-platform matching ability.',
        'same_key_cross_platform_pairs': int(len(t2)),
        'lightgbm_match_rate': float((p2 >= thr_model).mean()),
        'baseline_match_rate': float((X2[cfg.baseline_feature].to_numpy() >= thr_base).mean()),
        'names_byte_identical_share': float((L2.product_name.to_numpy() == R2.product_name.to_numpy()).mean()),
    }

    rng = np.random.default_rng(cfg.seed)
    n = cfg.tier3_random_pairs
    ra, rb = rng.integers(0, len(sp), n), rng.integers(0, len(sp), n)
    ok = (sp.platform.to_numpy()[ra] != sp.platform.to_numpy()[rb]) & \
         (sp.canonical_product_key.to_numpy()[ra] != sp.canonical_product_key.to_numpy()[rb])
    ra, rb = ra[ok], rb[ok]
    L3, R3 = sp.iloc[ra].reset_index(drop=True), sp.iloc[rb].reset_index(drop=True)
    X3 = fz.transform(L3, R3)
    p3 = model.predict_proba(L.select_features(X3, FEATS))[:, 1]
    # hard cross-platform pairs: real candidate key pairs placed on two different platforms
    key_plats = sp.groupby('canonical_product_key').apply(lambda g: dict(zip(g.platform, g.index)))
    lab_by_pair = labels.drop_duplicates('pair_id').set_index('pair_id')
    hi, hj, hprov = [], [], []
    for r in labels[labels.pair_level == 'product'].itertuples():
        if r.blocking_method == 'random_pair':
            continue
        pa, pb = key_plats.get(r.key_a), key_plats.get(r.key_b)
        if not pa or not pb:
            continue
        for p1, i1 in pa.items():
            for p2_, i2 in pb.items():
                if p1 != p2_:
                    hi.append(i1); hj.append(i2); hprov.append(r.provenance)
                    break
            else:
                continue
            break
    hprov = np.array(hprov)
    if len(hi):
        LH, RH = sp.iloc[hi].reset_index(drop=True), sp.iloc[hj].reset_index(drop=True)
        XH = fz.transform(LH, RH)
        pH = model.predict_proba(L.select_features(XH, FEATS))[:, 1]
    else:
        XH, pH = pd.DataFrame(columns=FEATS), np.array([])
    neg_mask, rev_mask = hprov == 'auto_negative', hprov == 'needs_review'
    tier3 = {
        'NOTE': 'Different canonical keys on different platforms. Random pairs are near-certain negatives; '
                'rule negatives are certain; needs_review pairs have unknown truth (match rate is an upper bound on FP).',
        'random_cross_platform_pairs': {
            'n': int(len(ra)),
            'lightgbm_false_positive_rate': float((p3 >= thr_model).mean()),
            'lightgbm_false_positives': int((p3 >= thr_model).sum()),
            'baseline_false_positive_rate': float((X3[cfg.baseline_feature].to_numpy() >= thr_base).mean()),
        },
        'hard_rule_negative_cross_platform_pairs': {
            'n': int(neg_mask.sum()),
            'lightgbm_false_positive_rate': float((pH[neg_mask] >= thr_model).mean()) if neg_mask.any() else None,
            'baseline_false_positive_rate': float((XH[cfg.baseline_feature].to_numpy()[neg_mask] >= thr_base).mean()) if neg_mask.any() else None,
        },
        'hard_unlabelled_cross_platform_pairs': {
            'n': int(rev_mask.sum()),
            'lightgbm_predicted_match_rate_upper_bound_fp': float((pH[rev_mask] >= thr_model).mean()) if rev_mask.any() else None,
            'baseline_predicted_match_rate_upper_bound_fp': float((XH[cfg.baseline_feature].to_numpy()[rev_mask] >= thr_base).mean()) if rev_mask.any() else None,
        },
    }

    importance = pd.Series(model.booster_.feature_importance('gain'), index=FEATS).sort_values(ascending=False)

    def pct(v):
        return 'n/a' if v is None else f'{v:.4%}'

    rnd3, hard3 = tier3['random_cross_platform_pairs'], tier3['hard_rule_negative_cross_platform_pairs']
    if tier1_status == 'MEASURED':
        verdict = tier1['lightgbm_vs_baseline'] + ' on human-reviewed real name variation (tier 1).'
    else:
        verdict = ('NO VALID CLAIM that LightGBM beats the string-similarity baseline: tier 1 (real name variation) is '
                   'not measurable without human labels, and auto-label scores are uninformative. Negative '
                   'discrimination (tier 3): random-pair false-positive rate LightGBM '
                   + pct(rnd3['lightgbm_false_positive_rate']) + ' vs baseline ' + pct(rnd3['baseline_false_positive_rate'])
                   + '; hard rule-negative false-positive rate LightGBM ' + pct(hard3['lightgbm_false_positive_rate'])
                   + ' vs baseline ' + pct(hard3['baseline_false_positive_rate']) + '.')
    result = {
        'model_version': 'product_matcher_v1',
        'blocking': blocking_report, 'labels': label_counts, 'label_degeneracy': degen, 'split': split_info,
        'tier1_main_real_name_variation': tier1, 'pipeline_check_auto_labels_NOT_TIER1': pipeline_check,
        'unlabelled_needs_review_behaviour': unlabelled,
        'tier2_sanity_synthetic_same_key': tier2, 'tier3_negative_discrimination_synthetic': tier3,
        'lightgbm_vs_baseline_verdict': verdict,
        'thresholds': {'lightgbm': thr_model, 'baseline_feature': cfg.baseline_feature, 'baseline': thr_base},
        'feature_importance_gain': importance.round(2).to_dict(),
        'review_queue': {'path': str(LB.QUEUE_PATH.relative_to(L.ROOT)), 'pairs': int(len(queue))},
    }
    print(json.dumps({k: result[k] for k in ['tier1_main_real_name_variation', 'pipeline_check_auto_labels_NOT_TIER1',
                                              'tier2_sanity_synthetic_same_key', 'tier3_negative_discrimination_synthetic',
                                              'unlabelled_needs_review_behaviour', 'lightgbm_vs_baseline_verdict']},
                     indent=1, default=str))
    if not save:
        return result

    # ---------------- save through the output contract
    BOOSTER_PATH.parent.mkdir(exist_ok=True)
    model.booster_.save_model(str(BOOSTER_PATH))
    real_pred = pd.concat([te.assign(split_role='test'), review_scored.assign(split_role='needs_review_unlabelled')])
    real_pred = pd.DataFrame({
        'observation_key': real_pred.rep_observation_key_a.to_numpy(),
        'data_status': 'REAL',
        'observation_key_b': real_pred.rep_observation_key_b.to_numpy(),
        'pair_id': real_pred.pair_id.to_numpy(), 'key_a': real_pred.key_a.to_numpy(), 'key_b': real_pred.key_b.to_numpy(),
        'provenance': real_pred.provenance.to_numpy(), 'rule': real_pred.rule.to_numpy(),
        'label': real_pred.label.to_numpy(), 'split_role': real_pred.split_role.to_numpy(),
        'proba_lightgbm': real_pred.proba.to_numpy(), 'pred_lightgbm': (real_pred.proba.to_numpy() >= thr_model).astype(int),
        'baseline_score': real_pred[cfg.baseline_feature].to_numpy(),
        'pred_baseline': (real_pred[cfg.baseline_feature].to_numpy() >= thr_base).astype(int),
    })
    params = {'lightgbm_params': LGBM_PARAMS, 'features': FEATS, 'threshold_lightgbm': thr_model,
              'baseline': {'feature': cfg.baseline_feature, 'threshold': thr_base, 'chosen_by': 'max F1 on train split'},
              'blocking_config': block_cfg.__dict__, 'label_config': LB.LabelConfig.from_yaml().__dict__,
              'train_config': cfg.__dict__, 'booster_file': str(BOOSTER_PATH.relative_to(L.ROOT)),
              'feature_importance_gain': result['feature_importance_gain']}
    metrics = {k: result[k] for k in ['blocking', 'labels', 'label_degeneracy', 'split', 'tier1_main_real_name_variation',
                                      'pipeline_check_auto_labels_NOT_TIER1', 'unlabelled_needs_review_behaviour',
                                      'lightgbm_vs_baseline_verdict', 'thresholds']}
    notes = ('Model 1 v1. Trained on REAL Blinkit pairs only. TIER 1 STATUS: ' + tier1_status + ' '
             'Predictions: held-out test pairs (auto labels) + unlabelled needs_review pairs. Pair rows: observation_key = '
             'representative listing of key_a, observation_key_b = of key_b. Tiers 2-3 (synthetic) are in '
             f'outputs/models/{CHECKS_NAME}/.')
    out1 = save_model_outputs(MODEL_NAME, real_pred, params, metrics, training_data=listings,
                              split={'type': 'group split by canonical_product_key', 'fit': 'train keys',
                                     'evaluated_on': 'test keys', **split_info},
                              target='same_product (pair label)', feature_columns=FEATS,
                              training_source='data/raw REAL Blinkit rows via src.load + data/reference/CANONICAL_KEY_AUDIT.csv',
                              notes=notes)
    chk = pd.concat([
        pd.DataFrame({'observation_key': L2.observation_key.to_numpy(), 'data_status': 'SYNTHETIC',
                      'observation_key_b': R2.observation_key.to_numpy(), 'tier': 'tier2_sanity_same_key',
                      'key_a': L2.canonical_product_key.to_numpy(), 'key_b': R2.canonical_product_key.to_numpy(),
                      'platform_a': L2.platform.to_numpy(), 'platform_b': R2.platform.to_numpy(),
                      'proba_lightgbm': p2, 'baseline_score': X2[cfg.baseline_feature].to_numpy()}),
        pd.DataFrame({'observation_key': L3.observation_key.to_numpy()[:50000], 'data_status': 'SYNTHETIC',
                      'observation_key_b': R3.observation_key.to_numpy()[:50000], 'tier': 'tier3_random_different_key',
                      'key_a': L3.canonical_product_key.to_numpy()[:50000], 'key_b': R3.canonical_product_key.to_numpy()[:50000],
                      'platform_a': L3.platform.to_numpy()[:50000], 'platform_b': R3.platform.to_numpy()[:50000],
                      'proba_lightgbm': p3[:50000], 'baseline_score': X3[cfg.baseline_feature].to_numpy()[:50000]}),
    ], ignore_index=True)
    if len(hi):
        chk = pd.concat([chk, pd.DataFrame({
            'observation_key': LH.observation_key.to_numpy(), 'data_status': 'SYNTHETIC',
            'observation_key_b': RH.observation_key.to_numpy(),
            'tier': np.where(neg_mask, 'tier3_hard_rule_negative', 'tier3_hard_unlabelled'),
            'key_a': LH.canonical_product_key.to_numpy(), 'key_b': RH.canonical_product_key.to_numpy(),
            'platform_a': LH.platform.to_numpy(), 'platform_b': RH.platform.to_numpy(),
            'proba_lightgbm': pH, 'baseline_score': XH[cfg.baseline_feature].to_numpy()})], ignore_index=True)
    out2 = save_model_outputs(CHECKS_NAME, chk, {'evaluates': MODEL_NAME, 'threshold_lightgbm': thr_model,
                                                 'baseline_threshold': thr_base, 'tier3_random_pairs_scored': int(len(ra)),
                                                 'tier3_random_pairs_stored': int(min(len(ra), 50000))},
                              {'tier2_sanity_synthetic_same_key': tier2, 'tier3_negative_discrimination_synthetic': tier3},
                              training_data=listings, split={'type': 'evaluation only, no fitting'},
                              target='same_product (pair label)', feature_columns=FEATS,
                              training_source='model trained on REAL Blinkit rows; this output scores SYNTHETIC cross-platform pairs',
                              notes='Tier 2 is a sanity check on byte-copied names, not evidence of cross-platform matching. '
                                    'Tier 3 is negative discrimination (false-positive rate).')
    result['saved'] = {'real': str(out1.relative_to(L.ROOT)), 'checks': str(out2.relative_to(L.ROOT)),
                       'booster': str(BOOSTER_PATH.relative_to(L.ROOT))}
    print('SAVED', json.dumps(result['saved']))
    return result


if __name__ == '__main__':
    main()
