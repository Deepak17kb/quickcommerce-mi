"""Product matcher (model 1): blocking recall, feature guard, group-split integrity, label integrity."""
import numpy as np
import pandas as pd
import pytest

from conftest import raw_path
import src.load as L
from src.matching import blocking as B
from src.matching import labels as LB
from src.matching import train as T
from src.matching.features import PairFeaturizer, pair_frames


@pytest.fixture(scope='module')
def block():
    raw_path('Blinkit')
    cfg = B.BlockingConfig.from_yaml()
    listings = B.real_listings()
    rec = B.product_records(listings)
    cand = B.candidate_pairs(rec, cfg)
    return cfg, listings, rec, cand


# ------------------------------------------------------------------ data scope
def test_matcher_uses_real_rows_only(block):
    _, listings, rec, _ = block
    assert listings.data_status.eq('REAL').all() and rec.data_status.eq('REAL').all()
    assert len(listings) == 21_945          # 21,949 REAL minus the 4 unnamed listings


# ------------------------------------------------------------------ blocking
def test_blocking_recall_floor(block):
    cfg, listings, rec, cand = block
    audit = B.audit_recall(listings, cand)
    assert audit['audit_pairs'] == 3_581 and audit['recall'] >= 0.99, audit
    old = B.old_strategy_recall(rec, cand)
    assert old['recall'] == 1.0, f"widened blocking must include every old base-name + pack pair: {old}"
    assert 5_000 <= len(cand) <= 150_000, f"candidate pair count {len(cand)} outside sane range"
    assert (cand.key_a != cand.key_b).all()


def test_blocking_recall_on_name_variation_stress_test(block):
    """Audit pairs have identical names, so they cannot test hard cases. The perturbation stress test can."""
    cfg, _, rec, _ = block
    r = B.perturbation_recall(rec, cfg, n=600, seed=1)
    assert r['recall'] >= 0.95, r


def test_blocking_config_is_read_from_yaml():
    cfg = B.BlockingConfig.from_yaml(ngram_min_cosine=0.42)
    assert cfg.ngram_min_cosine == 0.42 and set(cfg.methods) <= set(B.METHODS)
    with pytest.raises(ValueError):
        B.BlockingConfig.from_yaml(not_a_setting=1)


# ------------------------------------------------------------------ features
def test_feature_set_has_no_id_or_target_columns(block):
    _, _, rec, cand = block
    L.check_feature_set(T.FEATS)
    assert not set(T.FEATS) & (set(L.identifier_columns()) | set(L.target_columns()))
    fz = PairFeaturizer().fit(rec.product_name)
    X = fz.transform(*pair_frames(rec, cand.i[:200], cand.j[:200]))
    assert set(X.columns) == set(T.FEATS), "features.py output and train.FEATS are out of sync"
    L.check_feature_set(X.columns)
    with pytest.raises(L.FeatureSetError):
        L.select_features(X.assign(canonical_product_key='k'), T.FEATS + ['canonical_product_key'])


def test_pack_parser_ignores_markup_and_multiplies():
    assert B.parse_pack('**180 ml**') == (180.0, 'volume')
    assert B.parse_pack('2 x 180 ml') == (360.0, 'volume')
    assert B.parse_pack('1 kg') == (1000.0, 'mass')
    assert B.parse_pack('3 x 72 wipes') == (216.0, 'count:wipe')
    q, d = B.parse_pack('50 g + 10 ml')
    assert np.isnan(q) and d == ''


# ------------------------------------------------------------------ labels
def test_markup_only_pack_difference_is_never_an_auto_negative():
    left = pd.DataFrame({'product_name': ['**Tata Coffee Grand Vietnamese Cold Coffee**'], 'pack_size': ['**180 ml**'],
                         'brand': ['Tata Coffee'], 'category': ['Beverages'], 'subcategory': ['Cold Coffee']})
    right = left.assign(product_name='Tata Coffee Grand Vietnamese Cold Coffee', pack_size='180 ml')
    fz = PairFeaturizer().fit(pd.concat([left.product_name, right.product_name]))
    X = fz.transform(left, right)
    assert LB.negative_rule(left, right, X, LB.LabelConfig()).iloc[0] == ''


