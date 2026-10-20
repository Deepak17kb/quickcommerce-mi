"""
train_v2.py — product matcher v2: difference-aware features + constructed edits as a label source.

    python -m src.matching.train_v2          # needs data/raw only; v1 is untouched

WHY A v2
  v1 passes every identity-changing edit and almost no identity-preserving one, and no threshold fixes it (behaviour.py:
  AUC 0.39-0.44). Two things were missing: features that say WHAT differs (diff_features.py) and positives that
  actually vary (edits.py). v2 adds both, and nothing else changes: same blocking, same rules, same key split, same
  LightGBM settings.

WHAT IS TRAINED ON
  REAL pairs with v1's auto labels (identical records, rule-certain negatives, human labels if any exist), plus
  constructed edits of REAL records from TRAIN keys only. Constructed pairs are SYNTHETIC rows, so v2 is no longer a
  REAL-only model and its manifest says SYNTHETIC-DERIVED. v1 stays the REAL-only model.

HOW IT IS JUDGED  (in this order of weight)
  1 leave-one-family-out   a whole family of edits (all typos, all variant swaps...) is removed from training and the
                           model is tested on it. This is the only behavioural number that is not circular: the
                           in-distribution pass rate mostly shows the model learned the edit generator.
  2 2 x 2 ablation         {v1 features, v2 features} x {v1 labels, + constructed}: which of the two changes matters.
  3 no regression          v1's own checks (held-out auto labels, tier 2, tier 3 false positives) must not get worse.
  4 support                on the 11,834 REAL pairs with no label: how many differ in a way the training pairs cover.
                           The rest are OUT OF SUPPORT and the model ABSTAINS on them (decision = 'abstain').

THE GATE IS PART OF THE MODEL
  The booster alone is not safe to use. The only insertions it was shown are alias brackets, so it scores every pair
  where one name just says more as the same product: 'Amul Dark Chocolate Bar' / 'Amul Sugar Free Dark Chocolate Bar'
  gets 0.9996. Nothing can be constructed to fix that honestly, because whether an added word changes the product is a
  judgement call ('Fresh' does not, 'Sugar Free' does). So the saved decision is same / different only when the pair's
  difference signature is covered by training, and 'abstain' otherwise. pred_lightgbm is the gated decision.
  Tier 1 (human labels) is still the only measure of real matching accuracy and is still NOT MEASURABLE at 0 labels.
  The AI proxy is scored by a separate module that this one never reads or names (docs/MATCHER_v2.md gives the command).
"""
import json

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

import src.load as L
from src.matching import blocking as B
from src.matching import edits as E
from src.matching import labels as LB
from src.matching import train as T
from src.matching.diff_features import DIFF_FEATS, DiffFeaturizer, signature
from src.matching.features import PairFeaturizer, pair_frames
from src.model_output import MODELS_DIR, save_model_outputs

MODEL_NAME = 'product_matcher_v2'
BEHAVIOUR_NAME = 'product_matcher_v2_behaviour_check'
BOOSTER_PATH = L.ROOT / 'models' / 'product_matcher_v2.txt'
FEATS_V2 = T.FEATS + DIFF_FEATS            # guarded by tests/test_id_columns_excluded.py through train.FEATS + here
TRAIN_PER_KIND = 1500
TEST_PER_KIND = 600
SEED = 20261013
MIN_SUPPORT = 25                           # training pairs a difference signature needs before a pair counts as covered
TIER3_PAIRS = 100_000
THRESHOLD = 0.5

FAMILIES = {
    'formatting': ('markup', 'case', 'punctuation', 'spacing', 'and_amp'),
    'typos': ('typo', 'typo_drop', 'typo_double'),
    'alias bracket': ('alias',),
    'pack respelled': ('unit_spelling', 'pack_format'),
    'pack changed': ('pack', 'pack_scale', 'multipack'),
    'number changed': ('number', 'number_shift'),
    'variant word swapped': ('colour', 'size', 'flavour', 'audience', 'word_swap'),
}
PACK_ONLY = ('pack', 'pack_scale', 'multipack', 'unit_spelling', 'pack_format')
ABLATION = {'A_v1feats_v1labels': (T.FEATS, False), 'B_v1feats_constructed': (T.FEATS, True),
            'C_v2feats_v1labels': (FEATS_V2, False), 'D_v2feats_constructed': (FEATS_V2, True)}
FINAL = 'D_v2feats_constructed'


