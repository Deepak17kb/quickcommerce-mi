"""
ai_review.py — score the matcher against Claude's blind review of the priority batch. An AI PROXY, never tier 1.

    python -m src.matching.ai_review              # needs outputs/models/product_matcher/ (python -m src.matching.train)
    python -m src.matching.ai_review --model v2   # the same check for matcher v2 (python -m src.matching.train_v2)

WHAT THIS IS
  src/matching/ai_review_data.txt holds one AI judgement per MATCH_REVIEW_PRIORITY.csv row (S same, D different,
  U unsure), made blind: names, packs, brands and categories only, in the review page's shuffled order. This module
  scores LightGBM and the string-similarity baseline against those judgements, using the scores the trainer already
  saved for these (needs_review, reserved-test-key) pairs. Nothing is retrained.

WHAT IT CAN AND CANNOT CLAIM
  - It is NOT tier 1. Tier 1 is human labels only (CLAUDE.md §8). The AI labels are never read by labels.py or the
    trainer and never become human_reviewed (tests/test_matching.py enforces both).
  - A result here says how the matcher agrees with one AI reviewer. It turns into evidence about the matcher only once
    the AI reviewer's agreement with human labels is measured (`human_agreement` below, NOT MEASURABLE until the
    review page has labels).
  - The error table by reason (colour, flavour, size...) is a list of hypotheses for where the matcher fails. It
    tells a human labeller where to look, not what the answer is.
"""
import json
import re

import numpy as np
import pandas as pd

import src.load as L
from src.matching.train import MODEL_NAME
from src.model_output import MODELS_DIR, save_model_outputs

AI_FILE = L.ROOT / 'src' / 'matching' / 'ai_review_data.txt'
PRIORITY = L.REF / 'MATCH_REVIEW_PRIORITY.csv'
OUT_NAME = 'product_matcher_ai_proxy_check'
# model key -> (saved matcher output it scores, output it writes). The matcher modules never read this file.
MODELS = {'v1': (MODEL_NAME, OUT_NAME), 'v2': ('product_matcher_v2', 'product_matcher_v2_ai_proxy_check')}
CODE = {'S': 1, 'D': 0, 'U': None}
MIN_AGREEMENT_PAIRS = 20          # human+AI pairs needed before agreement is reported
BOOT = 2000
SEED = 20260925

# reason text -> kind of difference; first match wins. Only for D labels (why the AI said "different").
# Anything unmatched is a named variant ("almond vs oat", "front load vs top load", "laddu type").
REASONS = [('colour', r'colou?r'), ('flavour / variant word', r'flavour|scent|variant|natural|classic|chocolate'),
           ('size (S/M/L, cm, kg, length)', r'\bsize\b|\b(xs|s|m|l|xl|xxl)\b|length|\d+\s*(cm|m|kg|inch|")\b|weight'),
           ('pack size or count', r'pack|pcs|\bml\b|\bg\b|count|x \d'),
           ('brand', r'brand'), ('gender / age', r"men|women|years|kids|girl|boy")]


def read_ai(path=AI_FILE) -> pd.DataFrame:
    rows = []
    for ln in path.read_text(encoding='utf-8').splitlines():
        if not ln.strip() or ln.startswith('#'):
            continue
        row, lab, conf, reason = (ln.split('|', 3) + ['', '', ''])[:4]
        rows.append({'batch_row': int(row), 'ai_label': lab.strip(), 'ai_confidence': conf.strip(),
                     'ai_reason': reason.strip()})
    return pd.DataFrame(rows)


def validate(ai: pd.DataFrame, batch: pd.DataFrame) -> dict:
    rows = set(batch.batch_row.astype(int))
    bad = sorted(set(ai.ai_label) - set(CODE))
    dup = ai.batch_row[ai.batch_row.duplicated()].tolist()
    return {'pairs_in_batch': len(rows), 'ai_judgements': int(len(ai)),
            'missing_rows': sorted(rows - set(ai.batch_row)), 'unknown_rows': sorted(set(ai.batch_row) - rows),
            'duplicate_rows': dup, 'invalid_labels': bad,
            'ok': not bad and not dup and set(ai.batch_row) == rows}


def reason_kind(reason: str) -> str:
    r = reason.lower()
    for kind, pat in REASONS:
        if re.search(pat, r):
            return kind
    return 'other named variant'


def norm(text: str) -> str:
    return re.sub(r'[^a-z0-9]', '', text.lower())


