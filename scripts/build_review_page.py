"""
build_review_page.py — the Product Match Review page: label the 297-pair priority batch in a browser.

    python scripts/build_review_page.py      # -> outputs/showcase/match_review.html

Publish it with capabilities {db: {rules: [{path: "", write: "admin"}]}, user: {}}. Each decision is written to the
artifact's own store as labels/r<row>; `python -m src.matching.import_labels <export.json>` writes them into
data/reference/MATCH_REVIEW_PRIORITY.csv, where the trainer counts them as human_reviewed.

BLIND BY DESIGN
  The page shows names, pack sizes, brands and categories only. Unlike the terminal reviewer, it does not show the
  stratum, why a pair was chosen, or any similarity score: hints like those anchor a person's judgement, and these
  labels are the yardstick the matcher is measured against. The order is a fixed random shuffle, not grouped by stratum.
"""
import json
import random
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'data' / 'reference' / 'MATCH_REVIEW_PRIORITY.csv'
OUT = ROOT / 'outputs' / 'showcase' / 'match_review.html'
SEED = 20260925
NEEDED_PER_CLASS = 30          # src/matching/review.py: tier 1 unlocks at 30 same and 30 different


def pairs():
    df = pd.read_csv(SRC, dtype=str).fillna('')
    rows = [{'r': f"r{int(x.batch_row):03d}", 'row': int(x.batch_row), 'id': x.pair_id,
             'a': x.name_a, 'b': x.name_b, 'pa': x.pack_a, 'pb': x.pack_b, 'ba': x.brand_a, 'bb': x.brand_b,
             'ca': x.category_a, 'cb': x.category_b} for x in df.itertuples()]
    random.Random(SEED).shuffle(rows)
    return rows