def test_review_queue_preserves_human_labels(tmp_path):
    rec = pd.DataFrame({'canonical_product_key': ['a', 'b', 'c'], 'product_name': ['Amla', 'Amla (Aula)', 'Rose'],
                        'pack_size': ['250 g'] * 3, 'brand': ['UNBRANDED'] * 3, 'category': ['F&V'] * 3,
                        'name_norm': ['amla', 'amla (aula)', 'rose']})
    labels = pd.DataFrame({'pair_id': ['a || b', 'a || c'], 'key_a': ['a', 'a'], 'key_b': ['b', 'c'],
                           'provenance': ['needs_review', 'needs_review'], 'jw_base': [1.0, 0.5],
                           'ngram_cos_base': [1.0, 0.1], 'ngram_cos_full': [0.8, 0.1], 'tokjac_base': [1.0, 0.0],
                           'pack_exact': [1, 1], 'blocking_method': ['char_ngram', 'token']})
    path = tmp_path / 'queue.csv'
    q = LB.write_review_queue(labels, rec, path)
    assert q.label.eq('').all() and len(q) == 2
    q.loc[q.pair_id == 'a || b', 'label'] = '1'
    q.to_csv(path, index=False)
    q2 = LB.write_review_queue(labels, rec, path)
    assert q2.set_index('pair_id').loc['a || b', 'label'] == '1'
    assert LB.read_human_labels(path).set_index('pair_id').label.to_dict() == {'a || b': 1}


# ------------------------------------------------------------------ group split
def test_group_split_has_no_key_overlap(block):
    _, listings, rec, cand = block
    aud = B.audit_pairs()
    key_of = listings.set_index('product_id').canonical_product_key
    pos = pd.DataFrame({'key_a': aud.product_id_a.map(key_of), 'key_b': aud.product_id_b.map(key_of)})
    pairs = pd.concat([pos, cand[['key_a', 'key_b']]], ignore_index=True)
    role, info = T.group_split(pairs, test_share=0.25, seed=7)
    tr, te = pairs[role == 'train'], pairs[role == 'test']
    k_tr = set(tr.key_a) | set(tr.key_b)
    k_te = set(te.key_a) | set(te.key_b)
    assert len(tr) and len(te)
    assert not k_tr & k_te, f"{len(k_tr & k_te)} canonical keys in both train and test"
    assert info['keys_in_both_train_and_test'] == 0
    assert info['train_pairs'] + info['test_pairs'] + info['straddling_pairs_dropped'] == len(pairs)


# ------------------------------------------------------------------ R4, stable split, priority batch
def _rec(name, pack, brand='Tata Coffee', category='Beverages'):
    return pd.DataFrame({'product_name': [name], 'pack_size': [pack], 'brand': [brand], 'category': [category],
                         'subcategory': ['Cold Coffee']})


def test_r4_markup_only_difference_rule():
    base = _rec('Tata Coffee Grand Irish Cold Coffee', '180 ml')
    assert LB.positive_rule(_rec('**Tata Coffee Grand Irish Cold Coffee**', '**180 ml**'), base).iloc[0] == 'R4_markup_only_difference'
    assert LB.positive_rule(_rec('**TATA COFFEE Grand Irish Cold Coffee**', '**180 ml**'), base).iloc[0] == '', 'case must match'
    assert LB.positive_rule(_rec('**Tata Coffee Grand Irish Cold Coffee**', '**200 ml**'), base).iloc[0] == '', 'pack must match'
    assert LB.positive_rule(_rec('**Tata Coffee Grand Irish Cold Coffee**', '**180 ml**', brand='Tata'), base).iloc[0] == ''
    assert LB.positive_rule(_rec('**Tata Coffee Grand Irish Cold Coffee**', '**180 ml**', category='Tea'), base).iloc[0] == ''
    assert LB.positive_rule(base, base).iloc[0] == '', 'identical raw names are the same key, not an R4 pair'


def test_split_is_label_independent_and_honours_reserved_keys():
    pairs = pd.DataFrame({'key_a': [f'k{i}' for i in range(400)], 'key_b': [f'k{i + 1}' for i in range(400)]})
    reserved = {'k10', 'k11', 'k200', 'k201'}
    role, info = T.group_split(pairs, 0.25, 11, reserved)
    assert role[(pairs.key_a == 'k10') & (pairs.key_b == 'k11')].eq('test').all()
    assert role[(pairs.key_a == 'k200') & (pairs.key_b == 'k201')].eq('test').all()
    tr, te = pairs[role == 'train'], pairs[role == 'test']
    assert not (set(tr.key_a) | set(tr.key_b)) & (set(te.key_a) | set(te.key_b))
    role_sub, _ = T.group_split(pairs.iloc[:150], 0.25, 11, reserved)      # fewer labelled pairs, same assignment
    assert (role_sub == role.iloc[:150]).all()