def featurise(left: pd.DataFrame, right: pd.DataFrame, fz: PairFeaturizer, dz: DiffFeaturizer) -> pd.DataFrame:
    return pd.concat([fz.transform(left, right), dz.transform(left, right)], axis=1)


def constructed_pairs(rec: pd.DataFrame, per_kind: int, seed: int, fz, dz, kinds=E.KINDS) -> pd.DataFrame:
    """Edits of the given records, featurised against the unedited record."""
    ed = E.build(rec, kinds=kinds, per_kind=per_kind, seed=seed)
    left = rec.set_index('canonical_product_key').loc[ed.canonical_product_key].reset_index()
    right = left.copy()
    right['product_name'], right['pack_size'] = ed.name_edited.to_numpy(), ed.pack_edited.to_numpy()
    X = featurise(left, right, fz, dz)
    return pd.concat([ed.reset_index(drop=True).assign(
        name_original=left.product_name.to_numpy(), pack_original=left.pack_size.to_numpy(),
        label=(ed.expected == 'same').astype(float).to_numpy(), provenance='constructed_edit',
        data_status='SYNTHETIC'), X], axis=1)


def fit(train: pd.DataFrame, feats):
    import lightgbm as lgb
    return lgb.LGBMClassifier(**T.LGBM_PARAMS).fit(L.select_features(train, feats), train.label.astype(int))


def proba(model, df: pd.DataFrame, feats) -> np.ndarray:
    return model.predict_proba(L.select_features(df, feats))[:, 1]


def behaviour_table(ed: pd.DataFrame, p: np.ndarray) -> dict:
    """Pass rate per edit kind and the threshold-free separability of same vs different NAME edits."""
    d = ed.assign(p=p, ok=(p >= THRESHOLD) == (ed.expected == 'same'))
    by = d.groupby('edit', sort=False).agg(expected=('expected', 'first'), pairs=('ok', 'size'),
                                           pass_rate=('ok', 'mean'), median_proba=('p', 'median')).round(4)
    name = d[~d.edit.isin(PACK_ONLY + ('control', 'markup', 'case'))]
    v1k = d[d.edit.isin(['punctuation', 'typo', 'alias', 'number', 'colour'])]

    def auc(x):
        y = x.expected.eq('same').astype(int)
        return float(roc_auc_score(y, x.p)) if 0 < y.sum() < len(y) else None
    same, diff = d[(d.expected == 'same') & (d.edit != 'control')], d[d.expected == 'different']
    return {'by_edit': by.to_dict(orient='index'),
            'same_pass_rate': float(same.ok.mean()), 'different_pass_rate': float(diff.ok.mean()),
            'worst_edit': by.pass_rate.idxmin(), 'worst_edit_pass_rate': float(by.pass_rate.min()),
            'separability_auc_name_edits': auc(name), 'separability_auc_v1_five_edits': auc(v1k)}


def leave_family_out(base_tr, con_tr, con_te, feats) -> dict:
    out = {}
    for fam, kinds in FAMILIES.items():
        m = fit(pd.concat([base_tr, con_tr[~con_tr.edit.isin(kinds)]], ignore_index=True), feats)
        held = con_te[con_te.edit.isin(kinds)]
        ok = (proba(m, held, feats) >= THRESHOLD) == (held.expected == 'same')
        out[fam] = {'edits': list(kinds), 'expected': held.expected.iloc[0], 'pairs': int(len(held)),
                    'pass_rate_family_never_trained_on': float(ok.mean()),
                    'by_edit': ok.groupby(held.edit).mean().round(4).to_dict()}
    return out