def trivial(df: pd.DataFrame) -> pd.Series:
    """Pairs whose name AND pack are identical once case, markup, spaces and punctuation are removed. Mechanical, not
    the AI's call: these pairs carry no name variation, so they say nothing about tier 1's question."""
    return ((df.name_a.map(norm) == df.name_b.map(norm)) & (df.pack_a.map(norm) == df.pack_b.map(norm)))


def f1_pr(y, pred):
    tp = int(((pred == 1) & (y == 1)).sum()); fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {'precision': p, 'recall': r, 'f1': 2 * p * r / (p + r) if p + r else 0.0,
            'false_positive_rate': fp / int((y == 0).sum()) if (y == 0).any() else None}


def avg_precision(y, s):
    from sklearn.metrics import average_precision_score
    return float(average_precision_score(y, s)) if 0 < y.sum() < len(y) else None


def block(y, s, pred):
    return {**f1_pr(y, pred), 'pr_auc': avg_precision(y, s)}


def paired_bootstrap(y, s_m, p_m, s_b, p_b, n=BOOT, seed=SEED) -> dict:
    """Resample pairs; the same draw scores both models, so the CI is of the DIFFERENCE (LightGBM minus baseline)."""
    rng = np.random.default_rng(seed)
    d_f1, d_ap = [], []
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        if not 0 < y[i].sum() < len(i):
            continue
        d_f1.append(f1_pr(y[i], p_m[i])['f1'] - f1_pr(y[i], p_b[i])['f1'])
        d_ap.append(avg_precision(y[i], s_m[i]) - avg_precision(y[i], s_b[i]))
    ci = lambda v: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]
    return {'resamples': len(d_f1), 'f1_diff_ci95': ci(d_f1), 'pr_auc_diff_ci95': ci(d_ap)}


def human_agreement(df: pd.DataFrame) -> dict:
    """Cohen's kappa between the AI and the humans on pairs both labelled S/D."""
    h = df.label.astype(str).str.strip()
    both = df[h.isin(['0', '1']) & df.ai_y.notna()]
    if len(both) < MIN_AGREEMENT_PAIRS:
        return {'status': f'NOT MEASURABLE: {len(both)} pairs carry both a human and an AI same/different label '
                          f'(need >= {MIN_AGREEMENT_PAIRS}). Label pairs on the review page, import them, re-run.',
                'pairs': int(len(both))}
    a, b = both.ai_y.astype(int).to_numpy(), both.label.astype(int).to_numpy()
    po = float((a == b).mean())
    pe = float(a.mean() * b.mean() + (1 - a.mean()) * (1 - b.mean()))
    return {'status': 'MEASURED', 'pairs': int(len(both)), 'raw_agreement': po,
            'cohen_kappa': (po - pe) / (1 - pe) if pe < 1 else None,
            'confusion_ai_rows_human_cols': pd.crosstab(a, b).to_dict(),
            'ai_unsure_that_humans_labelled': int((h.isin(['0', '1']) & df.ai_y.isna()).sum())}


def gate_report(nt: pd.DataFrame) -> dict:
    """v2 only: what the support gate does on the name-variation pairs, and which half of v2 (features or
    constructed labels) moves the AI-proxy score. `pred_lightgbm` is already the gated decision."""
    y = nt.ai_y.astype(int).to_numpy()
    ins, outs = nt[nt.in_support], nt[~nt.in_support]
    called = outs[outs.pred_ungated == 1]
    return {
        'pairs': int(len(nt)), 'in_support_pairs': int(len(ins)), 'abstained_pairs': int(len(outs)),
        'ai_same_in_support': int(ins.ai_y.sum()), 'ai_same_abstained': int(outs.ai_y.sum()),
        'in_support_only': block(ins.ai_y.astype(int).to_numpy(), ins.proba_lightgbm.to_numpy(),
                                 ins.pred_lightgbm.to_numpy()),
        'ungated_booster_all_pairs': block(y, nt.proba_lightgbm.to_numpy(), nt.pred_ungated.to_numpy()),
        'ungated_same_calls_on_abstained_pairs': {
            'calls': int(len(called)), 'ai_agrees_same': int(called.ai_y.sum()),
            'precision': float(called.ai_y.mean()) if len(called) else None},
        'ablation_2x2_ungated': {
            c.replace('proba_ablation_', ''): block(y, nt[c].to_numpy(), (nt[c].to_numpy() >= 0.5).astype(int))
            for c in nt.columns if c.startswith('proba_ablation_')}}


