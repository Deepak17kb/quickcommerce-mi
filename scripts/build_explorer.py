"""
build_explorer.py — the Listing Chain Explorer: one listing through seven stages, three scenarios, and the cited market
context, in one self-contained page.

    python scripts/build_explorer.py      # -> outputs/showcase/explorer.html

Reads only saved outputs (the chain gallery and the scenario models); nothing is recomputed. Every block on the page
carries its provenance by form: REAL solid, SYNTHETIC hatched, METHOD outlined, EXTERNAL dashed.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M = ROOT / 'outputs' / 'models'
OUT = ROOT / 'outputs' / 'showcase' / 'explorer.html'
PLAT = ['Blinkit', 'Swiggy Instamart', 'Flipkart Minutes', 'BigBasket']
MODEL_NAMES = {'1_product_matcher': 'Product matcher', '2_next_price': 'Next price', '3_direction': 'Price direction',
               '4_stock_next': 'Next-snapshot stock', '5_eta_next': 'Next ETA', '6_anomaly': 'Anomaly',
               '7_time_to_stockout': 'Time to stock-out', '8_restock': 'Restock time',
               '9_competitor_response': 'Competitor response', '10_assortment_gap': 'Assortment gap'}
# the planted restock groups (docs/GENERATOR_v15_PARAMETERS.md B), shown next to the outage cost by category
FAST = {'Fruits & Vegetables', 'Dairy, Bread & Eggs'}
SLOW = {'Home & Cleaning', 'Kitchen & Dining', 'Electronics & Stationery', 'Fashion & Lifestyle',
        'Other / General Merchandise'}


def metrics(name):
    return json.loads((M / name / 'metrics.json').read_text(encoding='utf-8'))


def rs(v):
    return f'₹{v:,.0f}' if abs(v - round(v)) < 1e-9 else f'₹{v:,.2f}'


def plain(s):
    return re.sub(r'\*\*|`', '', s)


# =========================================================================== chains
def pred_rows(P):
    rows = []
    x = P['2_next_price']
    if x.get('provenance'):
        rows.append(['2 · Next price', rs(x['predicted']), rs(x['actual_next']), 'SYNTHETIC'])
    x = P['3_direction']
    if x.get('provenance'):
        rows.append(['3 · Price direction', f"{x['predicted']} (down {100 * x['p_down']:.1f}%, flat {100 * x['p_flat']:.1f}%, "
                     f"up {100 * x['p_up']:.1f}%)", x['actual'], 'SYNTHETIC'])
    x = P['4_stock_next']
    if x.get('provenance') and x.get('p_stockout_next') is not None:
        rows.append(['4 · Next-snapshot stock', f"out of stock {100 * x['p_stockout_next']:.1f}%",
                     'in stock' if x['actual_in_stock_next'] else 'out of stock', 'SYNTHETIC'])
    x = P['5_eta_next']
    if x.get('provenance'):
        rows.append(['5 · Next ETA', f"{x['predicted_min']:g} min (90% interval {x['interval_90'][0]:g}–{x['interval_90'][1]:g})",
                     f"{x['actual_next_min']:g} min", 'SYNTHETIC'])
    x = P['6_anomaly']
    if x.get('decision_snapshot'):
        d = x['decision_snapshot']
        rows.append(['6 · Anomaly, generated panel', f"score {d['score']:g}, {'flagged' if d['flagged'] else 'not flagged'} "
                     f"(flag above {d['threshold']})", '—', 'SYNTHETIC'])
    if x.get('real_row'):
        d = x['real_row']
        rows.append(['6 · Anomaly, REAL row', f"score {d['score']:g}, {'flagged' if d['flag_unusual'] else 'not flagged'}",
                     '—', 'REAL'])
    x = P['7_time_to_stockout']
    if x.get('provenance'):
        act = x.get('actual_oos_within_1')
        rows.append(['7 · Time to stock-out', f"out within 1 / 2 / 4 / 6 snapshots: {100 * x['p_oos_within_1']:.1f} / "
                     f"{100 * x['p_oos_within_2']:.1f} / {100 * x['p_oos_within_4']:.1f} / {100 * x['p_oos_within_6']:.1f}%",
                     '—' if act is None else ('out at the next snapshot' if act else 'in stock at the next snapshot'),
                     'SYNTHETIC'])
    x = P['8_restock']
    if x.get('provenance'):
        rows.append(['8 · Restock time', f"back within 1 / 2 / 4 snapshots: {100 * x['p_back_within_1']:.1f} / "
                     f"{100 * x['p_back_within_2']:.1f} / {100 * x['p_back_within_4']:.1f}%", '—', 'SYNTHETIC'])
    x = P['9_competitor_response']
    rows.append(['9 · Competitor response', '; '.join(f"{k}: β {v['beta']:g}, {v['lag_snapshots']}-snapshot lag"
                                                      for k, v in x['followers'].items()), '—', 'SYNTHETIC'])
    return rows


def chains():
    out = []
    for f in sorted((M / 'listing_chain' / 'chains').glob('*.json')):
        r = json.loads(f.read_text(encoding='utf-8'))
        O, A, P, G, S, Z = (r[k] for k in r['stages'][:6])
        L, d, real = O['listing'], O['decision_snapshot'], O['real_observation']
        v = S['baseline_check']
        u = S.get('scenario_unavailable')
        out.append({
            'file': f.name, 'name': L['product_name'], 'pack': L['pack_size'], 'store': L['store_id'],
            'storeName': L['store_name'], 'area': L['area'], 'category': L['category'],
            'real': None if not real else {'price': real['selling_price'], 'mrp': real['mrp'], 'stock': real['stock_status'],
                                           'eta': [real['eta_min'], real['eta_max']], 'key': real['observation_key']},
            'dec': {'at': d['observed_at'], 'price': d['selling_price'], 'mrp': d['mrp'], 'disc': d['discount_pct'],
                    'promo': d['promo_listing'], 'inStock': d['in_stock'], 'eta': d['eta_min'],
                    'cheapest': d['cheapest_now'], 'comp': d['competitor_prices']},
            'app': [{'k': k.split('_')[0], 'name': MODEL_NAMES[k], 'on': bool(a['applies']), 'why': a['why'],
                     'gapIn': a.get('recommended_as_gap_in') or []} for k, a in A.items()],
            'pred': pred_rows(P),
            'grid': {'step': G['step'], 'rem': G['remainder'], 'from': G['inferred_from'], 'floor': G['floor_price'],
                     'ceiling': G.get('ceiling_price'), 'agrees': G['agrees_with_price_world_grid'],
                     'comp': G['competitor_grids_step_remainder']},
            'base': {'passed': v['passed'], 'cov': v['coverage_of_observed_prices_by_90pct_band'],
                     'obs': v['observed_blinkit_cheapest_share'], 'range': v['simulated_share_95_range'],
                     'n': v['snapshots_checked']},
            'sq': {'s': S['status_quo']['mean_cheapest_share'], 'b': S['status_quo']['band_90']},
            'ladder': [{'p': g['price'], 'k': g['kind'], 'm': g.get('move_pct', -g['cut_pct']),
                        's': round(g['strategic']['mean_cheapest_share'], 4),
                        'sb': [round(x, 4) for x in g['strategic']['band_90']],
                        't': round(g['static']['mean_cheapest_share'], 4),
                        'oos': g['promo']['extra_p_oos_within_12_pp'], 'mode': g['promo'].get('mode', '')}
                       for g in S['ladder']],
            'xcheck': S.get('cross_check_stock'),
            'unav': None if not u else {'now': u['cheapest_available_share_now'], 'spell': u['expected_spell_snapshots'],
                                        'back': u['p_back_within'], 'prio': u['expedite_priority_index'],
                                        'sc': {k: {'d': x['blinkit_change_pp'], 'b': x['band_90_pp'],
                                                   'inh': x['inherits_pp']} for k, x in u['scenarios'].items()}},
            'opt': {'dir': Z.get('direction', 'cut'), 'target': Z['target'], 'verdict': Z['verdict'],
                    'hold': Z.get('hold_mean_cheapest_share'), 'strategic': Z['strategic'], 'static': Z['static'],
                    'raise': Z.get('raise'), 'ifu': Z.get('if_unavailable')},
            'claims': [{'stage': c['stage'], 'prov': c['provenance'], 'text': c['text'],
                        'src': c['source_file'] + (f" · {c['source_detail']}" if c.get('source_detail') else '')}
                       for c in r.get('7_explanation', [])],
        })
    # the cut listings first (as the gallery was picked), then the ones where Blinkit is cheapest
    return sorted(out, key=lambda c: (c['dec']['cheapest'], c['name']))


# =========================================================================== scenarios
def outage():
    u = metrics('simulate_unavailable')
    L = u['blinkit_outage_by_length_pp']
    cats = []
    for c, row in u['blinkit_outage_by_category'].items():
        cats.append({'c': c, 'v': row['blinkit_change_pp'], 'now': row['blinkit_share_now_pp'], 'skus': row['skus'],
                     'grp': 'FAST' if c in FAST else 'SLOW' if c in SLOW else 'MEDIUM', 'inh': row['inherits']})
    sub = u['substitution_check']
    return {'now': u['cheapest_available_now'], 'priceOnly': u['cheapest_of_4_ignoring_stock'],
            'matrix': {p: {q: v['change_pp'] for q, v in d.items()} for p, d in u['who_inherits'].items()},
            'lengths': [[int(k), v] for k, v in L.items() if k.isdigit()], 'drawn': L['drawn_from_restock_model'],
            'cats': sorted(cats, key=lambda x: x['v']), 'horizon': u['horizon'], 'sims': u['n_sims'],
            'sub': {'or': sub['odds_ratio'], 'ci': sub['odds_ratio_ci95_cluster_by_product'],
                    'p': sub['p_value_cluster_by_product'], 'first': sub['first_spec_without_evening'],
                    'rows': sub['rows'], 'events': sub['events'], 'verdict': sub['verdict'],
                    'eveOut': sub.get('share_of_blinkit_out_rows_before_evening'),
                    'eveIn': sub.get('share_of_blinkit_in_rows_before_evening')},
            'eta': u['store_category_outage_eta']}


def adds():
    r, s = metrics('simulate_store_adds_real'), metrics('simulate_store_adds')
    real = [{'store': x['store_id'], 'n': x['n'], 'now': x['products_now'], 'added': x['added'],
             'tvb': x['tv_distance_to_peer_mix_before'], 'tva': x['tv_distance_to_peer_mix_after'],
             'under': x['share_of_additions_in_under_represented_categories'],
             'pAdd': x['median_real_price_of_additions'], 'pNow': x['median_real_price_now']} for x in r['by_store']]
    syn = [{'store': x['store_id'], 'n': x['n'], 'fixed': x['operations']['existing_oos_change_pct_fixed_capacity'],
            'scaled': x['operations']['existing_oos_change_pct_scaled_capacity'],
            'band': x['operations']['dilution_band_90_pct'], 'k': x['operations']['restock_actions_per_snapshot'],
            'ks': x['operations']['scaled_actions'], 'existing': x['operations']['existing_listings'],
            'inPanel': x['position']['additions_in_four_platform_panel'],
            'shA': x['position']['blinkit_cheapest_of_4_share_additions'],
            'shC': x['position']['blinkit_cheapest_of_4_share_current']} for x in s['by_store']]
    return {'ns': r['adds'], 'real': real, 'syn': syn, 'summary': s['summary_at_50'],
            'realSummary': {k: r[k] for k in ('stores_moving_closer_to_peer_mix_at_50', 'median_tv_distance_before_at_50',
                                              'median_tv_distance_after_at_50')}}


def restock():
    m = metrics('optimize_restock_objective')
    pol = [{'policy': p['policy'], 'j1': p['J1_reduction_pct'], 'j2': p['J2_reduction_pct'],
            'j3': p['J3_store_eta_minutes'], 'j2b': p['J2_reduction_band']} for p in m['policies']]
    return {'policies': pol, 'paired': m['paired_vs_plain_index'], 'dominated': m.get('dominated_alphas', []),
            'oracleShare': m['win_weighted_share_of_oracle_J2'], 'capacity': m['capacity_share'],
            'horizon': m['horizon'], 'sims': m['n_sims'], 'lostNoAction': m['lost_wins_with_no_action'],
            'weights': m['weights']}


def external():
    text = (ROOT / 'docs' / 'external' / 'MARKET_CONTEXT_EXTERNAL.md').read_text(encoding='utf-8')
    cards = []
    for part in re.split(r'(?m)^## ', text)[1:]:
        head, body = part.split('\n', 1)
        fact, _, src = body.partition('Source:')
        url = re.search(r'https?://[^\s)]+', src)
        url = url.group(0).rstrip('.,') if url else ''
        src_txt = re.sub(r'https?://[^\s)]+', '', src)
        src_txt = re.sub(r'\s+\.(\s|$)', '. ', ' '.join(src_txt.split())).strip()
        src_txt = re.sub(r'\.\s*\.', '.', src_txt)
        cards.append({'h': plain(head.strip()), 'body': [plain(' '.join(p.split())) for p in fact.strip().split('\n\n')],
                      'src': plain(src_txt), 'url': url})
    return cards


def data():
    import sys
    sys.path.insert(0, str(ROOT))
    from src import provenance
    return {'platforms': PLAT, 'chains': chains(), 'outage': outage(), 'adds': adds(), 'restock': restock(),
            'external': external(), 'storeUnverified': provenance.unverified()}


PAGE = r'''<title>Listing Chain Explorer</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@100..125,500..800&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
:root {
  color-scheme: light;
  --page: #eef2f0; --surface: #f7f9f8; --ink: #0f1512; --ink-2: #48514c; --muted: #6f7873;
  --grid: #dde4e0; --axis: #b6c0ba; --rule: rgba(15,21,18,.12);
  --blue: #2a78d6; --orange: #eb6834; --aqua: #1baf7a;
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
    --blue: #3987e5; --orange: #d95926; --aqua: #199e70;
    --wash-blue: rgba(57,135,229,.17); --hatch: rgba(237,242,238,.32); --tip-bg: #edf2ee; --tip-ink: #0c0f0d;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0c0f0d; --surface: #141816; --ink: #edf2ee; --ink-2: #b8c1bc; --muted: #8d9690;
  --grid: #232a26; --axis: #3b4540; --rule: rgba(237,242,238,.12);
  --blue: #3987e5; --orange: #d95926; --aqua: #199e70;
  --wash-blue: rgba(57,135,229,.17); --hatch: rgba(237,242,238,.32); --tip-bg: #edf2ee; --tip-ink: #0c0f0d;
}
* { box-sizing: border-box; }
body { background: var(--page); color: var(--ink); font: 15px/1.55 var(--sans); margin: 0; }
.wrap { max-width: 1080px; margin: 0 auto; padding-inline: 20px; padding-block: 28px 64px; }
header { display: flex; flex-wrap: wrap; align-items: end; justify-content: space-between; gap: 12px 24px; margin-bottom: 14px; }
h1 { font-family: var(--display); font-variation-settings: "wdth" 125; font-weight: 800; font-size: clamp(32px, 6vw, 54px);
     line-height: 1; letter-spacing: -.02em; margin: 0; text-wrap: balance; }
.intro { max-width: 72ch; color: var(--ink-2); margin: 0 0 14px; }
/* provenance chips: the label is the text, the form repeats it (REAL solid, SYNTHETIC hatched, METHOD outline, EXTERNAL dashed) */
.chip { display: inline-flex; align-items: center; font: 600 10.5px/1 var(--mono); letter-spacing: .06em; text-transform: uppercase;
        padding: 4px 6px 3px; border-radius: 3px; white-space: nowrap; color: var(--ink); vertical-align: 2px; }
.chip.REAL { border: 1.5px solid var(--ink); background: var(--surface); box-shadow: inset 0 0 0 1.5px var(--surface), inset 0 0 0 3px var(--ink); padding: 5px 8px 4px; }
.chip.SYNTHETIC { border: 1.5px solid var(--ink); background: repeating-linear-gradient(135deg, var(--hatch) 0 1.5px, transparent 1.5px 6px), var(--surface); }
.chip.METHOD { border: 1px solid var(--axis); color: var(--ink-2); background: var(--surface); }
.chip.EXTERNAL { border: 1.5px dashed var(--ink); background: var(--surface); }
.chip.UNVERIFIED { border: 1.5px dotted var(--ink); background: var(--surface); }
.storenote { font-size: 13.5px; color: var(--ink-2); border-left: 3px dotted var(--ink); padding-left: 12px; margin: 0 0 18px; max-width: 78ch; }
.key { display: flex; flex-wrap: wrap; gap: 8px 18px; align-items: center; font-size: 13px; color: var(--ink-2); margin: 0 0 20px; }
.key span { display: inline-flex; gap: 7px; align-items: center; }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--rule); margin-bottom: 20px; overflow-x: auto; }
.tabs button { font: 600 14px var(--sans); color: var(--ink-2); background: none; border: 0; border-bottom: 2px solid transparent;
               padding: 10px 14px; cursor: pointer; white-space: nowrap; }
.tabs button[aria-selected="true"] { color: var(--ink); border-bottom-color: var(--ink); }
button:focus-visible, select:focus-visible, a:focus-visible, [data-tip]:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.controls { display: flex; flex-wrap: wrap; gap: 14px 24px; align-items: end; margin-bottom: 18px; }
.ctl { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.ctl > span { font: 500 12px var(--mono); color: var(--muted); letter-spacing: .04em; text-transform: uppercase; }
select { font: 14px var(--sans); color: var(--ink); background: var(--surface); border: 1px solid var(--rule); border-radius: 6px;
         padding: 7px 10px; max-width: 100%; }
.seg { display: inline-flex; border: 1px solid var(--rule); border-radius: 6px; overflow: hidden; background: var(--surface); }
.seg button { font: 500 13px var(--sans); color: var(--ink-2); background: none; border: 0; padding: 7px 12px; cursor: pointer; }
.seg button + button { border-left: 1px solid var(--rule); }
.seg button[aria-pressed="true"] { background: var(--ink); color: var(--page); }
/* the seven-stage rail */
.listing-head { display: flex; flex-wrap: wrap; gap: 6px 16px; align-items: baseline; margin: 0 0 18px; }
.listing-head h2 { font: 600 22px/1.2 var(--sans); margin: 0; text-wrap: balance; }
.listing-head .meta { color: var(--ink-2); font-size: 14px; }
.rail { position: relative; display: grid; gap: 22px; }
.rail::before { content: ""; position: absolute; left: 27px; top: 8px; bottom: 8px; width: 2px; background: var(--grid); }
.stage { position: relative; display: grid; grid-template-columns: 56px minmax(0, 1fr); gap: 14px; }
.snum { position: relative; z-index: 1; font: 800 34px/1 var(--display); font-variation-settings: "wdth" 125; color: var(--ink);
        background: var(--page); text-align: center; padding-block: 2px 6px; font-variant-numeric: tabular-nums; }
.sbody { min-width: 0; }
.sbody h3 { font: 600 17px/1.3 var(--sans); margin: 2px 0 10px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.sbody h3 .what { font: 400 13px var(--sans); color: var(--muted); }
.cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr)); gap: 14px; }
.card { background: var(--surface); border: 1px solid var(--rule); border-radius: 6px; padding: 12px 14px; min-width: 0; }
.card h4 { font: 600 13px/1.3 var(--sans); margin: 0 0 6px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.card p { margin: 0; font-size: 14px; color: var(--ink-2); }
.card .big { font: 600 22px/1.2 var(--sans); color: var(--ink); display: block; margin: 2px 0 4px; font-variant-numeric: tabular-nums; }
.apps { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
.app { background: var(--surface); border: 1.5px solid var(--ink); border-radius: 5px; padding: 7px 9px; font-size: 13px; line-height: 1.3; }
.app.off { border: 1.5px dashed var(--axis); color: var(--muted); background: transparent; }
.app b { font: 600 12px var(--mono); display: block; margin-bottom: 2px; }
.app .st { font: 500 11px var(--mono); letter-spacing: .04em; text-transform: uppercase; display: block; margin-top: 3px; }
.rungs { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }
.rung { font: 500 11.5px var(--mono); padding: 3px 6px; border-radius: 3px; border: 1px solid var(--rule); color: var(--ink-2); font-variant-numeric: tabular-nums; }
.rung.hold { border: 1.5px solid var(--ink); color: var(--ink); font-weight: 600; }
.rung.increase { border-style: dashed; }
.pill { display: inline-flex; align-items: center; gap: 6px; font: 600 12px var(--mono); letter-spacing: .03em; padding: 4px 8px; border-radius: 999px;
        border: 1.5px solid var(--ink); }
.pill.fail { border-style: dashed; }
.verdict { font: 600 18px/1.35 var(--sans); margin: 0 0 10px; max-width: 70ch; text-wrap: pretty; }
.claims { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
.claims li { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 10px; font-size: 13.5px; align-items: start; }
.claims .src { display: block; font: 11.5px/1.4 var(--mono); color: var(--muted); margin-top: 2px; overflow-wrap: anywhere; }
.headline { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 1px; background: var(--rule); border: 1px solid var(--rule); margin-bottom: 18px; }
.tile { background: var(--surface); padding: 12px 14px; }
.tile .v { font: 600 22px/1.15 var(--sans); display: block; font-variant-numeric: tabular-nums; }
.tile .l { font-size: 12px; color: var(--muted); display: block; margin-top: 4px; }
.grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 460px), 1fr)); gap: 18px; }
.panel { background: var(--surface); border: 1px solid var(--rule); border-radius: 6px; padding: 16px 16px 10px; min-width: 0; }
.panel h2 { font: 600 15px/1.3 var(--sans); margin: 0 0 4px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.panel p.note { font-size: 13px; color: var(--ink-2); margin: 0 0 10px; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 12.5px; color: var(--ink-2); margin-bottom: 6px; }
.legend span { display: inline-flex; align-items: center; gap: 7px; }
.sw { width: 12px; height: 12px; display: inline-block; flex: none; border-radius: 50%; }
.sw.line { height: 2px; width: 18px; border-radius: 0; }
.sw.dash { height: 0; width: 18px; border-radius: 0; border-top: 2px dashed var(--orange); background: none; }
.sw.ring { background: var(--surface); border: 2px solid var(--axis); }
.chart svg { display: block; width: 100%; height: auto; }
.chart { overflow-x: auto; }
svg text { font-family: var(--sans); }
.g { stroke: var(--grid); stroke-width: 1; } .b { stroke: var(--axis); stroke-width: 1; }
.tick { fill: var(--muted); font: 11px var(--mono); } .lab { fill: var(--ink-2); font-size: 12px; }
.val { fill: var(--ink-2); font: 11px var(--mono); } .ttl { fill: var(--muted); font-size: 11px; } .dl { font: 600 11.5px var(--sans); fill: var(--ink); }
[data-tip] { outline: none; } circle[data-tip]:hover, rect[data-tip]:hover, circle[data-tip]:focus-visible, rect[data-tip]:focus-visible { stroke: var(--ink); stroke-width: 2; }
.hit { fill: transparent; }
.heat { border-collapse: separate; border-spacing: 2px; font: 12.5px var(--sans); width: 100%; }
.heat th { font-weight: 600; color: var(--ink-2); text-align: left; padding: 4px 6px; font-size: 12px; }
.heat td { text-align: center; padding: 10px 4px; border-radius: 3px; font: 500 12.5px var(--mono); font-variant-numeric: tabular-nums; color: var(--ink); }
.heat td.self { outline: 1.5px solid var(--ink); outline-offset: -1.5px; }
details { margin: 8px 0 4px; } summary { cursor: pointer; font: 500 13px var(--sans); color: var(--ink-2); padding-block: 4px; width: max-content; max-width: 100%; }
table.t { border-collapse: collapse; font: 12.5px/1.4 var(--sans); min-width: 100%; }
table.t th, table.t td { text-align: left; padding: 5px 12px 5px 0; border-bottom: 1px solid var(--grid); vertical-align: top; }
table.t th { color: var(--ink-2); font-weight: 600; white-space: nowrap; } table.t td { font-variant-numeric: tabular-nums; }
.tbl { overflow-x: auto; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); gap: 14px; }
.ext { background: var(--surface); border: 1.5px dashed var(--axis); border-radius: 6px; padding: 14px 16px; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.ext h3 { font: 600 15px/1.35 var(--sans); margin: 0; text-wrap: balance; }
.ext p { margin: 0; font-size: 13.5px; color: var(--ink-2); }
.ext .srcline { font: 11.5px/1.45 var(--mono); color: var(--muted); margin-top: auto; overflow-wrap: anywhere; }
.ext a { color: var(--ink); text-decoration-color: var(--axis); text-underline-offset: 3px; }
.grp { font: 600 10px/1 var(--mono); letter-spacing: .06em; }
.claim-limit { font-size: 13px; color: var(--muted); margin-top: 18px; max-width: 80ch; }
#tip { position: fixed; z-index: 10; pointer-events: none; max-width: 300px; padding: 7px 10px; border-radius: 4px;
       background: var(--tip-bg); color: var(--tip-ink); font: 12.5px/1.4 var(--sans); }
@media (max-width: 520px) {
  .rail::before { left: 17px; }
  .stage { grid-template-columns: 36px minmax(0, 1fr); gap: 10px; }
  .snum { font-size: 24px; }
}
@media (prefers-reduced-motion: no-preference) { .tabs button, .seg button { transition: color .15s, background-color .15s; } }
[hidden] { display: none !important; }
</style>

<div class="wrap">
  <header>
    <h1>Listing Chain Explorer</h1>
    <span class="chip SYNTHETIC">SYNTHETIC unless marked</span>
  </header>
  <p class="intro">One Blinkit listing at a time, through the project's seven stages: what was observed, which models apply,
  what they predicted, the prices Blinkit can actually post, a simulation checked against what happened before it is used,
  the move it recommends, and the labelled explanation. Then three scenarios and the cited market context. The generated
  panel and every simulation describe the fitted, generated dynamics of four Bhubaneswar platforms, never the real market,
  and nothing here is about demand or revenue.</p>
  <div class="key" aria-label="Provenance key">
    <span><span class="chip REAL">REAL</span> the observed 2026-07-10 Blinkit snapshot</span>
    <span><span class="chip SYNTHETIC">SYNTHETIC</span> generated data and models of it</span>
    <span><span class="chip METHOD">METHOD</span> how it works</span>
    <span><span class="chip EXTERNAL">EXTERNAL</span> a cited public source</span>
  </div>

  <nav class="tabs" role="tablist" aria-label="Sections">
    <button role="tab" id="t-listing" aria-selected="true" aria-controls="p-listing">One listing</button>
    <button role="tab" id="t-outage" aria-selected="false" aria-controls="p-outage">When stock runs out</button>
    <button role="tab" id="t-adds" aria-selected="false" aria-controls="p-adds">A store adds products</button>
    <button role="tab" id="t-restock" aria-selected="false" aria-controls="p-restock">Restock priorities</button>
    <button role="tab" id="t-market" aria-selected="false" aria-controls="p-market">Market context</button>
  </nav>

  <section id="p-listing" role="tabpanel" aria-labelledby="t-listing">
    <div class="controls">
      <div class="ctl"><span>Listing</span><select id="pick" aria-label="Choose a listing"></select></div>
    </div>
    <div id="listing"></div>
  </section>

  <section id="p-outage" role="tabpanel" aria-labelledby="t-outage" hidden>
    <p class="intro">A platform that is out of stock cannot be the cheapest option. <b>Cheapest-available-of-4</b> counts a
    platform as winning a product at a snapshot only when it is in stock and the cheapest of the four (ties count for each).
    Each scenario takes every listing of the four-platform panel out of stock now, with outage lengths drawn from the fitted
    restock model, and follows the next 12 snapshots, paired with the same run without the outage.</p>
    <div class="headline" id="o-tiles"></div>
    <div class="grid2">
      <div class="panel"><h2>Who picks up the wins when a platform runs out <span class="chip SYNTHETIC">SYNTHETIC</span></h2>
        <p class="note">Change in cheapest-available share over 12 snapshots, in percentage points. Rows: the platform that runs out. Outlined: its own loss.</p>
        <div class="tbl" id="o-heat"></div></div>
      <div class="panel"><h2>What waiting costs Blinkit <span class="chip SYNTHETIC">SYNTHETIC</span></h2>
        <p class="note">Blinkit's change in cheapest-available share by how long the outage lasts. At 0 the listing is back before the next snapshot, with a fresh in-stock clock.</p>
        <div class="chart" id="o-len"></div></div>
    </div>
    <div class="grid2" style="margin-top:18px">
      <div class="panel"><h2>A Blinkit outage, by category <span class="chip SYNTHETIC">SYNTHETIC</span></h2>
        <p class="note">Tag: the restock speed group the generator planted. The fast-restocking categories lose least, so the outage cost recovers the planted groups from a new direction.</p>
        <div class="chart" id="o-cat"></div>
        <details><summary>Show the numbers</summary><div class="tbl" id="o-cat-t"></div></details></div>
      <div class="panel"><h2>Is there substitution in the data? <span class="chip SYNTHETIC">SYNTHETIC</span></h2>
        <p class="note">If shoppers switched when Blinkit is out, competitor listings of the same product would run out faster. The generator planted no such link, and the check finds none.</p>
        <div class="chart" id="o-sub"></div><div id="o-sub-t"></div></div>
    </div>
  </section>

  <section id="p-adds" role="tabpanel" aria-labelledby="t-adds" hidden>
    <p class="intro">Each Blinkit store adds its top assortment gaps: products similar REAL stores list and it was not seen
    listing. The assortment and price parts use the REAL 2026-07-10 snapshot; the restock part simulates the store's
    generated listings with the additions competing for the same restock effort.</p>
    <p class="storenote" data-store-note hidden><span class="chip UNVERIFIED">store label unverified</span> The two REAL
    panels below group the real rows by store. On ten permutation tests that store label cannot be told apart from a
    random one, and the source file does not record how a product was tied to a store. Read them as a property of the
    file, not as findings about real stores.</p>
    <div class="controls"><div class="ctl"><span>Products added</span><div class="seg" id="a-n"></div></div></div>
    <div class="grid2">
      <div class="panel"><h2>Category mix against the peer stores <span class="chip REAL">REAL</span></h2>
        <p class="note">Total-variation distance between the store's category shares and the median of the other seven stores. Lower is closer.</p>
        <div class="legend"><span><i class="sw ring"></i>before</span><span><i class="sw" style="background:var(--blue)"></i>after adding</span></div>
        <div class="chart" id="a-tv"></div></div>
      <div class="panel"><h2>The additions are cheaper items <span class="chip REAL">REAL</span></h2>
        <p class="note">Median REAL price of the added products (in the stores that list them) against the store's current median.</p>
        <div class="legend"><span><i class="sw ring"></i>store's median now</span><span><i class="sw" style="background:var(--blue)"></i>median of the additions</span></div>
        <div class="chart" id="a-px"></div></div>
    </div>
    <div class="panel" style="margin-top:18px"><h2>Restock effort spread over more listings <span class="chip SYNTHETIC">SYNTHETIC</span></h2>
      <p class="note">Change in the existing listings' out-of-stock exposure over 12 snapshots. The added listings are simulated in every run, so all random streams stay paired.</p>
      <div class="legend"><span><i class="sw" style="background:var(--orange)"></i>same number of restock actions (whisker: 90% of simulations)</span><span><i class="sw" style="background:var(--blue)"></i>actions scaled to the larger assortment</span></div>
      <div class="chart" id="a-ops"></div>
      <details><summary>Show the numbers</summary><div class="tbl" id="a-t"></div></details></div>
  </section>

  <section id="p-restock" role="tabpanel" aria-labelledby="t-restock" hidden>
    <p class="intro">Deliverable 12b restocks whatever saves the most out-of-stock snapshots, and counts every listing alike.
    In positioning terms a stock-out only costs something when the listing would have won: been in stock and the cheapest.
    Weighting each listing by its chance of winning (α from 1, the plain index, to 0, fully weighted) trades one objective for the other.</p>
    <div class="headline" id="r-tiles"></div>
    <div class="grid2">
      <div class="panel"><h2>The trade-off <span class="chip SYNTHETIC">SYNTHETIC</span></h2>
        <p class="note">Reduction against doing nothing, in percent. Right is fewer out-of-stock snapshots; up is fewer lost cheapest-available wins.</p>
        <div class="legend"><span><i class="sw" style="background:var(--blue)"></i>the index at each α</span><span><i class="sw" style="background:var(--orange)"></i>clairvoyant benchmark</span><span><i class="sw ring"></i>simple rules</span></div>
        <div class="chart" id="r-front"></div></div>
      <div class="panel"><h2>Against the plain index, paired <span class="chip SYNTHETIC">SYNTHETIC</span></h2>
        <p class="note" id="r-note"></p>
        <div class="tbl" id="r-paired"></div></div>
    </div>
    <details><summary>Show every policy</summary><div class="tbl" id="r-t"></div></details>
  </section>

  <section id="p-market" role="tabpanel" aria-labelledby="t-market" hidden>
    <p class="intro">Public facts about the four platforms, each confirmed on the fetched page and cited with its URL and
    dates. They are context, not the project's data: none was checked against it, none confirms a synthetic result, and
    sales figures (revenue, order value, market share) are left out on purpose.</p>
    <div class="cards" id="m-cards"></div>
  </section>

  <p class="claim-limit">Built from saved outputs of the quickcommerce-mi project (outputs/models). Positioning and availability only;
  there are no orders, shoppers or revenue in this data.</p>
</div>
<div id="tip" role="tooltip" hidden></div>

<script>
const DATA = __DATA__;
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const pct = v => (100 * v).toFixed(1) + '%';
const sgn = (v, d = 1) => (v > 0 ? '+' : v < 0 ? '−' : '±') + Math.abs(v).toFixed(d);
const rs = v => '₹' + (Math.abs(v - Math.round(v)) < 1e-9 ? Math.round(v).toLocaleString('en-IN') : v.toFixed(2));
const chip = p => `<span class="chip ${esc(p)}">${esc(p)}</span>`;
document.querySelectorAll('[data-store-note]').forEach(n => { n.hidden = !DATA.storeUnverified; });
function scale(d0, d1, r0, r1) { return v => r0 + (v - d0) / (d1 - d0) * (r1 - r0); }
function tipAttr(t) { return ` data-tip="${esc(t)}" tabindex="0"`; }
function table(head, rows, raw) {
  return '<table class="t"><thead><tr>' + head.map(h => `<th>${esc(h)}</th>`).join('') + '</tr></thead><tbody>' +
    rows.map(r => '<tr>' + r.map((c, i) => `<td>${raw && raw.includes(i) ? c : esc(c)}</td>`).join('') + '</tr>').join('') + '</tbody></table>';
}
function tiles(el, items) {
  el.innerHTML = items.map(([v, l]) => `<div class="tile"><span class="v">${esc(v)}</span><span class="l">${esc(l)}</span></div>`).join('');
}
function niceTicks(lo, hi, n = 5) {
  const span = hi - lo || 1, raw = span / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => span / s <= n) || 10 * mag;
  const out = []; for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}
const state = { li: 0, n: 50, tab: 'listing' };
// draw every chart at its container's real pixel width: text then renders at its set size on a phone and on a wide
// screen alike, instead of an SVG scaled to fit (5 px text on a phone, 19 px on a wide panel)
function cw(el, fallback) { const w = el ? el.clientWidth : 0; return w > 0 ? Math.max(300, Math.round(w)) : fallback; }

// =============================================================== one listing
function priceStrip(L, W) {
  const P = DATA.platforms.filter(p => L.dec.comp[p] != null), prices = P.map(p => L.dec.comp[p]);
  const lo = Math.min(...prices), hi = Math.max(...prices), pad = Math.max((hi - lo) * 0.25, hi * 0.02);
  // the label column must fit "Swiggy Instamart" (about 104 px at 12 px) even on a phone
  const rowH = 26, l = Math.min(132, Math.max(120, Math.round(W * 0.34))), r = 86, t = 8, H = t + rowH * P.length + 24;
  const x = scale(lo - pad, hi + pad, l, W - r), cheapest = lo;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Prices of the four platforms at the decision snapshot">`;
  niceTicks(lo - pad, hi + pad, W < 520 ? 2 : 4).forEach(v => { if (v >= lo - pad && v <= hi + pad) s += `<line class="g" x1="${x(v)}" x2="${x(v)}" y1="${t}" y2="${H - 22}"/><text class="tick" x="${x(v)}" y="${H - 8}" text-anchor="middle">${esc(rs(v))}</text>`; });
  P.forEach((p, i) => {
    const yy = t + i * rowH + rowH / 2, v = L.dec.comp[p], blk = p === 'Blinkit';
    s += `<text class="${blk ? 'dl' : 'lab'}" x="${l - 12}" y="${yy + 4}" text-anchor="end">${esc(p)}</text>`;
    s += `<circle cx="${x(v)}" cy="${yy}" r="${blk ? 6.5 : 5}" fill="${blk ? 'var(--blue)' : 'var(--ink-2)'}" stroke="var(--surface)" stroke-width="2"${tipAttr(`${p}: ${rs(v)}${v <= cheapest + 1e-9 ? ' (cheapest)' : ''}`)}/>`;
    s += `<text class="val" x="${x(v) + 11}" y="${yy + 4}">${esc(rs(v))}${v <= cheapest + 1e-9 ? ' · cheapest' : ''}</text>`;
  });
  return s + '</svg>';
}

function ladderChart(L, W) {
  const R = L.ladder.slice().sort((a, b) => a.p - b.p);
  const H = Math.round(Math.min(380, Math.max(250, W * 0.5))), l = 48, r = 18, t = 22, b = 44;
  const pmin = R[0].p, pmax = R[R.length - 1].p, padx = (pmax - pmin) * 0.04 || 1;
  const x = scale(pmin - padx, pmax + padx, l, W - r), y = scale(0, 1, H - b, t);
  const now = L.dec.price;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Cheapest-of-4 share by posted price, with and without competitor response">`;
  [0, .25, .5, .75, 1].forEach(v => s += `<line class="${v === 0 ? 'b' : 'g'}" x1="${l}" x2="${W - r}" y1="${y(v)}" y2="${y(v)}"/><text class="tick" x="${l - 6}" y="${y(v) + 4}" text-anchor="end">${Math.round(v * 100)}%</text>`);
  niceTicks(pmin, pmax, 5).forEach(v => { if (v >= pmin - padx && v <= pmax + padx) s += `<text class="tick" x="${x(v)}" y="${H - b + 16}" text-anchor="middle">${esc(rs(v))}</text>`; });
  s += `<text class="ttl" x="${(l + W - r) / 2}" y="${H - 6}" text-anchor="middle">posted Blinkit price (cuts to the left, raises to the right)</text>`;
  // target and the current price
  s += `<line x1="${l}" x2="${W - r}" y1="${y(L.opt.target)}" y2="${y(L.opt.target)}" stroke="var(--muted)" stroke-dasharray="4 4"/>`;
  s += `<text class="ttl" x="${W - r}" y="${y(L.opt.target) - 5}" text-anchor="end">target ${Math.round(L.opt.target * 100)}%</text>`;
  s += `<line x1="${x(now)}" x2="${x(now)}" y1="${t - 6}" y2="${H - b}" stroke="var(--axis)" stroke-width="1.5"/>`;
  s += `<text class="lab" x="${x(now) + 6}" y="${H - b - 10}">now ${esc(rs(now))}</text>`;
  // strategic 90% band
  const band = R.map(g => `${x(g.p)},${y(g.sb[1])}`).join(' ') + ' ' + R.slice().reverse().map(g => `${x(g.p)},${y(g.sb[0])}`).join(' ');
  s += `<polygon points="${band}" fill="var(--wash-blue)" stroke="none"/>`;
  s += `<polyline fill="none" stroke="var(--orange)" stroke-width="2" stroke-dasharray="6 4" points="${R.map(g => `${x(g.p)},${y(g.t)}`).join(' ')}"/>`;
  s += `<polyline fill="none" stroke="var(--blue)" stroke-width="2" stroke-linejoin="round" points="${R.map(g => `${x(g.p)},${y(g.s)}`).join(' ')}"/>`;
  R.forEach(g => {
    const mv = g.m === 0 ? 'hold' : (g.m > 0 ? '+' : '−') + Math.abs(g.m).toFixed(2) + '%';
    const promo = g.mode === 'deepen' ? `; as a promo: ${sgn(g.oos, 2)} pp stock-out risk` : g.mode === 'withdraw' ? `; withdrawing the promo: ${sgn(g.oos, 2)} pp stock-out risk` : '';
    const tipTxt = `${rs(g.p)} (${mv}): competitors respond ${pct(g.s)} (90% band ${pct(g.sb[0])}–${pct(g.sb[1])}); no response ${pct(g.t)}${promo}`;
    s += `<circle cx="${x(g.p)}" cy="${y(g.t)}" r="3.5" fill="var(--orange)" stroke="var(--surface)" stroke-width="2"/>`;
    s += `<circle cx="${x(g.p)}" cy="${y(g.s)}" r="4" fill="var(--blue)" stroke="var(--surface)" stroke-width="2"/>`;
    s += `<rect class="hit" x="${x(g.p) - 7}" y="${t}" width="14" height="${H - b - t}"${tipAttr(tipTxt)}/>`;
  });
  // the recommended rung
  const o = L.opt, pick = o.dir === 'raise' ? (o.raise && o.raise.strategic) : o.strategic;
  const pickPrice = pick && (pick.price != null) ? pick.price : null;
  if (pickPrice != null && (o.dir === 'raise' ? pick.target_met_at_current_price : pick.reachable_within_30pct)) {
    const g = R.find(z => Math.abs(z.p - pickPrice) < 1e-9);
    if (g) s += `<circle cx="${x(g.p)}" cy="${y(g.s)}" r="9" fill="none" stroke="var(--ink)" stroke-width="2"/>`;
  }
  // direct labels where the two lines differ most
  let k = 0, best = -1; R.forEach((g, i) => { const d = Math.abs(g.s - g.t); if (d > best) { best = d; k = i; } });
  const g = R[k];
  if (best > 0.08) {
    // beside the points, on the side with room; pushed at least 16px apart and kept inside the plot
    const right = x(g.p) < (l + W - r) / 2, xx = x(g.p) + (right ? 12 : -12), anc = right ? 'start' : 'end';
    let ys = y(g.s) + 4, yt = y(g.t) + 4;
    if (Math.abs(ys - yt) < 16) { const mid = (ys + yt) / 2, up = g.s >= g.t; ys = mid + (up ? -8 : 8); yt = mid + (up ? 8 : -8); }
    const clamp = v => Math.min(Math.max(v, t + 12), H - b - 22);
    s += `<text class="dl" x="${xx}" y="${clamp(ys)}" text-anchor="${anc}">competitors respond</text>`;
    s += `<text class="dl" x="${xx}" y="${clamp(yt)}" text-anchor="${anc}">no response</text>`;
  }
  return s + '</svg>';
}

function stage(n, title, what, prov, inner) {
  return `<section class="stage"><div class="snum" aria-hidden="true">${n}</div><div class="sbody">` +
    `<h3>${esc(title)} ${prov ? chip(prov) : ''} <span class="what">${esc(what)}</span></h3>${inner}</div></section>`;
}

function renderListing() {
  const L = DATA.chains[state.li], d = L.dec, P = DATA.platforms;
  let h = `<div class="listing-head"><h2>${esc(L.name)} <span style="font-weight:400;color:var(--ink-2)">${esc(L.pack)}</span></h2>` +
          `<span class="meta">${esc(L.storeName)} · ${esc(L.store)} · ${esc(L.category)}</span></div><div class="rail">`;
  // 1 observe
  const real = L.real ? `<div class="card"><h4>${chip('REAL')} 2026-07-10 snapshot, same product${DATA.storeUnverified ? '' : ' and store'}</h4>` +
      `<span class="big">${esc(rs(L.real.price))}</span><p>MRP ${esc(rs(L.real.mrp))} · ${esc(L.real.stock)} · ETA ${L.real.eta[0] === L.real.eta[1] ? L.real.eta[0] : L.real.eta.join('–')} min. Context only: no model uses it.` +
      (DATA.storeUnverified ? ` <span class="chip UNVERIFIED">store label unverified</span> Its price and stock are verified against the source; that it belongs to this store is not.` : '') + `</p></div>` : '';
  const dec = `<div class="card"><h4>${chip('SYNTHETIC')} decision snapshot, ${esc(d.at)}</h4>` +
      `<span class="big">${esc(rs(d.price))}</span><p>${d.inStock ? 'In stock' : 'Out of stock'} · ETA ${d.eta} min · ${d.promo ? `on promo, ${d.disc.toFixed(1)}% off MRP ${esc(rs(d.mrp))}` : 'no promo'} · ` +
      `${d.cheapest ? 'Blinkit is the cheapest of the four' : 'Blinkit is not the cheapest'}</p></div>`;
  h += stage(1, 'Observe', 'the listing, its competitors, and the REAL row as context', null,
    `<div class="cols">${real}${dec}</div><div class="card" style="margin-top:14px"><h4>${chip('SYNTHETIC')} the same product on the four platforms, same snapshot</h4><div class="chart" id="c-strip"></div></div>`);
  // 2 applicability
  h += stage(2, 'Applicability', 'which of the ten models apply to this listing, and why', null,
    `<div class="apps">${L.app.map(a => `<div class="app${a.on ? '' : ' off'}"${tipAttr(a.why + (a.gapIn.length ? ' REAL gap elsewhere: ' + a.gapIn.join(', ') : ''))}><b>${esc(a.k)}</b>${esc(a.name)}<span class="st">${a.on ? '✓ applies' : '— not applied'}</span></div>`).join('')}</div>`);
  // 3 prediction record
  h += stage(3, 'Prediction record', 'each applicable model beside what happened next', null,
    `<div class="tbl">${table(['model', 'predicted', 'what happened', ''], L.pred.map(r => [r[0], r[1], r[2], chip(r[3])]), [3])}</div>`);
  // 4 price grid
  const rungs = L.ladder.slice().sort((a, b) => b.p - a.p).map(g => `<span class="rung ${g.k}">${esc(rs(g.p))}</span>`).join('');
  h += stage(4, 'Price grid', 'the prices Blinkit can actually post, from the listing\'s own past prices', 'SYNTHETIC',
    `<p style="margin:0;color:var(--ink-2);max-width:70ch">${esc(rs(L.grid.step))} steps ending in ${L.grid.rem}, inferred from ${esc(L.grid.from)}. ` +
    `Increases up to ${esc(rs(L.grid.ceiling))}, cuts down to ${esc(rs(L.grid.floor))}.</p><div class="rungs" aria-label="Price ladder">${rungs}</div>`);
  // 5 simulation
  const v = L.base, cov = P.map(p => `${p} ${Math.round(100 * v.cov[p])}%`).join(', ');
  let sim = `<p style="margin:0 0 10px"><span class="pill${v.passed ? '' : ' fail'}">${v.passed ? '✓ baseline check passed' : '✗ baseline check failed'}</span></p>` +
    `<p style="margin:0 0 12px;color:var(--ink-2);font-size:14px;max-width:72ch">Replaying the ${v.n} test snapshots put ${esc(cov)} of observed prices inside the simulated 90% band; ` +
    `the observed cheapest share ${pct(v.obs)} sits inside the simulated range ${pct(v.range[0])}–${pct(v.range[1])}.</p>` +
    `<div class="card"><h4>${chip('SYNTHETIC')} cheapest-of-4 share over the next 12 snapshots, by posted price</h4>` +
    `<div class="legend"><span><i class="sw line" style="background:var(--blue)"></i>competitors respond (shaded: 90% band)</span><span><i class="sw dash"></i>no response</span><span><i class="sw ring" style="border-color:var(--ink)"></i>recommended rung</span></div>` +
    `<div class="chart" id="c-ladder"></div></div>`;
  if (L.unav) {
    const u = L.unav, top = Object.entries(u.sc.drawn.inh).sort((a, b) => b[1] - a[1])[0];
    sim += `<div class="headline" style="margin:14px 0 0"><div class="tile"><span class="v">${pct(u.now)}</span><span class="l">in stock and cheapest now, next 12 snapshots</span></div>` +
      `<div class="tile"><span class="v">${sgn(u.sc.drawn.d, 2)} pp</span><span class="l">if it went out now (outage length from the restock model: ${u.spell.toFixed(2)} snapshots on average)</span></div>` +
      `<div class="tile"><span class="v">${sgn(u.sc.restored_now.d, 2)} pp</span><span class="l">if restored before the next snapshot</span></div>` +
      `<div class="tile"><span class="v">${top[1] > 0.05 ? esc(top[0]) : 'nobody'}</span><span class="l">${top[1] > 0.05 ? 'gains most from the outage (' + sgn(top[1], 2) + ' pp)' : 'gains much: Blinkit was rarely the cheapest available'}</span></div></div>`;
  }
  h += stage(5, 'Simulation', 'checked against what happened before any what-if is trusted', null, sim);
  // 6 optimization
  const o = L.opt;
  let det = [];
  if (o.dir === 'raise' && o.raise) {
    ['strategic', 'static'].forEach(k => { const z = o.raise[k]; det.push([k === 'strategic' ? 'competitors respond' : 'no response',
      z.target_met_at_current_price ? (z.raise_rs > 0 ? `raise ${rs(z.raise_rs)} (+${z.raise_pct}%) to ${rs(z.price)}` : 'hold') : 'target not met at the current price',
      z.mean_cheapest_share != null ? pct(z.mean_cheapest_share) : '—']); });
  } else {
    ['strategic', 'static'].forEach(k => { const z = o[k]; det.push([k === 'strategic' ? 'competitors respond' : 'no response',
      z.reachable_within_30pct ? (z.cut_rs > 0 ? `cut ${rs(z.cut_rs)} (${z.cut_pct}%) to ${rs(z.price)}` : 'hold') : 'not reachable within a 30% cut',
      z.mean_cheapest_share != null ? pct(z.mean_cheapest_share) : '—']); });
  }
  let six = `<p class="verdict">${esc(o.verdict.charAt(0).toUpperCase() + o.verdict.slice(1))}.</p>` +
    `<div class="tbl">${table(['view', o.dir === 'raise' ? 'largest raise that keeps the target' : 'smallest cut that reaches the target', 'cheapest-of-4 share'], det)}</div>`;
  if (o.dir !== 'raise' && o.strategic.reachable_within_30pct && o.strategic.cut_rs > 0)
    six += `<p style="margin:8px 0 0;font-size:14px;color:var(--ink-2)">Run as a promo, that cut adds ${sgn(o.strategic.promo_extra_p_oos_within_12_pp, 2)} pp to the chance of a stock-out within 12 snapshots and ${o.strategic.promo_eta_added_min.toFixed(3)} min of ETA; as a list-price cut, neither.</p>`;
  if (o.ifu) six += `<p style="margin:8px 0 0;font-size:14px;color:var(--ink-2)">If it goes out of stock: <b>${esc(o.ifu.action)}</b>. Restoring it at once recovers ${sgn(o.ifu.cheapest_available_pp_recovered_by_expediting, 2)} pp of cheapest-available share; its restock priority index is ${o.ifu.expedite_priority_index} expected out-of-stock snapshots saved.</p>`;
  h += stage(6, 'Optimization', `one target (cheapest in ${Math.round(o.target * 100)}% of the next 12 snapshots), two directions`, 'SYNTHETIC', six);
  // 7 explanation
  h += stage(7, 'Explanation', 'what the analyst says, claim by claim, each with its label and source', null,
    `<ol class="claims">${L.claims.map(c => `<li>${chip(c.prov)}<div>${esc(c.text)}<span class="src">stage ${esc(c.stage.replace('_', ' ').replace('_', ' '))} · ${esc(c.src)}</span></div></li>`).join('')}</ol>`);
  $('#listing').innerHTML = h + '</div>';
  $('#c-strip').innerHTML = priceStrip(L, cw($('#c-strip'), 560));
  $('#c-ladder').innerHTML = ladderChart(L, cw($('#c-ladder'), 560));
}

// =============================================================== outage
function renderOutage() {
  const O = DATA.outage, P = DATA.platforms;
  tiles($('#o-tiles'), P.map(p => [pct(O.now[p]), `${p}: in stock and cheapest now (cheapest on price alone: ${pct(O.priceOnly[p])})`]));
  const all = P.flatMap(a => P.map(b => O.matrix[a][b][1])), mx = Math.max(...all.map(Math.abs));
  let t = '<table class="heat" aria-label="Change in cheapest-available share by which platform runs out"><thead><tr><th>runs out ↓ · changes →</th>' + P.map(p => `<th>${esc(p)}</th>`).join('') + '</tr></thead><tbody>';
  P.forEach(a => {
    t += `<tr><th>${esc(a)}</th>` + P.map(b => {
      const [lo, med, hi] = O.matrix[a][b], w = Math.round(12 + 58 * Math.abs(med) / mx);
      const col = med < 0 ? 'var(--orange)' : 'var(--blue)';
      return `<td class="${a === b ? 'self' : ''}" style="background:color-mix(in srgb, ${col} ${w}%, var(--surface))"${tipAttr(`${a} runs out: ${b} ${sgn(med, 2)} pp (90% of simulations ${sgn(lo, 2)} to ${sgn(hi, 2)})`)}>${sgn(med, 2)}</td>`;
    }).join('') + '</tr>';
  });
  $('#o-heat').innerHTML = t + '</tbody></table>';
  // outage length
  const Ls = O.lengths.slice().sort((a, b) => a[0] - b[0]);
  const W = cw($('#o-len'), 520), H = 250, l = 50, r = 18, tp = 16, b = 40;
  const vals = Ls.map(z => z[1]).concat([O.drawn, 0]);
  const ymin = Math.floor(Math.min(...vals) / 2) * 2, ymax = Math.max(2, Math.ceil(Math.max(...vals) / 2) * 2);
  const x = scale(0, 8, l, W - r), y = scale(ymin, ymax, H - b, tp);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Blinkit's change in cheapest-available share by outage length">`;
  niceTicks(ymin, ymax, 6).forEach(v => s += `<line class="${v === 0 ? 'b' : 'g'}" x1="${l}" x2="${W - r}" y1="${y(v)}" y2="${y(v)}" ${v === 0 ? 'stroke-width="1.5"' : ''}/><text class="tick" x="${l - 6}" y="${y(v) + 4}" text-anchor="end">${v > 0 ? '+' : ''}${v}</text>`);
  Ls.forEach(z => s += `<text class="tick" x="${x(z[0])}" y="${H - b + 16}" text-anchor="middle">${z[0]}</text>`);
  s += `<text class="ttl" x="${(l + W - r) / 2}" y="${H - 6}" text-anchor="middle">snapshots out after now (two a day)</text>`;
  s += `<line x1="${l}" x2="${W - r}" y1="${y(O.drawn)}" y2="${y(O.drawn)}" stroke="var(--muted)" stroke-dasharray="4 4"/>`;
  s += `<text class="ttl" x="${W - r}" y="${y(O.drawn) + 14}" text-anchor="end">drawn length: ${sgn(O.drawn, 2)} pp</text>`;
  s += `<polyline fill="none" stroke="var(--blue)" stroke-width="2" points="${Ls.map(z => `${x(z[0])},${y(z[1])}`).join(' ')}"/>`;
  Ls.forEach(z => s += `<circle cx="${x(z[0])}" cy="${y(z[1])}" r="4.5" fill="var(--blue)" stroke="var(--surface)" stroke-width="2"${tipAttr(`out ${z[0]} snapshot(s) after now: ${sgn(z[1], 2)} pp`)}/>`);
  const f = Ls[0], e = Ls[Ls.length - 1];
  s += `<text class="val" x="${x(f[0]) + 9}" y="${y(f[1]) - 8}">${sgn(f[1], 2)}</text>`;
  s += `<text class="val" x="${x(e[0]) - 9}" y="${y(e[1]) + 4}" text-anchor="end">${sgn(e[1], 2)}</text>`;
  $('#o-len').innerHTML = s + '</svg>' + `<details><summary>Show the numbers</summary><div class="tbl">${table(['snapshots out after now', 'Blinkit change'], Ls.map(z => [String(z[0]), sgn(z[1], 2) + ' pp']).concat([['drawn from the restock model', sgn(O.drawn, 2) + ' pp']]))}</div></details>`;
  // by category
  const W2 = cw($('#o-cat'), 540), C = O.cats, rowH = 24, l2 = Math.min(232, Math.round(W2 * 0.5)), r2 = 58, t2 = 8,
        H2 = t2 + rowH * C.length + 24, maxc = Math.max(10, Math.floor((l2 - 64) / 6.2));
  const cmin = Math.min(0, ...C.map(c => c.v)), cmax = Math.max(0.5, ...C.map(c => c.v));
  const x2 = scale(cmin * 1.08, cmax * 1.08, l2, W2 - r2);
  let c = `<svg viewBox="0 0 ${W2} ${H2}" role="img" aria-label="Blinkit's change in cheapest-available share when it runs out, by category">`;
  c += `<line class="b" x1="${x2(0)}" x2="${x2(0)}" y1="${t2 - 4}" y2="${H2 - 20}"/>`;
  C.forEach((d, i) => {
    const yy = t2 + i * rowH, x0 = x2(Math.min(0, d.v)), wv = Math.max(1, Math.abs(x2(d.v) - x2(0)));
    c += `<text class="lab" x="${l2 - 58}" y="${yy + 15}" text-anchor="end">${esc(d.c.length > maxc ? d.c.slice(0, maxc - 1) + '…' : d.c)}</text>`;
    c += `<text class="grp" x="${l2 - 50}" y="${yy + 15}" fill="var(--muted)">${d.grp}</text>`;
    c += `<rect x="${x0}" y="${yy + 5}" width="${wv}" height="${rowH - 10}" rx="2" fill="var(--blue)"${tipAttr(`${d.c} (${d.skus} SKUs, planted restock group ${d.grp}): ${sgn(d.v, 2)} pp from ${d.now.toFixed(1)}% now`)}/>`;
    c += `<text class="val" x="${d.v < 0 ? x2(0) + 5 : x0 + wv + 5}" y="${yy + 15}">${sgn(d.v, 2)}</text>`;
  });
  niceTicks(cmin, cmax, 4).forEach(v => c += `<text class="tick" x="${x2(v)}" y="${H2 - 6}" text-anchor="middle">${v > 0 ? '+' : ''}${v}</text>`);
  $('#o-cat').innerHTML = c + '</svg>';
  $('#o-cat-t').innerHTML = table(['category', 'planted restock group', 'SKUs', 'Blinkit share now', 'change', 'biggest gainer'],
    C.map(d => { const g = Object.entries(d.inh).sort((a, b) => b[1] - a[1])[0]; return [d.c, d.grp, d.skus, d.now.toFixed(1) + '%', sgn(d.v, 2) + ' pp', `${g[0]} ${sgn(g[1], 2)} pp`]; }));
  // substitution
  const S = O.sub, W3 = cw($('#o-sub'), 520), H3 = 96, l3 = 20, r3 = 20, x3 = scale(0.8, 1.1, l3, W3 - r3), y3 = 40;
  let z = `<svg viewBox="0 0 ${W3} ${H3}" role="img" aria-label="Odds ratio with its 95% confidence interval">`;
  [0.8, 0.9, 1.0, 1.1].forEach(v => z += `<line class="${v === 1 ? 'b' : 'g'}" x1="${x3(v)}" x2="${x3(v)}" y1="${y3 - 22}" y2="${y3 + 18}" ${v === 1 ? 'stroke-width="1.5"' : ''}/><text class="tick" x="${x3(v)}" y="${y3 + 34}" text-anchor="middle">${v.toFixed(1)}</text>`);
  z += `<text class="ttl" x="${x3(1.0) + 6}" y="${y3 - 24}">no effect</text>`;
  z += `<line x1="${x3(S.ci[0])}" x2="${x3(S.ci[1])}" y1="${y3}" y2="${y3}" stroke="var(--blue)" stroke-width="2"/>`;
  z += `<circle cx="${x3(S.or)}" cy="${y3}" r="6" fill="var(--blue)" stroke="var(--surface)" stroke-width="2"${tipAttr(`odds ratio ${S.or.toFixed(3)}, 95% CI ${S.ci[0].toFixed(3)} to ${S.ci[1].toFixed(3)}, p = ${S.p.toFixed(3)} (clustered by product)`)}/>`;
  z += `<text class="ttl" x="${(l3 + W3 - r3) / 2}" y="${H3 - 4}" text-anchor="middle">${W3 < 560 ? 'odds ratio (above 1 = substitution)' : 'odds ratio: a competitor listing runs out at the next snapshot while Blinkit is out (above 1 = substitution)'}</text>`;
  $('#o-sub').innerHTML = z + '</svg>';
  $('#o-sub-t').innerHTML = `<p class="note" style="margin:6px 0 0">Odds ratio ${S.or.toFixed(3)} (95% CI ${S.ci[0].toFixed(3)} to ${S.ci[1].toFixed(3)}) over ${S.rows.toLocaleString('en-IN')} competitor listing-snapshots, controlling for category, platform, in-stock clock, store pressure and time of day, with errors clustered by product. ` +
    `The first check left out time of day and found a small <i>negative</i> association (${S.first.odds_ratio.toFixed(3)}): ${pct(1 - S.eveOut)} of the snapshots where Blinkit is out come before a morning snapshot, against ${pct(1 - S.eveIn)} of the others, and every hazard is lower overnight. Real substitution cannot be measured here: there are no shoppers or orders.</p>`;
}

// =============================================================== store adds
function renderAdds() {
  const A = DATA.adds, n = state.n;
  const R = A.real.filter(z => z.n === n), S = A.syn.filter(z => z.n === n);
  const dumb = (rows, get0, get1, fmt, label, tipf, W) => {
    const rowH = 28, l = Math.min(150, Math.round(W * 0.3)), r = 56, t = 6, H = t + rowH * rows.length + 22;
    const hi = Math.max(...rows.flatMap(z => [get0(z), get1(z)])) * 1.1, x = scale(0, hi, l, W - r);
    let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">`;
    niceTicks(0, hi, 4).forEach(v => s += `<line class="${v === 0 ? 'b' : 'g'}" x1="${x(v)}" x2="${x(v)}" y1="${t}" y2="${H - 20}"/><text class="tick" x="${x(v)}" y="${H - 6}" text-anchor="middle">${fmt(v)}</text>`);
    rows.forEach((z, i) => {
      const yy = t + i * rowH + rowH / 2, a = get0(z), b2 = get1(z);
      s += `<text class="lab" x="${l - 10}" y="${yy + 4}" text-anchor="end">${esc(z.store.replace('BLK-', ''))}</text>`;
      s += `<line x1="${x(a)}" x2="${x(b2)}" y1="${yy}" y2="${yy}" stroke="var(--axis)" stroke-width="2"/>`;
      s += `<circle cx="${x(a)}" cy="${yy}" r="5" fill="var(--surface)" stroke="var(--axis)" stroke-width="2"/>`;
      s += `<circle cx="${x(b2)}" cy="${yy}" r="6" fill="var(--blue)" stroke="var(--surface)" stroke-width="2"${tipAttr(tipf(z))}/>`;
      s += b2 >= a ? `<text class="val" x="${x(b2) + 10}" y="${yy + 4}">${fmt(b2)}</text>`
                   : `<text class="val" x="${x(b2) - 10}" y="${yy + 4}" text-anchor="end">${fmt(b2)}</text>`;
    });
    return s + '</svg>';
  };
  $('#a-tv').innerHTML = dumb(R, z => z.tvb, z => z.tva, v => v.toFixed(3), 'Category-mix distance to peers before and after adding',
    z => `${z.store}: ${z.tvb.toFixed(4)} → ${z.tva.toFixed(4)} (${z.tva < z.tvb ? 'closer' : 'further'}); ${pct(z.under)} of the additions in under-represented categories`,
    cw($('#a-tv'), 520));
  $('#a-px').innerHTML = dumb(R.filter(z => z.pAdd != null), z => z.pNow, z => z.pAdd, v => '₹' + Math.round(v), 'Median REAL price of the additions against the store median',
    z => `${z.store}: store median ${rs(z.pNow)}, additions ${rs(z.pAdd)}`, cw($('#a-px'), 520));
  // operations dot plot
  const W = cw($('#a-ops'), 1000), rowH = 30, l = 104, r = 24, t = 6, H = t + rowH * S.length + 24;
  const vals = S.flatMap(z => [z.fixed, z.scaled, z.band[0], z.band[1]]);
  const lo = Math.min(-1, ...vals), hi = Math.max(1, ...vals), x = scale(lo * 1.1, hi * 1.1, l, W - r);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Change in the existing listings' out-of-stock exposure, fixed versus scaled restock capacity">`;
  niceTicks(lo, hi, 6).forEach(v => s += `<line class="${v === 0 ? 'b' : 'g'}" x1="${x(v)}" x2="${x(v)}" y1="${t}" y2="${H - 22}" ${v === 0 ? 'stroke-width="1.5"' : ''}/><text class="tick" x="${x(v)}" y="${H - 8}" text-anchor="middle">${v > 0 ? '+' : ''}${v}%</text>`);
  S.forEach((z, i) => {
    const yy = t + i * rowH + rowH / 2;
    s += `<text class="lab" x="${l - 10}" y="${yy + 4}" text-anchor="end">${esc(z.store.replace('BLK-', ''))}</text>`;
    s += `<line x1="${x(z.band[0])}" x2="${x(z.band[1])}" y1="${yy - 4}" y2="${yy - 4}" stroke="var(--orange)" stroke-width="1.5" opacity=".7"/>`;
    s += `<circle cx="${x(z.fixed)}" cy="${yy - 4}" r="5" fill="var(--orange)" stroke="var(--surface)" stroke-width="2"${tipAttr(`${z.store}: ${z.k} restock actions per snapshot kept fixed: ${sgn(z.fixed, 2)}% (90% of simulations ${sgn(z.band[0], 2)} to ${sgn(z.band[1], 2)})`)}/>`;
    s += `<circle cx="${x(z.scaled)}" cy="${yy + 5}" r="5" fill="var(--blue)" stroke="var(--surface)" stroke-width="2"${tipAttr(`${z.store}: ${z.ks} actions (scaled): ${sgn(z.scaled, 2)}%`)}/>`;
  });
  $('#a-ops').innerHTML = s + '</svg>';
  $('#a-t').innerHTML = table(['store', 'products now (REAL)', 'distance to peers', 'additions median price (REAL)', 'restock actions fixed / scaled', 'existing listings OOS, fixed', 'scaled', 'additions in the 4-platform panel'],
    R.map(z => { const q = S.find(w => w.store === z.store) || {}; return [z.store, z.now.toLocaleString('en-IN'), `${z.tvb.toFixed(4)} → ${z.tva.toFixed(4)}`,
      z.pAdd != null ? `${rs(z.pAdd)} vs ${rs(z.pNow)}` : '—', `${q.k} / ${q.ks}`, sgn(q.fixed, 2) + '%', sgn(q.scaled, 2) + '%', String(q.inPanel)]; }));
}

// =============================================================== restock objective
function renderRestock() {
  const R = DATA.restock, P = Object.fromEntries(R.policies.map(p => [p.policy, p]));
  const plain = P['index_alpha_1'], orc = P['oracle_win_weighted'];
  const alphas = R.policies.filter(p => p.policy.startsWith('index_alpha_')).map(p => ({...p, a: +p.policy.split('_').pop()}));
  const knee = alphas.filter(p => p.a < 1 && !R.dominated.includes(p.a)).sort((a, b) => (b.j1 + b.j2) - (a.j1 + a.j2))[0];
  tiles($('#r-tiles'), [
    [`${plain.j1.toFixed(1)}% / ${plain.j2.toFixed(1)}%`, 'plain index (α = 1): out-of-stock snapshots / lost wins cut'],
    [`${knee.j1.toFixed(1)}% / ${knee.j2.toFixed(1)}%`, `weighted at α = ${knee.a}: the knee of the curve`],
    [`${orc.j2.toFixed(1)}%`, 'lost wins cut by the clairvoyant benchmark (knows true outage lengths)'],
    [`${Math.round(R.lostNoAction)}`, `cheapest-available wins lost per run with no restock action (${R.horizon} snapshots)`]]);
  // frontier scatter
  const pts = R.policies.filter(p => p.policy !== 'none');
  const W = cw($('#r-front'), 520), H = 300, l = 50, r = 20, t = 16, b = 42;
  const x = scale(Math.floor(Math.min(...pts.map(p => p.j1)) / 5) * 5, Math.ceil(Math.max(...pts.map(p => p.j1)) / 5) * 5, l, W - r);
  const ylo = Math.floor(Math.min(...pts.map(p => p.j2)) / 5) * 5, yhi = Math.ceil(Math.max(...pts.map(p => p.j2)) / 5) * 5;
  const y = scale(ylo, yhi, H - b, t);
  const xs = niceTicks(Math.floor(Math.min(...pts.map(p => p.j1)) / 5) * 5, Math.ceil(Math.max(...pts.map(p => p.j1)) / 5) * 5, 5);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Out-of-stock reduction against lost-wins reduction, by restock policy">`;
  niceTicks(ylo, yhi, 5).forEach(v => s += `<line class="g" x1="${l}" x2="${W - r}" y1="${y(v)}" y2="${y(v)}"/><text class="tick" x="${l - 6}" y="${y(v) + 4}" text-anchor="end">${v}%</text>`);
  xs.forEach(v => s += `<text class="tick" x="${x(v)}" y="${H - b + 16}" text-anchor="middle">${v}%</text>`);
  s += `<text class="ttl" x="${(l + W - r) / 2}" y="${H - 6}" text-anchor="middle">cut in out-of-stock listing-snapshots</text>`;
  s += `<text class="ttl" x="${l}" y="${t - 4}">cut in lost cheapest-available wins</text>`;
  const A = alphas.slice().sort((a, b) => b.a - a.a);
  s += `<polyline fill="none" stroke="var(--blue)" stroke-width="2" points="${A.map(p => `${x(p.j1)},${y(p.j2)}`).join(' ')}"/>`;
  A.forEach(p => s += `<circle cx="${x(p.j1)}" cy="${y(p.j2)}" r="5.5" fill="var(--blue)" stroke="var(--surface)" stroke-width="2"${tipAttr(`α = ${p.a}: out-of-stock snapshots cut ${p.j1.toFixed(1)}%, lost wins cut ${p.j2.toFixed(1)}%`)}/><text class="val" x="${x(p.j1) + 9}" y="${y(p.j2) + (p.a === 1 ? 14 : -7)}">α ${p.a}</text>`);
  [['random', 'random'], ['longest_out_first', 'longest out first']].forEach(([k, lab]) => { const p = P[k]; if (!p) return;
    s += `<circle cx="${x(p.j1)}" cy="${y(p.j2)}" r="5" fill="var(--surface)" stroke="var(--axis)" stroke-width="2"${tipAttr(`${lab}: ${p.j1.toFixed(1)}% / ${p.j2.toFixed(1)}%`)}/><text class="val" x="${x(p.j1) + 9}" y="${y(p.j2) + 4}">${lab}</text>`; });
  s += `<rect x="${x(orc.j1) - 5.5}" y="${y(orc.j2) - 5.5}" width="11" height="11" fill="var(--orange)" stroke="var(--surface)" stroke-width="2"${tipAttr(`clairvoyant benchmark: ${orc.j1.toFixed(1)}% / ${orc.j2.toFixed(1)}%`)}/><text class="val" x="${x(orc.j1) + 10}" y="${y(orc.j2) + 4}">clairvoyant</text>`;
  $('#r-front').innerHTML = s + '</svg>';
  const pr = R.paired;
  $('#r-note').textContent = `Each α against the plain index on the same ${R.sims} paired simulations: what weighting gains in lost wins and what it costs in out-of-stock snapshots, in percentage points of the reduction. The confidence interval is for the mean; single 12-snapshot windows vary far more.`;
  $('#r-paired').innerHTML = table(['α', 'lost-wins gain', '90% CI, mean', 'better in', 'exposure cost'],
    Object.entries(pr).map(([a, v]) => [a, sgn(v.J2_gain_pp) + ' pp', v.J2_gain_mean_ci90 ? `${sgn(v.J2_gain_mean_ci90[0])} to ${sgn(v.J2_gain_mean_ci90[1])}` : '—',
      pct(v.J2_gain_positive_in_share_of_sims), v.J1_cost_pp.toFixed(1) + ' pp']));
  $('#r-t').innerHTML = table(['policy', 'out-of-stock cut', 'lost-wins cut', 'lost-wins cut, 90% of runs', 'store ETA from stock-outs (min)'],
    R.policies.map(p => [p.policy.replace(/_/g, ' '), p.j1.toFixed(1) + '%', p.j2.toFixed(1) + '%', `${p.j2b[0].toFixed(1)} to ${p.j2b[1].toFixed(1)}`, p.j3.toFixed(3)]));
}

// =============================================================== market context
function renderMarket() {
  $('#m-cards').innerHTML = DATA.external.map(c => `<article class="ext"><div>${chip('EXTERNAL')}</div><h3>${esc(c.h)}</h3>` +
    c.body.map(p => `<p>${esc(p)}</p>`).join('') +
    `<p class="srcline">${esc(c.src)}<br><a href="${esc(c.url)}" target="_blank" rel="noopener noreferrer">${esc(c.url.replace(/^https?:\/\//, '').slice(0, 64))}${c.url.length > 72 ? '…' : ''}</a></p></article>`).join('');
}

// =============================================================== wiring
$('#pick').innerHTML = DATA.chains.map((c, i) => `<option value="${i}">${esc(c.name)} · ${esc(c.store.replace('BLK-', ''))}${c.dec.cheapest ? ' · Blinkit cheapest now' : ''}</option>`).join('');
$('#pick').addEventListener('change', e => { state.li = +e.target.value; renderListing(); });
$('#a-n').innerHTML = DATA.adds.ns.map(n => `<button type="button" aria-pressed="${n === state.n}" data-n="${n}">${n}</button>`).join('');
$('#a-n').addEventListener('click', e => { const bt = e.target.closest('button'); if (!bt) return;
  state.n = +bt.dataset.n; document.querySelectorAll('#a-n button').forEach(x => x.setAttribute('aria-pressed', x === bt)); renderAdds(); });
const TABS = ['listing', 'outage', 'adds', 'restock', 'market'];
const RENDER = { listing: renderListing, outage: renderOutage, adds: renderAdds, restock: renderRestock, market: renderMarket };
function show(name) {
  TABS.forEach(n => { $('#t-' + n).setAttribute('aria-selected', n === name); $('#p-' + n).hidden = n !== name; });
  state.tab = name; RENDER[name]();
}
let resizeTimer = null;
addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => RENDER[state.tab](), 150); });
document.querySelector('.tabs').addEventListener('click', e => { const bt = e.target.closest('button'); if (bt) show(bt.id.slice(2)); });
const hash = (location.hash || '').slice(1);
show(TABS.includes(hash) ? hash : 'listing');

// tooltips
const tip = $('#tip');
function place(el, x, y) { tip.textContent = el.getAttribute('data-tip'); tip.hidden = false;
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.min(Math.max(8, x + 14), innerWidth - w - 8) + 'px'; tip.style.top = (y - h - 12 < 8 ? y + 16 : y - h - 12) + 'px'; }
document.addEventListener('pointermove', e => { const el = e.target.closest && e.target.closest('[data-tip]'); if (el) place(el, e.clientX, e.clientY); else tip.hidden = true; });
document.addEventListener('focusin', e => { const el = e.target.closest && e.target.closest('[data-tip]'); if (!el) return; const r = el.getBoundingClientRect(); place(el, r.left + r.width / 2, r.top); });
document.addEventListener('focusout', () => { tip.hidden = true; });
</script>
'''


def main():
    d = data()
    # '</' inside a data string would end the script element early
    html = PAGE.replace('__DATA__', json.dumps(d, separators=(',', ':'), ensure_ascii=False).replace('</', '<\\/'))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding='utf-8')
    print(f'wrote {OUT.relative_to(ROOT)} ({len(html) / 1024:.0f} KB), {len(d["chains"])} listings, '
          f'{len(d["external"])} external facts')


if __name__ == '__main__':
    main()
