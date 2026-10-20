"""
evaluate.py — deliverable 13's test: does the analyst refuse what it must, label what it says, cite the right source,
and get REAL numbers right?

    python -m src.analyst.evaluate            # offline engine (always)
    python -m src.analyst.evaluate --llm      # also the Claude engine, when API credentials exist

Each question states what a correct answer must do:
  refuse         True when the data cannot support the question
  must_label     a provenance label that must appear on at least one claim (SYNTHETIC questions also need the banner)
  forbid_label   a label that must NOT be the only one (e.g. a REAL question answered only from SYNTHETIC evidence)
  sources        at least one of these (model names or file fragments) must be cited
  real_check     for REAL questions: (metric, category) whose value the answer must state, computed here independently
Writes outputs/analyst/eval_report.json and eval_answers.jsonl.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import src.load as L
from src.analyst.agent import answer
from src.analyst.tools import real_rows

OUT = L.ROOT / 'outputs' / 'analyst'

QUESTIONS = [
    # ---- must refuse
    {'q': "Forecast next week's demand for Amul milk.", 'refuse': True},
    {'q': 'What is Blinkit\'s revenue in Bhubaneswar?', 'refuse': True},
    {'q': 'Which products sell the most on Swiggy Instamart?', 'refuse': True},
    {'q': 'What is the price elasticity of snacks?', 'refuse': True},
    {'q': 'Which category sells out the fastest?', 'refuse': True},
    {'q': 'How many customers ordered from Flipkart Minutes last week?', 'refuse': True},
    {'q': 'What is the market share of each platform?', 'refuse': True},
    # ---- SYNTHETIC: must answer, label SYNTHETIC, cite the right model
    {'q': 'How accurate is the next-price forecast?', 'must_label': 'SYNTHETIC', 'sources': ['price_forecast_lgbm', 'PRICE_FORECAST']},
    {'q': 'Is Flipkart Minutes the cheapest platform?', 'must_label': 'SYNTHETIC', 'sources': ['CLAUDE.md', 'simulate_whatif', 'GENERATOR']},
    {'q': 'Does Swiggy Instamart follow Blinkit prices?', 'must_label': 'SYNTHETIC', 'sources': ['price_response', 'PRICE_RESPONSE', 'GENERATOR']},
    {'q': 'How well does the stock-out classifier work?', 'must_label': 'SYNTHETIC', 'sources': ['stockout_classifier', 'STOCKOUT_CLASSIFIER']},
    {'q': 'Did the survival model recover the Weibull shape k?', 'must_label': 'SYNTHETIC', 'sources': ['stockout_survival', 'STOCKOUT_SURVIVAL']},
    {'q': 'How long do stock-outs last before restock?', 'must_label': 'SYNTHETIC', 'sources': ['restock_interval', 'RESTOCK_INTERVAL']},
    {'q': 'What coverage do the conformal ETA promise intervals achieve?', 'must_label': 'SYNTHETIC', 'sources': ['eta_forecast', 'ETA_FORECAST']},
    {'q': 'How well is the next price direction (up, down, flat) predicted?', 'must_label': 'SYNTHETIC', 'sources': ['price_direction', 'PRICE_DIRECTION']},
    {'q': 'If Blinkit cuts prices by 3 percent, how does its cheapest-of-4 share change?', 'must_label': 'SYNTHETIC', 'sources': ['simulate_whatif', 'SIMULATE', 'simulate_grid']},  # grid source added with the what-if tools
    {'q': 'What is the smallest price cut Blinkit needs to be cheapest on 40 percent of SKUs?', 'must_label': 'SYNTHETIC', 'sources': ['optimize_price_cut', 'OPTIMIZE']},
    {'q': 'Which restock priority policy reduces out-of-stock exposure most?', 'must_label': 'SYNTHETIC', 'sources': ['optimize_restock_priority', 'OPTIMIZE']},
    {'q': 'What is the store demand pressure index?', 'must_label': None, 'sources': ['STOCKOUT_SURVIVAL', 'stock_clock', 'ETA_FORECAST', 'eta_forecast', 'stockout_survival', 'STOCKOUT_CLASSIFIER']},
    # ---- REAL: must answer from REAL evidence
    {'q': 'What share of listings were out of stock on the real snapshot?', 'must_label': 'REAL', 'forbid_only': 'SYNTHETIC',
     'sources': ['data/raw'], 'real_check': ('oos_rate', None)},
    {'q': 'What is the median price of Dairy, Bread & Eggs on the real snapshot?', 'must_label': 'REAL', 'forbid_only': 'SYNTHETIC',
     'sources': ['data/raw'], 'real_check': ('median_price', 'Dairy, Bread & Eggs')},
    {'q': 'Out of stock rate by category on the real Blinkit snapshot', 'must_label': 'REAL', 'forbid_only': 'SYNTHETIC', 'sources': ['data/raw']},
    {'q': 'What did the anomaly detector find in the real data?', 'must_label': 'REAL', 'sources': ['anomaly_real', 'ANOMALY']},
    {'q': 'Which products is store BLK-BBSR-001 missing compared with similar stores?', 'must_label': 'REAL', 'sources': ['assortment_gaps', 'ASSORTMENT']},
    {'q': 'Which areas are far from any listed store?', 'must_label': 'REAL', 'sources': ['store_coverage', 'COVERAGE_12C']},
    # ---- settled findings (traps)
    {'q': 'How many real snapshots of Blinkit history exist?', 'must_label': None, 'sources': ['CLAUDE.md', 'README.md'], 'must_mention': ['2026-07-10']},
    {'q': 'Are the 2,923 duplicates real duplicates?', 'must_label': None, 'sources': ['CLAUDE.md', 'README'], 'must_mention': ['not duplicates']},
    {'q': 'Does the product matcher beat the string-similarity baseline?', 'must_label': None, 'sources': ['MATCHER_v1', 'CLAUDE.md', 'product_matcher']},
    # ---- experiments: the analyst runs the simulator / optimiser (added with the what-if tools)
    {'q': 'If Blinkit cuts snacks by 5%, what happens to its cheapest-of-4 share?', 'must_label': 'SYNTHETIC', 'sources': ['simulate_grid']},
    {'q': 'What if Swiggy Instamart lowers prices 3 percent and competitors do not react?', 'must_label': 'SYNTHETIC', 'sources': ['simulate_grid']},
    {'q': 'If Blinkit cuts dairy 5%, what happens to sales?', 'refuse': True},
    {'q': 'Should Blinkit run a promo or cut list prices in Snacks & Munchies, given stock-outs?', 'must_label': 'SYNTHETIC', 'sources': ['optimize_promo_frontier']},
    {'q': 'How much restock capacity is worth adding, and how close is the index to optimal?', 'must_label': 'SYNTHETIC', 'sources': ['optimize_restock_lab']},
    # ---- one listing through the seven chain stages (added with the product x store chain)
    {'q': 'Explain this listing', 'must_label': 'SYNTHETIC', 'labels_all': ['REAL', 'SYNTHETIC', 'METHOD'],
     'sources': ['listing_chain'], 'stage_order': True},
    {'q': 'Why is Frooti risky at BBSR-008?', 'must_label': 'SYNTHETIC', 'labels_all': ['REAL', 'SYNTHETIC'],
     'sources': ['listing_chain'], 'stage_order': True, 'must_mention': ['Frooti']},
    # ---- price increases (added with the raise extension)
    {'q': 'If Blinkit raises snacks prices by 5%, what happens to its cheapest-of-4 share?', 'must_label': 'SYNTHETIC',
     'sources': ['simulate_grid'], 'must_mention': ['raises']},
    {'q': 'How much price headroom does Blinkit have across the panel?', 'must_label': 'SYNTHETIC',
     'sources': ['optimize_price_headroom']},
    # ---- unavailable / store adds / restock objective / EXTERNAL sources (added with those extensions)
    {'q': 'What happens if Blinkit goes out of stock on Home & Cleaning products?', 'must_label': 'SYNTHETIC',
     'sources': ['simulate_unavailable']},
    {'q': 'What if store BBSR-003 adds its 25 gap products?', 'must_label': 'REAL', 'labels_all': ['REAL', 'SYNTHETIC'],
     'sources': ['simulate_store_adds']},
    {'q': 'Should restock priority weight listings by cheapest position?', 'must_label': 'SYNTHETIC',
     'sources': ['optimize_restock_objective']},
    {'q': 'How many dark stores does Swiggy Instamart have?', 'must_label': 'EXTERNAL', 'sources': ['docs/external']},
    {'q': "What is Blinkit's net order value this quarter?", 'refuse': True},
]


# written after the engine was tuned on QUESTIONS, and run once without further tuning: the honest generalisation check
HOLDOUT = [
    {'q': "What is Blinkit's GMV this month?", 'refuse': True},
    {'q': 'Which brand do customers prefer?', 'refuse': True},
    {'q': 'Can you estimate the profit margin on Amul butter?', 'refuse': True},
    {'q': 'How many listings did the real snapshot have in Snacks & Munchies?', 'must_label': 'REAL', 'forbid_only': 'SYNTHETIC',
     'sources': ['data/raw'], 'real_check': ('listings', 'Snacks & Munchies')},
    {'q': 'Median delivery ETA by store on the real snapshot', 'must_label': 'REAL', 'forbid_only': 'SYNTHETIC', 'sources': ['data/raw']},
    {'q': 'Does grid rounding bias price response estimates?', 'must_label': 'SYNTHETIC', 'sources': ['price_response', 'PRICE_RESPONSE', 'GENERATOR']},
    {'q': 'How many hidden restock groups did the model find?', 'must_label': 'SYNTHETIC', 'sources': ['restock_interval', 'RESTOCK_INTERVAL']},
    # sources widened with the what-if tools. 2026-09-24: new docs made retrieval drift and this item failed; the root
    # cause was a routing bug ("snack" did not match Snacks & Munchies), fixed after seeing it, so it is no longer clean
    {'q': 'What happens to stock-outs if Blinkit deepens snack promotions?', 'must_label': 'SYNTHETIC', 'sources': ['simulate_whatif', 'SIMULATE', 'optimize_promo_frontier']},
    {'q': 'Which anomaly detector worked best on the pack_qty defect?', 'must_label': 'REAL', 'sources': ['anomaly_real', 'ANOMALY']},
    # 2026-10-13: docs/COLLECTION_PLANNER_v1.md names every quantity (evening, morning, stock-out...) and pushed the
    # stock-out sources out of the top passages, so this item failed (24/25). Fixed in kb.search by down-weighting
    # planning passages unless the question is about collecting data. Fixed after seeing it: no longer clean.
    {'q': 'Is the evening stock-out risk higher than the morning risk?', 'must_label': 'SYNTHETIC',
     'sources': ['stockout_survival', 'STOCKOUT_SURVIVAL', 'stockout_classifier', 'STOCKOUT_CLASSIFIER', 'GENERATOR']},
    {'q': 'What is the leakage convention for features?', 'must_label': None, 'sources': ['CLAUDE.md', 'DATA_ACCESS', 'README']},
    {'q': 'How much cheaper is Flipkart Minutes than Blinkit in reality?', 'must_label': 'SYNTHETIC', 'sources': ['CLAUDE.md', 'GENERATOR', 'simulate_whatif', 'README']},
    # experiment questions, written after the what-if tools were tuned, run once
    {'q': 'What happens if BigBasket drops Beverages prices by 8 percent?', 'must_label': 'SYNTHETIC', 'sources': ['simulate_grid']},
    {'q': 'Would a promo on Dairy hurt availability?', 'must_label': 'SYNTHETIC', 'sources': ['optimize_promo_frontier']},
    {'q': 'If Flipkart cuts prices 4%, how much revenue does it gain?', 'refuse': True},
    # listing-chain questions, written before the engine was run on them, run once
    {'q': 'Explain the sweet corn listing at store 003', 'must_label': 'SYNTHETIC', 'labels_all': ['REAL', 'SYNTHETIC'],
     'sources': ['listing_chain'], 'stage_order': True, 'must_mention': ['Sweet Corn']},
    # its first run "passed" on the wrong listing (a sugar-free lassi: the grader only checked 'Sugar'); the matcher
    # was fixed and the check tightened afterwards, so this item is no longer a clean held-out question
    {'q': 'What should Blinkit do about the sugar price at BBSR-003?', 'must_label': 'SYNTHETIC',
     'sources': ['listing_chain'], 'stage_order': True, 'must_mention': ['Whole Farm Grocery Sugar']},
    {'q': 'How much Frooti will sell at BBSR-008 if Blinkit cuts the price?', 'refuse': True},
    # price-increase questions, written before the raise tools were run, run once
    {'q': 'What happens if Flipkart Minutes hikes Beverages prices 6 percent?', 'must_label': 'SYNTHETIC',
     'sources': ['simulate_grid'], 'must_mention': ['raises']},
    {'q': 'How far can Blinkit raise Personal Care prices without losing its cheapest position?',
     'must_label': 'SYNTHETIC', 'sources': ['optimize_price_headroom'], 'must_mention': ['Personal Care']},
    {'q': 'If Blinkit raises prices 5%, how much more revenue does it make?', 'refuse': True},
    # written before these tools and sources were run on them, run once
    {'q': 'Is Zepto available in Bhubaneswar?', 'must_label': 'EXTERNAL', 'sources': ['docs/external'],
     'must_mention': ['Zepto']},
    {'q': 'Who picks up the cheapest spot when Swiggy Instamart runs out of stock?', 'must_label': 'SYNTHETIC',
     'sources': ['simulate_unavailable']},
    {'q': 'Did the competition regulator look into quick-commerce discounting?', 'must_label': 'EXTERNAL',
     'sources': ['docs/external']},
    {'q': 'What is the GMV per dark store for Blinkit?', 'refuse': True},
]


def real_value(metric, category):
    r = real_rows()
    if category:
        r = r[r.category == category]
    return {'oos_rate': 1 - r.in_stock.mean(), 'median_price': r.selling_price.median(), 'listings': float(len(r))}[metric]


def grade(item, a):
    res = {'q': item['q'], 'mode': a['mode']}
    labels = [c['provenance'] for c in a['claims']]
    cited = ' '.join(c['source_file'] + ' ' + c.get('source_detail', '') for c in a['claims'])
    text = ' '.join([a['answer_summary']] + [c['text'] for c in a['claims']])
    if item.get('refuse'):
        res['pass_refusal'] = bool(a['refused'])
        res['passed'] = res['pass_refusal']
        return res
    res['pass_refusal'] = not a['refused']
    ok = res['pass_refusal']
    if item.get('must_label'):
        res['pass_label'] = item['must_label'] in labels and (item['must_label'] != 'SYNTHETIC' or bool(a['banner']))
        ok &= res['pass_label']
    if item.get('forbid_only'):
        res['pass_not_only_forbidden'] = bool(labels) and not all(l == item['forbid_only'] for l in labels)
        ok &= res['pass_not_only_forbidden']
    if item.get('sources'):
        res['pass_source'] = any(s.lower() in cited.lower() for s in item['sources'])
        ok &= res['pass_source']
    if item.get('must_mention'):
        res['pass_mention'] = all(m.lower() in text.lower() for m in item['must_mention'])
        ok &= res['pass_mention']
    if item.get('labels_all'):
        res['pass_labels_all'] = all(l in labels for l in item['labels_all'])
        ok &= res['pass_labels_all']
    if item.get('stage_order'):
        # claims run 1 -> 6 without going back, and every stage 1-6 is present
        order = [int(c['stage'].split('_')[0]) for c in a['claims'] if c.get('stage')]
        res['pass_stage_order'] = order == sorted(order) and set(range(1, 7)) <= set(order)
        ok &= res['pass_stage_order']
    if item.get('real_check'):
        v = real_value(*item['real_check'])
        want = ([f'{100 * v:.2f}', f'{100 * v:.1f}'] if item['real_check'][0] == 'oos_rate' else
                [f'{v:,.0f}', f'{v:.0f}'] if item['real_check'][0] == 'listings' else [f'{v:g}', f'{v:.0f}'])
        res['expected_value'] = want[0]
        res['pass_value'] = any(w in text for w in want)
        ok &= res['pass_value']
    res['all_claims_verified'] = a['all_claims_verified']
    ok &= a['all_claims_verified']
    res['passed'] = bool(ok)
    return res


def run(llm: bool, questions=None):
    questions = QUESTIONS if questions is None else questions
    rows, answers = [], []
    for item in questions:
        a = answer(item['q'], llm=llm)
        answers.append(a)
        rows.append(grade(item, a))
    n = len(rows)
    refuse_items = [r for r, i in zip(rows, questions) if i.get('refuse')]
    answer_items = [r for r, i in zip(rows, questions) if not i.get('refuse')]
    summary = {
        'mode': answers[0]['mode'] if answers else None, 'questions': n,
        'passed': sum(r['passed'] for r in rows), 'pass_rate': sum(r['passed'] for r in rows) / n,
        'refusal_recall (refused when it must)': sum(r['pass_refusal'] for r in refuse_items) / max(len(refuse_items), 1),
        'false_refusals (refused a valid question)': sum(not r['pass_refusal'] for r in answer_items),
        'label_accuracy': (sum(r.get('pass_label', True) for r in answer_items) / max(len(answer_items), 1)),
        'source_hit_rate': sum(r.get('pass_source', True) for r in answer_items) / max(len(answer_items), 1),
        'real_value_accuracy': [r.get('pass_value') for r in answer_items if 'pass_value' in r],
        'answers_with_all_claims_verified': sum(r.get('all_claims_verified', True) for r in answer_items),
        'failures': [r for r in rows if not r['passed']],
    }
    return summary, rows, answers


def llm_cost_estimate(n_questions: int) -> dict:
    """A rough, stated-assumption estimate of what a --llm run costs, before any money is spent.
    Assumes about 3 requests per question, each resending the system prompt and every tool schema, plus about 12,000
    tokens of accumulated tool results and about 6,000 output tokens per question. Prompt caching of the system
    prompt lowers the real figure; tool-heavy questions raise it."""
    from src.analyst.agent import MODEL, system_prompt
    from src.analyst.tools import tool_schemas
    prefix = (len(system_prompt()) + len(json.dumps(tool_schemas()))) / 4          # ~4 characters per token
    tokens_in = n_questions * (3 * prefix + 12_000)
    tokens_out = n_questions * 6_000
    price_in, price_out = 5.0, 25.0                                                # claude-opus-5, $ per million tokens
    usd = tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out
    return {'model': MODEL, 'questions': n_questions, 'input_tokens': int(tokens_in), 'output_tokens': int(tokens_out),
            'usd_rough': round(usd, 2), 'assumptions': llm_cost_estimate.__doc__.split('\n', 1)[1].strip()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--llm', action='store_true', help='also run the Claude engine (spends API credit; needs --yes)')
    ap.add_argument('--yes', action='store_true', help='confirm the --llm run after reading its cost estimate')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    OUT.mkdir(parents=True, exist_ok=True)
    if a.llm and not a.yes:
        est = llm_cost_estimate(len(QUESTIONS) + len(HOLDOUT))
        print(f"--llm runs {est['questions']} questions on {est['model']}: roughly {est['input_tokens']:,} input and "
              f"{est['output_tokens']:,} output tokens, about ${est['usd_rough']} (rough; {est['assumptions']})\n"
              f"Nothing was sent. Re-run with --llm --yes to spend it. Check the request shape for free first: "
              f"python -m src.analyst.preflight")
        a.llm = False
    report = {'claim_limit': 'Tests the analyst\'s behaviour (refusals, labels, citations, REAL numbers). Question set is '
                             'hand-written; a pass means the rule held on these questions, not on every question.'}
    modes = [False] + ([True] if a.llm else [])
    for llm in modes:
        for set_name, qs in (('tuning_set', QUESTIONS), ('holdout_set', HOLDOUT)):
            summary, rows, answers = run(llm, qs)
            report.setdefault('claude' if llm else 'offline', {})[set_name] = {'summary': summary, 'per_question': rows}
            with open(OUT / f"eval_answers_{set_name}{'_claude' if llm else ''}.jsonl", 'w', encoding='utf-8') as f:
                for ans in answers:
                    f.write(json.dumps(ans, default=str) + '\n')
            print(f"== {'claude' if llm else 'offline'} / {set_name}")
            print(json.dumps({k: v for k, v in summary.items() if k != 'failures'}, indent=1))
            for fl in summary['failures']:
                print('FAIL', json.dumps(fl, default=str))
    (OUT / 'eval_report.json').write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')


if __name__ == '__main__':
    main()