def crossplatform_checks(model, feats, fz, dz, seed: int) -> dict:
    """v1's tiers 2 and 3 for this model. SYNTHETIC catalogs are byte copies of the Blinkit names: tier 2 is a
    sanity check, tier 3 measures false positives on different products."""
    sp = T.synthetic_platform_records()
    rng = np.random.default_rng(seed)
    nth = sp.groupby('canonical_product_key').cumcount()
    b = sp[nth == 1].set_index('canonical_product_key')
    a = sp[nth == 0].set_index('canonical_product_key').loc[b.index].reset_index()
    b = b.reset_index()
    assert (a.platform.to_numpy() != b.platform.to_numpy()).all()
    p2 = proba(model, featurise(a, b, fz, dz), feats)
    ra, rb = rng.integers(0, len(sp), TIER3_PAIRS), rng.integers(0, len(sp), TIER3_PAIRS)
    ok = (sp.platform.to_numpy()[ra] != sp.platform.to_numpy()[rb]) & \
         (sp.canonical_product_key.to_numpy()[ra] != sp.canonical_product_key.to_numpy()[rb])
    l3, r3 = sp.iloc[ra[ok]].reset_index(drop=True), sp.iloc[rb[ok]].reset_index(drop=True)
    p3 = proba(model, featurise(l3, r3, fz, dz), feats)
    return {'NOTE': 'SYNTHETIC catalogs (byte copies of Blinkit names). Tier 2 is a sanity check, not evidence of '
                    'cross-platform matching.',
            'tier2_same_key_cross_platform_pairs': int(len(a)), 'tier2_match_rate': float((p2 >= THRESHOLD).mean()),
            'tier3_random_different_key_pairs': int(len(l3)),
            'tier3_false_positive_rate': float((p3 >= THRESHOLD).mean()),
            'tier3_false_positives': int((p3 >= THRESHOLD).sum())}


