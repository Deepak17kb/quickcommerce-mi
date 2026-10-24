/*
 * site_smoke.js — run the built site's own scripts against a stand-in DOM and visit every page.
 *
 *     node scripts/site_smoke.js outputs/site/index.html
 *
 * It cannot see the page. What it proves: every page's render code runs to the end on the real embedded data, every
 * control's handler runs without throwing, the analyst answers, and no rendered text or tooltip uses the project's two
 * data-label words (the site says Snapshot and Lab instead; see `plain` in site/app.js). A wrong layout would still
 * pass; a missing field, a bad key, a typo or a leaked label word would not. Exit code 1 on any failure.
 */
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const dataBlocks = {};
for (const m of html.matchAll(/<script type="application\/json" id="d-(\w+)">([\s\S]*?)<\/script>/g)) dataBlocks[m[1]] = m[2];
const scripts = [...html.matchAll(/<script>\r?\n([\s\S]*?)\r?\n<\/script>/g)].map(m => m[1]);
if (scripts.length !== 2) { console.log('FAIL expected 2 inline scripts, found ' + scripts.length); process.exit(1); }

const handlers = [];
const made = new Map();
function fake(id) {
  if (id && made.has(id)) return made.get(id);
  const el = {
    id: id || '', hidden: false, value: '0', max: '0', checked: true, selectedIndex: 0, dataset: {}, style: {}, _html: '', textContent: '',
    classList: {add() {}, remove() {}, toggle() {}},
    set innerHTML(v) { this._html = String(v); }, get innerHTML() { return this._html; },
    get firstChild() { return fake((id || 'x') + '>first'); },
    setAttribute() {}, removeAttribute() {}, getAttribute() { return null; }, focus() {}, scrollIntoView() {}, append() {}, click() {}, reset() {},
    getBoundingClientRect() { return {left: 0, bottom: 0, top: 0, right: 0}; }, offsetWidth: 10, offsetHeight: 10,
    addEventListener(type, fn) { handlers.push({id: id || '', type, fn}); },
    querySelector(s) { return fake((id || '') + ' ' + s); }, querySelectorAll() { return []; }, closest() { return null; },
  };
  if (id) made.set(id, el);
  return el;
}
const windowHandlers = {};
global.window = global;
global.document = {
  body: fake('body'), documentElement: fake('html'),
  getElementById(id) { if (id.startsWith('d-')) return {textContent: dataBlocks[id.slice(2)]}; return fake('#' + id); },
  querySelector(s) { return fake(s); }, querySelectorAll() { return []; },
  addEventListener(type, fn) { handlers.push({id: 'document', type, fn}); },
};
global.location = {hash: ''};
global.history = {replaceState() {}};
global.localStorage = (() => { const m = {}; return {getItem: k => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); }}; })();
global.innerWidth = 1280; global.innerHeight = 800;
global.addEventListener = (type, fn) => { (windowHandlers[type] = windowHandlers[type] || []).push(fn); };
global.scrollTo = () => {};

