"""
check_claims.py — headline numbers in the docs, each checked against the saved output it came from.

    python scripts/check_claims.py      # prints the ledger, writes outputs/audit/claims_ledger.json, exit 1 if any fails

WHY
  On 2026-10-13 a line in CLAUDE.md and a table in docs/MATCHER_v1.md ("LightGBM recalls 0 of 53") turned out to
  describe an earlier run than the saved output, which says 4 of 53. Nothing compared docs with outputs. This does.

A CLAIM is a short quote that must appear in a doc (whitespace-insensitive), plus the numbers in it. Each number names
the JSON file and path it must equal once rounded to the precision the doc quotes. A claim's status is
  ok             every number matches
  stale          a number no longer rounds to the saved value: update the doc, or find out why the output moved
  quote_missing  the doc no longer contains the quote: the text moved on, update the registry below
  not_built      the output file does not exist yet (never counted as passing)

Scope: the README headline table, the regression values and the 2026-10-13 additions. It is a registry, so it covers
what is listed here and nothing else; a number that is not registered is not checked.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs' / 'audit' / 'claims_ledger.json'


def M(model: str) -> str:
    return f'outputs/models/{model}/metrics.json'


EVAL = 'outputs/analyst/eval_report.json'
NV = ['ai_proxy_scores_NOT_TIER1', 'name_variation_only']
V2 = M('product_matcher_v2')
V2AI = M('product_matcher_v2_ai_proxy_check')
AUDIT = M('real_store_label_audit')
PLAN = M('collection_planner')
LOFO = ['leave_one_family_out']


def _policy(name):
    return lambda m: next(p for p in m['policies'] if p['policy'] == name)['reduction_vs_none_pct']


def _power(shift):
    return lambda m: next(r for r in m['positive_control_planted_eta_shift']
                          if r['planted_eta_shift_minutes'] == shift)['detected_share_at_5pct']


# (doc, quote, [(quoted number, file, path or function of the loaded JSON, multiplier)])
CLAIMS = [
    ('README.md', 'test MAE 9.66 vs naive 10.56 (+8.5%)',
     [('9.66', M('price_forecast_lgbm'), ['test', 'model', 'mae'], 1),
      ('10.56', M('price_forecast_lgbm'), ['test', 'baseline_naive', 'mae'], 1),
      ('8.5', M('price_forecast_lgbm'), ['test', 'skill_vs_naive'], 100)]),
    ('CLAUDE.md', 'test MAE 10.56 vs 11.41',
     [('10.56', M('price_forecast_lgbm'), ['test', 'baseline_naive', 'mae'], 1),
      ('11.41', M('price_forecast_lgbm'), ['test', 'baseline_price_avg_to_date', 'mae'], 1)]),
    ('README.md', '"will drop" radar 78% precision at 5%',
     [('78', M('price_direction'), ['price_drop_radar', 0, 'precision_model'], 100)]),
    ('README.md', '6× lift at 1% alerts', [('6', M('stockout_classifier'), ['stockout_radar', 'model', 0, 'lift'], 1)]),
    ('README.md', 'finds a real, known pack_qty defect at 70% precision@100',
     [('70', M('anomaly_real'), ['detector_eval_vs_known_defect', 'unit_price_z (|z|)', 'precision_at_100'], 100)]),
    ('README.md', 'frailty model recovers Weibull k = 1.98 (planted 2) where pooled curves say 1.38',
     [('1.98', M('stockout_survival'), ['parameter_recovery', 0, 'estimate'], 1),
      ('1.38', M('stockout_survival'), ['parameter_recovery', 2, 'estimate'], 1)]),
    ('README.md', '(adjusted Rand 1.0)',
     [('1.0', M('restock_interval'), ['recovery', 'latent_groups', 'adjusted_rand_vs_planted'], 1)]),
    ('README.md', 'indirect inference recovers 0.451 / 0.296 / 0.357',
     [('0.451', M('price_response'), ['response_recovery', 0, 'corrected_beta'], 1),
      ('0.296', M('price_response'), ['response_recovery', 1, 'corrected_beta'], 1),
      ('0.357', M('price_response'), ['response_recovery', 2, 'corrected_beta'], 1)]),
    ('README.md', '2.6× popularity at recovering hidden real listings',
     [('2.6', M('assortment_gaps'), ['hybrid_vs_popularity_recall@100'], 1)]),
    ('README.md', 'ignoring competitor response understates the needed cut by 1.62×',
     [('1.62', M('optimize_price_cut'), ['median_strategic_over_static'], 1)]),
    ('README.md', '−26.7% out-of-stock exposure',
     [('26.7', M('optimize_restock_priority'), _policy('priority_index'), 1)]),
    ('CLAUDE.md', 'the priority index cuts OOS exposure 26.7%',
     [('26.7', M('optimize_restock_priority'), _policy('priority_index'), 1)]),
    ('README.md', '+6.7 pp lost-wins cut for 1.3 pp exposure',
     [('6.7', M('optimize_restock_objective'), ['paired_vs_plain_index', '0.75', 'J2_gain_pp'], 1),
      ('1.3', M('optimize_restock_objective'), ['paired_vs_plain_index', '0.75', 'J1_cost_pp'], 1)]),
    ('README.md', 'followers soften a Blinkit raise 1.42×',
     [('1.42', M('simulate_grid'), ['raise_static_over_strategic_loss_median'], 1)]),
    ('README.md', '25/25 on a held-out question set (42/42 tuning)',
     [('25', EVAL, ['offline', 'holdout_set', 'summary', 'passed'], 1),
      ('25', EVAL, ['offline', 'holdout_set', 'summary', 'questions'], 1),
      ('42', EVAL, ['offline', 'tuning_set', 'summary', 'passed'], 1),
      ('42', EVAL, ['offline', 'tuning_set', 'summary', 'questions'], 1)]),
    ('CLAUDE.md', 'Gallery: 9/9 baselines pass',
     [('9', M('listing_chain'), ['baseline_checks_passed'], 1), ('9', M('listing_chain'), ['n_listings'], 1)]),
    ('docs/audit/AUDIT_2026-10-13.md', '9 of 9 gallery baselines pass',
     [('9', M('listing_chain'), ['baseline_checks_passed'], 1), ('9', M('listing_chain'), ['n_listings'], 1)]),
    ('docs/audit/AUDIT_2026-10-13.md', 'MAE 1.52 against 1.55 for the best baseline; 90% intervals cover 90.1%',
     [('1.52', M('eta_forecast'), ['test', 'model', 'mae'], 1),
      ('1.55', M('eta_forecast'), ['test', 'listing same-hour mean to date', 'mae'], 1),
      ('90.1', M('eta_forecast'), ['conformal_intervals', '90%', 'marginal_cqr_test_coverage'], 100)]),
    # the regression values: the planner recomputes them from the common panel with its own code
    ('CLAUDE.md', '| Flipkart Minutes | 56.6% | −5.34% |',
     [('56.6', PLAN, ['quantities', 'cheapest_share', 'full_panel_value'], 1),
      ('5.34', PLAN, lambda m: -m['quantities']['price_gap']['full_panel_value'], 1)]),
    # ---- matcher: the corrected v1 AI-proxy line, and v2
    ('CLAUDE.md', 'LightGBM finds 4 of 53 AI-same pairs and PR-AUC is at chance (0.222 vs 0.225; baseline 0.228)',
     [('4', M('product_matcher_ai_proxy_check'), lambda m: _get(m, NV + ['lightgbm', 'recall']) * _get(m, NV + ['ai_same']), 1),
      ('53', M('product_matcher_ai_proxy_check'), NV + ['ai_same'], 1),
      ('0.222', M('product_matcher_ai_proxy_check'), NV + ['lightgbm', 'pr_auc'], 1),
      ('0.225', M('product_matcher_ai_proxy_check'), NV + ['chance_pr_auc'], 1),
      ('0.228', M('product_matcher_ai_proxy_check'), NV + ['baseline', 'pr_auc'], 1)]),
    ('docs/MATCHER_v2.md', '| **v2** | **+ constructed** | **99.9%** | **100.0%** | **1.000** |',
     [('99.9', V2, ['ablation_2x2', 'D_v2feats_constructed', 'behaviour_on_test_keys', 'same_pass_rate'], 100),
      ('100.0', V2, ['ablation_2x2', 'D_v2feats_constructed', 'behaviour_on_test_keys', 'different_pass_rate'], 100),
      ('1.000', V2, ['ablation_2x2', 'D_v2feats_constructed', 'behaviour_on_test_keys', 'separability_auc_name_edits'], 1)]),
    ('docs/MATCHER_v2.md', '| number changed | different | 85.3% | 3.5% |',
     [('85.3', V2, LOFO + ['number changed', 'pass_rate_family_never_trained_on'], 100),
      ('3.5', V2, LOFO + ['number changed', 'pass_rate_with_v1_features_only'], 100)]),
    ('docs/MATCHER_v2.md', '| variant word swapped | different | 98.6% | 9.6% |',
     [('98.6', V2, LOFO + ['variant word swapped', 'pass_rate_family_never_trained_on'], 100),
      ('9.6', V2, LOFO + ['variant word swapped', 'pass_rate_with_v1_features_only'], 100)]),
    ('docs/MATCHER_v2.md', '| **alias bracket** | same | **0.3%** | 1.7% |',
     [('0.3', V2, LOFO + ['alias bracket', 'pass_rate_family_never_trained_on'], 100),
      ('1.7', V2, LOFO + ['alias bracket', 'pass_rate_with_v1_features_only'], 100)]),
    ('README.md', '98.6% on variant swaps where similarity features reach 9.6%',
     [('98.6', V2, LOFO + ['variant word swapped', 'pass_rate_family_never_trained_on'], 100),
      ('9.6', V2, LOFO + ['variant word swapped', 'pass_rate_with_v1_features_only'], 100)]),
    ('README.md', 'abstains on 33.1% of unlabelled real pairs',
     [('33.1', V2, lambda m: 1 - m['support_on_unlabelled_real_pairs']['in_support_share'], 100)]),
    ('CLAUDE.md', '7,847 different, 70 same, 3,917 abstain',
     [('7847', V2, ['support_on_unlabelled_real_pairs', 'decisions', 'different'], 1),
      ('70', V2, ['support_on_unlabelled_real_pairs', 'decisions', 'same'], 1),
      ('3917', V2, ['support_on_unlabelled_real_pairs', 'decisions', 'abstain'], 1)]),
    ('docs/MATCHER_v2.md', '| **v2, gated** | **0.84** | 0.30 | 0.44 | **1.6%** | 0.705 |',
     [('0.84', V2AI, NV + ['lightgbm', 'precision'], 1), ('0.30', V2AI, NV + ['lightgbm', 'recall'], 1),
      ('0.44', V2AI, NV + ['lightgbm', 'f1'], 1), ('1.6', V2AI, NV + ['lightgbm', 'false_positive_rate'], 100),
      ('0.705', V2AI, NV + ['lightgbm', 'pr_auc'], 1)]),
    ('CLAUDE.md', 'gated v2 0.84 precision / 0.30 recall / PR-AUC 0.705',
     [('0.84', V2AI, NV + ['lightgbm', 'precision'], 1), ('0.30', V2AI, NV + ['lightgbm', 'recall'], 1),
      ('0.705', V2AI, NV + ['lightgbm', 'pr_auc'], 1)]),
    # ---- store-label audit
    ('docs/STORE_LABEL_AUDIT_v1.md', '| records of one name\\|pack that sit in the same store | 21.0% | 21.9% | 0.007 |',
     [('21.0', AUDIT, ['permutation_tests', 'same_key_pairs_in_same_store_share', 'observed'], 100),
      ('21.9', AUDIT, ['permutation_tests', 'same_key_pairs_in_same_store_share', 'null_mean'], 100),
      ('0.007', AUDIT, ['permutation_tests', 'same_key_pairs_in_same_store_share', 'p_permutation'], 1)]),
    ('README.md', 'fall in the same store in 21.0% of pairs; a label independent of the product gives 21.9%',
     [('21.0', AUDIT, ['permutation_tests', 'same_key_pairs_in_same_store_share', 'observed'], 100),
      ('21.9', AUDIT, ['permutation_tests', 'same_key_pairs_in_same_store_share', 'null_mean'], 100)]),
    ('docs/STORE_LABEL_AUDIT_v1.md', 'It detects 0.2 minutes 99% of the time and 0.1 minutes 46% of the time.',
     [('99', AUDIT, _power(0.2), 100), ('46', AUDIT, _power(0.1), 100)]),
    ('CLAUDE.md', 'given one is out of stock another is out 47.1% of the time, 6.4x the 7.4% rate; a shuffle within '
                  'category gives 10.1%',
     [('47.1', AUDIT, ['record_level_anatomy', 'stock', 'p_other_record_out_given_one_out'], 100),
      ('6.4', AUDIT, ['record_level_anatomy', 'stock', 'lift_over_rate'], 1),
      ('7.4', AUDIT, ['record_level_anatomy', 'stock', 'out_of_stock_rate'], 100),
      ('10.1', AUDIT, ['record_level_anatomy', 'stock', 'null_shuffled_within_category', 'null_mean'], 100)]),
    ('CLAUDE.md', 'the same statistic is 0.73 on the SYNTHETIC rows',
     [('0.73', M('real_store_label_audit_synthetic_control'), ['permutation_tests', 'eta2_eta_minutes', 'observed'], 1)]),
    # ---- collection planner
    ('docs/COLLECTION_PLANNER_v1.md',
     '| Blinkit out-of-stock rate | 5.8% | ±1 pp | 14 days × 128 products (80 h) | 14 days (80 h) |',
     [('5.8', PLAN, ['quantities', 'oos_rate', 'full_panel_value'], 1),
      ('14', PLAN, ['quantities', 'oos_rate', 'smallest_identifying_design', 'days'], 1),
      ('128', PLAN, ['quantities', 'oos_rate', 'smallest_identifying_design', 'products'], 1),
      ('80', PLAN, ['quantities', 'oos_rate', 'smallest_identifying_design', 'hours_at_assumed_speed'], 1)]),
    ('docs/COLLECTION_PLANNER_v1.md',
     'biased by −1.28 snapshots in a 2-day panel, −0.34 at 7 days, −0.11 at 14 and −0.05 at 21',
     [('1.28', PLAN, lambda m: -m['bias_from_a_short_window_at_1000_products']['restock_mean']['2'], 1),
      ('0.34', PLAN, lambda m: -m['bias_from_a_short_window_at_1000_products']['restock_mean']['7'], 1),
      ('0.11', PLAN, lambda m: -m['bias_from_a_short_window_at_1000_products']['restock_mean']['14'], 1),
      ('0.05', PLAN, lambda m: -m['bias_from_a_short_window_at_1000_products']['restock_mean']['21'], 1)]),
    ('CLAUDE.md', 'bias -1.28 snapshots at 2 days, -0.11 at 14',
     [('1.28', PLAN, lambda m: -m['bias_from_a_short_window_at_1000_products']['restock_mean']['2'], 1),
      ('0.11', PLAN, lambda m: -m['bias_from_a_short_window_at_1000_products']['restock_mean']['14'], 1)]),
]


def _get(obj, path):
    for k in path:
        obj = obj[k]
    return obj


def _squash(text: str) -> str:
    return re.sub(r'\s+', ' ', text)


def check_number(quoted: str, data, path, mult: float) -> dict:
    actual = (path(data) if callable(path) else _get(data, path)) * mult
    decimals = len(quoted.split('.')[1]) if '.' in quoted else 0
    ok = abs(float(actual) - float(quoted)) <= 0.5 * 10 ** (-decimals) + 1e-9
    return {'quoted': quoted, 'saved_value': round(float(actual), decimals + 2), 'ok': bool(ok),
            'path': 'computed' if callable(path) else '.'.join(str(k) for k in path)}


def ledger() -> list[dict]:
    docs, files, rows = {}, {}, []
    for doc, quote, numbers in CLAIMS:
        if doc not in docs:
            docs[doc] = _squash((ROOT / doc).read_text(encoding='utf-8'))
        row = {'doc': doc, 'quote': quote, 'numbers': []}
        missing = sorted({f for _, f, _, _ in numbers if not (ROOT / f).exists()})
        if _squash(quote) not in docs[doc]:
            row['status'] = 'quote_missing'
        elif missing:
            row['status'], row['missing_outputs'] = 'not_built', missing
        else:
            for quoted, f, path, mult in numbers:
                if f not in files:
                    files[f] = json.loads((ROOT / f).read_text(encoding='utf-8'))
                try:
                    row['numbers'].append({**check_number(quoted, files[f], path, mult), 'file': f})
                except (KeyError, IndexError, StopIteration, TypeError) as e:
                    row['numbers'].append({'quoted': quoted, 'file': f, 'ok': False, 'error': f'path not found: {e!r}'})
            row['status'] = 'ok' if all(n['ok'] for n in row['numbers']) else 'stale'
        rows.append(row)
    return rows


def main() -> int:
    rows = ledger()
    counts = {s: sum(r['status'] == s for r in rows) for s in ('ok', 'stale', 'quote_missing', 'not_built')}
    for r in rows:
        if r['status'] != 'ok':
            print(f"{r['status'].upper():<14} {r['doc']}: {r['quote'][:90]}")
            for n in r['numbers']:
                if not n['ok']:
                    print(f"               quoted {n['quoted']}, saved {n.get('saved_value', n.get('error'))}  ({n['file']})")
    numbers = sum(len(r['numbers']) for r in rows)
    print(f"claims: {len(rows)} | numbers checked: {numbers} | " + ' | '.join(f'{k} {v}' for k, v in counts.items()))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({'claims': len(rows), 'numbers_checked': numbers, 'counts': counts, 'rows': rows},
                              indent=1, ensure_ascii=False), encoding='utf-8')
    return 1 if counts['stale'] or counts['quote_missing'] else 0


if __name__ == '__main__':
    sys.exit(main())
