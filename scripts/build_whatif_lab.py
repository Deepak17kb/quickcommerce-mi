"""
build_whatif_lab.py — renders outputs/showcase/whatif_lab.html, the interactive What-If Lab.

    python -m src.simulate.grid && python -m src.optimize.promo_frontier && python -m src.optimize.restock_lab
    python scripts/build_whatif_lab.py

Everything the page shows is embedded from saved outputs (the what-if grid, the promo frontier, the restock lab);
the page computes nothing new, it only lets a reader move through results that were simulated in advance.
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
M = ROOT / 'outputs' / 'models'
OUT = ROOT / 'outputs' / 'showcase' / 'whatif_lab.html'


def data():
    grid = json.loads((M / 'simulate_grid' / 'grid.json').read_text(encoding='utf-8'))
    cells = {}
    for c in grid['cells']:
        move = c.get('move_pct', -c['cut_pct'])            # signed: -3 is a 3% cut, +3 a 3% raise
        key = f"{c['mover']}|{c['group']}|{move}|{c['view']}"
        cells[key] = {'s': [round(c['share'][p], 4) for p in grid['platforms']],
                      'b': [round(c['base'][p], 4) for p in grid['platforms']],
                      'd': [c['change_pp'][p] for p in grid['platforms']],
                      'mp': [round(v, 4) for v in c['mover_path']], 'bp': [round(v, 4) for v in c['base_path']],
                      'n': c['skus']}
    fr = pd.read_csv(M / 'optimize_promo_frontier' / 'frontier.csv')
    fm = json.loads((M / 'optimize_promo_frontier' / 'metrics.json').read_text(encoding='utf-8'))
    frontier = {}
    for g, t in fr.groupby('category'):
        t = t.sort_values('cut_pct')
        frontier[g] = {'cut': t.cut_pct.tolist(),
                       'acP': [round(v, 4) for v in t.available_cheapest_promo], 'acL': [round(v, 4) for v in t.available_cheapest_list_price],
                       'oos': [round(v, 3) for v in t.oos_added_pp], 'lo': [round(v, 3) for v in t.oos_added_pp_p05],
                       'hi': [round(v, 3) for v in t.oos_added_pp_p95], 'eta': [round(v, 3) for v in t.eta_added_min_promo],
                       'listings': int(t.blinkit_listings.iloc[0])}
    summ = {r['category']: r for r in fm['by_category']}
    rl = json.loads((M / 'optimize_restock_lab' / 'metrics.json').read_text(encoding='utf-8'))
    hm = json.loads((M / 'optimize_price_headroom' / 'metrics.json').read_text(encoding='utf-8'))
    headroom = {r['category']: {'hs': r['headroom_pct_strategic']['5pp'], 'hst': r['headroom_pct_static']['5pp']}
                for r in hm['by_category'] + [hm['panel']]}
    return {'platforms': grid['platforms'], 'cuts': grid['cuts_pct'], 'groups': grid['groups'], 'cells': cells,
            'frontier': frontier, 'frontierSummary': summ, 'budget': fm['oos_budget_pp'],
            'headroom': headroom, 'headroomBudget': 5,
            'restock': {'rows': rl['rows'], 'shareOfOracle': rl['index_share_of_oracle_by_capacity'],
                        'topup': rl['topup_contribution_pp_by_capacity'], 'baseline': rl['baseline_oos_listing_snapshots']}}


PAGE = r'''<title>What-If Lab</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@100..125,500..800&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
:root {
  color-scheme: light;
  --page: #eef2f0; --surface: #f7f9f8; --ink: #0f1512; --ink-2: #48514c; --muted: #6f7873;
  --grid: #dde4e0; --axis: #b6c0ba; --rule: rgba(15,21,18,.12);
  --blue: #2a78d6; --orange: #eb6834; --aqua: #1baf7a;
  --wash-blue: rgba(42,120,214,.12); --wash-orange: rgba(235,104,52,.14);
  --hatch: rgba(15,21,18,.30); --tip-bg: #0f1512; --tip-ink: #f7f9f8;
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
    --wash-blue: rgba(57,135,229,.16); --wash-orange: rgba(217,89,38,.18);
    --hatch: rgba(237,242,238,.32); --tip-bg: #edf2ee; --tip-ink: #0c0f0d;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0c0f0d; --surface: #141816; --ink: #edf2ee; --ink-2: #b8c1bc; --muted: #8d9690;
  --grid: #232a26; --axis: #3b4540; --rule: rgba(237,242,238,.12);
  --blue: #3987e5; --orange: #d95926; --aqua: #199e70;
  --wash-blue: rgba(57,135,229,.16); --wash-orange: rgba(217,89,38,.18);
  --hatch: rgba(237,242,238,.32); --tip-bg: #edf2ee; --tip-ink: #0c0f0d;
}
* { box-sizing: border-box; }
body { background: var(--page); color: var(--ink); font: 15px/1.55 var(--sans); margin: 0; }
.wrap { max-width: 1080px; margin: 0 auto; padding-inline: 20px; padding-block: 28px 64px; }
header { display: flex; flex-wrap: wrap; align-items: end; justify-content: space-between; gap: 12px 24px; margin-bottom: 18px; }
h1 { font-family: var(--display); font-variation-settings: "wdth" 125; font-weight: 800; font-size: clamp(34px, 6vw, 56px);
     line-height: 1; letter-spacing: -.02em; margin: 0; }
.stamp { display: inline-flex; font: 600 11px/1 var(--mono); letter-spacing: .06em; text-transform: uppercase; padding: 5px 8px 4px;
         border: 1.5px solid var(--ink); border-radius: 3px; white-space: nowrap; color: var(--ink);
         background: repeating-linear-gradient(135deg, var(--hatch) 0 1.5px, transparent 1.5px 6px), var(--surface); }
.intro { max-width: 70ch; color: var(--ink-2); margin: 0 0 22px; }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--rule); margin-bottom: 20px; overflow-x: auto; }
.tabs button { font: 600 14px var(--sans); color: var(--ink-2); background: none; border: 0; border-bottom: 2px solid transparent;
               padding: 10px 14px; cursor: pointer; white-space: nowrap; }
.tabs button[aria-selected="true"] { color: var(--ink); border-bottom-color: var(--ink); }
.tabs button:focus-visible, .seg button:focus-visible, select:focus-visible, input:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.controls { display: flex; flex-wrap: wrap; gap: 14px 24px; align-items: end; margin-bottom: 18px; }
.ctl { display: flex; flex-direction: column; gap: 6px; }
.ctl > span { font: 500 12px var(--mono); color: var(--muted); letter-spacing: .04em; text-transform: uppercase; }
.seg { display: inline-flex; border: 1px solid var(--rule); border-radius: 6px; overflow: hidden; background: var(--surface); }
.seg button { font: 500 13px var(--sans); color: var(--ink-2); background: none; border: 0; padding: 7px 11px; cursor: pointer; }
.seg button + button { border-left: 1px solid var(--rule); }
.seg button[aria-pressed="true"] { background: var(--ink); color: var(--page); }
select { font: 14px var(--sans); color: var(--ink); background: var(--surface); border: 1px solid var(--rule); border-radius: 6px; padding: 7px 10px; }
input[type=range] { width: 220px; accent-color: var(--blue); }
.cutval { font: 600 15px var(--mono); }
.toggle { display: inline-flex; align-items: center; gap: 8px; font-size: 14px; color: var(--ink-2); cursor: pointer; }
.toggle input { width: 16px; height: 16px; accent-color: var(--blue); }
.headline { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 1px; background: var(--rule);
            border: 1px solid var(--rule); margin-bottom: 18px; }
.tile { background: var(--surface); padding: 12px 14px; }
.tile .v { font: 600 24px/1.15 var(--sans); display: block; }
.tile .l { font-size: 12px; color: var(--muted); display: block; margin-top: 4px; }
.grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 460px), 1fr)); gap: 18px; }
.panel { background: var(--surface); border: 1px solid var(--rule); border-radius: 6px; padding: 16px 16px 8px; }
.panel h2 { font: 600 15px/1.3 var(--sans); margin: 0 0 4px; }
.panel p.note { font-size: 13px; color: var(--ink-2); margin: 0 0 10px; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 12.5px; color: var(--ink-2); margin-bottom: 6px; }
.legend span { display: inline-flex; align-items: center; gap: 7px; }
.sw { width: 12px; height: 12px; display: inline-block; flex: none; border-radius: 50%; }
.sw.line { height: 2px; width: 16px; border-radius: 0; }
.chart svg { display: block; width: 100%; height: auto; }
.chart { overflow-x: auto; }
svg text { font-family: var(--sans); }
.g { stroke: var(--grid); stroke-width: 1; } .b { stroke: var(--axis); stroke-width: 1; }
.tick { fill: var(--muted); font: 11px var(--mono); } .lab { fill: var(--ink-2); font-size: 12px; }
.val { fill: var(--ink-2); font: 11px var(--mono); } .ttl { fill: var(--muted); font-size: 11px; }
[data-tip] { outline: none; } [data-tip]:hover, [data-tip]:focus-visible { stroke: var(--ink); stroke-width: 2; }
details { margin: 4px 0 6px; } summary { cursor: pointer; font: 500 13px var(--sans); color: var(--ink-2); padding-block: 4px; width: max-content; }
table { border-collapse: collapse; font: 12.5px/1.4 var(--sans); min-width: 100%; }
th, td { text-align: left; padding: 5px 12px 5px 0; border-bottom: 1px solid var(--grid); white-space: nowrap; }
th { color: var(--ink-2); font-weight: 600; } td { font-variant-numeric: tabular-nums; }
.tbl { overflow-x: auto; }
.claim { font-size: 13px; color: var(--muted); margin-top: 18px; max-width: 80ch; }
#tip { position: fixed; z-index: 10; pointer-events: none; max-width: 280px; padding: 7px 10px; border-radius: 4px;
       background: var(--tip-bg); color: var(--tip-ink); font: 12.5px/1.4 var(--sans); }
[hidden] { display: none !important; }
</style>

<div class="wrap">
  <header>
    <h1>What-If Lab</h1>
    <span class="stamp">SYNTHETIC · fitted, generated dynamics</span>
  </header>
  <p class="intro">Every number here was simulated in advance from models fitted to the generated panel of four Bhubaneswar
    quick-commerce platforms, and the engine was checked against the status quo first. It answers positioning and
    availability questions: who is cheapest, what is in stock, how long delivery takes. It never answers demand or revenue,
    because no order data exists.</p>

  <nav class="tabs" role="tablist">
    <button role="tab" id="t-price" aria-selected="true" aria-controls="p-price">Price move</button>
    <button role="tab" id="t-promo" aria-selected="false" aria-controls="p-promo">Promo vs list price</button>
    <button role="tab" id="t-restock" aria-selected="false" aria-controls="p-restock">Restock capacity</button>
  </nav>

  <section id="p-price" role="tabpanel" aria-labelledby="t-price">
    <div class="controls">
      <div class="ctl"><span>Who moves</span><div class="seg" id="mover"></div></div>
      <div class="ctl"><span>Category</span><select id="group"></select></div>
      <div class="ctl"><span>Price move <b class="cutval" id="cutv"></b></span><input type="range" id="cut" min="-10" max="10" step="1" value="-3" aria-label="Price move, cut to the left, raise to the right"></div>
      <label class="toggle"><input type="checkbox" id="react" checked> Competitors react (fitted response)</label>
    </div>
    <div class="headline" id="p-tiles"></div>
    <div class="grid2">
      <div class="panel"><h2>Cheapest-of-4 share, before and after</h2>
        <p class="note">Share of SKU-snapshots where each platform is the cheapest of the four (ties count for each).</p>
        <div class="legend"><span><i class="sw" style="border:2px solid var(--axis)"></i>before</span>
          <span><i class="sw" style="background:var(--blue)"></i>after, the platform that moved</span>
          <span><i class="sw" style="background:var(--ink-2)"></i>after, the others</span></div>
        <div class="chart" id="c-dumb"></div></div>
      <div class="panel"><h2>The mover's share over the next 12 snapshots</h2>
        <p class="note">When Blinkit moves and competitors react, followers close the gap from the next snapshot on: they eat into a cut's gain and soften a raise's loss.</p>
        <div class="legend"><span><i class="sw line" style="background:var(--axis)"></i>no change</span>
          <span><i class="sw line" style="background:var(--blue)"></i>with the move</span></div>
        <div class="chart" id="c-path"></div></div>
    </div>
    <details><summary>Show the numbers</summary><div class="tbl" id="tbl-price"></div></details>
  </section>

  <section id="p-promo" role="tabpanel" aria-labelledby="t-promo" hidden>
    <div class="controls"><div class="ctl"><span>Category</span><select id="fgroup"></select></div></div>
    <div class="headline" id="f-tiles"></div>
    <div class="grid2">
      <div class="panel"><h2>Cheapest and in stock</h2>
        <p class="note">A listing that is out of stock cannot win the comparison. Same price cut, two ways to deliver it.</p>
        <div class="legend"><span><i class="sw line" style="background:var(--blue)"></i>list-price cut (discount unchanged)</span>
          <span><i class="sw line" style="background:var(--orange)"></i>promo (deeper discount)</span></div>
        <div class="chart" id="c-ac"></div></div>
      <div class="panel"><h2>Stock-outs a promo adds</h2>
        <p class="note">Percentage points of Blinkit listings out of stock, with the 90% band; the line marks a 1 pp budget.</p>
        <div class="chart" id="c-oos"></div></div>
    </div>
    <details><summary>Show the numbers</summary><div class="tbl" id="tbl-promo"></div></details>
  </section>

  <section id="p-restock" role="tabpanel" aria-labelledby="t-restock" hidden>
    <div class="headline" id="r-tiles"></div>
    <div class="panel"><h2>Out-of-stock exposure removed, by restock capacity</h2>
      <p class="note">Capacity is the share of each store's listings that can be acted on per snapshot. The clairvoyant
        oracle knows every outage's true length, which no operator does: it is a benchmark, not a policy.</p>
      <div class="legend" id="r-legend"></div>
      <div class="chart" id="c-cap"></div></div>
    <details><summary>Show the numbers</summary><div class="tbl" id="tbl-restock"></div></details>
  </section>

  <p class="claim">SYNTHETIC. Results show what the fitted models imply about the generated market; the generator's planted
    dynamics, not the real platforms. Built by <code>scripts/build_whatif_lab.py</code> from outputs/models/simulate_grid,
    optimize_promo_frontier and optimize_restock_lab.</p>
</div>
<div id="tip" role="status" aria-live="polite" hidden></div>

<script>
const DATA = __DATA__;
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const pct = v => (100 * v).toFixed(1) + '%';
const pp = v => (v >= 0 ? '+' : '') + v.toFixed(1) + ' pp';
const state = { mover: 'Blinkit', group: 'All', cut: -3, react: true, fgroup: null };

function scale(d0, d1, r0, r1) { return v => r0 + (v - d0) / (d1 - d0) * (r1 - r0); }
function tipAttr(t) { return ` data-tip="${esc(t)}" tabindex="0"`; }
function table(head, rows) {
  return '<table><thead><tr>' + head.map(h => `<th>${esc(h)}</th>`).join('') + '</tr></thead><tbody>' +
    rows.map(r => '<tr>' + r.map(c => `<td>${esc(c)}</td>`).join('') + '</tr>').join('') + '</tbody></table>';
}
function tiles(el, items) {
  el.innerHTML = items.map(([v, l]) => `<div class="tile"><span class="v">${esc(v)}</span><span class="l">${esc(l)}</span></div>`).join('');
}
function yAxis(y, ticks, x0, x1, fmt) {
  return ticks.map(t => `<line class="${t === ticks[0] ? 'b' : 'g'}" x1="${x0}" x2="${x1}" y1="${y(t)}" y2="${y(t)}"/>` +
    `<text class="tick" x="${x0 - 6}" y="${y(t) + 4}" text-anchor="end">${fmt(t)}</text>`).join('');
}
function niceMax(v, step) { return Math.max(step, Math.ceil(v / step) * step); }

// ---------------------------------------------------------------- price move
function cell() { return DATA.cells[`${state.mover}|${state.group}|${state.cut}|${state.react ? 'strategic' : 'static'}`]; }
function other() { return DATA.cells[`${state.mover}|${state.group}|${state.cut}|${state.react ? 'static' : 'strategic'}`]; }
function renderPrice() {
  const c = cell(), o = other(), P = DATA.platforms, j = P.indexOf(state.mover);
  $('#cutv').textContent = `${state.cut < 0 ? '−' : '+'}${Math.abs(state.cut)}% ${state.cut < 0 ? 'cut' : 'raise'}`;
  const d = c.d[j];
  const items = [
    [`${pct(c.b[j])} → ${pct(c.s[j])}`, `${state.mover} cheapest-of-4 share, ${state.group === 'All' ? 'whole common panel' : state.group} (${c.n} SKUs)`],
    [pp(d[1]), `change, 90% band ${d[0].toFixed(1)} to ${d[2].toFixed(1)} pp`],
    [pp(o.d[j][1]), state.react ? 'what a static comparison would say' : 'with the fitted competitor response'],
  ];
  const h = DATA.headroom[state.group];
  if (state.cut > 0 && state.mover === 'Blinkit' && h) {
    const hr = x => x ? `up to ${x}%` : 'none';
    items.push([hr(state.react ? h.hs : h.hst), `raise headroom: the largest raise costing at most ${DATA.headroomBudget} pp of share (${state.react ? 'fitted response' : 'static'})`]);
  }
  tiles($('#p-tiles'), items);
  // dumbbell
  const W = 520, top = 16, rowH = 42, left = 150, right = 60, H = top + rowH * 4 + 30;
  const mx = niceMax(Math.max(...c.s, ...c.b), 0.1);
  const x = scale(0, mx, left, W - right);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Cheapest-of-4 share before and after for each platform">`;
  for (let t = 0; t <= mx + 1e-9; t += 0.1) s += `<line class="${t === 0 ? 'b' : 'g'}" x1="${x(t)}" x2="${x(t)}" y1="${top - 6}" y2="${H - 26}"/><text class="tick" x="${x(t)}" y="${H - 10}" text-anchor="middle">${Math.round(t * 100)}%</text>`;
  P.forEach((p, i) => {
    const cy = top + i * rowH + rowH / 2, mover = i === j;
    s += `<text class="lab" x="${left - 10}" y="${cy + 4}" text-anchor="end">${esc(p)}</text>`;
    s += `<line x1="${x(c.b[i])}" x2="${x(c.s[i])}" y1="${cy}" y2="${cy}" stroke="var(--axis)" stroke-width="2"/>`;
    s += `<circle cx="${x(c.b[i])}" cy="${cy}" r="5" fill="var(--surface)" stroke="var(--axis)" stroke-width="2"${tipAttr(`${p} before: ${pct(c.b[i])}`)}/>`;
    s += `<circle cx="${x(c.s[i])}" cy="${cy}" r="6" fill="${mover ? 'var(--blue)' : 'var(--ink-2)'}" stroke="var(--surface)" stroke-width="2"${tipAttr(`${p} after: ${pct(c.s[i])} (${pp(c.d[i][1])}, 90% band ${c.d[i][0].toFixed(1)} to ${c.d[i][2].toFixed(1)})`)}/>`;
    s += `<text class="val" x="${Math.max(x(c.s[i]), x(c.b[i])) + 12}" y="${cy + 4}">${pct(c.s[i])}</text>`;
  });
  $('#c-dumb').innerHTML = s + '</svg>';
  // path
  const W2 = 520, H2 = 250, l2 = 46, r2 = 16, t2 = 14, b2 = 34;
  const ys = [...c.mp, ...c.bp]; const ymx = niceMax(Math.max(...ys), 0.05);
  const xs = scale(1, 12, l2, W2 - r2), yv = scale(0, ymx, H2 - b2, t2);
  let p2 = `<svg viewBox="0 0 ${W2} ${H2}" role="img" aria-label="The mover's cheapest-of-4 share over twelve snapshots">`;
  const ticks = []; for (let t = 0; t <= ymx + 1e-9; t += 0.05) ticks.push(+t.toFixed(2));
  p2 += yAxis(yv, ticks, l2, W2 - r2, t => Math.round(t * 100) + '%');
  [1, 3, 6, 9, 12].forEach(t => p2 += `<text class="tick" x="${xs(t)}" y="${H2 - b2 + 16}" text-anchor="middle">${t}</text>`);
  p2 += `<text class="ttl" x="${(l2 + W2 - r2) / 2}" y="${H2 - 4}" text-anchor="middle">snapshots after the move (two a day)</text>`;
  const line = (arr, col) => `<polyline fill="none" stroke="${col}" stroke-width="2" stroke-linejoin="round" points="${arr.map((v, i) => `${xs(i + 1)},${yv(v)}`).join(' ')}"/>`;
  p2 += line(c.bp, 'var(--axis)') + line(c.mp, 'var(--blue)');
  c.mp.forEach((v, i) => p2 += `<circle cx="${xs(i + 1)}" cy="${yv(v)}" r="4" fill="var(--blue)" stroke="var(--surface)" stroke-width="2"${tipAttr(`snapshot ${i + 1}: ${pct(v)} with the move, ${pct(c.bp[i])} without`)}/>`);
  $('#c-path').innerHTML = p2 + '</svg>';
  $('#tbl-price').innerHTML = table(['platform', 'before', 'after', 'change (median)', '90% band'],
    P.map((p, i) => [p, pct(c.b[i]), pct(c.s[i]), pp(c.d[i][1]), `${c.d[i][0].toFixed(1)} to ${c.d[i][2].toFixed(1)} pp`]));
}

// ---------------------------------------------------------------- promo vs list price
function renderPromo() {
  const g = state.fgroup, f = DATA.frontier[g], sm = DATA.frontierSummary[g];
  tiles($('#f-tiles'), [
    [`${sm.largest_promo_within_budget_pct}%`, `largest promo that keeps added stock-outs within ${DATA.budget} pp`],
    [`+${sm.share_gain_at_10pct_pp.toFixed(1)} pp`, 'cheapest-of-4 share a 10% cut buys (either way)'],
    [`+${sm.oos_added_at_10pct_pp.toFixed(2)} pp`, 'stock-outs a 10% promo adds'],
    [`+${sm.eta_added_at_10pct_min.toFixed(2)} min`, 'delivery time a 10% promo adds'],
  ]);
  const W = 520, H = 250, l = 46, r = 16, t = 14, b = 34;
  const xs = scale(0, 10, l, W - r);
  const all = [...f.acP, ...f.acL]; const lo = Math.floor(Math.min(...all) * 20) / 20, hi = niceMax(Math.max(...all), 0.05);
  const y = scale(lo, hi, H - b, t);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Cheapest and in stock share against the price cut, promo versus list price">`;
  const ticks = []; for (let v = lo; v <= hi + 1e-9; v += 0.05) ticks.push(+v.toFixed(2));
  s += yAxis(y, ticks, l, W - r, v => Math.round(v * 100) + '%');
  [0, 2, 4, 6, 8, 10].forEach(v => s += `<text class="tick" x="${xs(v)}" y="${H - b + 16}" text-anchor="middle">${v}%</text>`);
  s += `<text class="ttl" x="${(l + W - r) / 2}" y="${H - 4}" text-anchor="middle">Blinkit price cut</text>`;
  const line = (arr, col) => `<polyline fill="none" stroke="${col}" stroke-width="2" points="${arr.map((v, i) => `${xs(f.cut[i])},${y(v)}`).join(' ')}"/>`;
  s += line(f.acL, 'var(--blue)') + line(f.acP, 'var(--orange)');
  f.cut.forEach((c, i) => {
    s += `<circle cx="${xs(c)}" cy="${y(f.acP[i])}" r="4" fill="var(--orange)" stroke="var(--surface)" stroke-width="2"${tipAttr(`${c}% as a promo: ${pct(f.acP[i])} cheapest and in stock`)}/>`;
    s += `<circle cx="${xs(c)}" cy="${y(f.acL[i])}" r="4" fill="var(--blue)" stroke="var(--surface)" stroke-width="2"${tipAttr(`${c}% as a list-price cut: ${pct(f.acL[i])} cheapest and in stock`)}/>`;
  });
  $('#c-ac').innerHTML = s + '</svg>';
  const ymx = niceMax(Math.max(DATA.budget, ...f.hi), 0.5), ymn = Math.min(0, Math.floor(Math.min(...f.lo) * 2) / 2);
  const y2 = scale(ymn, ymx, H - b, t);
  let o = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Stock-outs added by a promo against the price cut, with a 90 percent band">`;
  const t2 = []; for (let v = ymn; v <= ymx + 1e-9; v += 0.5) t2.push(+v.toFixed(1));
  o += yAxis(y2, t2, l, W - r, v => v.toFixed(1));
  [0, 2, 4, 6, 8, 10].forEach(v => o += `<text class="tick" x="${xs(v)}" y="${H - b + 16}" text-anchor="middle">${v}%</text>`);
  o += `<text class="ttl" x="${(l + W - r) / 2}" y="${H - 4}" text-anchor="middle">Blinkit price cut, delivered as a promo</text>`;
  const band = f.cut.map((c, i) => `${xs(c)},${y2(f.hi[i])}`).join(' ') + ' ' + f.cut.slice().reverse().map((c, k) => `${xs(c)},${y2(f.lo[f.cut.length - 1 - k])}`).join(' ');
  o += `<polygon points="${band}" fill="var(--wash-orange)" stroke="none"/>`;
  o += `<line x1="${l}" x2="${W - r}" y1="${y2(DATA.budget)}" y2="${y2(DATA.budget)}" stroke="var(--ink)" stroke-width="1.5"/>`;
  o += `<text class="lab" x="${l + 6}" y="${y2(DATA.budget) - 6}">${DATA.budget} pp budget</text>`;
  o += `<polyline fill="none" stroke="var(--orange)" stroke-width="2" points="${f.cut.map((c, i) => `${xs(c)},${y2(f.oos[i])}`).join(' ')}"/>`;
  f.cut.forEach((c, i) => o += `<circle cx="${xs(c)}" cy="${y2(f.oos[i])}" r="4" fill="var(--orange)" stroke="var(--surface)" stroke-width="2"${tipAttr(`${c}% promo: +${f.oos[i].toFixed(2)} pp stock-outs (90% band ${f.lo[i].toFixed(2)} to ${f.hi[i].toFixed(2)}), +${f.eta[i].toFixed(2)} min ETA`)}/>`);
  $('#c-oos').innerHTML = o + '</svg>';
  $('#tbl-promo').innerHTML = table(['cut', 'cheapest & in stock, list price', 'cheapest & in stock, promo', 'stock-outs added', 'ETA added'],
    f.cut.map((c, i) => [`${c}%`, pct(f.acL[i]), pct(f.acP[i]), `${f.oos[i].toFixed(2)} pp`, `${f.eta[i].toFixed(2)} min`]));
}

// ---------------------------------------------------------------- restock capacity
const POL = [
  ['clairvoyant_oracle', 'clairvoyant oracle (benchmark)', 'var(--ink)'],
  ['priority_index', 'priority index (model)', 'var(--blue)'],
  ['index_restock_only', 'index, restock only (no top-ups)', 'var(--aqua)'],
  ['random', 'random', 'var(--axis)'],
  ['longest_out_first', 'longest out first', 'var(--orange)'],
];
function renderRestock() {
  const R = DATA.restock, rows = R.rows;
  const caps = [...new Set(rows.map(r => r.capacity_pct))].sort((a, b) => a - b);
  const get = (p, c) => rows.find(r => r.policy === p && r.capacity_pct === c);
  const one = caps.find(c => Math.abs(c - 1) < 1e-9);
  // metric dicts are keyed by the capacity as pandas wrote it ("1.0"); match numerically
  const kv = (obj, c) => obj[Object.keys(obj).find(k => Math.abs(parseFloat(k) - c) < 1e-9)];
  tiles($('#r-tiles'), [
    [`${(100 * kv(R.shareOfOracle, one)).toFixed(0)}%`, 'of the oracle\'s reduction the index reaches at 1% capacity'],
    [`${get('priority_index', one).reduction_pct.toFixed(1)}%`, 'out-of-stock exposure removed at 1% capacity'],
    [`${kv(R.topup, one).toFixed(1)} pp`, 'of that comes from pre-emptive top-ups'],
  ]);
  $('#r-legend').innerHTML = POL.map(([, n, c]) => `<span><i class="sw line" style="background:${c}"></i>${esc(n)}</span>`).join('');
  const W = 760, H = 300, l = 50, r = 20, t = 14, b = 40;
  const lx = c => Math.log(c);
  const xs = scale(lx(caps[0]), lx(caps[caps.length - 1]), l, W - r);
  const ymx = niceMax(Math.max(...rows.map(r => r.reduction_pct)), 10);
  const y = scale(0, ymx, H - b, t);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Out-of-stock exposure removed by restock capacity for five policies">`;
  const ticks = []; for (let v = 0; v <= ymx; v += 10) ticks.push(v);
  s += yAxis(y, ticks, l, W - r, v => v + '%');
  caps.forEach(c => s += `<text class="tick" x="${xs(lx(c))}" y="${H - b + 16}" text-anchor="middle">${c}%</text>`);
  s += `<text class="ttl" x="${(l + W - r) / 2}" y="${H - 4}" text-anchor="middle">restock capacity, share of each store's listings per snapshot (log scale)</text>`;
  // draw the model last so it sits on top where it coincides with the restock-only variant
  const DRAW = [3, 4, 2, 0, 1].map(i => POL[i]);
  DRAW.forEach(([p, n, col]) => {
    const pts = caps.map(c => [xs(lx(c)), y(get(p, c).reduction_pct)]);
    s += `<polyline fill="none" stroke="${col}" stroke-width="2" points="${pts.map(q => q.join(',')).join(' ')}"/>`;
    caps.forEach((c, i) => { const g = get(p, c);
      s += `<circle cx="${pts[i][0]}" cy="${pts[i][1]}" r="4" fill="${col}" stroke="var(--surface)" stroke-width="2"${tipAttr(`${n} at ${c}%: ${g.reduction_pct.toFixed(1)}% removed (90% band ${g.reduction_p05.toFixed(1)} to ${g.reduction_p95.toFixed(1)})`)}/>`; });
  });
  $('#c-cap').innerHTML = s + '</svg>';
  $('#tbl-restock').innerHTML = table(['capacity', ...POL.map(p => p[1])],
    caps.map(c => [`${c}%`, ...POL.map(([p]) => `${get(p, c).reduction_pct.toFixed(1)}%`)]));
}

// ---------------------------------------------------------------- wiring
$('#mover').innerHTML = DATA.platforms.map(p => `<button type="button" aria-pressed="${p === state.mover}" data-p="${esc(p)}">${esc(p)}</button>`).join('');
$('#mover').addEventListener('click', e => { const bt = e.target.closest('button'); if (!bt) return;
  state.mover = bt.dataset.p; document.querySelectorAll('#mover button').forEach(x => x.setAttribute('aria-pressed', x === bt)); renderPrice(); });
$('#group').innerHTML = DATA.groups.map(g => `<option value="${esc(g)}">${esc(g === 'All' ? 'All categories' : g)}</option>`).join('');
$('#group').addEventListener('change', e => { state.group = e.target.value; renderPrice(); });
$('#cut').addEventListener('input', e => {
  let v = +e.target.value;
  if (v === 0) { v = state.cut < 0 ? 1 : -1; e.target.value = v; }        // there is no 0% cell: step across it
  state.cut = v; renderPrice();
});
$('#react').addEventListener('change', e => { state.react = e.target.checked; renderPrice(); });
const fg = Object.keys(DATA.frontier); state.fgroup = fg.includes('Snacks & Munchies') ? 'Snacks & Munchies' : fg[0];
$('#fgroup').innerHTML = fg.map(g => `<option value="${esc(g)}"${g === state.fgroup ? ' selected' : ''}>${esc(g)}</option>`).join('');
$('#fgroup').addEventListener('change', e => { state.fgroup = e.target.value; renderPromo(); });
const TABS = ['price', 'promo', 'restock'];
function show(name) { TABS.forEach(n => { $('#t-' + n).setAttribute('aria-selected', n === name); $('#p-' + n).hidden = n !== name; }); }
document.querySelector('.tabs').addEventListener('click', e => { const bt = e.target.closest('button'); if (bt) show(bt.id.slice(2)); });
const hash = (location.hash || '').slice(1); if (TABS.includes(hash)) show(hash);
renderPrice(); renderPromo(); renderRestock();

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
    html = PAGE.replace('__DATA__', json.dumps(d, separators=(',', ':')))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding='utf-8')
    print(f'wrote {OUT.relative_to(ROOT)} ({len(html) / 1024:.0f} KB)')


if __name__ == '__main__':
    main()