def test_priority_batch_is_reserved_and_lands_in_test():
    from src.matching import priority as P
    if not P.PRIORITY_PATH.exists():
        pytest.skip('priority batch not built')
    b = pd.read_csv(P.PRIORITY_PATH, dtype=str)
    reserved = P.reserved_test_keys()
    assert set(b.key_a) | set(b.key_b) == reserved and b.pair_id.is_unique
    role, info = T.group_split(b[['key_a', 'key_b']], 0.25, 20260917, reserved)
    assert role.eq('test').all() and info['keys_in_both_train_and_test'] == 0


def test_conflicting_human_labels_are_dropped(tmp_path):
    q, p = tmp_path / 'q.csv', tmp_path / 'p.csv'
    pd.DataFrame({'pair_id': ['a || b', 'c || d'], 'label': ['1', '1']}).to_csv(q, index=False)
    pd.DataFrame({'pair_id': ['a || b', 'e || f'], 'label': ['0', '0']}).to_csv(p, index=False)
    h = LB.read_human_labels(q, p).set_index('pair_id').label.to_dict()
    assert h == {'c || d': 1, 'e || f': 0}


# ------------------------------------------------------------------ review page import + AI review (2026-09-25)
def _batch():
    return pd.DataFrame({'batch_row': ['1', '2', '3'], 'pair_id': ['a || b', 'c || d', 'e || f'],
                         'label': ['', '', '1'], 'reviewer_note': ['', '', '']})


def test_import_labels_checks_row_text_owner_and_existing_labels():
    from src.matching.import_labels import plan
    labels = {'r001': {'row': 1, 'pair_id': 'a || b', 'label': 'same', 'by_owner': True, 'at': '2026-09-25T10:00'},
              'r002': {'row': 2, 'pair_id': 'WRONG', 'label': 'different', 'by_owner': True},
              'r003': {'row': 3, 'pair_id': 'e || f', 'label': 'different', 'by_owner': True},
              'r004': {'row': 4, 'label': 'same', 'by_owner': True},
              'r005': {'row': 1, 'pair_id': 'a || b', 'label': 'maybe', 'by_owner': True}}
    writes, problems = plan(labels, _batch(), relabel=False, allow_editors=False)
    assert [w['row'] for w in writes] == [1] and writes[0]['label'] == '1'
    assert len(problems) == 4          # wrong pair text, existing label kept, row not in batch, invalid label
    editor = {'r002': {'row': 2, 'pair_id': 'c || d', 'label': 'unsure', 'by_owner': False}}
    assert plan(editor, _batch(), False, False)[0] == []
    w, _ = plan(editor, _batch(), False, True)
    assert w[0]['label'] == '' and 'not confirmed as owner' in w[0]['note']
    w, _ = plan({'r003': labels['r003']}, _batch(), relabel=True, allow_editors=False)
    assert w[0]['label'] == '0' and w[0]['was'] == '1'


def test_ai_review_never_reaches_the_trainer():
    """The AI review is a proxy, never a label source: no labelling or training module may read it."""
    from pathlib import Path
    src = Path(L.ROOT) / 'src' / 'matching'
    for mod in ['labels.py', 'train.py', 'import_labels.py', 'review.py', 'priority.py', 'blocking.py', 'features.py',
                'train_v2.py', 'diff_features.py', 'edits.py']:
        text = (src / mod).read_text(encoding='utf-8')
        assert 'ai_review' not in text, f'{mod} references the AI review'
    from src.matching import priority as P
    if P.PRIORITY_PATH.exists():
        b = pd.read_csv(P.PRIORITY_PATH, dtype=str).fillna('')
        assert not b.reviewer_note.str.contains('AI review|claude', case=False).any()


def test_ai_review_file_covers_the_batch_once():
    from src.matching import ai_review as A
    if not A.PRIORITY.exists():
        pytest.skip('priority batch not built')
    batch = pd.read_csv(A.PRIORITY, dtype=str)
    check = A.validate(A.read_ai(), batch)
    assert check['ok'], check
    assert 'NOT human labels' in A.AI_FILE.read_text(encoding='utf-8').splitlines()[0]