PAGE = r'''<title>Product Match Review</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@100..125,500..800&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
:root {
  color-scheme: light;
  --page: #eef2f0; --surface: #f7f9f8; --ink: #0f1512; --ink-2: #48514c; --muted: #6f7873;
  --grid: #dde4e0; --axis: #b6c0ba; --rule: rgba(15,21,18,.12);
  --blue: #2a78d6; --orange: #eb6834; --mark: rgba(235,104,52,.22); --hatch: rgba(15,21,18,.30);
  --display: "Archivo", "Arial Narrow", Arial, sans-serif;
  --sans: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0c0f0d; --surface: #141816; --ink: #edf2ee; --ink-2: #b8c1bc; --muted: #8d9690;
    --grid: #232a26; --axis: #3b4540; --rule: rgba(237,242,238,.12);
    --blue: #3987e5; --orange: #d95926; --mark: rgba(217,89,38,.32); --hatch: rgba(237,242,238,.32);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0c0f0d; --surface: #141816; --ink: #edf2ee; --ink-2: #b8c1bc; --muted: #8d9690;
  --grid: #232a26; --axis: #3b4540; --rule: rgba(237,242,238,.12);
  --blue: #3987e5; --orange: #d95926; --mark: rgba(217,89,38,.32); --hatch: rgba(237,242,238,.32);
}
* { box-sizing: border-box; }
body { background: var(--page); color: var(--ink); font: 15px/1.55 var(--sans); margin: 0; }
.wrap { max-width: 980px; margin: 0 auto; padding-inline: 20px; padding-block: 26px 64px; }
header { display: flex; flex-wrap: wrap; align-items: end; justify-content: space-between; gap: 10px 24px; margin-bottom: 10px; }
h1 { font-family: var(--display); font-variation-settings: "wdth" 125; font-weight: 800; font-size: clamp(30px, 5.4vw, 46px);
     line-height: 1; letter-spacing: -.02em; margin: 0; text-wrap: balance; }
.chip { display: inline-flex; font: 600 10.5px/1 var(--mono); letter-spacing: .06em; text-transform: uppercase; padding: 5px 8px 4px;
        border-radius: 3px; border: 1.5px solid var(--ink); background: var(--surface);
        box-shadow: inset 0 0 0 1.5px var(--surface), inset 0 0 0 3px var(--ink); white-space: nowrap; }
.intro { max-width: 70ch; color: var(--ink-2); margin: 0 0 12px; }
.rules { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 250px), 1fr)); gap: 10px; margin: 0 0 18px; padding: 0; list-style: none; }
.rules li { background: var(--surface); border: 1px solid var(--rule); border-radius: 6px; padding: 10px 12px; font-size: 13.5px; color: var(--ink-2); }
.rules b { color: var(--ink); display: block; font-size: 14px; margin-bottom: 2px; }
.status { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 1px; background: var(--rule);
          border: 1px solid var(--rule); margin-bottom: 8px; }
.status div { background: var(--surface); padding: 10px 12px; }
.status .v { font: 600 22px/1.15 var(--sans); display: block; font-variant-numeric: tabular-nums; }
.status .l { font-size: 12px; color: var(--muted); display: block; margin-top: 3px; }
.unlock { font-size: 13px; color: var(--ink-2); margin: 0 0 16px; min-height: 1.4em; }
.bar { height: 6px; background: var(--grid); border-radius: 3px; overflow: hidden; margin: 6px 0 16px; }
.bar i { display: block; height: 100%; background: var(--ink); width: 0; }
.card { background: var(--surface); border: 1px solid var(--rule); border-radius: 8px; padding: 16px; }
.cardhead { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 6px 16px; align-items: baseline; margin-bottom: 12px; }
.cardhead b { font: 600 15px var(--sans); }
.cardhead .cur { font: 500 12px var(--mono); color: var(--muted); letter-spacing: .03em; }
.pair { display: grid; grid-template-columns: 92px minmax(0, 1fr) minmax(0, 1fr); gap: 0; border-top: 1px solid var(--grid); }
.pair > div { padding: 10px 10px 10px 0; border-bottom: 1px solid var(--grid); min-width: 0; overflow-wrap: anywhere; }
.pair .k { font: 500 11.5px var(--mono); color: var(--muted); letter-spacing: .04em; text-transform: uppercase; padding-top: 13px; }
.pair .h { font: 600 12px var(--mono); color: var(--muted); letter-spacing: .06em; border-bottom: 1px solid var(--grid); }
.pair .name { font: 500 16.5px/1.4 var(--sans); }
.pair .diff { background: var(--mark); border-radius: 2px; box-shadow: 0 0 0 1px var(--mark); }
.pair .same { color: var(--muted); }
.pair .ne { font-weight: 600; }
.pair .ne::after { content: " ≠"; color: var(--orange); font-weight: 700; }
.actions { display: flex; flex-wrap: wrap; gap: 10px; margin: 16px 0 10px; }
.btn { font: 600 15px var(--sans); border-radius: 6px; padding: 11px 16px; cursor: pointer; border: 1.5px solid var(--ink);
       background: var(--surface); color: var(--ink); display: inline-flex; gap: 8px; align-items: center; min-height: 44px; }
.btn kbd { font: 600 11px var(--mono); border: 1px solid var(--axis); border-radius: 3px; padding: 1px 5px; color: var(--muted); }
.btn.same { background: var(--ink); color: var(--page); }
.btn.same kbd { color: var(--page); border-color: var(--page); opacity: .7; }
.btn.diff { border-style: solid; }
.btn.unsure { border-style: dashed; }
.btn.nav { border-color: var(--rule); font-weight: 500; }
.btn[aria-pressed="true"] { outline: 3px solid var(--blue); outline-offset: 2px; }
.btn:disabled { opacity: .45; cursor: not-allowed; }
button:focus-visible, textarea:focus-visible, select:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.note { width: 100%; font: 14px var(--sans); color: var(--ink); background: var(--page); border: 1px solid var(--rule); border-radius: 6px;
        padding: 8px 10px; min-height: 42px; resize: vertical; }
.save { font: 500 12.5px var(--mono); color: var(--muted); margin-top: 8px; min-height: 1.4em; }
.save.bad { color: var(--orange); }
.all { margin-top: 26px; }
.all h2 { font: 600 16px var(--sans); margin: 0 0 8px; display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; }
.seg { display: inline-flex; border: 1px solid var(--rule); border-radius: 6px; overflow: hidden; background: var(--surface); }
.seg button { font: 500 12.5px var(--sans); color: var(--ink-2); background: none; border: 0; padding: 6px 10px; cursor: pointer; }
.seg button + button { border-left: 1px solid var(--rule); }
.seg button[aria-pressed="true"] { background: var(--ink); color: var(--page); }
.cells { display: grid; grid-template-columns: repeat(auto-fill, minmax(38px, 1fr)); gap: 4px; }
.cell { font: 600 11px var(--mono); height: 30px; border-radius: 4px; border: 1px solid var(--rule); background: var(--surface); color: var(--muted);
        cursor: pointer; display: flex; align-items: center; justify-content: center; font-variant-numeric: tabular-nums; }
.cell.s { background: var(--ink); color: var(--page); border-color: var(--ink); }
.cell.d { border: 1.5px solid var(--ink); color: var(--ink); }
.cell.u { border: 1.5px dashed var(--ink-2); color: var(--ink-2); }
.cell.now { outline: 2px solid var(--blue); outline-offset: 1px; }
.foot { font-size: 13px; color: var(--muted); margin-top: 22px; max-width: 76ch; }
.copy { margin-top: 10px; }
@media (max-width: 560px) {
  .pair { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
  .pair .k { grid-column: 1 / -1; padding: 10px 0 0; border-bottom: 0; }
  .pair .h.k0 { display: none; }
  .pair .name { font-size: 15px; }
}
[hidden] { display: none !important; }
</style>

<div class="wrap">
  <header>
    <h1>Product Match Review</h1>
    <span class="chip">REAL listings · your labels</span>
  </header>
  <p class="intro">Each pair is two REAL Blinkit catalog listings. Decide whether they are the same product. Your answers are
  the human labels that measure the product matcher on real name variation (tier 1), so decide from what you see: this
  page deliberately shows no model score or hint. Words that differ between the two names are highlighted.</p>
  <ul class="rules">
    <li><b>Same product</b>The same item in the same pack size, even if the wording, spelling, a bracketed local name or formatting differs ("Amla" and "Amla (Aula)").</li>
    <li><b>Different products</b>A different variant (flavour, scent, colour, model), a different pack size or count, or a different brand.</li>
    <li><b>Not sure</b>You can't tell from the names. It is kept as a note and not counted, so it never becomes a guess.</li>
  </ul>
  <div class="status" id="status"></div>
  <div class="bar" aria-hidden="true"><i id="bar"></i></div>
  <p class="unlock" id="unlock" aria-live="polite"></p>

  <section class="card" id="card" aria-labelledby="pairhead"></section>

  <section class="all">
    <h2>All pairs <span class="seg" id="filter" role="group" aria-label="Show"></span></h2>
    <div class="cells" id="cells"></div>
  </section>
  <p class="foot" id="foot">Decisions save as you click. Label as many as you like, in any number of sittings; tier 1 can be
  measured once there are 30 "same" and 30 "different". Reopen this page to continue where you stopped.</p>
</div>

<script>
const PAIRS = __PAIRS__;
const NEEDED = __NEEDED__;
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const labels = new Map();              // r -> {label, note, at, by_owner}
let pos = 0, filter = 'todo', db = null, canWrite = true, byOwner = null, saving = false, mode = 'loading';
const LS = 'match-review-labels-v1';

// ---------------------------------------------------------------- word-level difference between the two names
const norm = w => w.toLowerCase().replace(/^[^a-z0-9]+|[^a-z0-9]+$/g, '');
function marked(text, other) {
  const bag = new Set(other.split(/\s+/).map(norm).filter(Boolean));
  return text.split(/(\s+)/).map(w => /^\s+$/.test(w) || !norm(w) ? esc(w)
    : bag.has(norm(w)) ? esc(w) : `<span class="diff">${esc(w)}</span>`).join('');
}

// ---------------------------------------------------------------- rendering
function counts() {
  let s = 0, d = 0, u = 0;
  labels.forEach(v => { if (v.label === 'same') s++; else if (v.label === 'different') d++; else if (v.label === 'unsure') u++; });
  return {s, d, u, done: s + d + u};
}
function renderStatus() {
  const c = counts();
  $('#status').innerHTML = [[`${c.done} / ${PAIRS.length}`, 'pairs decided'], [c.s, 'same product'], [c.d, 'different products'], [c.u, 'not sure (not counted)']]
    .map(([v, l]) => `<div><span class="v">${esc(v)}</span><span class="l">${esc(l)}</span></div>`).join('');
  $('#bar').style.width = (100 * c.done / PAIRS.length).toFixed(1) + '%';
  const ns = Math.max(0, NEEDED - c.s), nd = Math.max(0, NEEDED - c.d);
  $('#unlock').textContent = ns === 0 && nd === 0
    ? `Tier 1 can be measured now (${c.s} same, ${c.d} different). Every further label narrows the estimate.`
    : `Tier 1 needs ${NEEDED} of each: ${ns} more "same" and ${nd} more "different" to go.`;
}
function field(k, a, b, cls = '') {
  const ne = String(a).trim() !== String(b).trim();
  return `<div class="k">${esc(k)}</div><div class="${cls} ${ne ? 'ne' : 'same'}">${esc(a) || '—'}</div><div class="${cls} ${ne ? 'ne' : 'same'}">${esc(b) || '—'}</div>`;
}
function renderCard() {
  const p = PAIRS[pos], cur = labels.get(p.r), c = cur ? cur.label : null;
  const said = c ? `your label: ${c === 'unsure' ? 'not sure' : c}` : 'not decided yet';
  $('#card').innerHTML = `<div class="cardhead"><b id="pairhead">Pair ${pos + 1} of ${PAIRS.length}</b><span class="cur">${esc(said)} · batch row ${p.row}</span></div>
    <div class="pair" role="table" aria-label="The two listings side by side">
      <div class="h k0"></div><div class="h">LISTING A</div><div class="h">LISTING B</div>
      <div class="k">name</div><div class="name">${marked(p.a, p.b)}</div><div class="name">${marked(p.b, p.a)}</div>
      ${field('pack', p.pa, p.pb)}${field('brand', p.ba, p.bb)}${field('category', p.ca, p.cb)}
    </div>
    <div class="actions">
      <button type="button" class="btn same" data-l="same" aria-pressed="${c === 'same'}">Same product <kbd>S</kbd></button>
      <button type="button" class="btn diff" data-l="different" aria-pressed="${c === 'different'}">Different products <kbd>D</kbd></button>
      <button type="button" class="btn unsure" data-l="unsure" aria-pressed="${c === 'unsure'}">Not sure <kbd>U</kbd></button>
      <button type="button" class="btn nav" data-nav="-1">Back <kbd>B</kbd></button>
      <button type="button" class="btn nav" data-nav="1">Skip <kbd>N</kbd></button>
    </div>
    <label for="note" style="font:500 12px var(--mono);color:var(--muted);letter-spacing:.04em;text-transform:uppercase">note (optional, saved with your label)</label>
    <textarea id="note" class="note" rows="1" placeholder="e.g. same product, Odia name in brackets">${esc(cur && cur.note || '')}</textarea>
    <div class="save" id="save" aria-live="polite">${esc(saveLine())}</div>
    <div class="copy" id="copywrap" ${mode === 'local' ? '' : 'hidden'}><button type="button" class="btn nav" id="copy">Copy all labels as text</button></div>`;
  $('#card').querySelectorAll('[data-l]').forEach(b => { b.disabled = !canWrite || saving; });
}
function saveLine() {
  if (mode === 'loading') return 'Connecting to the label store…';
  if (mode === 'db') return canWrite ? 'Labels save to this page’s store as you click.' : 'Read-only: you can view the labels but not change them.';
  return 'The label store is not available here: labels are kept in this browser only. Use “Copy all labels as text” and paste them to Claude.';
}
function renderCells() {
  const want = r => { const v = labels.get(r); return filter === 'all' || (filter === 'todo' ? !v : v && v.label === filter); };
  $('#cells').innerHTML = PAIRS.map((p, i) => { const v = labels.get(p.r), cls = v ? ({same: 's', different: 'd', unsure: 'u'})[v.label] : '';
    return want(p.r) ? `<button type="button" class="cell ${cls}${i === pos ? ' now' : ''}" data-i="${i}" aria-label="Pair ${i + 1}${v ? ', ' + v.label : ', not decided'}">${i + 1}</button>` : ''; }).join('')
    || `<p style="color:var(--muted);font-size:13px;margin:4px 0">No pairs here.</p>`;
}
function render() { renderStatus(); renderCard(); renderCells(); }
function renderFilter() {
  $('#filter').innerHTML = [['todo', 'To do'], ['all', 'All'], ['same', 'Same'], ['different', 'Different'], ['unsure', 'Not sure']]
    .map(([k, t]) => `<button type="button" data-f="${k}" aria-pressed="${k === filter}">${t}</button>`).join('');
}

// ---------------------------------------------------------------- saving
function nextUndecided(from) {
  for (let k = 1; k <= PAIRS.length; k++) { const i = (from + k) % PAIRS.length; if (!labels.has(PAIRS[i].r)) return i; }
  return from;
}
async function decide(label) {
  if (!canWrite || saving) return;
  const p = PAIRS[pos], note = ($('#note') && $('#note').value || '').trim();
  const body = {row: p.row, pair_id: p.id, label, note, at: new Date().toISOString(), by_owner: byOwner};
  const prev = labels.get(p.r);
  labels.set(p.r, body);                        // optimistic; reverted if the write fails
  if (mode === 'db') {
    saving = true; setSave('Saving…');
    try { await db.doc('labels/' + p.r).set(body); setSave('Saved.'); }
    catch (e) {
      const code = e && e.code;
      if (code === 'unavailable') {
        try { await new Promise(r => setTimeout(r, 400 + Math.random() * 600)); await db.doc('labels/' + p.r).set(body); setSave('Saved.'); }
        catch (e2) { revert(p.r, prev); setSave('Could not save just now. Try that pair again in a moment.', true); saving = false; render(); return; }
      } else if (code === 'invalid_argument' || code === 'not_granted') {
        revert(p.r, prev); canWrite = false; saving = false; render(); setSave('Read-only: this view cannot save labels.', true); return;
      } else if (code === 'quota_exceeded') {
        revert(p.r, prev); saving = false; render(); setSave('The label store is full; no new labels can be saved.', true); return;
      } else { revert(p.r, prev); saving = false; render(); setSave('Could not save that label.', true); return; }
    }
    saving = false;
  } else {
    try { localStorage.setItem(LS, JSON.stringify(Object.fromEntries(labels))); } catch (e) { /* storage blocked: keep in memory */ }
  }
  pos = nextUndecided(pos);
  render();
}
function revert(r, prev) { if (prev) labels.set(r, prev); else labels.delete(r); }
function setSave(t, bad) { const el = $('#save'); if (el) { el.textContent = t; el.classList.toggle('bad', !!bad); } }
let noteTimer = null;
function noteChanged() {                        // a note on an already-decided pair: one write per pause
  const p = PAIRS[pos], cur = labels.get(p.r);
  if (!cur || !canWrite) return;
  clearTimeout(noteTimer);
  noteTimer = setTimeout(async () => {
    const note = ($('#note').value || '').trim();
    if (note === (cur.note || '')) return;
    const body = {...cur, note, at: new Date().toISOString()};
    labels.set(p.r, body);
    if (mode === 'db') { try { await db.doc('labels/' + p.r).set(body); setSave('Note saved.'); } catch (e) { setSave('Could not save the note.', true); } }
    else { try { localStorage.setItem(LS, JSON.stringify(Object.fromEntries(labels))); } catch (e) {} }
  }, 700);
}

// ---------------------------------------------------------------- events
document.addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  if (b.dataset.l) decide(b.dataset.l);
  else if (b.dataset.nav) { pos = (pos + Number(b.dataset.nav) + PAIRS.length) % PAIRS.length; render(); }
  else if (b.dataset.i) { pos = Number(b.dataset.i); render(); $('#card').scrollIntoView({block: 'start', behavior: 'smooth'}); }
  else if (b.dataset.f) { filter = b.dataset.f; renderFilter(); renderCells(); }
  else if (b.id === 'copy') {
    const text = JSON.stringify(Object.fromEntries(labels));
    const done = () => setSave('Copied. Paste it to Claude to import the labels.');
    try { navigator.clipboard.writeText(text).then(done, () => fallbackCopy(text)); } catch (err) { fallbackCopy(text); }
  }
});
function fallbackCopy(text) {
  const t = document.createElement('textarea'); t.value = text; t.className = 'note'; t.rows = 3;
  $('#copywrap').append(t); t.select(); setSave('Select-all is ready: copy the text box with your keyboard.');
}
document.addEventListener('input', e => { if (e.target.id === 'note') noteChanged(); });
document.addEventListener('keydown', e => {
  if (e.target.closest && e.target.closest('textarea, input, select')) return;
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (k === 's') decide('same'); else if (k === 'd') decide('different'); else if (k === 'u') decide('unsure');
  else if (k === 'b' || k === 'arrowleft') { pos = (pos - 1 + PAIRS.length) % PAIRS.length; render(); }
  else if (k === 'n' || k === 'arrowright') { pos = (pos + 1) % PAIRS.length; render(); }
  else return;
  e.preventDefault();
});

// ---------------------------------------------------------------- start: render at once, then connect the store
renderFilter(); render();
(async () => {
  const [store, user] = await Promise.all([
    window.claude ? window.claude.use('db') : Promise.resolve(null),
    window.claude ? window.claude.use('user') : Promise.resolve(null)]);
  if (user) {
    try { byOwner = await user.isOwner(); } catch (e) { byOwner = null; }
    try { const w = await user.can('data.write'); if (w === false) canWrite = false; } catch (e) { /* not told: keep inputs */ }
  }
  if (!store) {
    mode = 'local';
    try { const saved = JSON.parse(localStorage.getItem(LS) || '{}'); Object.entries(saved).forEach(([k, v]) => labels.set(k, v)); } catch (e) {}
    pos = labels.has(PAIRS[0].r) ? nextUndecided(0) : 0; render(); return;
  }
  db = store; mode = 'db';
  let first = true;
  db.collection('labels').onSnapshot(snap => {
    labels.clear();
    snap.docs.forEach(d => { const v = d.data(); if (v && v.label) labels.set(d.id, v); });
    if (first) { first = false; pos = labels.has(PAIRS[0].r) ? nextUndecided(0) : 0; }
    if (!saving) render();
  }, err => { setSave('Lost the connection to the label store. Reload the page to reconnect.', true); });
  render();
})();
</script>
'''


def main():
    ps = pairs()
    html = (PAGE.replace('__PAIRS__', json.dumps(ps, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/'))
                .replace('__NEEDED__', str(NEEDED_PER_CLASS)))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding='utf-8')
    print(f'wrote {OUT.relative_to(ROOT)} ({len(html) / 1024:.0f} KB), {len(ps)} pairs')


if __name__ == '__main__':
    main()
