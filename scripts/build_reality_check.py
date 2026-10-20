"""
build_reality_check.py — one page for the three additions of 2026-10-13, built from saved outputs only.

    python scripts/build_reality_check.py      # -> outputs/showcase/reality_check.html

Tabs: the store-label audit (REAL), matcher v2 (constructed edits, gate, AI proxy), and the collection planner
(SYNTHETIC planning prior, interactive). Every number comes from outputs/models/*/metrics.json; nothing is recomputed.
"""
import json
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / 'outputs' / 'models'
OUT = ROOT / 'outputs' / 'showcase' / 'reality_check.html'

TESTS = {
    'eta2_eta_minutes': 'Delivery time varies by store',
    'eta2_log_price': 'Price level varies by store',
    'eta2_in_stock': 'Stock-out rate varies by store',
    'chi2_category_x_store': 'Category mix differs by store',
    'chi2_subcategory_x_store': 'Subcategory mix differs by store',
    'chi2_brand_x_store': 'Brand mix differs by store',
    'chi2_eta_value_x_store': 'Delivery-time values differ by store',
    'chi2_price_decile_x_store': 'Price bands differ by store',
    'same_key_pairs_in_same_store_share': "One product's records share a store",
    'store_changes_along_source_id': 'Neighbouring source rows share a store',
}
QUANTITIES = {
    'price_gap': ('Flipkart Minutes price gap', 'pp', '%'),
    'cheapest_share': ('Flipkart Minutes cheapest-of-4 share', 'pp', '%'),
    'oos_rate': ('Blinkit out-of-stock rate', 'pp', '%'),
    'restock_mean': ('Mean out-of-stock spell', 'snapshots', ' snapshots'),
    'hazard_ratio': ('Stock-out hazard, long run over short', '', '×'),
    'response_beta': ("Instamart's response to Blinkit", '', ''),
    'evening_eta': ('Blinkit evening ETA minus morning', 'min', ' min'),
}


def load(name: str) -> dict:
    return json.loads((MODELS / name / 'metrics.json').read_text(encoding='utf-8'))


def payload() -> dict:
    audit, ctrl = load('real_store_label_audit'), load('real_store_label_audit_synthetic_control')
    v2, ai1, ai2 = load('product_matcher_v2'), load('product_matcher_ai_proxy_check'), load('product_matcher_v2_ai_proxy_check')
    plan = load('collection_planner')
    grid = pd.read_parquet(MODELS / 'collection_planner' / 'predictions.parquet')

    an = audit['record_level_anatomy']
    sv = an['same_store_vs_other_store_pairs']
    store = {
        'rows': audit['rows'],
        'tests': [{'name': TESTS[k], 'obs': t['observed'], 'null': t['null_mean'], 'z': t['z'], 'p': t['p_permutation']}
                  for k, t in audit['permutation_tests'].items()],
        'pair': {'obs': audit['permutation_tests']['same_key_pairs_in_same_store_share']['observed'],
                 'null': audit['permutation_tests']['same_key_pairs_in_same_store_share']['null_mean']},
        'pairs': an['record_pairs'], 'permutations': audit['permutations'],
        'power': audit['positive_control_planted_eta_shift'],
        'eta': {'real': audit['permutation_tests']['eta2_eta_minutes']['observed'],
                'syn': ctrl['permutation_tests']['eta2_eta_minutes']['observed'],
                'synMin': ctrl['eta2_eta_minutes_by_snapshot']['min']},
        'agree': [{'what': 'Same price', 'same': sv['price_equal_share']['same_store'], 'other': sv['price_equal_share']['other_store']},
                  {'what': 'Same delivery time', 'same': sv['eta_equal_share']['same_store'], 'other': sv['eta_equal_share']['other_store']},
                  {'what': 'Both out of stock, given either is', 'same': sv['both_out_given_either_out']['same_store'],
                   'other': sv['both_out_given_either_out']['other_store']}],
        'stock': {'rate': an['stock']['out_of_stock_rate'], 'cond': an['stock']['p_other_record_out_given_one_out'],
                  'lift': an['stock']['lift_over_rate'], 'cat': an['stock']['null_shuffled_within_category']['null_mean']},
        'affected': audit['verdict']['affected_REAL_results'],
    }

    nv1 = ai1['ai_proxy_scores_NOT_TIER1']['name_variation_only']
    nv2 = ai2['ai_proxy_scores_NOT_TIER1']['name_variation_only']
    gate = ai2['ai_proxy_scores_NOT_TIER1']['v2_support_gate_on_name_variation']
    sup = v2['support_on_unlabelled_real_pairs']

    def row(who, b):
        return {'who': who, 'p': b['precision'], 'r': b['recall'], 'f1': b['f1'], 'fpr': b['false_positive_rate'], 'ap': b['pr_auc']}
    match = {
        'lofo': [{'family': f, 'expected': v['expected'], 'v2': v['pass_rate_family_never_trained_on'],
                  'v1': v['pass_rate_with_v1_features_only'], 'edits': v['edits']}
                 for f, v in v2['leave_one_family_out'].items()],
        'decisions': sup['decisions'], 'pairs': sup['unlabelled_real_pairs'],
        'ungatedOut': sup['ungated_booster_would_call_same']['out_of_support'],
        'examples': sup['ungated_booster_would_call_same']['examples_out_of_support_scored_same'][:6],
        'ai': [row('Matcher v1', nv1['lightgbm']), row('String-similarity baseline', nv1['baseline']),
               row('Matcher v2, with the gate', nv2['lightgbm']), row('v2, covered pairs only', gate['in_support_only']),
               row('v2 booster without the gate', gate['ungated_booster_all_pairs']),
               row('v1 features + constructed labels, no gate', gate['ablation_2x2_ungated']['B_v1feats_constructed'])],
        'aiPairs': nv2['pairs'], 'aiSame': nv2['ai_same'], 'chance': nv2['chance_pr_auc'],
        'gate': {'covered': gate['in_support_pairs'], 'abstained': gate['abstained_pairs'],
                 'calls': gate['ungated_same_calls_on_abstained_pairs']['calls'],
                 'agree': gate['ungated_same_calls_on_abstained_pairs']['ai_agrees_same']},
        'trainReal': v2['split']['train_pairs'], 'trainConstructed': v2['split']['constructed_train_pairs'],
    }

    days = sorted(int(d) for d in grid.days.unique())
    prods = sorted(int(p) for p in grid.products.unique())
    cells = {}
    for q in QUANTITIES:
        cells[q] = {}
        for pd_ in (2, 1):
            g = grid[(grid.quantity == q) & (grid.snapshots_per_day == pd_)].set_index(['days', 'products'])
            cells[q][str(pd_)] = [[[None if pd.isna(g.loc[(d, p), c]) else round(float(g.loc[(d, p), c]), 4)
                                    for c in ('half_width_90', 'within_tolerance_share', 'bias')]
                                   + [bool(g.loc[(d, p), 'identified'])] for p in prods] for d in days]
    planner = {
        'days': days, 'products': prods, 'watch': plan['watchlist_products'],
        'seconds': plan['assumed_seconds_per_observation'],
        'q': [{'key': k, 'label': lab, 'unit': unit, 'suffix': suf, 'tol': plan['quantities'][k]['tolerance'],
               'full': plan['quantities'][k]['full_panel_value'], 'both': plan['quantities'][k]['needs_both_daily_snapshots'],
               'transfer': plan['quantities'][k]['what_transfers_to_the_real_market']}
              for k, (lab, unit, suf) in QUANTITIES.items()],
        'cells': cells,
        'cluster': {'syn': plan['same_product_stock_clustering']['SYNTHETIC_across_platforms']['lift_over_rate'],
                    'real': (plan['same_product_stock_clustering']['REAL_across_records_of_one_name_pack'] or {}).get('lift_over_rate')},
        'bias': plan['bias_from_a_short_window_at_1000_products']['restock_mean'],
    }
    return {'built': date.today().isoformat(), 'store': store, 'match': match, 'plan': planner}