def test_ai_proxy_output_is_labelled_and_never_tier1():
    import json
    from src.model_output import MODELS_DIR
    d = MODELS_DIR / 'product_matcher_ai_proxy_check'
    if not (d / 'metrics.json').exists():
        pytest.skip('ai proxy check has not been run')
    m = json.loads((d / 'metrics.json').read_text(encoding='utf-8'))
    m = m.get('metrics', m)
    assert 'NOT TIER 1' in m['NOTE'] and m['ai_proxy_scores_NOT_TIER1']['verdict'].startswith('AI PROXY, NOT TIER 1')
    assert not any('tier1' in k.lower() and 'not_tier1' not in k.lower() for k in m)
    p = pd.read_parquet(d / 'predictions.parquet')
    assert p.label_source.eq('AI_REVIEW_NOT_HUMAN').all() and p.data_status.eq('REAL').all()


# ------------------------------------------------------------------ behavioural test (2026-09-25)
def test_behaviour_edits_do_what_they_say():
    from src.matching.behaviour import edit
    rng = np.random.default_rng(0)
    assert edit('Amla', '250 g', 'pack', rng) == ('Amla', '500 g')
    assert edit('Amla', '2 x 180 ml', 'pack', rng) == ('Amla', '4 x 180 ml')
    assert edit('Amla (Aula)', '250 g', 'alias', rng) is None          # only names without a bracket get an alias
    assert edit('Amla', '250 g', 'alias', rng)[0].startswith('Amla (')
    assert edit('Pad 10 Patterns', '1 pc', 'number', rng)[0] == 'Pad 20 Patterns'
    n, _ = edit('Goggles (Black)', '1 pc', 'colour', rng)
    assert n != 'Goggles (Black)' and n.startswith('Goggles (') and n[9].isupper()
    t, _ = edit('Sunfeast Biscuits', '1 pc', 'typo', rng) or ('Sunfeast Biscuits', '')
    assert len(t) == len('Sunfeast Biscuits') and sorted(t) == sorted('Sunfeast Biscuits')
    assert edit('Plain Name', '1 pc', 'punctuation', rng) is None       # nothing to remove, no edit


def test_behaviour_check_is_parity_checked_and_labelled():
    import json
    from src.model_output import MODELS_DIR
    d = MODELS_DIR / 'product_matcher_behaviour_check'
    if not (d / 'metrics.json').exists():
        pytest.skip('behaviour check has not been run')
    m = json.loads((d / 'metrics.json').read_text(encoding='utf-8'))
    assert m['parity_with_saved_model']['ok'] and 'NOT TIER 1' in m['NOTE']
    assert m['by_edit']['control']['lightgbm_pass_rate'] == 1.0
    assert m['summary']['directional_pass_lightgbm'] >= 0.99      # v1 rejects every identity-changing edit...
    assert m['summary']['excluding_edits_removed_by_normalisation']['lightgbm'] <= 0.05   # ...and every real variation
    assert m['separability_NO_THRESHOLD']['lightgbm_auc'] < 0.6    # no threshold separates typo/alias from colour/number
    p = pd.read_parquet(d / 'predictions.parquet')
    assert p.data_status.eq('SYNTHETIC').all() and p.label_source.eq('CONSTRUCTED_EDIT_NOT_A_LABEL').all()


# ------------------------------------------------------------------ matcher v2 (2026-10-13)
def test_diff_features_say_what_differs():
    from src.matching.diff_features import DIFF_FEATS, DiffFeaturizer
    names = ['Sunfeast Biscuits', 'Mint Candy', 'Mini Candy', 'Mint Leaves', 'Mini Pack', 'Mint Gum', 'Mini Bar', 'Amla']
    dz = DiffFeaturizer().fit(names)
    d = dz.describe
    assert d('Tea & Coffee - 250ml', 'tea and coffee 250 ML')['d_nothing'] == 1          # formatting only
    assert d('Sunfeast Biscuits', 'Sunfeast Bisciuts')['d_typo_like'] == 1               # a rare token one edit away
    t = d('Mint Candy', 'Mini Candy')                                                    # two common words: not a typo
    assert t['d_typo_like'] == 0 and t['d_near_word_subst'] == 1 and t['d_subst'] == 1
    a = d('Amla', 'Amla (Aula)')                                                         # one name says more, in a bracket
    assert a['d_insert'] == 1 and a['d_subst'] == 0 and a['d_res_bracket_share'] == 1
    assert d('Milk Chocolate', 'Chocolate Milk')['d_order_changed'] == 1
    n = d('SPF 50 Sunscreen', 'SPF 60 Sunscreen')
    assert n['d_num_subst'] == 1 and n['d_alpha_subst'] == 0
    assert d('Goggles (Black)', 'Goggles (White)')['d_lex_contrast'] == 1
    left = pd.DataFrame({'product_name': ['Atta'], 'pack_size': ['1 kg']})
    X = dz.transform(left, left.assign(pack_size='1000 g'))
    assert list(X.columns) == DIFF_FEATS and X.d_pack_equal_qty.iloc[0] == 1
    L.check_feature_set(DIFF_FEATS)