const failures = [];
// a value that failed to bind shows up in the markup as one of these words, or as a bar wider than its track
// "Infinity" as a word inside a product name ("Ajmal Royal Touch Infinity Jewellery") is a name, not a number: a printed
// Infinity has a sign, a digit or punctuation on at least one side; a name has a word on both. (Lookbehind is fine here:
// this runs under node, not in a browser.)
const BAD = /\b(NaN|undefined)\b|(?<![A-Za-z] )\bInfinity\b|\bInfinity\b(?! [A-Z])|\[object |width:\s*(1[1-9]\d|[2-9]\d\d|\d{4,})(\.\d+)?%/;
// the two label words, as a reader would see them: standing alone or as a part of a name (real_rows). "Real" before
// a number or a capital is a juice brand in the catalog ("Real 4.20%", "Real Fruit Power"); the filter leaves it alone.
const WORD = /(?<![A-Za-z0-9])(real|synthetic)(?![A-Za-z0-9])/gi;
let wordsScanned = 0;
function leaked(markup) {
  // what is read: the text between tags, and the site's own tooltips. A title holds an exact file name and is not scanned.
  const tips = [...markup.matchAll(/data-tip="([^"]*)"/g)].map(m => m[1]).join(' | ');
  const text = markup.replace(/<[^>]*>/g, ' ') + ' | ' + tips;
  wordsScanned += text.length;
  const out = [];
  for (const m of text.matchAll(WORD)) if (m[1] !== 'Real' || /^ [a-z]/.test(text.slice(m.index + m[0].length))) out.push(text.slice(Math.max(0, m.index - 70), m.index + 50).replace(/\s+/g, ' '));
  // nor "snapshot", in any form (the owner asked for it off the pages too, 2026-10-14): the site says "check"; nor the
  // collection day as a label, "Seen 10 Jul" or "10 Jul" (asked off the pages 2026-10-24: an untagged number is Blinkit's)
  for (const m of text.matchAll(/snapshot|\b10 Jul\b/gi)) out.push(text.slice(Math.max(0, m.index - 70), m.index + 50).replace(/\s+/g, ' '));
  return out;
}
function scan(what) {
  for (const [id, el] of made) {
    // what a person typed, shown back to them (<q class="echo">), is theirs and may say anything
    const all = (el._html + ' ' + (typeof el.textContent === 'string' ? el.textContent : '')).replace(/<q class="echo">[\s\S]*?<\/q>/g, '');
    // a step's own log lines are quoted on the Pipeline page and may hold any number
    const m = all.replace(/<pre class="log">[\s\S]*?<\/pre>/g, '').match(BAD);
    if (m) failures.push(`${what}: "${m[0]}" in ${id}: …${all.slice(Math.max(0, m.index - 90), m.index + 40).replace(/\s+/g, ' ')}…`);
    for (const w of leaked(all)) failures.push(`label word on the page (${id}): …${w}…`);
  }
}
const attempt = (what, fn) => {
  try { fn(); } catch (e) { failures.push(`${what}: ${e && e.stack ? e.stack.split('\n').slice(0, 2).join(' | ') : e}`); }
  scan(what);
};

attempt('analyst.js', () => new Function(scripts[0])());
attempt('app.js', () => new Function(scripts[1])());

const view = fake('#view');
const pages = ['home', 'findings', 'data', 'models', 'simulate', 'optimize', 'analyst', 'listings', 'festive', 'plan', 'pipeline'];
const FEST = JSON.parse(dataBlocks.festive);
const drawn = {};
for (const page of pages) {
  const before = handlers.length;
  location.hash = '#' + page;
  attempt(`route ${page}`, () => (windowHandlers.hashchange || []).forEach(fn => fn()));
  drawn[page] = view._html.length;
  if (/could not be drawn/.test(view._html)) failures.push(`page ${page}: ${view._html.replace(/<[^>]+>/g, ' ').slice(0, 300)}`);
  // every control this page registered, pressed with plausible values (tabs and segments by each of their values)
  const mine = handlers.slice(before);
  // real values for each control, then junk: a stale saved state or a stray event must never break a page
  const W = JSON.parse(dataBlocks.whatif);
  const REAL = {
    '#sim-tabs': ['move', 'promo', 'outage', 'listing'], '#opt-tabs': ['target', 'listing', 'restock'],
    '#s-mover': ['0', '1', '2', '3'], '#o-mover': ['0', '1', '2', '3'], '#s-group': W.groups, '#o-group': W.groups, '#p-cat': Object.keys(W.frontier),
    '#s-move': ['-10', '-3', '0', '7', '10'], '#s-app': ['0', '1', '2', '3'], '#s-change': ['-10', '-5', '-3', '3', '5', '10'], '#o-app': ['0', '1', '2', '3'], '#o-goal': ['20', '40', '60'], '#p-cut': ['0', '5', '10'], '#o-target': ['10', '40', '75'], '#ol-target': ['10', '50', '90'],
    '#l-rung': ['0', '2', '5'], '#r-cap': ['0.25', '0.5', '1', '2', '4'], '#n-prod': ['0', '3', '6'], '#n-per': ['1', '2'], '#n-days': ['0', '4', '8'],
    '#n-sec': ['5', '60'], '#m-filter': ['all', 'REAL', 'SYNTHETIC'], '#pf-sort': ['feat', 'low', 'high', 'eta', 'cheap'],
    '#pf-q': ['frooti', 'diya', 'zzz'], '#pf-cat': ['Beverages', 'Personal Care', ''], '#n-rows': ['price_gap', 'cheapest_share', 'oos_rate', 'restock_mean', 'hazard_ratio', 'response_beta', 'evening_eta'],
    '#x-shelf': ['0', '1', '2', '3', '4', '5', '6', '7', '8'], '#l-pick': ['0', '4', '8'], '#ol-pick': ['0', '4', '8'],
    '#f-list': FEST.festivals.map(f => f.key), '#f-next': FEST.festivals.slice(0, 3).map(f => f.key), '#f-lead': ['1', '10', '30'],
    '#f-look': ['Handmade diya', 'Scented candles', 'Rakhi', 'Holi colours', 'Diwali', 'Christmas cake', 'garden hose'],
  };
  const JUNK = ['', 'zzz', '-1', '999', 'NaN'];
  for (const h of mine) {
    for (const val of (REAL[h.id] || ['1', '2']).concat(JUNK)) {
      const btn = {dataset: {v: val, i: '1', q: val, di: '2', pi: '3', pick: val, fest: val, fq: val, edit: val, optListing: '1', simListing: '1'}, closest() { return this; }};
      const ev = {target: {value: val === 'move' ? '5' : (isNaN(+val) ? '3' : val), checked: false, selectedIndex: isNaN(+val) ? 1 : +val, dataset: btn.dataset, closest: sel => (/button|td|\.col|\[data/.test(sel) ? btn : null)},
        key: 'Enter', preventDefault() {}, clientX: 5, clientY: 5};
      attempt(`${page} · ${h.id} ${h.type} (${val})`, () => h.fn(ev));
      if (/could not be drawn/.test(view._html)) failures.push(`page ${page} after ${h.id} ${h.type} (${val})`);
    }
  }
}

// the analyst, through the same engine the page uses
let answers = 0, rendered = 0;
const A = JSON.parse(dataBlocks.analyst), M = JSON.parse(dataBlocks.meta);
attempt('analyst answers', () => {
  const engine = global.QCAnalyst.create(A, {whatif: () => JSON.parse(dataBlocks.whatif)});
  for (const q of ['What is Blinkit revenue?', 'What happens if Blinkit cuts prices by 3 percent?', 'Out-of-stock rate by category on the real snapshot',
    'Explain this listing', 'Median delivery ETA by store on the real snapshot', 'a question about nothing in particular zzz']) {
    const a = engine.answer(q, {cache: false});
    if (typeof a.answer_summary !== 'string' || !Array.isArray(a.claims)) throw new Error('bad answer for ' + q);
    const ev = engine.evidenceFor(q), prompt = engine.writerPrompt(q, ev);
    if (!a.refused && prompt.length < 200) throw new Error('empty writer prompt for ' + q);
    engine.fromWriter(q, {summary: 'x', claims: ev.length ? [{text: 'A claim.', evidence: ['E1']}] : [], caveats: []}, ev);
    answers++;
  }
});

// every answer as the page would draw it: the project analyst's own answers saved at build time (the shape the local
// server returns live), and the engine in the page with those saved answers switched off
attempt('answers as drawn', () => {
  const site = global.QCSite, engine = global.QCAnalyst.create(A, {whatif: () => JSON.parse(dataBlocks.whatif)});
  if (!site || typeof site.answerHtml !== 'function') throw new Error('the page does not expose its answer renderer');
  for (const shown of M.suggested) {
    if (leaked(shown).length) failures.push(`label word in a suggested question: ${shown}`);
    const asked = site.internal(shown);
    if (!(asked in A.answers)) failures.push(`suggested question has no saved answer: ${shown} -> ${asked}`);
  }
  const brand = ['Out-of-stock rate by brand on the real snapshot', 'How many listings per brand on the snapshot?', 'Median price by brand in the snapshot',
    'Mean discount by subcategory on the snapshot', 'What does the snapshot say about delivery time by area?'];
  const drawnAnswers = [];
  for (const [q, a] of Object.entries(A.answers)) drawnAnswers.push([q + ' (saved)', a], [q + ' (in page)', engine.answer(q, {cache: false})]);
  for (const q of brand) drawnAnswers.push([q + ' (in page)', engine.answer(q, {cache: false})]);
  for (const [q, a] of drawnAnswers) {
    const markup = site.answerHtml(a);
    if (BAD.test(markup.replace(/width:[^;"]*/g, ''))) failures.push(`answer markup has an unbound value: ${q}`);
    for (const w of leaked(markup)) failures.push(`label word in an answer (${q}): …${w}…`);
    rendered++;
  }
});

// the basket, the go-anywhere palette, the theme and sharing are on every page, so no page presses them: they are
// pressed here through the handles the page exposes, and what they draw is scanned like any page
let basketLines = 0, paletteItems = 0;
attempt('basket', () => {
  const site = global.QCSite, X = JSON.parse(dataBlocks.explorer);
  if (!site.basket) throw new Error('the page does not expose its basket');
  site.basket.clear();
  for (const c of X.chains) site.basket.add('x:' + c.name);
  site.basket.add('x:' + X.chains[0].name);                    // a second of the same
  site.basket.add('u:0123456789ab');                           // one of yours that is no longer there
  site.basket.add('junk');
  site.basket.set('x:' + X.chains[1].name, 0);                 // taken out again
  site.basket.set('x:' + X.chains[2].name, 500);               // more than the cap
  site.basket.open();
  const items = site.basket.items(), lines = items.map(x => Object.assign(site.basket.line(x.k) || {}, {q: x.q})).filter(l => l.name);
  if (lines.length !== X.chains.length - 1) throw new Error(`expected ${X.chains.length - 1} basket lines, got ${lines.length}`);
  if (items.find(x => x.k === 'x:' + X.chains[0].name).q !== 2 || items.find(x => x.k === 'x:' + X.chains[2].name).q !== 99) throw new Error('quantities were not kept');
  const T = site.basket.totals(lines);
  if (T.length !== 4 || T.some(t => !(t.total > 0) || t.missing)) throw new Error('basket totals: ' + JSON.stringify(T));
  const by = (pl) => lines.reduce((s, l) => s + l.q * l.prices[pl], 0);
  for (const t of T) if (Math.abs(t.total - by(t.pl)) > 0.01) throw new Error(`basket total for ${t.pl} is ${t.total}, lines add to ${by(t.pl)}`);
  basketLines = lines.length;
  site.basket.close(); site.basket.clear(); site.basket.open(); site.basket.close();
});
attempt('palette', () => {
  const site = global.QCSite, inp = fake('#pal-q');
  if (!site.palette) throw new Error('the page does not expose its palette');
  const idx = site.palette.index();
  if (!idx.length || idx.some(it => !it.name || typeof it.go !== 'function')) throw new Error('a palette entry has no name or action');
  paletteItems = idx.length;
  for (const shown of idx.map(it => it.name)) for (const w of leaked(shown)) failures.push(`label word in the palette: …${w}…`);
  for (const q of ['', 'frooti', 'diwali', 'simulate', 'basket', 'zzz qqq', 'What is Blinkit revenue?']) {
    site.palette.open(); inp.value = q; site.palette.draw(); site.palette.pick(0);
  }
  site.toggleTheme(); site.toggleTheme(); site.shareLink(); site.toast('a toast');
});

console.log(JSON.stringify({pages: drawn, handlers: handlers.length, analyst_answers: answers, answers_drawn: rendered, basket_lines: basketLines, palette_items: paletteItems,
  characters_checked_for_label_words: wordsScanned, failures: failures.length}));
for (const f of [...new Set(failures)].slice(0, 40)) console.log('FAIL', f);
process.exit(failures.length ? 1 : 0);