TEMPLATE = r'''<title>Quickcommerce Reality Check</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@100..125,500..800&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
/* layout: one column, three tabs; each tab opens on its verdict, then the evidence, then what it changes */
:root {
  color-scheme: light;
  --page: #eef2f0; --surface: #f7f9f8; --ink: #0f1512; --ink-2: #48514c; --muted: #6f7873;
  --grid: #dde4e0; --axis: #b6c0ba; --rule: rgba(15,21,18,.12);
  --blue: #2a78d6; --orange: #eb6834;
  --wash-blue: rgba(42,120,214,.13); --hatch: rgba(15,21,18,.30); --tip-bg: #0f1512; --tip-ink: #f7f9f8;
  --display: "Archivo", "Arial Narrow", Arial, sans-serif;
  --sans: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0c0f0d; --surface: #141816; --ink: #edf2ee; --ink-2: #b8c1bc; --muted: #8d9690;
    --grid: #232a26; --axis: #3b4540; --rule: rgba(237,242,238,.12);
    --blue: #3987e5; --orange: #d95926;
    --wash-blue: rgba(57,135,229,.17); --hatch: rgba(237,242,238,.32); --tip-bg: #edf2ee; --tip-ink: #0c0f0d;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0c0f0d; --surface: #141816; --ink: #edf2ee; --ink-2: #b8c1bc; --muted: #8d9690;
  --grid: #232a26; --axis: #3b4540; --rule: rgba(237,242,238,.12);
  --blue: #3987e5; --orange: #d95926;
  --wash-blue: rgba(57,135,229,.17); --hatch: rgba(237,242,238,.32); --tip-bg: #edf2ee; --tip-ink: #0c0f0d;
}
* { box-sizing: border-box; }
body { background: var(--page); color: var(--ink); font: 15px/1.55 var(--sans); margin: 0; }
.wrap { max-width: 1040px; margin: 0 auto; padding-inline: 20px; padding-block: 28px 64px; }
header { display: flex; flex-wrap: wrap; align-items: end; justify-content: space-between; gap: 12px 24px; margin-bottom: 14px; }
h1 { font-family: var(--display); font-variation-settings: "wdth" 125; font-weight: 800; font-size: clamp(32px, 6vw, 54px);
     line-height: 1; letter-spacing: -.02em; margin: 0; text-wrap: balance; }
.intro { max-width: 70ch; color: var(--ink-2); margin: 0 0 14px; }
.chip { display: inline-flex; align-items: center; font: 600 10.5px/1 var(--mono); letter-spacing: .06em; text-transform: uppercase;
        padding: 4px 6px 3px; border-radius: 3px; white-space: nowrap; color: var(--ink); vertical-align: 2px; }
.chip.REAL { border: 1.5px solid var(--ink); background: var(--surface); box-shadow: inset 0 0 0 1.5px var(--surface), inset 0 0 0 3px var(--ink); padding: 5px 8px 4px; }
.chip.SYNTHETIC { border: 1.5px solid var(--ink); background: repeating-linear-gradient(135deg, var(--hatch) 0 1.5px, transparent 1.5px 6px), var(--surface); }
.chip.METHOD { border: 1px solid var(--axis); color: var(--ink-2); background: var(--surface); }
.chip.PROXY { border: 1.5px dashed var(--ink); background: var(--surface); }
.key { display: flex; flex-wrap: wrap; gap: 8px 18px; align-items: center; font-size: 13px; color: var(--ink-2); margin: 0 0 20px; }
.key span { display: inline-flex; gap: 7px; align-items: center; }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--rule); margin-bottom: 22px; overflow-x: auto; }
.tabs button { font: 600 14px var(--sans); color: var(--ink-2); background: none; border: 0; border-bottom: 2px solid transparent;
               padding: 10px 14px; cursor: pointer; white-space: nowrap; }
.tabs button[aria-selected="true"] { color: var(--ink); border-bottom-color: var(--ink); }
button:focus-visible, input:focus-visible, [tabindex]:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.verdict { font: 600 clamp(19px, 2.6vw, 24px)/1.3 var(--sans); margin: 0 0 8px; max-width: 34ch; text-wrap: balance; }
.lede { max-width: 70ch; color: var(--ink-2); margin: 0 0 20px; }
.headline { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 1px; background: var(--rule);
            border: 1px solid var(--rule); margin-bottom: 20px; }
.tile { background: var(--surface); padding: 12px 14px; }
.tile .v { font: 600 24px/1.15 var(--sans); display: block; font-variant-numeric: tabular-nums; }
.tile .l { font-size: 12.5px; color: var(--muted); display: block; margin-top: 4px; }
.stack { display: grid; gap: 18px; }
.grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 440px), 1fr)); gap: 18px; }
.panel { background: var(--surface); border: 1px solid var(--rule); border-radius: 6px; padding: 16px; min-width: 0; }
.panel h2 { font: 600 15.5px/1.3 var(--sans); margin: 0 0 4px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; text-wrap: balance; }
.panel p.note { font-size: 13.5px; color: var(--ink-2); margin: 0 0 12px; max-width: 72ch; }
.panel p.note:last-child { margin-bottom: 0; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 12.5px; color: var(--ink-2); margin-bottom: 8px; }
.legend span { display: inline-flex; align-items: center; gap: 7px; }
.sw { width: 12px; height: 12px; display: inline-block; flex: none; border-radius: 50%; }
.sw.blue { background: var(--blue); } .sw.orange { background: var(--orange); }
.sw.ring { background: var(--surface); border: 2.5px solid var(--orange); }
.sw.band { border-radius: 2px; width: 18px; background: var(--wash-blue); }
.sw.hatch { border-radius: 2px; width: 18px; border: 1px solid var(--ink-2); background: repeating-linear-gradient(135deg, var(--hatch) 0 1.5px, transparent 1.5px 5px); }
.sw.neutral { border-radius: 2px; width: 18px; background: var(--axis); }
/* rows shared by the dot plot, the paired bars and the dumbbell */
.row { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 1.5fr) minmax(74px, auto); gap: 4px 14px; align-items: center;
       padding-block: 8px; border-bottom: 1px solid var(--grid); font-size: 13.5px; }
.row:last-of-type { border-bottom: 0; }
.row .lab { min-width: 0; }
.row .lab small { display: block; color: var(--muted); font-size: 12px; }
.row .num { font: 500 12.5px var(--mono); color: var(--ink-2); text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.track { position: relative; height: 20px; min-width: 0; }
.track .band { position: absolute; top: 2px; bottom: 2px; background: var(--wash-blue); border-radius: 2px; }
.track .mid { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--axis); }
.track .link { position: absolute; top: 50%; height: 2px; margin-top: -1px; background: var(--axis); }
.dot { position: absolute; top: 50%; width: 12px; height: 12px; margin: -6px 0 0 -6px; border-radius: 50%; background: var(--blue);
       box-shadow: 0 0 0 2px var(--surface); }
.dot.ring { background: var(--surface); border: 2.5px solid var(--orange); }
.dot:hover, .dot:focus-visible, .bar:hover, .seg:hover { box-shadow: 0 0 0 2px var(--surface), 0 0 0 4px var(--ink); }
.axis { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 1.5fr) minmax(74px, auto); gap: 14px; margin-top: 2px; }
.axis .ticks { position: relative; height: 30px; font: 11px var(--mono); color: var(--muted); }
.axis .ticks span { position: absolute; top: 2px; transform: translateX(-50%); }
.axis .ticks em { position: absolute; left: 0; right: 0; top: 16px; text-align: center; font: 11.5px var(--sans); font-style: normal; color: var(--muted); }
.bars { display: grid; gap: 2px; min-width: 0; }
.bars > div { display: flex; align-items: center; gap: 8px; }
.bar { height: 9px; border-radius: 0 4px 4px 0; min-width: 2px; }
.bar.blue { background: var(--blue); } .bar.orange { background: var(--orange); }
.bars span { font: 500 12px var(--mono); color: var(--ink-2); font-variant-numeric: tabular-nums; }
.split { display: flex; gap: 2px; height: 22px; margin: 6px 0 8px; }
.seg { height: 100%; min-width: 8px; }
.seg:first-child { border-radius: 4px 0 0 4px; } .seg:last-child { border-radius: 0 4px 4px 0; }
.seg.different { background: var(--axis); } .seg.same { background: var(--blue); }
.seg.abstain { border: 1px solid var(--ink-2); background: repeating-linear-gradient(135deg, var(--hatch) 0 1.5px, transparent 1.5px 5px); }
.tbl { overflow-x: auto; }
table.t { border-collapse: collapse; font: 13px/1.4 var(--sans); min-width: 100%; }
table.t th, table.t td { text-align: left; padding: 6px 14px 6px 0; border-bottom: 1px solid var(--grid); vertical-align: top; }
table.t th { color: var(--ink-2); font-weight: 600; white-space: nowrap; font-size: 12.5px; }
table.t td.n, table.t th.n { text-align: right; font-variant-numeric: tabular-nums; font-family: var(--mono); font-size: 12.5px; white-space: nowrap; }
table.t tr.hi td { font-weight: 600; }
.lists { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr)); gap: 16px; }
.lists h3 { font: 600 12px var(--mono); letter-spacing: .05em; text-transform: uppercase; color: var(--muted); margin: 0 0 6px; }
.lists ul { margin: 0; padding-left: 18px; font-size: 13.5px; color: var(--ink-2); }
.lists li + li { margin-top: 3px; }
/* planner */
.controls { display: flex; flex-wrap: wrap; gap: 16px 28px; align-items: end; margin-bottom: 18px; }
.ctl { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.ctl > label, .ctl > span { font: 500 12px var(--mono); color: var(--muted); letter-spacing: .04em; text-transform: uppercase; }
.ctl b { color: var(--ink); font-weight: 600; }
.segs { display: inline-flex; flex-wrap: wrap; border: 1px solid var(--rule); border-radius: 6px; overflow: hidden; background: var(--surface); }
.segs button { font: 500 13px var(--sans); color: var(--ink-2); background: none; border: 0; padding: 7px 11px; cursor: pointer;
               border-right: 1px solid var(--rule); font-variant-numeric: tabular-nums; }
.segs button:last-child { border-right: 0; }
.segs button[aria-pressed="true"] { background: var(--ink); color: var(--page); }
input[type=range] { width: min(240px, 60vw); accent-color: var(--blue); }
.qrow { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) auto; gap: 4px 14px; align-items: center; width: 100%;
        text-align: left; font: inherit; color: inherit; background: none; border: 0; border-bottom: 1px solid var(--grid);
        padding: 9px 8px; cursor: pointer; }
.qrow:last-child { border-bottom: 0; }
.qrow:hover { background: var(--page); }
.qrow[aria-pressed="true"] { background: var(--page); box-shadow: inset 3px 0 0 var(--ink); }
.qrow .lab small { display: block; color: var(--muted); font-size: 12px; }
.qrow .prec { font: 500 12.5px var(--mono); color: var(--ink-2); font-variant-numeric: tabular-nums; }
.pill { display: inline-flex; font: 600 11px/1 var(--mono); letter-spacing: .03em; padding: 5px 8px 4px; border-radius: 999px;
        border: 1.5px solid var(--ink); white-space: nowrap; color: var(--ink); }
.pill.no { border-style: dashed; color: var(--ink-2); border-color: var(--axis); }
.pill.na { border: 1px dotted var(--axis); color: var(--muted); }
table.heat { border-collapse: separate; border-spacing: 2px; font: 12.5px var(--mono); }
table.heat th { font: 600 11.5px var(--mono); color: var(--muted); padding: 4px 6px; text-align: center; white-space: nowrap; }
table.heat th.r { text-align: right; }
table.heat td { text-align: center; min-width: 44px; padding: 8px 4px; border-radius: 3px; cursor: pointer; color: var(--ink);
                font-variant-numeric: tabular-nums; }
table.heat td.id { font-weight: 600; box-shadow: inset 0 0 0 1.5px var(--blue); }
table.heat td.sel { box-shadow: inset 0 0 0 2.5px var(--ink); }
table.heat td.na { color: var(--muted); cursor: default; background: transparent; border: 1px dotted var(--grid); }
.foot { font-size: 13px; color: var(--muted); margin-top: 24px; max-width: 80ch; }
#tip { position: fixed; z-index: 10; pointer-events: none; max-width: 300px; padding: 7px 10px; border-radius: 4px;
       background: var(--tip-bg); color: var(--tip-ink); font: 12.5px/1.4 var(--sans); }
@media (max-width: 620px) {
  .row, .axis { grid-template-columns: minmax(0, 1fr) minmax(64px, auto); }
  .row .lab { grid-column: 1 / -1; } .axis > div:first-child { display: none; }
  .qrow { grid-template-columns: minmax(0, 1fr) auto; } .qrow .lab { grid-column: 1 / -1; }
}
@media (prefers-reduced-motion: no-preference) { .tabs button, .segs button, .qrow { transition: color .15s, background-color .15s; } }
</style>

<div class="wrap">
  <header>
    <h1>Reality Check</h1>
    <span class="chip METHOD" id="built"></span>
  </header>
  <p class="intro">Three checks on what the quick-commerce project can claim. One looks at the single real snapshot, one at the
  product matcher, and one at the real panel that has not been collected yet.</p>
  <div class="key" aria-label="Provenance key">
    <span><span class="chip REAL">REAL</span> the observed Blinkit snapshot of 2026-07-10</span>
    <span><span class="chip SYNTHETIC">SYNTHETIC</span> generated data, or built from it</span>
    <span><span class="chip PROXY">AI PROXY</span> one AI reviewer, not human labels</span>
  </div>

  <nav class="tabs" role="tablist" aria-label="Sections">
    <button role="tab" id="t-store" aria-selected="true" aria-controls="p-store">The store label</button>
    <button role="tab" id="t-match" aria-selected="false" aria-controls="p-match">Matcher v2</button>
    <button role="tab" id="t-plan" aria-selected="false" aria-controls="p-plan">Plan the real panel</button>
  </nav>

  <section id="p-store" role="tabpanel" aria-labelledby="t-store">
    <p class="verdict">On the real rows, the store a listing belongs to cannot be told apart from a random tag.</p>
    <p class="lede">Four results in this project read the store column of the real snapshot as "this store listed this
    product". Ten tests ask whether that column carries any information. None finds any.</p>
    <div class="headline" id="s-tiles"></div>
    <div class="stack">
      <div class="panel">
        <h2>Ten tests, each against shuffled store tags <span class="chip REAL">REAL</span></h2>
        <p class="note" id="s-note"></p>
        <div class="legend"><span><i class="sw blue"></i>the real data</span><span><i class="sw band"></i>where 95% of shuffles fall</span></div>
        <div id="s-tests"></div>
      </div>
      <div class="grid2">
        <div class="panel">
          <h2>Two records of one product agree no more inside a store than across stores <span class="chip REAL">REAL</span></h2>
          <p class="note">If the tag marked real stores, two records of one product inside one store would be duplicates,
          and would agree more often than records from different stores.</p>
          <div class="legend"><span><i class="sw blue"></i>both in the same store</span><span><i class="sw orange"></i>in different stores</span></div>
          <div id="s-agree"></div>
        </div>
        <div class="panel">
          <h2>Could the tests have seen a store effect?</h2>
          <p class="note">A test that finds nothing only counts if it finds an effect that is there. Two checks.</p>
          <div id="s-power"></div>
        </div>
      </div>
      <div class="panel">
        <h2>What the snapshot does say, with the store tag set aside <span class="chip REAL">REAL</span></h2>
        <p class="note" id="s-stock-note"></p>
        <div id="s-stock"></div>
      </div>
      <div class="panel">
        <h2>What it changes</h2>
        <p class="note">This is a property of the data in the project, not a verdict on how it was collected. The source
        workbook was then checked: its store names and addresses come from a public store map, and nothing in it records
        how a product was tied to a store. So the store label is marked unverified, and the analyst, the manifests and
        the Explorer page all show that status. The person who collected the data can still settle it. No result was withdrawn.</p>
        <div class="lists">
          <div><h3>Now carries the caveat</h3><ul>
            <li>Assortment gaps by store (deliverable 10)</li><li>Category coverage by store (12c)</li>
            <li>The real half of "a store adds products"</li><li>The store half of the listing chain's real context row</li></ul></div>
          <div><h3>Not affected</h3><ul>
            <li>Price and stock status of each record, verified against the source</li><li>The product matcher</li>
            <li>The real anomaly detector</li><li>The generator's calibration, which is per category</li>
            <li>Store addresses and coordinates, from a separate public source</li></ul></div>
        </div>
      </div>
    </div>
  </section>

  <section id="p-match" role="tabpanel" aria-labelledby="t-match" hidden>
    <p class="verdict">Matcher v2 learns name variation from constructed edits, and abstains where nothing taught it.</p>
    <p class="lede" id="m-lede"></p>
    <div class="stack">
      <div class="panel">
        <h2>A whole kind of edit withheld from training <span class="chip SYNTHETIC">SYNTHETIC</span></h2>
        <p class="note">Each row removes one family of edits from training, then tests on it. Both models get the same
        labels. Features that measure how much two names differ memorise each family; features that say what differs
        carry over. The alias row fails for both: that rule is taught, not learned.</p>
        <div class="legend"><span><i class="sw blue"></i>v2 features (what differs)</span><span><i class="sw ring"></i>v1 features (how much differs)</span></div>
        <div id="m-lofo"></div>
      </div>
      <div class="grid2">
        <div class="panel">
          <h2>What v2 says about the real pairs nobody has labelled <span class="chip REAL">REAL</span></h2>
          <p class="note" id="m-dec-note"></p>
          <div class="split" id="m-split"></div>
          <div class="legend" id="m-split-legend"></div>
        </div>
        <div class="panel">
          <h2>Why it abstains <span class="chip REAL">REAL</span></h2>
          <p class="note">The only insertions v2 was shown are alias brackets, so its booster reads "one name says more"
          as the same product. These real pairs differ in a way training never covered. Without the gate they score:</p>
          <div class="tbl" id="m-examples"></div>
        </div>
      </div>
      <div class="panel">
        <h2>Against one AI reviewer <span class="chip PROXY">AI PROXY</span></h2>
        <p class="note" id="m-ai-note"></p>
        <div class="tbl" id="m-ai"></div>
        <p class="note" id="m-gate-note" style="margin-top:12px"></p>
      </div>
    </div>
  </section>

  <section id="p-plan" role="tabpanel" aria-labelledby="t-plan" hidden>
    <p class="verdict">A hand-logged panel can answer some of this project's questions and not others.</p>
    <p class="lede">Pick a panel a person could log. The generated panel is cut down to that size 200 times and each cut is
    estimated the plain way. A quantity counts as identified when 9 cuts in 10 land within its target. This is a planning
    prior <span class="chip SYNTHETIC">SYNTHETIC</span>: it holds if the real market is about as noisy as the generator.</p>
    <div class="controls">
      <div class="ctl"><span>Products, on all four apps</span><div class="segs" id="c-products"></div></div>
      <div class="ctl"><label for="c-days">Days <b id="c-days-v"></b></label><input type="range" id="c-days" min="0" step="1"></div>
      <div class="ctl"><span>Snapshots</span><div class="segs" id="c-per"></div></div>
      <div class="ctl"><label for="c-sec">Seconds per observation, assumed <b id="c-sec-v"></b></label><input type="range" id="c-sec" min="5" max="60" step="5"></div>
    </div>
    <div class="headline" id="p-tiles"></div>
    <div class="grid2">
      <div class="panel">
        <h2>What this panel pins down</h2>
        <p class="note">How many of the 200 cuts land within each target. At 90% the quantity counts as identified. Select a row to see it across every panel size.</p>
        <div id="p-rows"></div>
      </div>
      <div class="panel">
        <h2 id="p-heat-title"></h2>
        <p class="note" id="p-heat-note"></p>
        <div class="tbl" id="p-heat"></div>
        <p class="note" id="p-transfer" style="margin-top:12px"></p>
      </div>
    </div>
    <div class="panel" style="margin-top:18px">
      <h2>Four things to take from it</h2>
      <div class="lists">
        <div><h3>Days and products buy different things</h3><ul><li>The price gap and the cheapest-of-4 share are limited by products: more days barely help.</li><li>The evening delivery time is limited by days.</li></ul></div>
        <div><h3>A short panel is precisely wrong about restocking</h3><ul><li id="p-bias"></li></ul></div>
        <div><h3>Once a day keeps the cross-section only</h3><ul><li>Mornings only halves the work and still gives the price gap. It cannot estimate anything that needs the half-day step.</li></ul></div>
        <div><h3>One real fact widens the stock-out answer</h3><ul><li id="p-cluster"></li></ul></div>
      </div>
    </div>
  </section>

  <p class="foot">Built from saved outputs of the quickcommerce-mi project: real_store_label_audit, product_matcher_v2 and its
  checks, collection_planner. Positioning and availability only; there are no orders, shoppers or revenue in this data.</p>
</div>
<div id="tip" role="tooltip" hidden></div>

<script>
const DATA = __DATA__;
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const pct = (x, d = 1) => (100 * x).toFixed(d) + '%';
const fix = (x, d = 2) => Number(x).toFixed(d);
const int = x => Math.round(x).toLocaleString('en-IN');
$('built').textContent = 'Built ' + DATA.built;

/* ---------- tabs */
const TABS = ['store', 'match', 'plan'];
function show(t) {
  TABS.forEach(k => { $('p-' + k).hidden = k !== t; $('t-' + k).setAttribute('aria-selected', String(k === t)); });
  try { history.replaceState(null, '', '#' + t); } catch (e) {}
}
TABS.forEach(k => $('t-' + k).addEventListener('click', () => show(k)));
show(TABS.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'store');

/* ---------- tooltip */
const tip = $('tip');
function place(x, y) {
  tip.style.left = Math.max(8, Math.min(x, innerWidth - tip.offsetWidth - 8)) + 'px';
  tip.style.top = (y + tip.offsetHeight + 8 > innerHeight ? Math.max(8, y - tip.offsetHeight - 24) : y) + 'px';
}
document.addEventListener('pointermove', e => {
  const t = e.target.closest ? e.target.closest('[data-tip]') : null;
  if (!t) { tip.hidden = true; return; }
  tip.textContent = t.dataset.tip; tip.hidden = false; place(e.clientX + 14, e.clientY + 16);
});
document.addEventListener('focusin', e => {
  const t = e.target.closest ? e.target.closest('[data-tip]') : null;
  if (!t) return;
  const r = t.getBoundingClientRect(); tip.textContent = t.dataset.tip; tip.hidden = false; place(r.left, r.bottom + 8);
});
document.addEventListener('focusout', () => { tip.hidden = true; });

/* ---------- the store label */
(function store() {
  const S = DATA.store;
  $('s-tiles').innerHTML = [
    [pct(S.pair.obs), "of pairs of one product's records sit in the same store"],
    [pct(S.pair.null), 'is what a tag unrelated to the product gives'],
    ['about 0%', 'is what a real store would give: it lists a product once'],
    ['0 of ' + S.tests.length, 'tests depart from random after correction'],
  ].map(([v, l]) => `<div class="tile"><span class="v">${v}</span><span class="l">${l}</span></div>`).join('');
  $('s-note').textContent = `Each dot is one test on the ${int(S.rows)} real rows: how far the data sits from ` +
    `${int(S.permutations)} shuffles of the store tag, in standard deviations of those shuffles. A store effect would put a dot far to the right.`;
  const x = z => 100 * (Math.max(-4, Math.min(4, z)) + 4) / 8;
  const fmt = v => Math.abs(v) >= 100 ? int(v) : Math.abs(v) >= 1 ? fix(v, 1) : Math.abs(v) >= 0.01 ? fix(v, 3) : fix(v, 5);
  $('s-tests').innerHTML = S.tests.map(t =>
    `<div class="row"><div class="lab">${esc(t.name)}</div>
      <div class="track"><i class="band" style="left:${x(-1.96)}%;width:${x(1.96) - x(-1.96)}%"></i><i class="mid" style="left:50%"></i>
        <i class="dot" tabindex="0" style="left:${x(t.z)}%" data-tip="${esc(t.name)}: observed ${fmt(t.obs)}, shuffled mean ${fmt(t.null)}, ${t.z >= 0 ? '+' : ''}${fix(t.z, 2)} sd, p ${fix(t.p, 3)}"></i></div>
      <div class="num">p ${fix(t.p, 3)}</div></div>`).join('') +
    `<div class="axis"><div></div><div class="ticks">${[-4, -2, 0, 2, 4].map(v => `<span style="left:${x(v)}%">${v > 0 ? '+' + v : v}</span>`).join('')}
      <em>standard deviations from the shuffled mean</em></div><div></div></div>`;
  $('s-agree').innerHTML = S.agree.map(a =>
    `<div class="row"><div class="lab">${esc(a.what)}</div>
      <div class="bars"><div><i class="bar blue" style="width:${200 * a.same * 0.8}%" data-tip="Both records in the same store: ${pct(a.same)}"></i><span>${pct(a.same)}</span></div>
        <div><i class="bar orange" style="width:${200 * a.other * 0.8}%" data-tip="Records in different stores: ${pct(a.other)}"></i><span>${pct(a.other)}</span></div></div>
      <div class="num"></div></div>`).join('');
  const p2 = S.power.find(r => r.planted_eta_shift_minutes === 0.2), p1 = S.power.find(r => r.planted_eta_shift_minutes === 0.1);
  $('s-power').innerHTML = `<div class="tbl"><table class="t"><tbody>
    <tr><td>A delivery-time shift of 0.2 minutes planted in the smallest store</td><td class="n">found ${pct(p2.detected_share_at_5pct, 0)} of the time</td></tr>
    <tr><td>A shift of 0.1 minutes</td><td class="n">found ${pct(p1.detected_share_at_5pct, 0)} of the time</td></tr>
    <tr><td>Share of delivery-time variance between stores, generated rows <span class="chip SYNTHETIC">SYNTHETIC</span></td><td class="n">${fix(S.eta.syn, 2)}</td></tr>
    <tr class="hi"><td>The same share on the real rows <span class="chip REAL">REAL</span></td><td class="n">${fix(S.eta.real, 5)}</td></tr>
    </tbody></table></div>`;
  $('s-stock-note').textContent = `${int(S.pairs)} pairs of real records share a name and pack. Whatever those records are, the same ` +
    `product in different places or at different times, they run out together: ${fix(S.stock.lift, 1)} times the base rate. Category explains little of it.`;
  const sb = [['Any record is out of stock', S.stock.rate], ['Another record of the same product is out, given one is', S.stock.cond],
              ['The same, with stock status shuffled within category', S.stock.cat]];
  $('s-stock').innerHTML = sb.map(([l, v]) =>
    `<div class="row"><div class="lab">${l}</div><div class="bars"><div><i class="bar blue" style="width:${200 * v * 0.8}%" data-tip="${l}: ${pct(v)}"></i><span>${pct(v)}</span></div></div><div class="num"></div></div>`).join('');
})();

/* ---------- matcher v2 */
(function match() {
  const M = DATA.match;
  $('m-lede').textContent = `The first matcher treats any textual difference as a different product. The second is trained on ` +
    `${int(M.trainReal)} real pairs plus ${int(M.trainConstructed)} constructed edits of real names, each changed in a way whose effect on ` +
    `identity is known. Its real accuracy is still unmeasured: the review page has no human labels.`;
  $('m-lofo').innerHTML = M.lofo.map(f => {
    const a = 100 * f.v1, b = 100 * f.v2, lo = Math.min(a, b), hi = Math.max(a, b);
    return `<div class="row"><div class="lab">${esc(f.family)}<small>must be judged ${f.expected === 'same' ? 'the same product' : 'a different product'}</small></div>
      <div class="track"><i class="link" style="left:${lo}%;width:${hi - lo}%"></i>
        <i class="dot ring" tabindex="0" style="left:${a}%" data-tip="${esc(f.family)}, v1 features: ${pct(f.v1)} judged correctly"></i>
        <i class="dot" tabindex="0" style="left:${b}%" data-tip="${esc(f.family)}, v2 features: ${pct(f.v2)} judged correctly"></i></div>
      <div class="num">${pct(f.v1)} → ${pct(f.v2)}</div></div>`;
  }).join('') + `<div class="axis"><div></div><div class="ticks">${[0, 25, 50, 75, 100].map(v => `<span style="left:${v}%">${v}%</span>`).join('')}
      <em>held-out edits judged correctly</em></div><div></div></div>`;
  const d = M.decisions, total = d.different + d.same + d.abstain;
  $('m-dec-note').textContent = `${int(total)} real pairs with similar names and no label. v2 decides only when at least 25 training pairs ` +
    `differ in the same way; otherwise it abstains.`;
  const parts = [['different', 'Different product', d.different], ['same', 'Same product', d.same], ['abstain', 'Abstains', d.abstain]];
  $('m-split').innerHTML = parts.map(([k, l, n]) =>
    `<i class="seg ${k}" tabindex="0" style="flex:${n} 1 0" data-tip="${l}: ${int(n)} pairs (${pct(n / total)})"></i>`).join('');
  $('m-split-legend').innerHTML = [['neutral', 'Different product', d.different], ['blue', 'Same product', d.same], ['hatch', 'Abstains', d.abstain]]
    .map(([c, l, n]) => `<span><i class="sw ${c}"></i>${l} · ${int(n)} (${pct(n / total)})</span>`).join('');
  $('m-examples').innerHTML = `<table class="t"><thead><tr><th>Pair, same pack size</th><th class="n">Score</th></tr></thead><tbody>` +
    M.examples.map(e => `<tr><td>${esc(e.name_a)}<br><span style="color:var(--muted)">${esc(e.name_b)}</span></td><td class="n">${fix(e.booster_proba, 4)}</td></tr>`).join('') +
    `</tbody></table>`;
  $('m-ai-note').textContent = `${M.aiPairs} real pairs whose names actually vary, ${M.aiSame} of them judged the same product by one AI reviewer. ` +
    `Scored once, after the design was fixed. Chance ranking score ${fix(M.chance, 3)}. None of this is evidence until the reviewer's agreement with people is measured.`;
  $('m-ai').innerHTML = `<table class="t"><thead><tr><th></th><th class="n">Precision</th><th class="n">Recall</th><th class="n">F1</th><th class="n">False positives</th><th class="n">Ranking (PR-AUC)</th></tr></thead><tbody>` +
    M.ai.map((r, i) => `<tr class="${i === 2 ? 'hi' : ''}"><td>${esc(r.who)}</td><td class="n">${fix(r.p)}</td><td class="n">${fix(r.r)}</td><td class="n">${fix(r.f1)}</td><td class="n">${pct(r.fpr)}</td><td class="n">${fix(r.ap, 3)}</td></tr>`).join('') +
    `</tbody></table>`;
  $('m-gate-note').textContent = `The gate withholds ${M.gate.calls} "same" calls on the ${M.gate.abstained} pairs it abstains on; the reviewer agrees with ` +
    `${M.gate.agree} of them. The ungated model built on v1's features ranks pairs better against this reviewer than v2 does. Choosing between them needs human labels.`;
})();

/* ---------- the planner */
(function plan() {
  const P = DATA.plan, st = {di: P.days.indexOf(14), pi: P.products.indexOf(P.watch), per: 2, sec: P.seconds, q: 'oos_rate'};
  try { const s = JSON.parse(localStorage.getItem('qc-plan') || 'null'); if (s && P.days[s.di] && P.products[s.pi]) Object.assign(st, s); } catch (e) {}
  if (!P.q.some(x => x.key === st.q)) st.q = 'oos_rate';
  if (st.per !== 1 && st.per !== 2) st.per = 2;
  const save = () => { try { localStorage.setItem('qc-plan', JSON.stringify(st)); } catch (e) {} };
  const cell = (q, di = st.di, pi = st.pi, per = st.per) => P.cells[q][String(per)][di][pi];   // [half width, share, bias, identified]
  const days = $('c-days'), sec = $('c-sec');
  days.max = P.days.length - 1; days.value = st.di; sec.value = st.sec;
  $('c-products').innerHTML = P.products.map((p, i) =>
    `<button type="button" data-i="${i}">${p}${p === P.watch ? ' · watchlist' : ''}</button>`).join('');
  $('c-per').innerHTML = [[2, 'Morning and evening'], [1, 'Morning only']].map(([v, l]) => `<button type="button" data-v="${v}">${l}</button>`).join('');
  const unit = q => q.unit ? ' ' + q.unit : '';
  function draw() {
    const d = P.days[st.di], p = P.products[st.pi], obs = d * st.per * 4 * p, hrs = obs * st.sec / 3600;
    $('c-days-v').textContent = d + (d === 1 ? ' day' : ' days'); $('c-sec-v').textContent = st.sec + ' s';
    document.querySelectorAll('#c-products button').forEach(b => b.setAttribute('aria-pressed', String(+b.dataset.i === st.pi)));
    document.querySelectorAll('#c-per button').forEach(b => b.setAttribute('aria-pressed', String(+b.dataset.v === st.per)));
    const got = P.q.filter(q => cell(q.key)[3]).length;
    $('p-tiles').innerHTML = [
      [int(obs), 'observations to log'], [fix(hrs / d, 1) + ' h', 'a day, at ' + st.sec + ' s each'],
      [fix(hrs, 0) + ' h', 'in total'], [got + ' of ' + P.q.length, 'quantities identified'],
    ].map(([v, l]) => `<div class="tile"><span class="v">${v}</span><span class="l">${l}</span></div>`).join('');
    $('p-rows').innerHTML = P.q.map(q => {
      const c = cell(q.key), na = q.both && st.per === 1;
      const pill = na ? '<span class="pill na">needs both snapshots</span>' : c[3] ? '<span class="pill">identified</span>' : '<span class="pill no">not yet</span>';
      const prec = na || c[0] == null ? 'cannot be estimated' : `${pct(c[1], 0)} of cuts within ±${q.tol}${unit(q)}`;
      return `<button type="button" class="qrow" data-q="${q.key}" aria-pressed="${q.key === st.q}">
        <span class="lab">${esc(q.label)}<small>full panel: ${fix(q.full, q.tol < 0.1 ? 3 : 2)}${esc(q.suffix)}</small></span>
        <span class="prec">${prec}</span>${pill}</button>`;
    }).join('');
    const q = P.q.find(x => x.key === st.q);
    $('p-heat-title').textContent = q.label + ', across every panel size';
    $('p-heat-note').textContent = `Each cell: the share of 200 cuts that land within ±${q.tol}${unit(q)} of the full-panel value, ` +
      `${st.per === 2 ? 'logging morning and evening' : 'logging mornings only'}. Outlined in blue: identified. Select a cell to choose that panel.`;
    const na = q.both && st.per === 1;
    $('p-heat').innerHTML = `<table class="heat"><thead><tr><th class="r">products ↓ days →</th>${P.days.map(x => `<th>${x}</th>`).join('')}</tr></thead><tbody>` +
      P.products.map((pp, pi) => `<tr><th class="r">${pp}</th>` + P.days.map((dd, di) => {
        const c = cell(q.key, di, pi);
        if (na || c[0] == null) return `<td class="na" data-tip="${dd} days, ${pp} products: cannot be estimated">–</td>`;
        const cls = (c[3] ? 'id ' : '') + (di === st.di && pi === st.pi ? 'sel' : '');
        return `<td class="${cls}" tabindex="0" data-di="${di}" data-pi="${pi}" style="background:color-mix(in srgb, var(--blue) ${Math.round(55 * c[1])}%, var(--surface))"
          data-tip="${dd} days, ${pp} products: ${pct(c[1], 0)} of cuts within target; half-width ±${fix(c[0], 2)}${unit(q)}; bias ${c[2] >= 0 ? '+' : ''}${fix(c[2], 2)}">${Math.round(100 * c[1])}</td>`;
      }).join('') + '</tr>').join('') + '</tbody></table>';
    $('p-transfer').textContent = 'What carries over to the real market: ' + q.transfer;
    save();
  }
  $('c-products').addEventListener('click', e => { const b = e.target.closest('button'); if (b) { st.pi = +b.dataset.i; draw(); } });
  $('c-per').addEventListener('click', e => { const b = e.target.closest('button'); if (b) { st.per = +b.dataset.v; draw(); } });
  days.addEventListener('input', () => { st.di = +days.value; draw(); });
  sec.addEventListener('input', () => { st.sec = +sec.value; draw(); });
  $('p-rows').addEventListener('click', e => { const b = e.target.closest('.qrow'); if (b) { st.q = b.dataset.q; draw(); } });
  function pick(e) { const c = e.target.closest('td[data-di]'); if (c) { st.di = +c.dataset.di; st.pi = +c.dataset.pi; days.value = st.di; draw(); } }
  $('p-heat').addEventListener('click', pick);
  $('p-heat').addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(e); } });
  const b = P.bias;
  $('p-bias').textContent = `A window only holds spells shorter than itself. The mean out-of-stock spell reads ${fix(-b['2'], 2)} snapshots too short ` +
    `in a 2-day panel, ${fix(-b['7'], 2)} at 7 days and ${fix(-b['14'], 2)} at 14, while looking just as tight.`;
  $('p-cluster').textContent = P.cluster.real == null ? 'Run the store-label audit to fill this in.' :
    `In the real snapshot, records of one product run out together at ${fix(P.cluster.real, 1)} times the base rate. The generator plants ` +
    `${fix(P.cluster.syn, 2)} times. If the real figure holds across apps, a fourth app adds less about stock-outs than a few more products would.`;
  draw();
})();
</script>
'''


def main():
    data = json.dumps(payload(), separators=(',', ':'), ensure_ascii=False).replace('</', '<\\/')
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(TEMPLATE.replace('__DATA__', data), encoding='utf-8')
    print(f'wrote {OUT.relative_to(ROOT)}  ({OUT.stat().st_size / 1024:.0f} KB)')


if __name__ == '__main__':
    main()
