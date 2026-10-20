/*
 * analyst.js — the project's analyst, running in the page. A port of the offline engine in src/analyst (guard.py,
 * kb.py, agent.py), with the same order of work:
 *
 *   1. refusal policy, before any retrieval      (demand, revenue, elasticity, customers, best sellers ...)
 *   2. experiment routing                         (price moves, outages, store adds, promos, restock, one listing)
 *   3. real-snapshot routing                      (counts, stock-out share, price, discount, ETA on the REAL rows)
 *   4. BM25 retrieval over the project's documents and saved model outputs
 *   5. labels and banners                         (REAL / SYNTHETIC / METHOD / EXTERNAL, store label unverified)
 *
 * What differs from the Python analyst: experiment claims are looked up from answers the Python analyst produced and
 * verified at build time (a price move is formatted here from the same grid), and nothing is recomputed from raw
 * data. scripts/site_analyst_eval.js scores this file on the project's two question sets with the answer cache off.
 *
 * Loads in a browser (window.QCAnalyst) and under node (module.exports).
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.QCAnalyst = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const PLATFORMS = ['Blinkit', 'Swiggy Instamart', 'Flipkart Minutes', 'BigBasket'];
  const REAL_DATE = '2026-07-10';

  // ------------------------------------------------------------------ 1. refusal policy (guard.py, same order)
  const REFUSALS = [
    [/\b(demand|sales|units? sold|sales? volume|sell[- ]through|how (many|much) .*\b(sold|sell|bought|ordered)\b)/,
      'demand / sales volume',
      'There are no orders or quantities in this data. The honest substitute is time-until-stock-out (deliverable 7), which is itself SYNTHETIC.'],
    [/\b(revenue|gmv|aov|average order value|gross order value|net order value|turnover|profit|margin|earn(s|ings)?)\b|\bgov\b(?!\.)|\bnov\b(?!\s*\d)/,
      'revenue / GMV / profit',
      'No order, basket or cost data exists, so revenue, GMV, AOV and profit cannot be computed. SIMULATE and OPTIMIZE answer positioning questions (price rank, cheapest-of-4 share, availability, ETA) instead.'],
    [/\b(elastic(ity)?|price sensitiv)/,
      'price elasticity',
      "Elasticity needs demand, which is absent. The substitute is competitive price-response (deliverable 9, SYNTHETIC): how platforms respond to each other's prices."],
    [/\b(customers?|shoppers?|buyers?|users?|conversions?|basket)\b.*\b(buy|order|prefer|want|convert|spend|many)\b|\b(how many|number of) (customers|orders|users|buyers)\b/,
      'customer behaviour',
      'There are no customers or orders in the data. The substitute for recommendation is the assortment-gap model (deliverable 10, REAL): products similar real stores list.'],
    [/\b(best[- ]?sell(er|ing)|most popular|sells? (the )?most|top[- ]selling)\b/,
      'best sellers',
      "Sales are not observed. The only popularity signal is the platform's own is_bestseller badge, which is a display flag, not a sales count."],
    [/\bmarket share\b/,
      'market share',
      'Market share needs sales across platforms; none are observed. Cheapest-of-4 share (a price-position measure) is available, and on the four-platform panel it is SYNTHETIC.'],
    [/\bsells? out (the )?(faster|fastest|quick)|\bfastest[- ]selling\b|\bdeplet(es|ion) (faster|fastest|rate)/,
      'depletion speed by category',
      'One real snapshot gives stock-out prevalence, which mixes how fast items run out with how slowly they come back. The generator\'s category hazard scales were calibrated to that prevalence, so they are not depletion rates (CLAUDE.md s.2). The REAL out-of-stock share by category can be reported; "sells out faster" cannot.'],
  ];
  const LATENT_DEMAND = /(latent|store|b_)\s*demand|demand[\s_-]*(pressure|surge|index|term|effect|shock|proxy)/g;
  const SYNTHETIC_BANNER = 'SYNTHETIC-DERIVED: part of this answer comes from generated data. It shows what the modelling pipeline recovers from the v15.1 generator, not how the real market behaves.';
  const EXTERNAL_BANNER = "EXTERNAL: part of this answer comes from cited public web sources (news reports, a store map), not from the project's data, and was not checked against it. Each claim carries its URL.";
  const SUPPLY_NOTE = 'The data is supply-side only: prices, stock, ETA, offers. No customers, orders, quantities or revenue (CLAUDE.md s.4).';

  function refusal(question) {
    const q = question.toLowerCase().replace(LATENT_DEMAND, ' latent-pressure ');
    for (const [pat, topic, reason] of REFUSALS) if (pat.test(q)) return {topic, reason};
    return null;
  }

  // ------------------------------------------------------------------ numbers (guard.py)
  // no lookbehind (Safari before 16.4 cannot parse one): the character before a number is matched and set aside
  const NUM = /(^|[^\w.])([-+]?\d[\d,]*\.?\d*)/g;
  function numbersIn(text) {
    const out = [];
    for (const m of String(text).matchAll(NUM)) {
      const s = m[2].replace(/\.$/, '').replace(/,/g, '');
      if (!s || s === '-' || s === '+' || /^20\d\d$/.test(s) || /^\d$/.test(s)) continue;
      out.push(s);
    }
    return out;
  }
  function inEvidence(num, evidence, evNumbers) {
    if (evidence.includes(num)) return true;
    const v = parseFloat(num);
    if (!isFinite(v)) return false;
    const decimals = num.includes('.') ? num.split('.')[1].length : 0;
    const tol = 0.5 * Math.pow(10, -decimals) + 1e-9;
    for (const e of evNumbers) if (Math.abs(e - v) <= tol || Math.abs(100 * e - v) <= tol) return true;
    return false;
  }

  function create(data, extras) {
    extras = extras || {};
    const STOP = new Set(data.stop), ALIASES = data.aliases;

    // ---------------------------------------------------------------- tokens (kb.py)
    function stem(t) {
      if (t.length <= 4 || /^[0-9]/.test(t)) return t;
      for (const [suf, rep] of [['ies', 'y'], ['sses', 'ss'], ['ery', 'er'], ['ing', ''], ['ed', ''], ['ly', ''], ['es', 'e'], ['s', '']]) {
        if (t.endsWith(suf) && !(suf === 's' && t.endsWith('ss'))) return t.slice(0, t.length - suf.length) + rep;
      }
      return t;
    }
    function tokenize(text) {
      return (String(text).toLowerCase().match(/[a-z0-9]+(?:\.[0-9]+)?/g) || []).filter(t => !STOP.has(t) && t.length > 1).map(stem);
    }
    function expand(tokens) {
      const out = tokens.slice();
      for (const t of tokens) if (ALIASES[t]) out.push(...tokenize(ALIASES[t]));
      return out;
    }
    const PLANNING = new Set(tokenize(data.planningWords.join(' ')));

    // ---------------------------------------------------------------- index (kb.py)
    const P = data.passages;
    const df = new Map();
    let total = 0;
    for (const p of P) {
      const c = new Map();
      for (const t of tokenize(p.sec + ' ' + (p.model || '') + ' ' + p.text)) c.set(t, (c.get(t) || 0) + 1);
      p._tok = c; p._len = 0;
      for (const [t, n] of c) { p._len += n; df.set(t, (df.get(t) || 0) + 1); }
      total += p._len;
    }
    const N = P.length, avgdl = total / Math.max(N, 1);
    const idf = new Map();
    for (const [t, n] of df) idf.set(t, Math.log(1 + (N - n + 0.5) / (n + 0.5)));
    const idfOf = t => idf.get(t) || 0;

    function search(query, k) {
      const q = expand(tokenize(query)), k1 = 1.5, b = 0.75;
      const aboutCollecting = tokenize(query).some(t => PLANNING.has(t));
      const scored = [];
      for (const p of P) {
        let s = 0;
        for (const t of q) {
          const f = p._tok.get(t);
          if (f) s += idfOf(t) * f * (k1 + 1) / (f + k1 * (1 - b + b * p._len / avgdl));
        }
        if (p.hist || (p.plan && !aboutCollecting)) s *= 0.5;
        if (s > 0) scored.push([s, p]);
      }
      scored.sort((a, b2) => b2[0] - a[0]);
      return scored.slice(0, k || 6).map(([score, p]) => ({score, p}));
    }

    // ---------------------------------------------------------------- 3. real snapshot (agent.py)
    const MODEL_WORDS = ['model', 'forecast', 'classifier', 'recover', 'simulat', 'accura', 'predict', 'optimi', 'survival', 'planted', 'generator', 'baseline'];
    const METRICS = [['out of stock', 'oos_rate'], ['out-of-stock', 'oos_rate'], ['stock-out', 'oos_rate'], ['oos', 'oos_rate'], ['availability', 'oos_rate'],
      ['discount', 'mean_discount_pct'], ['eta', 'median_eta_min'], ['delivery time', 'median_eta_min'], ['price', 'median_price'],
      ['how many listings', 'listings'], ['number of listings', 'listings'], ['how many products', 'listings'], ['listings', 'listings']];
    const GROUPS = [['subcategor', 'subcategory'], ['categor', 'category'], ['brand', 'brand'], ['store', 'store_id'], ['area', 'area'], ['zone', 'area']];
    const PHRASE = {oos_rate: 'the share of listings out of stock', median_price: 'the median selling price (Rs)', mean_discount_pct: 'the mean discount (%)',
      median_eta_min: 'the median promised ETA (minutes)', listings: 'the number of listings'};
    const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const word = (w, q) => new RegExp('\\b' + esc(w)).test(q);
    const whole = (w, q) => new RegExp('\\b' + esc(w) + '\\b').test(q);
    const head = c => c.split(',')[0].split('&')[0].trim().toLowerCase();
    const thousands = v => Math.round(v).toLocaleString('en-US');
    const g = v => String(parseFloat(Number(v).toPrecision(6)));
    const fmtMetric = (m, v) => m === 'oos_rate' ? (100 * v).toFixed(2) + '%' : m === 'listings' ? thousands(v) : g(v);

    function parseRealQuery(question) {
      const q = question.toLowerCase();
      if (!['real', 'snapshot', '2026-07-10', 'july', 'observed'].some(w => q.includes(w)) || MODEL_WORDS.some(w => q.includes(w))) return null;
      const hit = METRICS.find(([w]) => word(w, q));
      if (!hit) return null;
      const grouped = /\b(by|per|each|which|across|every)\b/.test(q);
      let group = grouped ? (GROUPS.find(([w]) => q.includes(w)) || [null, 'none'])[1] : 'none';
      const cat = data.categories.find(c => whole(c.toLowerCase(), q) || whole(head(c), q)) || null;
      if (cat && group === 'category') group = 'none';
      return {metric: hit[1], group, category: cat};
    }
    function realClaims(rq) {
      const key = rq.category ? `${rq.metric}|none|${rq.category}` : `${rq.metric}|${rq.group}`;
      const res = data.cube[key];
      if (!res) return null;
      const m = rq.metric, scope = rq.category ? ` in ${rq.category}` : '';
      const base = {source_file: 'data/raw (REAL rows)', provenance: 'REAL', date: REAL_DATE};
      const group = rq.category ? 'none' : rq.group;
      let claim;
      if (group === 'none') {
        const row = res.rows[0];
        claim = {...base, source_detail: `query_real_snapshot(${m})`,
          text: `On the REAL Blinkit snapshot of ${REAL_DATE}, ${PHRASE[m]}${scope} is ${fmtMetric(m, row[m])} across ${thousands(row.listings)} listings.`};
      } else {
        const parts = res.rows.slice(0, 6).map(r => `${r.group} ${fmtMetric(m, r[m])} (${thousands(r.listings)} listings)`).join('; ');
        claim = {...base, source_detail: `query_real_snapshot(${m}, by ${group})`,
          text: `REAL snapshot ${REAL_DATE}, ${PHRASE[m]}${scope} by ${group}, highest first: ${parts}.`};
      }
      return {claims: [claim], caveats: res.caveats, evidence: JSON.stringify(res)};
    }

    // ---------------------------------------------------------------- 2. experiments (agent.py)
    const PLATFORM_WORDS = [['instamart', 'Swiggy Instamart'], ['swiggy', 'Swiggy Instamart'], ['flipkart', 'Flipkart Minutes'], ['bigbasket', 'BigBasket'], ['big basket', 'BigBasket'], ['blinkit', 'Blinkit']];
    const CUT = /\b(cut|cuts|cutting|drop|drops|lower|lowers|lowering|reduce|reduces|reducing|discount|discounts)\b[^0-9]{0,60}?(\d+(?:\.\d+)?)\s*(%|percent|per cent)/;
    const RAISE = /\b(raise|raises|raising|increase|increases|increasing|hike|hikes|hiking|put up|puts up|lift|lifts)\b[^0-9]{0,60}?(\d+(?:\.\d+)?)\s*(%|percent|per cent)/;
    const HEADROOM = /\bheadroom\b|how (much|far) (can|could) \w+( \w+)? (raise|increase|put up)|(raise|increase|hike)\w* .{0,40}\bwithout (losing|giving up|hurting)/;
    const STATIC = /\b(static|frozen|don'?t react|do not react|no (competitor )?(reaction|response)|nobody reacts|without (a |the )?(competitor )?(reaction|response))\b/;
    const groups = () => (extras.whatif ? extras.whatif().groups : []);

    function experimentCategory(q) {
      const qt = new Set(tokenize(q));
      for (const grp of groups()) {
        if (grp === 'All') continue;
        const h = head(grp), ht = tokenize(h);
        if (whole(grp.toLowerCase(), q) || whole(h, q) || (ht.length && ht.every(t => qt.has(t)))) return grp;
      }
      return null;
    }
    function parseExperiment(question) {
      const q = question.toLowerCase();
      const sm = q.match(/\b(?:blk-)?bbsr-?(\d{3})\b|\bstore\s*(\d{3})\b/);
      if (/\bexplain\b.*\b(listing|product)\b|\bthis listing\b/.test(q) || (sm && /\b(why|risky|risk|explain|what should|recommend)\b/.test(q))) {
        const store = sm ? (sm[1] || sm[2]) : null;
        const product = q.replace(/\b(explain|this|the|listing|product|why|is|risky|risk|at|in|store|what|should|blinkit|do|about|recommend|for|price|bbsr|blk)\b|[-?.,0-9]/g, ' ').split(/\s+/).filter(Boolean).join(' ') || null;
        return ['explain_listing', {product, store}];
      }
      if (HEADROOM.test(q)) return ['price_headroom', {category: experimentCategory(q) || 'All'}];
      const mover = (PLATFORM_WORDS.find(([w]) => q.includes(w)) || [])[1] || null;
      const r = q.match(RAISE);
      if (r && mover) return ['simulate_price_move', {mover, size: parseFloat(r[2]), direction: 'raise', category: experimentCategory(q), react: !STATIC.test(q)}];
      const m = q.match(CUT);
      const asksForCut = /\b(smallest|minimum|least|how (deep|big|large))\b.{0,40}\bcut/.test(q);
      if (m && mover && !asksForCut && !/\b(promo|promotion)\b.*\b(stock|availability)\b/.test(q)) {
        return ['simulate_price_move', {mover, size: parseFloat(m[2]), direction: 'cut', category: experimentCategory(q), react: !STATIC.test(q)}];
      }
      if (/\bsubstitut/.test(q) || (/\b(goes|go|went|is|are|were|become|becomes|ran|runs?)\s+(out of stock|unavailable)\b|\boutage\b|\bunavailab/.test(q) && !/\b(real|snapshot)\b/.test(q))) {
        const plat = (PLATFORM_WORDS.find(([w]) => q.includes(w)) || [])[1] || 'Blinkit';
        return ['outage_impact', {platform: plat, category: plat === 'Blinkit' ? experimentCategory(q) : null}];
      }
      if (/\b(add|adds|adding|added)\b/.test(q) && /\b(gap|gaps|products?|missing|assortment)\b/.test(q) && !/\bcapacity\b/.test(q)) {
        const s2 = q.match(/bbsr-?(\d{3})|store\s*(\d{3})/), nm = q.match(/\b(10|25|50)\b/);
        return ['store_adds', {store: s2 ? (s2[1] || s2[2]) : null, n: nm ? parseInt(nm[1], 10) : 50}];
      }
      if (/\b(promo|promotion|promotions|discount)/.test(q) && /\b(stock|availability|available)/.test(q)) {
        const cat = experimentCategory(q);
        if (cat) return ['promo_frontier', {category: cat}];
      }
      if (/\bcapacity\b/.test(q) && /restock|stock-out|out of stock|expedite/.test(q)) return ['restock_capacity', {}];
      if (/\b(oracle|clairvoyant|optimal|optimality)\b/.test(q) && q.includes('restock')) return ['restock_capacity', {}];
      if (q.includes('restock') && /\b(win|wins|cheapest|objective|weight|weighted|weighting|pareto|trade-?off|position|positions)\b/.test(q)) return ['restock_objective', {}];
      return null;
    }

    const pct1 = v => (100 * v).toFixed(1) + '%';
    const signed = (v, d) => (v >= 0 ? '+' : '') + Number(v).toFixed(d);
    function priceMoveClaims(a) {
      const W = extras.whatif && extras.whatif();
      if (!W) return null;
      const size = Math.max(1, Math.min(10, Math.round(a.size)));
      const group = a.category || 'All', move = a.direction === 'raise' ? size : -size;
      const view = a.react ? 'strategic' : 'static', otherView = a.react ? 'static' : 'strategic';
      const c = W.cells[`${a.mover}|${group}|${move}|${view}`], o = W.cells[`${a.mover}|${group}|${move}|${otherView}`];
      if (!c || !o) return null;
      const i = PLATFORMS.indexOf(a.mover), raising = a.direction === 'raise', verb = raising ? 'raises' : 'cuts';
      const where = group === 'All' ? 'across the common panel' : `in ${group} (${c.n} SKUs)`;
      const [lo, med, hi] = c.d[i], otherMed = o.d[i][1];
      const src = {provenance: 'SYNTHETIC', source_file: 'outputs/models/simulate_grid/grid.json', date: extras.gridDate || ''};
      const c1 = {...src, source_detail: `simulate_price_move(${a.mover}, ${verb} ${size}%, ${group}, ${view})`,
        text: `If ${a.mover} ${verb} prices ${size}% ${where}, ${a.react ? 'with the fitted competitor response' : 'with competitors frozen'}, its cheapest-of-4 share moves from ${pct1(c.b[i])} to ${pct1(c.s[i])}: ${signed(med, 1)} pp (90% band ${signed(lo, 1)} to ${signed(hi, 1)}) over the next 12 snapshots.`};
      const others = PLATFORMS.map((p, j) => j === i ? null : `${p} ${pct1(c.b[j])} to ${pct1(c.s[j])}`).filter(Boolean).join('; ');
      const c2 = {...src, source_detail: 'the other platforms in the same run', text: `The others: ${others}.`};
      let verdict;
      if (Math.abs(otherMed - med) < 0.5) verdict = "Nobody responds to this platform's move in the fitted dynamics (only Blinkit is followed), so both views agree.";
      else if (raising) verdict = otherView === 'static' ? 'Followers follow Blinkit up, so ignoring the response overstates the loss.' : 'The fitted response gives part of the loss back.';
      else verdict = otherView === 'static' ? 'Ignoring the response overstates the gain.' : 'The fitted response takes part of the gain back.';
      const c3 = {...src, source_detail: `same scenario, ${otherView} view`, text: `The ${otherView} view of the same ${raising ? 'raise' : 'cut'} gives ${signed(otherMed, 1)} pp. ${verdict}`};
      return {claims: [c1, c2, c3], caveats: ['SYNTHETIC experiment under the fitted, generated dynamics: positioning and availability only. Not a market forecast and never demand or revenue.'],
        evidence: JSON.stringify({cells: [c, o], horizon_snapshots: 12, band: '90% band: 5th to 95th percentile over paired simulations'}),
        link: {page: 'simulate', mover: a.mover, group, move, react: a.react}};
    }
    function matchScore(text, name) {
      const a = new Set(tokenize(text)), b = new Set(tokenize(name));
      let both = 0;
      for (const t of a) if (b.has(t)) both++;
      return both / Math.max(a.size, 1) + 0.01 * both / Math.max(b.size, 1);
    }
    function experimentAnswer(tool, a) {
      const T = data.tools;
      if (tool === 'simulate_price_move') return priceMoveClaims(a);
      let key = null;
      if (tool === 'outage_impact') key = `outage|${a.platform}|${a.category || ''}`;
      else if (tool === 'store_adds') key = `adds|${a.store || ''}|${a.n}`;
      else if (tool === 'restock_objective') key = 'objective';
      else if (tool === 'restock_capacity') key = 'capacity';
      else if (tool === 'price_headroom') key = `headroom|${a.category}`;
      else if (tool === 'promo_frontier') key = `promo|${a.category}`;
      else if (tool === 'explain_listing') {
        let best = null, bestScore = 0;
        for (const k of Object.keys(T)) {
          if (!k.startsWith('listing|') || k === 'listing|default') continue;
          if (a.store && !(T[k].store || '').endsWith(a.store)) continue;
          const sc = a.product ? matchScore(a.product, T[k].product || '') : 0.01;
          if (sc > bestScore) { best = k; bestScore = sc; }
        }
        // the Python analyst runs a live chain for a listing with no saved one; the page cannot, so it says so
        if (!a.product && !a.store) key = 'listing|default';
        else if (best && (!a.product || bestScore >= 0.99)) key = best;
        else key = null;
      }
      const hit = key && T[key];
      if (!hit) return null;
      return {claims: hit.claims.map(c => ({...c})), caveats: hit.caveats, prebuilt: true, tool,
        link: tool === 'explain_listing' ? {page: 'listings', product: hit.product} : null};
    }

    // ---------------------------------------------------------------- 4. claims from search hits (agent.py)
    const KEY_TERMS = ['mae', 'skill', 'verdict', 'auc', 'recall', 'precision', 'coverage', 'estimate', 'planted', 'beats', 'log_loss', 'corrected', 'reduction', 'capture', 'k_hat', 'change_pp', 'min_cut', 'ari', 'rand'];
    function bestSentences(text, qtok, n, limit) {
      n = n || 2; limit = limit || 420;
      const parts = text.replace(/([.!?])\s+/g, '$1\n').split(/\n+/).map(p => p.replace(/^[ \-*|]+|[ \-*|]+$/g, '')).filter(p => p.length > 25);
      const score = parts.map(p => { let s = 0; for (const t of new Set(tokenize(p))) if (qtok.has(t)) s += idfOf(t); return s; });
      const top = parts.map((_, i) => i).sort((a, b) => score[b] - score[a]).slice(0, n);
      const picked = [];
      for (const i of top) {
        if (parts[i].length < 60 && i > 0 && !top.includes(i - 1) && !picked.includes(i - 1)) picked.push(i - 1);
        picked.push(i);
      }
      const out = picked.map(i => parts[i]).join(' ');
      return out.length <= limit ? out : out.slice(0, limit).replace(/\s+\S*$/, '') + ' …';
    }
    function metricClaim(p, qtok) {
      const leaves = data.leaves[p.id] || [];
      if (!leaves.length) return null;
      const score = ([path]) => {
        let s = 0;
        for (const t of new Set(tokenize(path.replace(/_/g, ' ').replace(/\./g, ' ')))) if (qtok.has(t)) s += idfOf(t);
        return s + 2 * (KEY_TERMS.some(t => path.toLowerCase().includes(t)) ? 1 : 0);
      };
      const ranked = leaves.map((l, i) => [score(l), i]).sort((a, b) => b[0] - a[0] || a[1] - b[1]).slice(0, 7).map(x => x[1]).sort((a, b) => a - b);
      return `${p.model} · ` + ranked.map(i => `${leaves[i][0]} = ${leaves[i][1]}`).join('; ');
    }
    const urlIn = text => { const m = text.match(/https?:\/\/[^\s)]+/); return m ? m[0].replace(/[.,]+$/, '') : ''; };
    function externalFact(p, limit) {
      limit = limit || 480;
      let body = p.text.split('Source:')[0].split(/\s+/).join(' ');
      if (body.length > limit) { const cut = body.slice(0, limit).split('. ').slice(0, -1).join('. '); body = cut ? cut + '.' : body.slice(0, limit); }
      return `${p.sec}: ${body}`;
    }
    function claimsFromHits(question, hits, maxClaims, allowed) {
      const qtok = new Set(expand(tokenize(question))), qplain = new Set(tokenize(question));
      const shared = text => { let n = 0; for (const t of new Set(tokenize(text))) if (qplain.has(t)) n++; return n; };
      let results = hits.filter(h => allowed.includes(h.p.prov));
      results = results.filter(h => h.p.prov !== 'EXTERNAL' || shared(h.p.sec + ' ' + h.p.text) >= 2);
      const boost = h => { if (h.p.prov !== 'EXTERNAL') return 1; const s = shared(h.p.sec); return s >= 2 ? 1 + s / Math.max(qplain.size, 1) : 1; };
      results = results.map((h, i) => [h, i]).sort((a, b) => b[0].score * boost(b[0]) - a[0].score * boost(a[0]) || a[1] - b[1]).map(x => x[0]);
      if (results.length) {
        const best = results[0].score * boost(results[0]);
        results = results.filter(h => h.p.prov !== 'EXTERNAL' || h.score * boost(h) >= 0.9 * best);
      }
      const claims = [], caveats = [], evidence = [], seen = new Set();
      const byModel = {};
      let totalScore = 0;
      for (const h of results) { totalScore += h.score; if (h.p.kind === 'metric') byModel[h.p.model] = (byModel[h.p.model] || 0) + h.score; }
      const lead = Object.keys(byModel).sort((a, b) => byModel[b] - byModel[a])[0];
      const topExternal = results.length && results[0].p.prov === 'EXTERNAL';
      if (lead && byModel[lead] >= 0.3 * (totalScore || 1) && !topExternal) {
        const L = data.lead[lead];
        if (L && L.text) {
          claims.push({text: `${lead} · ${L.text}`, provenance: L.prov, source_file: L.src, source_detail: L.key, date: L.date});
          seen.add(L.src + '|' + L.key); evidence.push(L.text);
        }
        if (L && L.limit) caveats.push(`${lead}: ${L.limit}`);
      }
      for (const h of results) {
        if (claims.length >= maxClaims) break;
        const p = h.p, key = p.src + '|' + p.sec;
        if (seen.has(key)) continue;
        seen.add(key);
        let text;
        if (p.kind === 'metric') {
          text = metricClaim(p, qtok);
          if (!text) continue;
          evidence.push((data.leaves[p.id] || []).map(l => l.join(' = ')).join('; '));
        } else if (p.prov === 'EXTERNAL') {
          text = externalFact(p); evidence.push(p.text);
        } else {
          const sib = results.filter(x => x.p.src === p.src && x.p.sec === p.sec).map(x => x.p)
            .sort((a, b) => (parseInt(a.id.split('#').pop(), 10) || 0) - (parseInt(b.id.split('#').pop(), 10) || 0));
          const joined = sib.map(x => x.text).join('\n\n');
          text = bestSentences(joined, qtok, 3);
          if (p.sec.split(/\s+/).length >= 3 && !/^(deliverable|what this)/i.test(p.sec)) text = `${p.sec}: ${text}`;
          evidence.push(joined + ' ' + p.sec);
        }
        let detail = p.sec + (p.hist ? ' (historical doc)' : '');
        if (p.prov === 'EXTERNAL') detail += ` · ${urlIn(p.text)}`;
        claims.push({text, provenance: p.prov, source_file: p.src, source_detail: detail, date: p.date});
      }
      return {claims, caveats, evidence: evidence.join('\n')};
    }

    // ---------------------------------------------------------------- 5. labels, numbers, banners (guard.py, provenance.py)
    function sourceProvenance(src) {
      if (src.startsWith('data/raw')) return 'REAL';
      if (src.startsWith('src/')) return 'METHOD';
      const exact = data.fileProv[src];
      return exact === 'MIXED' ? null : (exact || (src.startsWith('outputs/models/') ? 'SYNTHETIC' : null));
    }
    function verify(claims, evidenceText) {
      const evNumbers = new Set(numbersIn(evidenceText).map(parseFloat).filter(isFinite));
      return claims.map(c0 => {
        const c = {...c0}, issues = [];
        const src = c.source_file || '', srcProv = sourceProvenance(src), label = c.provenance;
        if (!['REAL', 'SYNTHETIC', 'METHOD', 'EXTERNAL'].includes(label)) { issues.push('missing provenance label; set to SYNTHETIC (conservative)'); c.provenance = 'SYNTHETIC'; }
        else if (srcProv === 'EXTERNAL' && label !== 'EXTERNAL') { issues.push(`labelled ${label} but the source is an EXTERNAL web source; relabelled EXTERNAL`); c.provenance = 'EXTERNAL'; }
        else if (label === 'EXTERNAL' && srcProv !== 'EXTERNAL') { issues.push('labelled EXTERNAL but the cited file is not an external source; relabelled from the source'); c.provenance = srcProv || 'SYNTHETIC'; }
        else if (srcProv === 'METHOD' && label === 'REAL') { issues.push('labelled REAL but the source is project code; relabelled METHOD'); c.provenance = 'METHOD'; }
        else if (srcProv === 'SYNTHETIC' && label !== 'SYNTHETIC') { issues.push(`labelled ${label} but the source is SYNTHETIC-derived; relabelled SYNTHETIC`); c.provenance = 'SYNTHETIC'; }
        if (c.provenance === 'EXTERNAL' && !((c.source_detail || '') + ' ' + (c.text || '')).includes('http')) issues.push('EXTERNAL claim without its source URL');
        const missing = numbersIn(c.text || '').filter(n => !inEvidence(n, evidenceText, evNumbers));
        if (missing.length) issues.push('numbers not found in the retrieved evidence: ' + missing.join(', '));
        c.verified = issues.length === 0; c.issues = issues;
        return c;
      });
    }
    function isStoreLevel(c) {
      if (c.provenance !== 'REAL') return false;
      const src = String(c.source_file || '').replace(/\\/g, '/'), detail = String(c.source_detail || '');
      if (data.storeOutputs.some(n => src.startsWith(`outputs/models/${n}/`)) || data.storeDocs.includes(src)) return true;
      if (detail.includes('by store_id') || detail.includes('by area')) return true;
      return c.stage === '1_observe';
    }
    function finish(question, o) {
      const claims = o.claims || [];
      for (const c of claims) if (data.storeUnverified && isStoreLevel(c)) c.store_label = 'UNVERIFIED';
      return {question, mode: o.mode || 'evidence', refused: !!o.refused, refusal_reason: o.refusal_reason || null,
        answer_summary: o.summary, claims, caveats: [...new Set(o.caveats || [])],
        banner: claims.some(c => c.provenance === 'SYNTHETIC') ? SYNTHETIC_BANNER : null,
        external_banner: claims.some(c => c.provenance === 'EXTERNAL') ? EXTERNAL_BANNER : null,
        store_label_banner: claims.some(c => c.store_label) ? data.storeBanner : null,
        note: o.note || null, link: o.link || null, all_claims_verified: claims.every(c => c.verified !== false)};
    }

    // ---------------------------------------------------------------- the answer
    const norm = q => q.toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim();
    const cached = new Map(Object.entries(data.answers).map(([q, a]) => [norm(q), a]));

    function evidenceFor(question) {
      // what a writer needs: routed results first, then the passages a search finds
      const out = [];
      const exp = parseExperiment(question);
      const e = exp && experimentAnswer(exp[0], exp[1]);
      if (e) e.claims.forEach(c => out.push({label: c.provenance, source: c.source_file + ' · ' + c.source_detail, text: c.text, date: c.date || ''}));
      const rq = !e && parseRealQuery(question);
      const r = rq && realClaims(rq);
      if (r) r.claims.forEach(c => out.push({label: 'REAL', source: c.source_file + ' · ' + c.source_detail, text: c.text, date: REAL_DATE}));
      for (const h of search(question, 8)) {
        const p = h.p;
        out.push({label: p.prov, source: p.src + ' · ' + p.sec, date: p.date,
          text: p.kind === 'metric' ? `${p.model} · ${p.sec}: ` + (data.leaves[p.id] || []).slice(0, 40).map(l => l.join(' = ')).join('; ') : p.text.slice(0, 1200)});
      }
      return out.slice(0, 10);
    }

    function answer(question, opts) {
      opts = opts || {};
      const ref = refusal(question);
      if (ref) {
        return finish(question, {refused: true, refusal_reason: ref.reason, mode: 'refused',
          summary: `I can't answer this from the project's data (${ref.topic}).`, caveats: [ref.reason, SUPPLY_NOTE]});
      }
      if (opts.cache !== false) {
        const hit = cached.get(norm(question));
        if (hit) return {...hit, mode: 'project analyst, answered at build time', link: null, note: null};
      }
      const exp = parseExperiment(question);
      if (exp) {
        const e = experimentAnswer(exp[0], exp[1]);
        if (e) {
          const claims = e.prebuilt ? e.claims : verify(e.claims, e.evidence);
          const headline = claims.find(c => c.stage === '6_optimization') || claims[0];
          return finish(question, {claims, caveats: e.caveats, summary: headline.text, link: e.link, mode: 'experiment',
            note: `Ran the ${exp[0]} experiment.`});
        }
        if (exp[0] === 'explain_listing') {
          return finish(question, {claims: [], summary: 'No saved chain matches that listing. The site holds the gallery listings only; pick one on the Listings page, or run python -m src.chain.listing for another.', mode: 'experiment'});
        }
      }
      let claims = [], caveats = [], evidence = '';
      const rq = parseRealQuery(question);
      const real = rq && realClaims(rq);
      if (real) { claims = real.claims; caveats = real.caveats.slice(); evidence = real.evidence; }
      const hits = search(question, 10);
      const more = claimsFromHits(question, hits, claims.length + (real ? 2 : 4), real ? ['REAL', 'METHOD'] : ['REAL', 'SYNTHETIC', 'METHOD', 'EXTERNAL']);
      evidence += '\n' + more.evidence;
      claims = verify(claims.concat(more.claims), evidence);
      caveats = caveats.concat(more.caveats);
      if (!claims.length) return finish(question, {claims: [], summary: 'Nothing in the project documents or model outputs matches this question.'});
      return finish(question, {claims, caveats, summary: claims[0].text, note: 'Evidence mode: the claims are the best-matching passages, not a written answer.'});
    }

    // ---------------------------------------------------------------- a written answer (Claude), still bound by the evidence
    function writerPrompt(question, evidence) {
      const lines = evidence.map((e, i) => `[E${i + 1}] label=${e.label} | source=${e.source} | date=${e.date}\n${e.text}`).join('\n\n');
      return 'You are the analyst for a quick-commerce market intelligence project about Blinkit, Swiggy Instamart, Flipkart Minutes and BigBasket in Bhubaneswar.\n' +
        'Answer the question using ONLY the evidence below. Rules:\n' +
        '- Every claim cites one or more evidence ids. A claim with no evidence is not allowed.\n' +
        '- Copy numbers exactly as the evidence writes them. Never compute, round differently, or invent a number.\n' +
        '- Evidence labelled SYNTHETIC describes generated data: it shows a method works, never how the real market behaves. Say so when you use it.\n' +
        '- The data has no customers, orders, demand, revenue or elasticity. Never state or imply any of them.\n' +
        '- If the evidence does not answer the question, say what is missing in the summary and return no claims.\n' +
        'Reply with only JSON: {"summary": "two or three plain sentences", "claims": [{"text": "one sentence", "evidence": ["E1"]}], "caveats": ["short sentence"]}\n\n' +
        `QUESTION: ${question}\n\nEVIDENCE:\n${lines}`;
    }
    function fromWriter(question, reply, evidence) {
      const all = evidence.map(e => e.text).join('\n');
      const claims = [];
      for (const c of (reply && reply.claims) || []) {
        const ids = (Array.isArray(c.evidence) ? c.evidence : []).map(x => parseInt(String(x).replace(/\D/g, ''), 10) - 1).filter(i => evidence[i]);
        if (!ids.length || !c.text) continue;
        const cited = ids.map(i => evidence[i]);
        const label = cited.some(e => e.label === 'SYNTHETIC') ? 'SYNTHETIC' : cited.some(e => e.label === 'EXTERNAL') ? 'EXTERNAL' : cited[0].label;
        const src = cited[0].source.split(' · ');
        claims.push({text: String(c.text), provenance: label, source_file: src[0], source_detail: src.slice(1).join(' · '), date: cited[0].date});
      }
      const checked = verify(claims, all);
      const summary = String((reply && reply.summary) || '').trim();
      const bad = numbersIn(summary).filter(n => !inEvidence(n, all, new Set(numbersIn(all).map(parseFloat))));
      return finish(question, {claims: checked, caveats: (reply && reply.caveats) || [], mode: 'written by Claude from the evidence',
        summary: summary || 'No answer was written.',
        note: bad.length ? 'The summary contains numbers that are not in the evidence (' + bad.join(', ') + '); rely on the claims below.' : null});
    }

    return {answer, refusal, search, verify, evidenceFor, writerPrompt, fromWriter, parseExperiment, parseRealQuery, tokenize,
      suggested: data.suggested, passages: P.length};
  }

  return {create, refusal, numbersIn, PLATFORMS};
});