def main(save: bool = True) -> dict:
    cfg = T.TrainConfig.from_yaml()
    L.check_feature_set(FEATS_V2)
    block_cfg = B.BlockingConfig.from_yaml()
    listings = B.real_listings()
    assert listings.data_status.eq('REAL').all()
    rec = B.product_records(listings)
    cand = B.candidate_pairs(rec, block_cfg)
    fz = PairFeaturizer(block_cfg.ngram_min, block_cfg.ngram_max).fit(rec.product_name)
    dz = DiffFeaturizer().fit(rec.product_name)
    labels, rec, fz = LB.build(listings=listings, rec=rec, cand=cand, featurizer=fz)
    labels = pd.concat([labels, dz.transform(*pair_frames(rec, labels.i, labels.j))], axis=1)
    labels['signature'] = signature(labels)

    # ---------------- the same key split as v1
    from src.matching.priority import reserved_test_keys
    reserved = set(reserved_test_keys())
    lab = labels[labels.label.notna()].copy()
    role, split_info = T.group_split(lab, cfg.test_share, cfg.seed, reserved)
    assert split_info['keys_in_both_train_and_test'] == 0
    base_tr, base_te = lab[role == 'train'], lab[role == 'test']
    is_test = T.is_test_key(rec.canonical_product_key, cfg.test_share, cfg.seed) | rec.canonical_product_key.isin(reserved).to_numpy()
    rec_train, rec_test = rec[~is_test].reset_index(drop=True), rec[is_test].reset_index(drop=True)
    con_tr = constructed_pairs(rec_train, TRAIN_PER_KIND, SEED, fz, dz)
    con_te = constructed_pairs(rec_test, TEST_PER_KIND, SEED + 1, fz, dz, kinds=('control',) + E.KINDS)
    train_keys = set(base_tr.key_a) | set(base_tr.key_b) | set(con_tr.canonical_product_key)
    test_keys = set(base_te.key_a) | set(base_te.key_b) | set(con_te.canonical_product_key) | reserved
    assert not train_keys & test_keys, 'a canonical_product_key is on both sides of the split'
    con_tr['signature'], con_te['signature'] = signature(con_tr), signature(con_te)
    print('SPLIT', json.dumps({**split_info, 'constructed_train_pairs': len(con_tr),
                               'constructed_test_pairs': len(con_te)}))

    # ---------------- 2 x 2 ablation
    full_tr = pd.concat([base_tr, con_tr], ignore_index=True)
    review = labels[labels.provenance == 'needs_review'].copy()
    auto_te = base_te[base_te.provenance.isin(['auto_positive', 'auto_negative'])]
    models, ablation, P_beh, P_rev, P_te = {}, {}, {}, {}, {}
    for name, (feats, use_con) in ABLATION.items():
        m = fit(full_tr if use_con else base_tr, feats)
        models[name] = m
        P_beh[name], P_rev[name], P_te[name] = proba(m, con_te, feats), proba(m, review, feats), proba(m, base_te, feats)
        beh = behaviour_table(con_te, P_beh[name])
        ablation[name] = {
            'features': 'v2 (v1 + difference-aware)' if feats is FEATS_V2 else 'v1',
            'labels': 'v1 auto labels + constructed edits' if use_con else 'v1 auto labels',
            'behaviour_on_test_keys': {k: v for k, v in beh.items() if k != 'by_edit'},
            'held_out_auto_labels': T.scores(auto_te.label, proba(m, auto_te, feats), THRESHOLD),
            'unlabelled_real_pairs_predicted_match_rate': float((P_rev[name] >= THRESHOLD).mean())}
        print(name, json.dumps(ablation[name]['behaviour_on_test_keys']))
    final, feats = models[FINAL], FEATS_V2

    # parity: A is v1 refitted here; it must agree with the saved v1 model where both scored the same pairs
    parity = {'status': 'v1 output not found'}
    v1_file = MODELS_DIR / T.MODEL_NAME / 'predictions.parquet'
    if v1_file.exists():
        v1 = pd.read_parquet(v1_file).drop_duplicates('pair_id').set_index('pair_id').proba_lightgbm
        mine = pd.Series(P_rev['A_v1feats_v1labels'], index=review.pair_id.to_numpy())
        both = mine.index.intersection(v1.index)
        diff = float((mine.loc[both] - v1.loc[both]).abs().max()) if len(both) else None
        parity = {'pairs_compared': int(len(both)), 'max_abs_diff_vs_saved_v1': diff,
                  'ok': bool(diff is not None and diff < 1e-6)}

    # ---------------- generalisation, behaviour, no regression
    lofo = leave_family_out(base_tr, con_tr, con_te, feats)
    lofo_v1feats = leave_family_out(base_tr, con_tr, con_te, T.FEATS)
    for fam in lofo:                                   # the same test with v1's similarity features only
        lofo[fam]['pass_rate_with_v1_features_only'] = lofo_v1feats[fam]['pass_rate_family_never_trained_on']
    beh_final = behaviour_table(con_te, P_beh[FINAL])
    checks = crossplatform_checks(final, feats, fz, dz, cfg.seed)
    checks_v1 = crossplatform_checks(models['A_v1feats_v1labels'], T.FEATS, fz, dz, cfg.seed)

    # ---------------- support: does a pair differ in a way the training pairs cover?
    sig_n = full_tr.groupby('signature').label.agg(['size', 'mean']).rename(columns={'size': 'pairs', 'mean': 'same_share'})
    covered = set(sig_n.index[sig_n.pairs >= MIN_SUPPORT])
    review['in_support'] = review.signature.isin(covered)
    review['proba'] = P_rev[FINAL]
    review['decision'] = np.where(~review.in_support, 'abstain', np.where(review.proba >= THRESHOLD, 'same', 'different'))
    names = rec.set_index('canonical_product_key').product_name
    extrapolated = (review[~review.in_support & (review.proba >= THRESHOLD) & (review.d_insert > 0)
                               & (review.d_res_bracket_share == 0)]
                        .sort_values('proba', ascending=False).head(400).sample(8, random_state=SEED))
    covered_tbl = (sig_n[sig_n.pairs >= MIN_SUPPORT].sort_values('pairs', ascending=False).head(15).round(4)
                   .to_dict(orient='index'))
    out_pat = (review[~review.in_support].groupby('signature')
               .agg(pairs=('proba', 'size'), predicted_same_share=('proba', lambda v: float((v >= THRESHOLD).mean())))
               .sort_values('pairs', ascending=False))
    in_pat = (review[review.in_support].groupby('signature')
              .agg(pairs=('proba', 'size'), predicted_same_share=('proba', lambda v: float((v >= THRESHOLD).mean())))
              .sort_values('pairs', ascending=False))
    support = {
        'rule': f'a pair is covered when at least {MIN_SUPPORT} training pairs share its difference signature',
        'training_signatures': int(len(sig_n)), 'covered_signatures': len(covered),
        'unlabelled_real_pairs': int(len(review)),
        'in_support_share': float(review.in_support.mean()),
        'decisions': review.decision.value_counts().to_dict(),
        'ungated_booster_would_call_same': {
            'in_support': int(((review.proba >= THRESHOLD) & review.in_support).sum()),
            'out_of_support': int(((review.proba >= THRESHOLD) & ~review.in_support).sum()),
            'examples_out_of_support_scored_same': [
                {'name_a': names[r.key_a], 'name_b': names[r.key_b], 'signature': r.signature,
                 'booster_proba': round(float(r.proba), 4)} for r in extrapolated.itertuples()],
            'reading': 'The only insertions in training are alias brackets, so the booster reads "one name says more" '
                       'as the same product. These pairs are extrapolation and the gate abstains on them.'},
        'largest_training_signatures': covered_tbl,
        'largest_out_of_support_patterns': out_pat.head(12).round(4).to_dict(orient='index'),
        'largest_covered_patterns': in_pat.head(8).round(4).to_dict(orient='index'),
        'reading': 'Out-of-support pairs differ in a way no rule and no constructed edit covers. Their scores are '
                   'extrapolation. They are where a human label is worth most.'}

    importance = pd.Series(final.booster_.feature_importance('gain'), index=feats).sort_values(ascending=False)
    fam_min = min(v['pass_rate_family_never_trained_on'] for v in lofo.values())
    fam_fail = sorted(k for k, v in lofo.items() if v['pass_rate_family_never_trained_on'] < 0.9)
    a, d = ablation['A_v1feats_v1labels'], ablation[FINAL]
    verdict = (
        'CONSTRUCTED-EDIT RESULT, NOT TIER 1. On edits of held-out REAL records v2 passes '
        f"{d['behaviour_on_test_keys']['same_pass_rate']:.1%} of identity-preserving and "
        f"{d['behaviour_on_test_keys']['different_pass_rate']:.1%} of identity-changing edits (v1 refit: "
        f"{a['behaviour_on_test_keys']['same_pass_rate']:.1%} / {a['behaviour_on_test_keys']['different_pass_rate']:.1%}); "
        f"same-vs-different AUC {d['behaviour_on_test_keys']['separability_auc_name_edits']:.3f} against "
        f"{a['behaviour_on_test_keys']['separability_auc_name_edits']:.3f}. With a whole edit family withheld from "
        f"training, the lowest pass rate is {fam_min:.1%}"
        + (f" (below 90%: {', '.join(fam_fail)})" if fam_fail else '')
        + f". {support['in_support_share']:.1%} of the {len(review):,} unlabelled REAL pairs differ in a way training "
        f"covers; on the rest v2 abstains ({support['decisions'].get('abstain', 0):,} pairs), because the ungated "
        f"booster calls {support['ungated_booster_would_call_same']['out_of_support']} of them the same on no evidence. "
        'None of this measures accuracy on real name variation: that is tier 1, human labels only.')
    result = {
        'model_version': 'product_matcher_v2',
        'NOTE': 'Trained on REAL auto-labelled pairs plus CONSTRUCTED edits (SYNTHETIC rows). Not tier 1.',
        'label_source_decision': 'constructed edits as a training label source: open decision of 2026-09-25, taken as '
                                 'approved from the owner\'s reply of 2026-10-13 ("whatever is open, start finishing it")',
        'split': {**split_info, 'constructed_train_pairs': int(len(con_tr)), 'constructed_test_pairs': int(len(con_te)),
                  'constructed_train_by_edit': con_tr.edit.value_counts().to_dict()},
        'tier1_main_real_name_variation': {'status': 'NOT MEASURABLE: ' + str(int((labels.provenance == 'human_reviewed').sum()))
                                                     + ' human-reviewed pairs. v2 does not change this.'},
        'ablation_2x2': ablation, 'v1_refit_parity': parity,
        'leave_one_family_out': lofo, 'behaviour_v2_by_edit': beh_final['by_edit'],
        'no_regression_crossplatform_SYNTHETIC': {'v2': checks, 'v1_refit': checks_v1},
        'support_on_unlabelled_real_pairs': support,
        'feature_importance_gain': importance.round(1).to_dict(),
        'verdict': verdict,
    }
    print(json.dumps({k: result[k] for k in ['v1_refit_parity', 'leave_one_family_out',
                                              'no_regression_crossplatform_SYNTHETIC', 'verdict']}, indent=1, default=str))
    print(json.dumps({k: support[k] for k in support if 'pattern' not in k and 'signatures' not in k}, indent=1))
    if not save:
        return result

    # ---------------- save: REAL pairs in the model output, constructed pairs in their own SYNTHETIC output
    BOOSTER_PATH.parent.mkdir(exist_ok=True)
    final.booster_.save_model(str(BOOSTER_PATH))
    thr_base = T.best_threshold(base_tr.label.astype(int).to_numpy(), base_tr[cfg.baseline_feature].to_numpy())
    te_rows = base_te.assign(split_role='test', in_support=base_te.signature.isin(covered))
    rv_rows = review.assign(split_role='needs_review_unlabelled')
    both = pd.concat([te_rows, rv_rows], ignore_index=True)
    pr = {n: np.r_[P_te[n], P_rev[n]] for n in ABLATION}
    gate = both.in_support.to_numpy(bool)
    real_pred = pd.DataFrame({
        'observation_key': both.rep_observation_key_a.to_numpy(), 'data_status': 'REAL',
        'observation_key_b': both.rep_observation_key_b.to_numpy(), 'pair_id': both.pair_id.to_numpy(),
        'key_a': both.key_a.to_numpy(), 'key_b': both.key_b.to_numpy(), 'provenance': both.provenance.to_numpy(),
        'rule': both.rule.to_numpy(), 'label': both.label.to_numpy(), 'split_role': both.split_role.to_numpy(),
        'signature': both.signature.to_numpy(), 'in_support': both.in_support.to_numpy(),
        'proba_lightgbm': pr[FINAL], 'pred_lightgbm': ((pr[FINAL] >= THRESHOLD) & gate).astype(int),
        'pred_ungated': (pr[FINAL] >= THRESHOLD).astype(int),
        'decision': np.where(~gate, 'abstain', np.where(pr[FINAL] >= THRESHOLD, 'same', 'different')),
        'baseline_score': both[cfg.baseline_feature].to_numpy(),
        'pred_baseline': (both[cfg.baseline_feature].to_numpy() >= thr_base).astype(int),
        **{f'proba_ablation_{n}': pr[n] for n in ABLATION}})
    params = {'lightgbm_params': T.LGBM_PARAMS, 'features': FEATS_V2, 'threshold_lightgbm': THRESHOLD,
              'baseline': {'feature': cfg.baseline_feature, 'threshold': thr_base, 'chosen_by': 'max F1 on train split'},
              'edit_kinds_same': E.SAME, 'edit_kinds_different': E.DIFFERENT, 'families': FAMILIES,
              'train_per_kind': TRAIN_PER_KIND, 'test_per_kind': TEST_PER_KIND, 'seed': SEED,
              'min_support': MIN_SUPPORT, 'booster_file': str(BOOSTER_PATH.relative_to(L.ROOT)),
              'final_model': FINAL}
    training_rows = pd.concat([base_tr[['data_status']], con_tr[['data_status']]], ignore_index=True)
    out1 = save_model_outputs(
        MODEL_NAME, real_pred, params, result, training_data=training_rows,
        split={'type': 'group split by canonical_product_key (same as v1)', 'fit': 'train keys',
               'evaluated_on': 'test keys', **split_info},
        target='same_product (pair label)', feature_columns=FEATS_V2,
        training_source='data/raw REAL Blinkit rows via src.load + constructed edits of train-key records (src/matching/edits.py)',
        notes='Model 1 v2. Trained on REAL auto-labelled pairs plus constructed edits, which are SYNTHETIC rows: the '
              'claim scope is SYNTHETIC-DERIVED and v1 remains the REAL-only model. Tier 1 is still not measurable. '
              f'Constructed test-key pairs are in outputs/models/{BEHAVIOUR_NAME}/.')
    out_pat.reset_index().to_csv(out1 / 'out_of_support_patterns.csv', index=False)
    beh_pred = con_te[['observation_key', 'data_status', 'canonical_product_key', 'edit', 'expected', 'name_original',
                       'pack_original', 'name_edited', 'pack_edited', 'signature']].copy()
    beh_pred['label_source'] = 'CONSTRUCTED_EDIT'
    for n in ABLATION:
        beh_pred[f'proba_{n}'] = P_beh[n]
    out2 = save_model_outputs(
        BEHAVIOUR_NAME, beh_pred, {'evaluates': MODEL_NAME, 'test_per_kind': TEST_PER_KIND, 'seed': SEED + 1},
        {'NOTE': 'Constructed edits of held-out REAL records. In-distribution pass rates mostly show the model learned '
                 'the edit generator; leave_one_family_out is the generalisation measure. NOT TIER 1.',
         'by_model': {n: behaviour_table(con_te, P_beh[n]) for n in ABLATION}, 'leave_one_family_out': lofo},
        training_data=beh_pred, split={'fit': 'train keys', 'evaluated_on': 'constructed edits of test-key records'},
        target='behaviour under constructed edits (labels by construction, not observed)',
        training_source='constructed edits of REAL catalog records (src/matching/edits.py)',
        notes='Behavioural check of model 1 v2 and its ablation. Rows are SYNTHETIC (constructed text).')
    result['saved'] = {'model': str(out1.relative_to(L.ROOT)), 'behaviour': str(out2.relative_to(L.ROOT)),
                       'booster': str(BOOSTER_PATH.relative_to(L.ROOT))}
    print('SAVED', json.dumps(result['saved']))
    return result


if __name__ == '__main__':
    main()