def run(save: bool = True, model: str = 'v1') -> dict:
    model_name, out_name = MODELS[model]
    batch = pd.read_csv(PRIORITY, dtype=str).fillna('')
    batch['batch_row'] = batch.batch_row.astype(int)
    ai = read_ai()
    check = validate(ai, batch)
    if not check['ok']:
        raise ValueError(f'AI review file does not match the batch: {check}')
    pred = pd.read_parquet(MODELS_DIR / model_name / 'predictions.parquet')
    pred = pred[pred.split_role == 'needs_review_unlabelled']
    params = json.loads((MODELS_DIR / model_name / 'params.json').read_text(encoding='utf-8'))
    extra = [c for c in pred.columns if c.startswith('proba_ablation_')
             or c in ('in_support', 'decision', 'pred_ungated', 'signature')]
    df = batch.merge(ai, on='batch_row').merge(
        pred[['key_a', 'key_b', 'observation_key', 'observation_key_b', 'data_status', 'proba_lightgbm',
              'pred_lightgbm', 'baseline_score', 'pred_baseline'] + extra], on=['key_a', 'key_b'], how='left')
    assert len(df) == len(batch) and df.proba_lightgbm.notna().all(), 'priority pairs missing from saved predictions'
    assert df.data_status.eq('REAL').all()
    df['ai_y'] = df.ai_label.map(CODE)

    lab = df[df.ai_y.notna()]
    y = lab.ai_y.astype(int).to_numpy()
    s_m, p_m = lab.proba_lightgbm.to_numpy(), lab.pred_lightgbm.to_numpy()
    s_b, p_b = lab.baseline_score.to_numpy(), lab.pred_baseline.to_numpy()
    proxy = {'lightgbm': block(y, s_m, p_m), 'baseline': block(y, s_b, p_b),
             'difference_lightgbm_minus_baseline': paired_bootstrap(y, s_m, p_m, s_b, p_b),
             'pairs': int(len(lab)), 'ai_same': int(y.sum()), 'ai_different': int((y == 0).sum())}
    hi = lab[lab.ai_confidence == 'high']
    proxy['high_confidence_only'] = {
        'pairs': int(len(hi)),
        'lightgbm': block(hi.ai_y.astype(int).to_numpy(), hi.proba_lightgbm.to_numpy(), hi.pred_lightgbm.to_numpy()),
        'baseline': block(hi.ai_y.astype(int).to_numpy(), hi.baseline_score.to_numpy(), hi.pred_baseline.to_numpy())}
    # the question tier 1 asks: pairs with real name variation, trivial (identical-after-normalising) pairs removed
    nt = lab[~trivial(lab)]
    ynt = nt.ai_y.astype(int).to_numpy()
    proxy['name_variation_only'] = {
        'pairs': int(len(nt)), 'ai_same': int(ynt.sum()), 'trivial_pairs_removed': int(trivial(lab).sum()),
        'lightgbm': block(ynt, nt.proba_lightgbm.to_numpy(), nt.pred_lightgbm.to_numpy()),
        'baseline': block(ynt, nt.baseline_score.to_numpy(), nt.pred_baseline.to_numpy()),
        'difference_lightgbm_minus_baseline': paired_bootstrap(
            ynt, nt.proba_lightgbm.to_numpy(), nt.pred_lightgbm.to_numpy(),
            nt.baseline_score.to_numpy(), nt.pred_baseline.to_numpy())}
    nv = proxy['name_variation_only']
    base_rate = nv['ai_same'] / nv['pairs']
    ci = nv['difference_lightgbm_minus_baseline']['f1_diff_ci95']
    f1_call = ('LightGBM ahead of the baseline on F1' if ci[0] > 0 else 'LightGBM behind the baseline on F1'
               if ci[1] < 0 else 'no F1 difference the 95% CI can separate')
    exact = max(nv['lightgbm']['recall'], nv['baseline']['recall']) < 0.05
    proxy['verdict'] = (
        f"AI PROXY, NOT TIER 1. On the {nv['pairs']} pairs with real name variation, LightGBM finds "
        f"{nv['lightgbm']['recall']:.0%} of the {nv['ai_same']} AI-same pairs at precision "
        f"{nv['lightgbm']['precision']:.0%} ({f1_call}); PR-AUC LightGBM "
        f"{nv['lightgbm']['pr_auc']:.3f}, baseline {nv['baseline']['pr_auc']:.3f}, chance {base_rate:.3f}. "
        + ("Against one AI reviewer, both behave as exact-match detectors. " if exact else '')
        + "Not evidence about the matcher until AI-human agreement is measured.")
    proxy['name_variation_only']['chance_pr_auc'] = base_rate
    if 'in_support' in nt.columns:
        proxy['v2_support_gate_on_name_variation'] = gate_report(nt)

    # stratum was hidden from the reviewer: how the blind labels fall across strata is a consistency check
    strata = pd.crosstab(df.stratum, df.ai_label).to_dict(orient='index')

    diff = lab[lab.ai_y == 0].assign(kind=lambda d: d.ai_reason.map(reason_kind))
    errors = (diff.groupby('kind')
              .agg(pairs=('ai_y', 'size'), lightgbm_says_same=('pred_lightgbm', 'mean'),
                   baseline_says_same=('pred_baseline', 'mean'))
              .sort_values('pairs', ascending=False).round(3))
    same = lab[lab.ai_y == 1]
    missed = {'ai_same_pairs': int(len(same)), 'lightgbm_says_different': float(1 - same.pred_lightgbm.mean()),
              'baseline_says_different': float(1 - same.pred_baseline.mean()),
              'by_ai_reason': (same.groupby('ai_reason')
                               .agg(pairs=('ai_y', 'size'), lightgbm_says_different=('pred_lightgbm', lambda v: 1 - v.mean()),
                                    baseline_says_different=('pred_baseline', lambda v: 1 - v.mean()),
                                    lightgbm_median_proba=('proba_lightgbm', 'median'))
                               .sort_values('pairs', ascending=False).round(3).to_dict(orient='index'))}

    result = {
        'NOTE': 'AI PROXY, NOT TIER 1 and NOT human labels. Labels by Claude (claude-opus-5-5), blind, 2026-09-25. '
                'Tier 1 stays NOT MEASURABLE until humans label the review page.',
        'model_scored': model_name,
        'file_check': check,
        'ai_label_counts': ai.ai_label.value_counts().to_dict(),
        'ai_labels_by_hidden_stratum': strata,
        'ai_proxy_scores_NOT_TIER1': proxy,
        'false_positives_by_ai_reason_NOT_TIER1': errors.to_dict(orient='index'),
        'false_negatives_on_ai_same_NOT_TIER1': missed,
        'human_agreement': human_agreement(df),
        'thresholds_from_trainer': {'lightgbm': params['threshold_lightgbm'], 'baseline': params['baseline']},
    }
    print(json.dumps(result, indent=1, default=str))
    if not save:
        return result

    out = pd.DataFrame({
        'observation_key': df.observation_key, 'data_status': 'REAL', 'observation_key_b': df.observation_key_b,
        'batch_row': df.batch_row, 'stratum': df.stratum, 'key_a': df.key_a, 'key_b': df.key_b,
        'label_source': 'AI_REVIEW_NOT_HUMAN', 'ai_label': df.ai_label, 'ai_confidence': df.ai_confidence,
        'ai_reason': df.ai_reason, 'trivial_pair': trivial(df), 'human_label': df.label, 'proba_lightgbm': df.proba_lightgbm,
        'pred_lightgbm': df.pred_lightgbm, 'baseline_score': df.baseline_score, 'pred_baseline': df.pred_baseline})
    for c in extra:
        out[c] = df[c].to_numpy()
    # the claim scope must follow the model being scored: v2 was trained partly on constructed (SYNTHETIC) rows
    mix = json.loads((MODELS_DIR / model_name / 'manifest.json').read_text(encoding='utf-8'))['training_row_mix']
    scored_model_training = pd.DataFrame({'data_status': ['REAL'] * mix['REAL'] + ['SYNTHETIC'] * mix['SYNTHETIC']})
    save_model_outputs(out_name, out, {'evaluates': model_name, 'ai_review_file': str(AI_FILE.relative_to(L.ROOT)),
                                       'bootstrap_resamples': BOOT, 'seed': SEED,
                                       'min_agreement_pairs': MIN_AGREEMENT_PAIRS},
                       result, training_data=scored_model_training, split={'fit': f'nothing (scores reused from {model_name})',
                                                         'evaluated_on': 'MATCH_REVIEW_PRIORITY.csv, reserved test keys'},
                       target='same_product per AI review (NOT human, NOT tier 1)',
                       training_source=f'outputs/models/{model_name}/predictions.parquet + src/matching/ai_review_data.txt',
                       notes=f'AI PROXY check of {model_name}. Not tier 1: labels are an AI reviewer\'s, blind. '
                             'Meaningful only alongside human_agreement.')
    return result


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', choices=sorted(MODELS), default='v1')
    run(model=ap.parse_args().model)