def test_v2_edits_do_what_they_say():
    from src.matching import edits as E
    from src.matching.train_v2 import FAMILIES
    rng = np.random.default_rng(0)
    assert E.edit('Atta', '1 kg', 'pack_format', rng) == ('Atta', '1000 g')
    assert E.edit('Atta', '500 g', 'unit_spelling', rng) == ('Atta', '500 gm')
    assert E.edit('Cola', '180 ml', 'multipack', rng)[1].endswith('x 180 ml')
    assert E.edit('Tea & Coffee', '1 pc', 'and_amp', rng)[0] == 'Tea and Coffee'
    assert E.edit('Spikes 3.7 inch - Steel', '1 pc', 'punctuation', rng) is None        # would break a decimal
    assert E.edit('Mango Drink', '1 pc', 'flavour', rng)[0] != 'Mango Drink'
    assert E.edit('Plain Name', '1 pc', 'colour', rng) is None
    assert {E.EXPECTED[k] for k in E.SAME} == {'same'} and {E.EXPECTED[k] for k in E.DIFFERENT} == {'different'}
    assert sorted(k for f in FAMILIES.values() for k in f) == sorted(E.KINDS)            # every edit is in one family


def test_v2_is_gated_labelled_and_never_tier1():
    import json
    from src.model_output import MODELS_DIR
    d = MODELS_DIR / 'product_matcher_v2'
    if not (d / 'metrics.json').exists():
        pytest.skip('matcher v2 has not been run')
    m = json.loads((d / 'metrics.json').read_text(encoding='utf-8'))
    man = json.loads((d / 'manifest.json').read_text(encoding='utf-8'))
    assert man['claim_scope'].startswith('SYNTHETIC-DERIVED') and man['training_row_mix']['SYNTHETIC'] > 0
    assert m['tier1_main_real_name_variation']['status'].startswith('NOT MEASURABLE')
    assert m['verdict'].startswith('CONSTRUCTED-EDIT RESULT, NOT TIER 1')
    assert m['v1_refit_parity']['ok']                                   # the ablation's v1 cell IS the saved v1 model
    assert m['split']['keys_in_both_train_and_test'] == 0
    lofo = m['leave_one_family_out']
    # the documented generalisation result: difference-aware features carry to unseen families, similarity does not
    assert lofo['typos']['pass_rate_family_never_trained_on'] > 0.9 > lofo['typos']['pass_rate_with_v1_features_only']
    assert lofo['variant word swapped']['pass_rate_family_never_trained_on'] > 0.9
    assert lofo['alias bracket']['pass_rate_family_never_trained_on'] < 0.1      # the alias rule is taught, not learned
    p = pd.read_parquet(d / 'predictions.parquet')
    assert p.data_status.eq('REAL').all()
    assert (p.pred_lightgbm[~p.in_support] == 0).all() and (p.decision[~p.in_support] == 'abstain').all()
    assert p.decision.isin(['same', 'different', 'abstain']).all() and (p.decision == 'abstain').any()
    b = pd.read_parquet(MODELS_DIR / 'product_matcher_v2_behaviour_check' / 'predictions.parquet')
    assert b.data_status.eq('SYNTHETIC').all() and b.label_source.eq('CONSTRUCTED_EDIT').all()


def test_v2_ai_proxy_scope_follows_the_scored_model():
    import json
    from src.model_output import MODELS_DIR
    d = MODELS_DIR / 'product_matcher_v2_ai_proxy_check'
    if not (d / 'metrics.json').exists():
        pytest.skip('v2 ai proxy check has not been run')
    m = json.loads((d / 'metrics.json').read_text(encoding='utf-8'))
    assert m['model_scored'] == 'product_matcher_v2' and 'NOT TIER 1' in m['NOTE']
    assert m['ai_proxy_scores_NOT_TIER1']['verdict'].startswith('AI PROXY, NOT TIER 1')
    assert json.loads((d / 'manifest.json').read_text(encoding='utf-8'))['claim_scope'].startswith('SYNTHETIC-DERIVED')
    g = m['ai_proxy_scores_NOT_TIER1']['v2_support_gate_on_name_variation']
    assert g['in_support_pairs'] + g['abstained_pairs'] == g['pairs']
