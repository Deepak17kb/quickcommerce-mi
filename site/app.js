/* app.js — the storefront pages. Every number is read from the JSON blocks build_site.py embeds; nothing is computed
   from raw data here. Simulate and Optimize read simulations that were run in advance and say so.

   Wording: a number from the simulated 30-day panel is tagged "Lab"; one observed on Blinkit is tagged "Observed", with no
   date (owner, 2026-10-24: first the observed tag and its date came off the pages, then the tag came back, because a
   missing tag is not read as a meaning; the date stays off). A
   snapshot, as a unit of time, is a "check": one round of prices and stock, morning or evening. plain() rewrites the
   project's own labels into those words wherever project text is shown, so a number never loses its tag. */
(function () {
  'use strict';
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const blocks = {};
  const D = n => blocks[n] || (blocks[n] = JSON.parse(document.getElementById('d-' + n).textContent));
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const pct = (x, d) => (100 * x).toFixed(d == null ? 1 : d) + '%';
  const fix = (x, d) => Number(x).toFixed(d == null ? 2 : d);
  const int = x => Math.round(x).toLocaleString('en-IN');
  const rs = v => '₹' + (Math.abs(v - Math.round(v)) < 1e-9 ? int(v) : fix(v, 2));
  const sgn = (v, d) => (v >= 0 ? '+' : '') + Number(v).toFixed(d == null ? 1 : d);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const P = ['Blinkit', 'Swiggy Instamart', 'Flipkart Minutes', 'BigBasket'];

  /* plain:start */
  function plain(s) {
    const cap = w => w.charAt(0).toUpperCase() + w.slice(1);
    const NOUNS = '(?:rows?|snapshots?|data|records?|listings?|pairs?|days?|observations?|Blinkit (?:snapshot|rows?|listings?)|and|or)';
    return String(s == null ? '' : s)
      // the project's working notes are not a source a reader can open: a "(CLAUDE.md s.4)" citation is dropped and
      // any other mention reads as the project notes
      .replace(/\s*\((?:see )?CLAUDE\.md[^)]*\)/g, '').replace(/\bCLAUDE\.md\b/g, 'project notes')
      // the site was called Qcom until 2026-10-24; older notes the analyst quotes still say so
      .replace(/\bQcom\b/g, 'ShelfPulse')
      // names of outputs, files and columns: real_store_label_audit -> observed_store_label_audit
      .replace(/query_real_snapshot/g, 'observed_query').replace(/_the_real_market/g, '_the_market')
      // (no lookbehind anywhere: Safari before 16.4 rejects the whole script over one)
      .replace(/_real(?![A-Za-z0-9])|(^|[^A-Za-z0-9])real(?=_)/gi, (m, a) => (a === undefined ? '_observed' : a + 'observed'))
      .replace(/_synthetic(?![A-Za-z0-9])|(^|[^A-Za-z0-9])synthetic(?=_)/gi, (m, a) => (a === undefined ? '_lab' : a + 'lab'))
      .replace(/\b(anomaly|adds) real\b/g, '$1 observed').replace(/\breal store label\b/g, 'observed store label').replace(/\bsynthetic control\b/g, 'lab control')
      // the labels
      .replace(/\bSYNTHETIC-DERIVED\b/g, 'Lab result').replace(/\bsynthetic-derived\b/gi, 'Lab-derived')
      .replace(/\bREAL-ONLY\b/g, 'Observed data only').replace(/\breal-only\b/gi, 'observed-only')
      .replace(/\bREAL ONLY\b/g, 'Observed data only').replace(/\bSYNTHETIC ONLY\b/g, 'Lab only')
      .replace(/\breal-(calibrated|derived)\b/gi, 'observation-$1')
      .replace(/\bREAL (anomaly|detector)\b/g, 'observed $1')
      .replace(/\bREAL:/g, 'Observed:').replace(/\bSYNTHETIC:/g, 'Lab:')
      .replace(/(^|[.!?]\s+)SYNTHETIC\./g, '$1Lab result.')
      .replace(/\bREAL\b/g, 'observed').replace(/\bSYNTHETIC\b/g, 'simulated')
      .replace(/\bsynthetic\b/g, 'simulated').replace(/\bSynthetic\b/g, 'Simulated')
      // the adjective, by what it describes ("Real" before a number or a capital is a juice brand and stays)
      .replace(/\b(r|R)eal[- ]time\b/g, (m, r) => (r === 'R' ? 'Live' : 'live'))
      .replace(/\b(r|R)eal[- ]world\b/g, (m, r) => (r === 'R' ? 'Live-market' : 'live-market'))
      .replace(/\breal((?: multi-day| hand-logged)? panel)\b/g, 'collected$1')
      .replace(new RegExp('\\breal(?=\\/|[- ]' + NOUNS + '\\b)', 'g'), 'observed')
      .replace(new RegExp('\\bReal(?=\\/|[- ]' + NOUNS + '\\b)', 'g'), 'Observed')
      .replace(/\b(is|are|was|were|be|as) real\b/g, '$1 observed')
      .replace(/\breal\b/g, 'actual')
      .replace(/\bReal(?= [a-z])/g, 'Actual')
      .replace(/\b([Aa]) (observed|actual)\b/g, '$1n $2')
      .replace(/(^|[.!?]\s+)(observed|simulated|actual)\b/g, (m, a, w) => a + cap(w))
      // a snapshot, as a unit of time, is a check: one round of prices and stock
      .replace(/snapshot/g, 'check').replace(/Snapshot/g, 'Check').replace(/SNAPSHOT/g, 'CHECK');
  }
  /* plain:end */
  const pe = s => esc(plain(s));
  const prose = s => pe(s).replace(/\*\*|`/g, '');      // quoted passages keep their markdown marks; drop them
  const ident = s => plain(s).replace(/_/g, ' ');
  /* a citation is shown by a readable name; the exact file is in its title */
  function srcLabel(f) {
    const parts = String(f || '').replace(/\\/g, '/').split(' · '), file = parts[0];
    let m, out;
    if ((m = file.match(/^outputs\/models\/([^/]+)\//))) out = 'saved result · ' + ident(m[1]);
    else if (/^data\/raw/.test(file)) out = 'the observed rows';
    else if ((m = file.match(/^docs\/external\/(.+)\.md$/))) out = 'public source notes · ' + ident(m[1]);
    else if (/(^|\/)CLAUDE\.md$/.test(file)) out = 'project notes';
    else if ((m = file.match(/([^/]+)\.md$/))) out = 'project doc · ' + ident(m[1]);
    else out = plain(file);
    // a raw row key (BASELINE_... | BBSR-007 | MASTER-18104) is named in words; the full path stays in the tooltip
    return [out].concat(parts.slice(1).map(x => (/\b[A-Z]+_\d{4}-\d{2}-\d{2}\s*\|/.test(x) ? (/observed/i.test(x) ? 'one observed row' : 'one row') : plain(x)))).join(' · ');
  }

  const PATHS = {
    bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>', flask: '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4a2 2 0 0 0 1.8-3l-5-9V3"/><path d="M7.5 15h9"/>',
    camera: '<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>', book: '<path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z"/><path d="M5 17a3 3 0 0 1 3-3h11"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    alert: '<path d="M12 4 3 19h18z"/><path d="M12 10v4M12 17v.01"/>', chat: '<path d="M21 12a8 8 0 0 1-11.8 7L4 20l1.2-4.4A8 8 0 1 1 21 12z"/>',
    sliders: '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>', target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
    home: '<path d="M4 11 12 4l8 7v9h-5v-6H9v6H4z"/>', grid: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
    chart: '<path d="M4 20V10M10 20V4M16 20v-8M22 20H2"/>', shield: '<path d="M12 3 5 6v6c0 4.5 3 7.5 7 9 4-1.5 7-4.5 7-9V6z"/><path d="m9 12 2 2 4-4"/>',
    calendar: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/>', route: '<circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="6" r="2.5"/><path d="M8.5 18H15a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h6.5"/>',
    box: '<path d="M4 8 12 4l8 4v8l-8 4-8-4z"/><path d="M4 8l8 4 8-4M12 12v8"/>', leaf: '<path d="M5 19c0-9 5-14 15-14 0 10-5 15-14 15"/><path d="M5 19 14 10"/>',
    cup: '<path d="M6 4h12l-1.5 16h-9z"/><path d="M6.5 9h11"/>', drop: '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>', bag: '<path d="M6 8h12l1 12H5z"/><path d="M9 8a3 3 0 0 1 6 0"/>',
    snow: '<path d="M12 3v18M4.2 7.5l15.6 9M19.8 7.5l-15.6 9"/>', mug: '<path d="M5 9h11v6a4 4 0 0 1-4 4H9a4 4 0 0 1-4-4z"/><path d="M16 11h2a2 2 0 0 1 0 4h-2M8 3v3M12 3v3"/>',
    spray: '<path d="M9 10h6v10H9z"/><path d="M10 10V6h4v4M14 7h3M19 5v.01M20 7.5v.01M19 10v.01"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>', check: '<path d="m5 12 5 5 9-10"/>', moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a7 7 0 1 0 10.5 10.5z"/>',
    lamp: '<path d="M3.5 13.5h17c-.5 3.5-4 6-8.5 6s-8-2.5-8.5-6z"/><path d="M12 11c-1.8-1.6-1.8-3.6 0-6.5 1.8 2.9 1.8 4.9 0 6.5z"/>',
    flame: '<path d="M12 3c2.5 3 5.5 5.5 5.5 10a5.5 5.5 0 0 1-11 0c0-2.2 1-3.8 2.2-5 0 2 .9 3.2 2.1 3.2 0-3-1-5.2 1.2-8.2z"/>',
    bell: '<path d="M6 16v-5a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
    flower: '<circle cx="12" cy="12" r="2.5"/><path d="M12 9.5C10 6 10 4 12 3c2 1 2 3 0 6.5M14.5 12c3.5-2 5.5-2 6.5 0-1 2-3 2-6.5 0M12 14.5c2 3.5 2 5.5 0 6.5-2-1-2-3 0-6.5M9.5 12C6 14 4 14 3 12c1-2 3-2 6.5 0"/>',
    spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
    gift: '<rect x="4" y="9" width="16" height="11" rx="1.5"/><path d="M3 9h18M12 9v11M12 9c-1.5-3.5-6-4-6-1.5 0 1.2 2 1.5 6 1.5 4 0 6-.3 6-1.5 0-2.5-4.5-2-6 1.5z"/>',
    nut: '<path d="M12 3.5c4 0 7 3.8 7 8.5s-3 8.5-7 8.5-7-3.8-7-8.5 3-8.5 7-8.5z"/><path d="M12 6v12"/>',
    cake: '<path d="M4 20h16v-7H4z"/><path d="M4 15.5c2 1.5 4 1.5 6 0s4-1.5 6 0 4 1.5 4 0M12 13V9.5M12 6.5v.01"/>',
    bowl: '<path d="M3 11h18a9 9 0 0 1-18 0z"/><path d="M8 7.5c0-1.5 1-2 1-3.5M12 7.5c0-1.5 1-2 1-3.5M16 7.5c0-1.5 1-2 1-3.5"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.6-3.6"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1-4.5 4.5-6.5 8-6.5s7 2 8 6.5"/>',
    upload: '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
    plus: '<path d="M12 5v14M5 12h14"/>', minus: '<path d="M5 12h14"/>',
    download: '<path d="M12 4v12M7 11l5 5 5-5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
    cart: '<path d="M3 4h2l2.2 10.4a2 2 0 0 0 2 1.6h7.7a2 2 0 0 0 1.9-1.5L20.5 8H6.1"/><circle cx="10" cy="20" r="1.4"/><circle cx="17" cy="20" r="1.4"/>',
    share: '<circle cx="18" cy="5.5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="18.5" r="2.5"/><path d="m8.2 10.8 7.6-4.1M8.2 13.2l7.6 4.1"/>',
    command: '<path d="M9 6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3z"/>',
    x: '<path d="M6 6l12 12M18 6 6 18"/>', play: '<path d="M7 5v14l11-7z"/>',
    eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    bulb: '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2V17h5v-1.1c0-.8.4-1.5 1-2A6 6 0 0 0 12 3z"/>',
    more: '<circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/>',
  };
  const ico = n => `<svg class="ic" viewBox="0 0 24 24" aria-hidden="true">${PATHS[n] || PATHS.box}</svg>`;
  /* the project's data labels, as the site's tags. Observed numbers are marked too: a tag that is missing is not read
     as a meaning, so "Observed" says it out loud (owner, 2026-10-24). No date on it. */
  const CHIPS = {REAL: ['is-obs', 'eye', 'Observed'], SYNTHETIC: ['is-lab', 'flask', 'Lab'], METHOD: ['is-method', 'book', 'Method'],
    EXTERNAL: ['is-source', 'link', 'Public source'], UNVERIFIED: ['is-unverified', 'alert', 'Store unverified'], USER: ['is-user', 'user', 'Added by you']};
  const chip = p => { const c = CHIPS[p] || CHIPS.METHOD; return `<span class="chip ${c[0]}">${ico(c[1])}${c[2]}</span>`; };
  const CAT_ICON = {'Fruits & Vegetables': 'leaf', 'Beverages': 'cup', 'Personal Care': 'drop', 'Snacks & Munchies': 'bag', 'Home & Cleaning': 'spray',
    'Frozen Foods': 'snow', 'Tea, Coffee & More': 'mug'};
  const tipAttr = t => ` tabindex="0" data-tip="${pe(t)}"`;
  const mem = {
    get(k, d) { try { const v = localStorage.getItem('qcmi-' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem('qcmi-' + k, JSON.stringify(v)); } catch (e) { /* storage is optional */ } },
  };
  const tiles = items => `<div class="tiles">${items.map(([v, l]) => `<div class="tile"><span class="v">${v}</span><span class="l">${l}</span></div>`).join('')}</div>`;
  const segs = (id, opts, cur) => `<div class="segs" id="${id}">${opts.map(([v, l]) => `<button type="button" data-v="${esc(v)}" aria-pressed="${String(v) === String(cur)}">${esc(l)}</button>`).join('')}</div>`;
  const select = (id, opts, cur, label) => `<select id="${id}" aria-label="${esc(label)}">${opts.map(o => `<option${o === cur ? ' selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
  const onSeg = (id, fn) => $('#' + id).addEventListener('click', e => { const b = e.target.closest('button'); if (b) fn(b.dataset.v); });
  const ticks = (vals, max, fmt, title) => `<div class="axis"><div></div><div class="ticks">${vals.map(v => `<span style="left:${100 * v / max}%">${fmt(v)}</span>`).join('')}<em>${esc(title)}</em></div><div></div></div>`;
  const pname = i => `<i class="pdot c${i}"></i>${esc(P[i])}`;
  const tabsHtml = (id, opts, cur) => `<div class="tabs" role="tablist" id="${id}">${opts.map(([v, l]) => `<button type="button" role="tab" data-v="${v}" aria-selected="${v === cur}">${esc(l)}</button>`).join('')}</div>`;
  const LAB_NOTE = `${chip('SYNTHETIC')} Run in advance on the simulated 30-day panel. It shows what those fitted dynamics imply, not how the market itself would move, and never demand or revenue.`;

  /* ================================================================== header: pages, theme */
  /* [page, label, icon, mode, under "More"]: seven pages up front, the rest one tap away (a tech lead's review,
     2026-10-24: ten tabs read as a project that could not decide what it is) */
  const NAV = [['home', 'Home', 'home'], ['findings', 'Findings', 'bulb'], ['listings', 'Products', 'grid'], ['simulate', 'Simulate', 'sliders', 1], ['optimize', 'Optimize', 'target', 1], ['analyst', 'Analyst', 'chat', 1],
    ['models', 'Models', 'chart'], ['data', 'Data & trust', 'shield', 0, 1], ['pipeline', 'Pipeline', 'route', 0, 1], ['festive', 'Festive planner', 'lamp', 0, 1], ['plan', 'Collection plan', 'calendar', 0, 1]];
  const navLink = ([p, l, i, m]) => `<a href="#${p}" data-page="${p}"${m ? ' class="mode"' : ''}>${ico(i)}${l}</a>`;
  $('#nav').innerHTML = NAV.filter(n => !n[4]).map(navLink).join('') +
    `<button type="button" class="more-btn" id="more-btn" aria-haspopup="true" aria-expanded="false" aria-controls="more-menu">${ico('more')}More</button>` +
    `<span class="tools"><button type="button" class="pal-btn" id="pal-btn" aria-haspopup="dialog" aria-controls="pal" aria-label="Go anywhere (Ctrl K)">${ico('command')}<kbd>Ctrl K</kbd></button>` +
    `<button type="button" class="share" id="share" aria-label="Share a link to this page">${ico('share')}</button>` +
    `<button type="button" class="theme" id="theme" aria-label="Switch between light and dark">${ico('moon')}</button></span>`;
  const root = document.documentElement;
  const saved = mem.get('theme', null);
  if (saved === 'light' || saved === 'dark') root.setAttribute('data-theme', saved);
  /* the colours cross-fade for a moment when the theme changes, then transitions are off again */
  function toggleTheme() {
    const dark = root.getAttribute('data-theme') ? root.getAttribute('data-theme') === 'dark'
      : (typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches);
    const next = dark ? 'light' : 'dark';
    root.classList.add('theming');
    root.setAttribute('data-theme', next); mem.set('theme', next);
    setTimeout(() => root.classList.remove('theming'), 450);
  }
  $('#theme').addEventListener('click', toggleTheme);
  /* the "More" pages open in a small menu that hangs from the header, outside the nav strip (which scrolls sideways on
     a phone and would clip it) */
  const moreMenu = $('#more-menu'), moreBtn = $('#more-btn');
  if (moreMenu) moreMenu.innerHTML = NAV.filter(n => n[4]).map(([p, l, i]) => `<a href="#${p}" data-page="${p}" role="menuitem">${ico(i)}${l}</a>`).join('');
  function moreClose() { if (moreMenu && !moreMenu.hidden) { moreMenu.hidden = true; moreBtn.setAttribute('aria-expanded', 'false'); } }
  function moreOpen() {
    if (!moreMenu) return;
    const top = $('header.top'), b = moreBtn.getBoundingClientRect ? moreBtn.getBoundingClientRect() : null, t = top && top.getBoundingClientRect ? top.getBoundingClientRect() : null;
    moreMenu.hidden = false; moreBtn.setAttribute('aria-expanded', 'true');
    if (b && t) {
      const w = moreMenu.offsetWidth || 220, vw = window.innerWidth || 1024;
      moreMenu.style.top = (b.bottom - t.top + 6) + 'px';
      moreMenu.style.left = Math.max(8, Math.min(b.left - t.left, vw - w - 8)) + 'px';
    }
    const first = moreMenu.querySelector('a'); if (first && first.focus) first.focus({preventScroll: true});
  }
  if (moreBtn) moreBtn.addEventListener('click', e => { e.stopPropagation(); if (moreMenu.hidden) moreOpen(); else moreClose(); });
  document.addEventListener('click', e => { if (moreMenu && !moreMenu.hidden && !(e.target.closest && e.target.closest('#more-menu'))) moreClose(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && moreMenu && !moreMenu.hidden) { moreClose(); moreBtn.focus(); } });
  window.addEventListener('resize', moreClose, {passive: true});
  const navScroller = $('#nav'); if (navScroller) navScroller.addEventListener('scroll', moreClose, {passive: true});

  /* ================================================================== the analyst: the project's own when served, the page's engine otherwise */
  let engine = null, live = false;
  const thread = [];
  function getEngine() {
    if (!engine) engine = window.QCAnalyst.create(D('analyst'), {whatif: () => D('whatif')});
    return engine;
  }
  /* Where questions go. The server that sent this page answers first (localhost, Wi-Fi, or a public host). A page
     on GitHub Pages has no server of its own: if meta.api names the project's public analyst (site/config.json), it
     asks there. A free host sleeps when idle, so while it wakes up the page answers with its own engine, and it
     switches to the live analyst as soon as the host answers. Products are kept on a server only if it keeps them. */
  let API = '', writable = false;
  const remoteApi = (() => {                       // https, or this machine while trying it out
    const a = String(D('meta').api || '').trim();
    return /^(https:\/\/[^\s"'<>]+|http:\/\/(localhost|127\.0\.0\.1)(:\d+)?(\/[^\s"'<>]*)?)$/.test(a) ? a.replace(/\/?$/, '/') : '';
  })();
  function probe(base, ms) {
    const ctl = typeof AbortController === 'function' ? new AbortController() : null;
    const timer = setTimeout(() => ctl && ctl.abort(), ms);
    return fetch(base + 'api/health', {signal: ctl ? ctl.signal : undefined, cache: 'no-store'})
      .then(r => (r.ok ? r.json() : null)).catch(() => null).finally(() => clearTimeout(timer));
  }
  function goLive(base, j) {
    API = base; live = true; writable = !base && j.writes !== false;
    const m = $('#dock-mode'); if (m) m.textContent = 'live from the project analyst';
  }
  let waking = null;
  function wakeRemote() {                          // one patient probe at a time; a sleeping free host takes up to a minute
    if (!remoteApi || live || waking) return;
    waking = probe(remoteApi, 75000).then(j => { waking = null; if (j && j.ok) goLive(remoteApi, j); });
  }
  let liveReady = Promise.resolve(false);          // resolves once it is known whether a server is there
  if (typeof fetch === 'function' && typeof location !== 'undefined' && /^https?:$/.test(String(location.protocol))) {
    liveReady = probe('', 8000).then(j => {
      if (j && j.ok) {
        goLive('', j);
        if (j.lan && j.lan.urls && j.lan.urls.length) showLan(j.lan);
        return true;
      }
      if (!remoteApi) return false;
      return probe(remoteApi, 5000).then(r => { if (r && r.ok) { goLive(remoteApi, r); return true; } wakeRemote(); return false; });
    }).catch(() => false);
  }
  const serverKeeps = async () => (await liveReady) && writable;   // products go to a server only if it keeps them
  /* started with --lan: this computer is shown how to open ShelfPulse on a phone or tablet (other devices never get this) */
  function showLan(lan) {
    const pill = $('#lan-pill'), pop = $('#lan-pop');
    if (!pill || !pop) return;
    pop.innerHTML = `<div class="lp-head"><b>Open ShelfPulse on a phone or tablet</b><button type="button" class="linkish" id="lan-close">Close</button></div>
      <ol><li>Join the same Wi-Fi as this computer.</li>
        <li>Open ${lan.urls.map(u => `<code>${esc(u)}</code>`).join(' or ')} in Safari, Chrome or any browser.</li>
        <li>Enter the code <span class="lan-code">${esc(lan.code)}</span></li></ol>
      <p class="fine">To keep it like an app: on iPhone or iPad tap Share, then Add to Home Screen; on Android open the menu, then Add to Home screen. A new code is made each time ShelfPulse starts.</p>`;
    pill.hidden = false;
    pill.addEventListener('click', () => { pop.hidden = !pop.hidden; });
    pop.addEventListener('click', e => { if (e.target.closest('#lan-close')) pop.hidden = true; });
  }
  function claimHtml(c) {
    const lab = chip(c.provenance) + (c.store_label ? chip('UNVERIFIED') : '');
    const stage = c.stage ? `stage ${esc(c.stage.replace(/_/g, ' '))} · ` : '';
    const flag = c.verified === false ? `<span class="src flag">not verified: ${pe((c.issues || []).join('; '))}</span>` : '';
    // a raw row key (BASELINE_... | BBSR-007 | MASTER-18104) reads as noise: it is named in words, and kept in the tooltip
    const raw = String(c.source_detail || ''), key = /\b[A-Z]+_\d{4}-\d{2}-\d{2}\s*\|/.test(raw);
    const detail = !raw ? '' : key ? (/observed/i.test(raw) ? 'one observed row' : 'one row') : pe(raw);
    const title = [c.source_file, key ? raw : ''].filter(Boolean).join(' · ');
    return `<li><span class="tags">${lab}</span><span>${prose(c.text)}<span class="src" title="${esc(title)}">${stage}${esc(srcLabel(c.source_file))}${detail ? ' · ' + detail : ''}${c.date ? ' · ' + esc(c.date) : ''}</span>${flag}</span></li>`;
  }
  const NOTES = {
    lab: ['flask', '', 'Part of this answer comes from the Lab: the simulated panel. It shows what the method recovers, not how the market behaves.'],
    source: ['link', '', 'Part of this answer comes from cited public sources. They are context and were not checked against the project data.'],
    store: ['alert', ' warn', 'Part of this answer groups the observed rows by store. The store column cannot be told apart from a random tag, so read it as a property of the file, not of actual stores.'],
  };
  function answerHtml(a) {
    const notes = [a.banner && NOTES.lab, a.external_banner && NOTES.source, a.store_label_banner && NOTES.store].filter(Boolean)
      .map(([i, cls, t]) => `<p class="banner${cls}">${ico(i)}<span>${t}</span></p>`).join('');
    const where = {simulate: 'Open in Simulate', listings: 'Open in Products', festive: 'See it in the Festive planner'};
    const link = a.link ? `<a class="btn ghost" href="#${a.link.page}" data-link='${esc(JSON.stringify(a.link))}'>${where[a.link.page] || 'Open'} ${ico('arrow')}</a>` : '';
    return `<div class="ans${a.refused ? ' refused' : ''}">
      <p class="mode">${a.refused ? 'cannot be answered from this data' : pe(a.mode || 'evidence')}</p>
      <p class="sum">${prose(a.answer_summary)}</p>${notes}
      ${a.claims && a.claims.length ? `<ul class="claims">${a.claims.map(claimHtml).join('')}</ul>` : ''}
      ${a.caveats && a.caveats.length ? `<ul class="cav">${a.caveats.map(c => `<li>${pe(c)}</li>`).join('')}</ul>` : ''}
      ${a.note ? `<p class="fine" style="margin:16px 0 0">${pe(a.note)}</p>` : ''}
      ${link ? `<div class="acts">${link}</div>` : ''}</div>`;
  }
  const msgHtml = m => `<div class="msg"><p class="q">${esc(m.q)}</p>${m.a ? answerHtml(m.a) : '<div class="ans"><span class="typing"><i></i><i></i><i></i></span></div>'}</div>`;
  /* on the Analyst page the newest answer is on top, under the box it was asked in; the floating chat reads downwards */
  function renderThreads() {
    for (const box of $$('[data-thread]')) {
      const chat = box.dataset.thread === 'chat', items = thread.map(msgHtml);
      box.innerHTML = (chat ? items : items.reverse()).join('') || box.dataset.empty || '';
      const last = chat && thread.length ? box.lastElementChild : null;
      if (last && box.parentElement) box.parentElement.scrollTop = Math.max(0, last.offsetTop - 6);
    }
    const n = $('#fab-count'); if (n) { n.hidden = !thread.length; n.textContent = String(thread.length); }
  }
  function linkFor(q) {
    try {
      const exp = getEngine().parseExperiment(q);
      if (exp && exp[0] === 'simulate_price_move') {
        const a = exp[1], size = clamp(Math.round(a.size), 1, 10);
        return {page: 'simulate', mover: a.mover, group: a.category || 'All', move: a.direction === 'raise' ? size : -size, react: a.react};
      }
    } catch (e) { /* an answer without a link is still an answer */ }
    return null;
  }
  async function fromServer(q) {
    const ctl = typeof AbortController === 'function' ? new AbortController() : null;
    const timer = setTimeout(() => ctl && ctl.abort(), 30000);
    try {
      const r = await fetch(API + 'api/ask', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({q}), signal: ctl ? ctl.signal : undefined});
      if (!r.ok) return null;
      const j = await r.json();
      return j && typeof j.answer_summary === 'string' && Array.isArray(j.claims) ? j : null;
    } catch (e) { return null; } finally { clearTimeout(timer); }
  }
  /* A question is shown in the site's words and asked in the project's: its documents call the observed day and the Lab by
     two label words, so a question that says "observed", "seen", "10 Jul", "simulated" or "the Lab" gets those words added
     for the search. A question the analyst must turn down is passed on untouched. */
  function internal(shown) {
    const alias = (D('meta').ask || {})[shown];
    if (alias) return alias;
    try { if (getEngine().refusal(shown)) return shown; } catch (e) { return shown; }
    let q = shown.replace(/\bthe lab\b/gi, 'the synthetic panel').replace(/\blab (results?|numbers?|findings?)\b/gi, 'synthetic $1');
    if (/\b(observed|snapshot|seen)\b|\b10(th)? jul(y)?\b|\bjul(y)? 10(th)?\b/i.test(q) && !/\breal\b/i.test(q)) q += ' real';
    if (/\bsimulated\b/i.test(q) && !/\bsynthetic\b/i.test(q)) q += ' synthetic';
    return q;
  }

  /* ---- the festive calendar: dates are read in the viewer's own today, so the countdown is always current */
  const dOf = s => { const [y, m, d] = String(s).split('-').map(Number); return new Date(y, m - 1, d); };
  const today0 = () => { const t = new Date(); t.setHours(0, 0, 0, 0); return t; };
  const dayDiff = (a, b) => Math.round((a - b) / 864e5);
  const daysTo = s => dayDiff(dOf(s), today0());
  const shift = (s, n) => { const d = dOf(s); d.setDate(d.getDate() + n); return d; };
  const fmtD = (d, o) => d.toLocaleDateString('en-IN', Object.assign({day: 'numeric', month: 'short'}, d.getFullYear() !== today0().getFullYear() ? {year: 'numeric'} : {}, o || {}));
  /* festivals not yet over, soonest first; `days` keeps only those starting within that many days (the calendar runs
     years ahead, computed by src/seasonal/almanac.py, so the page always has the next ones without a rebuild) */
  const upcoming = days => D('festive').festivals.filter(f => daysTo(f.end) >= 0 && (days == null || daysTo(f.start) <= days));
  const firstOfEach = list => list.filter((f, i) => list.findIndex(g => g.name === f.name) === i);   // the next Diwali, not every one
  /* where a festival stands today, given how many days ahead the shelf must be ready */
  function festState(f, lead) {
    const s = daysTo(f.start), by = shift(f.start, -lead), left = dayDiff(by, today0());
    if (s <= 0) return {s, by, left, tag: 'on now', cls: 'deal'};
    if (left <= 0) return {s, by, left, tag: 'stock up now', cls: 'bad'};
    return {s, by, left, tag: `stock up by ${fmtD(by)}`, cls: ''};
  }
  const wordRx = w => new RegExp('(^|[^a-z])' + w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(s|es)?($|[^a-z])');
  /* which product groups and which festivals a typed text names */
  function festMatch(text) {
    const q = String(text || '').toLowerCase(), F = D('festive');
    const groups = Object.keys(F.groups).filter(k => F.groups[k].words.some(w => wordRx(w).test(q)));
    const fests = upcoming().filter(f => (f.aliases || []).some(w => wordRx(w).test(q))).map(f => f.key);
    return {groups, fests};
  }
  function festiveLink(text) {
    try { const r = festMatch(text); return r.groups.length || r.fests.length ? {page: 'festive', q: String(text)} : null; } catch (e) { return null; }
  }

  async function ask(shown) {
    shown = String(shown || '').trim();
    if (!shown) return;
    const q = internal(shown), m = {q: shown, a: null};
    thread.push(m);
    renderThreads();
    if (!live) wakeRemote();
    let a = live ? await fromServer(q) : null;
    if (a) a.mode = 'project analyst, live';
    else {
      try {
        a = getEngine().answer(q);
        if (a.mode === 'evidence') a.mode = 'answered in the page';
      } catch (e) {
        a = {answer_summary: 'The analyst could not answer that question.', claims: [], caveats: [], refused: false, mode: 'error', note: String((e && e.message) || e)};
      }
    }
    // a question about a festival or a festive product also gets the planner, which answers WHEN from the calendar;
    // the analyst itself still turns down "what sells most", because the data has no sales
    if (!a.link) a.link = (!a.refused && linkFor(q)) || festiveLink(shown);
    m.a = a;
    renderThreads();
  }
  document.addEventListener('click', e => {
    const sg = e.target.closest('[data-ask]'); if (sg) { ask(sg.dataset.ask); return; }
    const od = e.target.closest('[data-open-dock]'); if (od) { openDock(); return; }
    const pr = e.target.closest('[data-product]'); if (pr) mem.set('listing', pr.dataset.product);
    if (e.target.closest('[data-add-product]')) mem.set('openAdd', 1);
    const l = e.target.closest('[data-link]');
    if (l) {
      try {
        const k = JSON.parse(l.dataset.link);
        if (k.page === 'simulate') mem.set('sim', {tab: 'move', mover: P.indexOf(k.mover), group: k.group, move: k.move, react: k.react});
        if (k.page === 'listings' && k.product) mem.set('listing', k.product);
        if (k.page === 'festive') mem.set('festive', Object.assign(mem.get('festive', {}), {q: String(k.q || '')}));
      } catch (err) { /* the link still navigates */ }
      closeDock();
    }
  });
  const dock = $('#dock'), fab = $('#fab');
  function openDock() { dock.hidden = false; fab.hidden = true; renderThreads(); $('#dock-input').focus(); }
  function closeDock() { dock.hidden = true; fab.hidden = false; }
  fab.addEventListener('click', openDock);
  $('#dock-close').addEventListener('click', closeDock);
  $('#dock-open').addEventListener('click', closeDock);
  $('#dock-form').addEventListener('submit', e => { e.preventDefault(); const i = $('#dock-input'); ask(i.value); i.value = ''; });
  $('#top-search').addEventListener('submit', e => { e.preventDefault(); hideDrop(); const i = $('#top-q'); if (String(i.value || '').trim()) { openDock(); ask(i.value); i.value = ''; } });

  /* ---- live suggestions under the header search: products, your products, festivals, festive items; then the analyst */
  let dropItems = [], dropSel = -1;
  const goTo = page => { if (location.hash === '#' + page) route(false); else location.hash = '#' + page; };
  function searchIndex() {
    const out = [], seen = new Set(), add = it => { const k = it.kind + '|' + it.name.toLowerCase(); if (!seen.has(k)) { seen.add(k); out.push(it); } };
    for (const c of D('explorer').chains) add({kind: 'listing', name: c.name, cat: c.category, pack: c.pack, meta: `Followed listing · ${rs(c.dec.price)} on Blinkit`, go: () => { mem.set('listing', c.name); goTo('listings'); }});
    for (const p of userCache) add({kind: 'yours', name: p.name, cat: p.category, pack: p.pack, meta: 'Your product', go: () => goTo('listings')});
    for (const f of firstOfEach(upcoming())) add({kind: 'festival', name: f.name, meta: `${/\b(Day|Eve)\b/.test(f.name) ? 'Special day' : 'Festival'} ·${fmtD(dOf(f.day), {weekday: 'short'})}`, go: () => { mem.set('festive', Object.assign(mem.get('festive', {}), {fest: f.key})); goTo('festive'); }});
    for (const g of Object.values(D('festive').groups)) for (const e of g.examples) add({kind: 'item', name: e.name, cat: e.category, pack: e.pack, meta: `${g.label} · listed on Blinkit`, go: () => { mem.set('festive', Object.assign(mem.get('festive', {}), {q: e.name})); goTo('festive'); }});
    return out;
  }
  function hideDrop() { const d = $('#top-drop'); if (d) d.hidden = true; dropSel = -1; }
  function showDrop() {
    const d = $('#top-drop'), q = String($('#top-q').value || '').trim();
    if (!d) return;
    if (q.length < 2) { hideDrop(); return; }
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    dropItems = searchIndex().filter(it => words.every(w => it.name.toLowerCase().includes(w))).slice(0, 6);
    dropSel = -1;
    const icon = it => it.kind === 'festival' ? `<span class="dr-ic">${ico('lamp')}</span>` : thumb(it.name, it.cat, it.pack);
    d.innerHTML = dropItems.map((it, i) => `<button type="button" class="dr-it" role="option" data-di="${i}">${icon(it)}<span><b>${esc(it.name)}</b><i>${esc(it.meta)}</i></span></button>`).join('') +
      `<button type="button" class="dr-it ask" role="option" data-di="ask"><span class="dr-ic">${ico('chat')}</span><span><b>Ask the analyst</b><i>${esc(q)}</i></span></button>`;
    d.hidden = false;
  }
  function pickDrop(i) {
    const q = String($('#top-q').value || '').trim();
    hideDrop();
    if (i === 'ask' || !dropItems[i]) { if (q) { openDock(); ask(q); } } else dropItems[i].go();
    $('#top-q').value = '';
  }
  $('#top-q').addEventListener('input', showDrop);
  $('#top-q').addEventListener('focus', showDrop);
  $('#top-q').addEventListener('blur', () => setTimeout(hideDrop, 150));
  $('#top-q').addEventListener('keydown', e => {
    const d = $('#top-drop'); if (!d || d.hidden) return;
    const opts = $$('#top-drop .dr-it');
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      dropSel = (dropSel + (e.key === 'ArrowDown' ? 1 : -1) + opts.length + 1) % (opts.length + 1) - 1;
      opts.forEach((o, k) => o.setAttribute('aria-selected', String(k === dropSel)));
    } else if (e.key === 'Enter' && dropSel >= 0) {
      e.preventDefault(); const o = opts[dropSel]; pickDrop(o && o.dataset.di === 'ask' ? 'ask' : +(o ? o.dataset.di : -1));
    } else if (e.key === 'Escape') hideDrop();
  });
  $('#top-drop').addEventListener('mousedown', e => {
    const b = e.target.closest('[data-di]'); if (!b) return;
    e.preventDefault(); pickDrop(b.dataset.di === 'ask' ? 'ask' : +b.dataset.di);
  });
  liveReady.then(() => userStore.list()).then(l => { userCache = l.slice().reverse(); basketSync(); }).catch(() => {});
  const sugg = n => `<div class="sugg">${D('meta').suggested.slice(0, n).map(q => `<button type="button" data-ask="${esc(q)}">${esc(q)}</button>`).join('')}</div>`;
  $('#dock-body').innerHTML = '<div data-thread="chat"></div>';
  $('#dock-body').firstChild.dataset.empty = `<p class="note" style="margin-top:14px">Ask in plain words. Every answer shows where it came from, and it says no to questions this data cannot answer, like sales or revenue.</p>${sugg(5)}`;
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !dock.hidden) closeDock(); });

  /* ================================================================== tooltip */
  const tip = $('#tip');
  function place(x, y) {
    tip.style.left = clamp(x, 8, innerWidth - tip.offsetWidth - 8) + 'px';
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

  /* ================================================================== shared pieces */
  function lineChart(series, opt) {
    const Wd = 520, Hd = 220, L = 46, R = 100, T = 12, B = 30;
    const sx = x => L + (Wd - L - R) * x / opt.xmax, sy = y => T + (Hd - T - B) * (1 - (y - opt.ymin) / (opt.ymax - opt.ymin));
    const yt = [0, 0.25, 0.5, 0.75, 1].map(f => opt.ymin + f * (opt.ymax - opt.ymin));
    const id = 'vz' + (++vizSeq);
    let s = `<svg viewBox="0 0 ${Wd} ${Hd}" role="img" aria-label="${esc(opt.label)}">` + gradDefs(id, L, Wd - R, T, Hd - B);
    for (const y of yt) s += `<line class="g" x1="${L}" x2="${Wd - R}" y1="${sy(y)}" y2="${sy(y)}"/><text x="${L - 6}" y="${sy(y) + 4}" text-anchor="end">${opt.yfmt(y)}</text>`;
    for (const x of opt.xticks) s += `<text x="${sx(x)}" y="${Hd - 10}" text-anchor="middle">${opt.xfmt(x)}</text>`;
    if (opt.target != null && opt.target >= opt.ymin && opt.target <= opt.ymax) s += `<line class="tg" x1="${L}" x2="${Wd - R}" y1="${sy(opt.target)}" y2="${sy(opt.target)}"/><text x="${L + 6}" y="${sy(opt.target) - 6}">target</text>`;
    for (const se of series) {
      if (se.cls === 'l0') s += `<path class="area" style="fill:url(#${id}-a-own)" d="M${sx(se.pts[0][0]).toFixed(1)},${sy(opt.ymin).toFixed(1)} ${se.pts.map(([x, y]) => `L${sx(x).toFixed(1)},${sy(clamp(y, opt.ymin, opt.ymax)).toFixed(1)}`).join(' ')} L${sx(se.pts[se.pts.length - 1][0]).toFixed(1)},${sy(opt.ymin).toFixed(1)}Z"/>`;
      s += `<polyline class="${se.cls}" points="${se.pts.map(([x, y]) => `${sx(x).toFixed(1)},${sy(clamp(y, opt.ymin, opt.ymax)).toFixed(1)}`).join(' ')}"/>`;
      const last = se.pts[se.pts.length - 1];
      if (se.label) s += `<text x="${sx(last[0]) + 6}" y="${sy(clamp(last[1], opt.ymin, opt.ymax)) + (se.dy || 4)}" style="fill:var(--ink-2)">${esc(se.label)}</text>`;
    }
    for (const [x, y, cls, t] of opt.marks || []) s += `<circle cx="${sx(x)}" cy="${sy(y)}" r="5.5" style="fill:var(--${cls})"${tipAttr(t)}/>`;
    return `<div class="chart">${s}</svg></div>`;
  }
  /* ================================================================== model charts
     One look for every kind: a soft grid, the model in blue, its strongest rival in orange, the rest in grey or aqua,
     each line named at its end, each mark with a tooltip. Drawn as SVG from the numbers the model saved. */
  const vfmt = (f, v) => f === 'pct0' ? pct(v, 0) : f === 'pct1' ? pct(v, 1) : f === 'int' ? int(v) : fix(v, Math.abs(v) >= 10 ? 1 : 2);
  function niceTicks(lo, hi, n) {
    const span = (hi - lo) || 1, raw = span / n, mag = Math.pow(10, Math.floor(Math.log10(raw))), r = raw / mag;
    const step = (r <= 1 ? 1 : r <= 2 ? 2 : r <= 2.5 ? 2.5 : r <= 5 ? 5 : 10) * mag, out = [];
    for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + step * 1e-6; v += step) out.push(+v.toFixed(10));
    return out;
  }
  /* labels at the ends of lines, pushed apart so they never overlap */
  function spread(items, gap, lo, hi) {
    const s = items.slice().sort((a, b) => a.y - b.y);
    for (let i = 1; i < s.length; i++) s[i].y = Math.max(s[i].y, s[i - 1].y + gap);
    const over = s.length ? s[s.length - 1].y - hi : 0;
    if (over > 0) { s[s.length - 1].y -= over; for (let i = s.length - 2; i >= 0; i--) s[i].y = Math.min(s[i].y, s[i + 1].y - gap); }
    for (const it of s) it.y = Math.max(it.y, lo);
    return s;
  }
  const svgWrap = (w, h, label, body) => `<svg class="viz-svg" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(plain(label))}">${body}</svg>`;
  /* gradients: every chart gets its own set (ids are unique per chart), coloured from the theme's tokens */
  let vizSeq = 0;
  const VCOL = {own: 'var(--blue)', alt: 'var(--orange)', c3: 'var(--p2)', base: 'var(--axis)'};
  const stop = (o, col, a) => `<stop offset="${o}" style="stop-color:${col};stop-opacity:${a}"/>`;
  function gradDefs(id, x1, x2, y1, y2) {
    let g = '';
    for (const [k, col] of Object.entries(VCOL)) {
      g += `<linearGradient id="${id}-a-${k}" x1="0" y1="${y1}" x2="0" y2="${y2}" gradientUnits="userSpaceOnUse">${stop(0, col, k === 'own' ? 0.45 : 0.22)}${stop(1, col, 0)}</linearGradient>`;
      g += `<linearGradient id="${id}-b-${k}" x1="0" y1="0" x2="0" y2="1">${stop(0, col, 1)}${stop(1, col, 0.5)}</linearGradient>`;
      g += `<linearGradient id="${id}-l-${k}" x1="${x1}" y1="0" x2="${x2}" y2="0" gradientUnits="userSpaceOnUse">${stop(0, col, 0.5)}${stop(0.4, col, 1)}${stop(1, col, 1)}</linearGradient>`;
    }
    g += `<linearGradient id="${id}-db" x1="${x1}" y1="0" x2="${x2}" y2="0" gradientUnits="userSpaceOnUse">${stop(0, VCOL.base, 0.5)}${stop(1, VCOL.own, 0.75)}</linearGradient>`;
    return `<defs>${g}</defs>`;
  }
  const legendHtml = items => `<div class="vlegend">${items.map(([t, cls]) => `<span><i class="sw2 ${cls}"></i>${pe(t)}</span>`).join('')}</div>`;
  function yGrid(ticks, Y, x1, x2, fmt) {
    return ticks.map(t => `<line class="g" x1="${x1}" x2="${x2}" y1="${Y(t).toFixed(1)}" y2="${Y(t).toFixed(1)}"/><text class="tk" x="${x1 - 8}" y="${(Y(t) + 4).toFixed(1)}" text-anchor="end">${vfmt(fmt, t)}</text>`).join('');
  }
  function vizLines(c) {
    const W = 560, H = 272, L = 56, R = 128, T = 18, B = 48, cat = c.x.cat;
    const xv = cat || [...new Set(c.series.flatMap(s => s.pts.map(p => p[0])))].sort((a, b) => a - b);
    const xi = v => (cat ? cat.indexOf(v) : v), xmin = cat ? 0 : Math.min(...xv), xmax = cat ? cat.length - 1 : Math.max(...xv);
    const all = c.series.flatMap(s => s.pts.map(p => p[1])).concat((c.refs || []).map(r => r.y));
    const ymin = c.y.min != null ? c.y.min : Math.min(...all), top = c.y.max != null ? c.y.max : Math.max(...all) * 1.12;
    const yt = niceTicks(ymin, top, 4), ymax = Math.max(top, yt[yt.length - 1]);
    const X = v => L + (W - L - R) * (xi(v) - xmin) / ((xmax - xmin) || 1), Y = v => T + (H - T - B) * (1 - (v - ymin) / ((ymax - ymin) || 1));
    const id = 'vz' + (++vizSeq);
    let s = gradDefs(id, L, W - R, T, H - B) + yGrid(yt, Y, L, W - R, c.y.fmt) + xv.map(t => `<text class="tk" x="${X(t).toFixed(1)}" y="${H - B + 20}" text-anchor="middle">${vfmt(c.x.fmt, t)}</text>`).join('');
    s += `<text class="ttl" x="${(L + (W - R)) / 2}" y="${H - 6}" text-anchor="middle">${pe(c.x.title)}</text>`;
    for (const r of c.refs || []) s += `<line class="ref" x1="${L}" x2="${W - R}" y1="${Y(r.y).toFixed(1)}" y2="${Y(r.y).toFixed(1)}"/><text class="rl" x="${L + 6}" y="${(Y(r.y) - 6).toFixed(1)}">${pe(r.label)} ${vfmt(c.y.fmt, r.y)}</text>`;
    const ends = [];
    for (const se of c.series) {
      const p = se.pts.map(([x, y]) => [X(x), Y(y)]), d = p.map(q => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(' L');
      if (se.area) s += `<path class="area ${se.cls}" style="fill:url(#${id}-a-${se.cls})" d="M${p[0][0].toFixed(1)},${Y(ymin).toFixed(1)} L${d} L${p[p.length - 1][0].toFixed(1)},${Y(ymin).toFixed(1)}Z"/>`;
      s += `<path class="ln ${se.cls}${se.dash ? ' dash' : ''}"${se.dash ? '' : ` style="stroke:url(#${id}-l-${se.cls})"`} d="M${d}"/>`;
      ends.push({y: p[p.length - 1][1], text: se.name, cls: se.cls});
    }
    for (const se of c.series) s += se.pts.map(([x, y]) => `<circle class="pt ${se.cls}" cx="${X(x).toFixed(1)}" cy="${Y(y).toFixed(1)}" r="${se.cls === 'own' ? 5 : 3.8}"${tipAttr(`${se.name}: ${vfmt(c.y.fmt, y)} at ${vfmt(c.x.fmt, x)}`)}/>`).join('');
    for (const e of spread(ends, 16, T + 4, H - B)) s += `<text class="el ${e.cls}" x="${W - R + 12}" y="${(e.y + 4).toFixed(1)}">${pe(e.text)}</text>`;
    return svgWrap(W, H, c.title, s);
  }
  function vizColumns(c) {
    const W = 560, H = 272, L = 56, R = 16, T = 30, B = 48, n = c.series.length;
    const vals = c.groups.flatMap(g => g[1].concat(g[2] != null ? [g[2]] : []));
    const top = c.max != null ? c.max : Math.max(...vals) * 1.18, yt = niceTicks(0, top, 4), ymax = Math.max(top, yt[yt.length - 1]);
    const Y = v => T + (H - T - B) * (1 - v / ymax), gw = (W - L - R) / c.groups.length, bw = Math.min(54, (gw - 40) / n), gap = 8;
    const id = 'vz' + (++vizSeq);
    let s = gradDefs(id, L, W - R, T, H - B) + yGrid(yt, Y, L, W - R, c.fmt);
    c.groups.forEach(([label, values, target], gi) => {
      const span = n * bw + (n - 1) * gap, x0 = L + gi * gw + (gw - span) / 2;
      values.forEach((v, i) => {
        const x = x0 + i * (bw + gap), cls = c.series[i][1], h = Math.max(1, Y(0) - Y(v));
        s += `<path class="bar ${cls}" style="fill:url(#${id}-b-${cls})" d="M${x.toFixed(1)},${Y(0).toFixed(1)} V${(Y(v) + 7).toFixed(1)} q0,-7 7,-7 H${(x + bw - 7).toFixed(1)} q7,0 7,7 V${Y(0).toFixed(1)}Z"${h > 8 ? '' : ''}${tipAttr(`${label}, ${c.series[i][0]}: ${vfmt(c.fmt, v)}`)}/>`;
        s += `<text class="vl ${cls}" x="${(x + bw / 2).toFixed(1)}" y="${(Y(v) - 7).toFixed(1)}" text-anchor="middle">${vfmt(c.fmt, v)}</text>`;
      });
      if (target != null) s += `<line class="ref" x1="${(x0 - 10).toFixed(1)}" x2="${(x0 + span + 10).toFixed(1)}" y1="${Y(target).toFixed(1)}" y2="${Y(target).toFixed(1)}"/><text class="rl" x="${(x0 - 10).toFixed(1)}" y="${(Y(target) - 6).toFixed(1)}">promise ${vfmt(c.fmt, target)}</text>`;
      s += `<text class="tk strong" x="${(L + gi * gw + gw / 2).toFixed(1)}" y="${H - B + 22}" text-anchor="middle">${pe(label)}</text>`;
    });
    s += `<line class="axis0" x1="${L}" x2="${W - R}" y1="${Y(0).toFixed(1)}" y2="${Y(0).toFixed(1)}"/>`;
    return svgWrap(W, H, c.title, s) + legendHtml(c.series);
  }
  function vizForest(c) {
    const rowH = 27, W = 560, T = 26, B = 40, L = 258, R = 24, H = T + B + rowH * c.rows.length;
    const d = Math.max(...c.rows.map(r => Math.max(1 - r[2], r[3] - 1)), 0.25) * 1.12, lo = 1 - d, hi = 1 + d;
    const X = v => L + (W - L - R) * (v - lo) / (hi - lo), ticks = niceTicks(lo, hi, 4);
    let s = ticks.map(t => `<line class="g" x1="${X(t).toFixed(1)}" x2="${X(t).toFixed(1)}" y1="${T - 6}" y2="${H - B + 4}"/><text class="tk" x="${X(t).toFixed(1)}" y="${H - B + 20}" text-anchor="middle">${fix(t, 2)}×</text>`).join('');
    s += `<line class="ref" x1="${X(1).toFixed(1)}" x2="${X(1).toFixed(1)}" y1="${T - 12}" y2="${H - B + 4}"/><text class="rl" x="${(X(1) + 6).toFixed(1)}" y="${T - 4}">planted</text>`;
    c.rows.forEach(([label, est, a, b, ok], i) => {
      const y = T + rowH * i + rowH / 2, cls = ok ? 'own' : 'alt', short = label.length > 40 ? label.slice(0, 39) + '…' : label;
      s += `<text class="rlab" x="${L - 12}" y="${(y + 4).toFixed(1)}" text-anchor="end">${pe(short)}</text>`;
      s += `<line class="wh ${cls}" x1="${X(a).toFixed(1)}" x2="${X(b).toFixed(1)}" y1="${y}" y2="${y}"/><circle class="pt ${cls}" cx="${X(est).toFixed(1)}" cy="${y}" r="5"${tipAttr(`${label}: ${fix(est, 3)} × planted (95% interval ${fix(a, 3)} to ${fix(b, 3)})${ok ? '' : ', misses the planted value'}`)}/>`;
    });
    s += `<text class="ttl" x="${((L + W - R) / 2).toFixed(1)}" y="${H - 6}" text-anchor="middle">estimate ÷ planted value</text>`;
    return svgWrap(W, H, c.title, s) + legendHtml([['interval covers the planted value', 'own'], ['interval misses it', 'alt']]);
  }
  function vizScatter(c) {
    const W = 560, H = 290, L = 56, R = 24, T = 16, B = 48;
    const vals = c.points.flatMap(p => [p[2], p[4], p[5]]), lo = Math.floor(Math.min(...vals) * 2) / 2, top = Math.ceil(Math.max(...vals) * 2) / 2;
    const ticks = niceTicks(lo, top, 4), X = v => L + (W - L - R) * (v - lo) / (top - lo), Y = v => T + (H - T - B) * (1 - (v - lo) / (top - lo));
    const cls = Object.fromEntries(c.groups);
    let s = yGrid(ticks, Y, L, W - R, 'num') + ticks.map(t => `<text class="tk" x="${X(t).toFixed(1)}" y="${H - B + 20}" text-anchor="middle">${vfmt('num', t)}</text>`).join('');
    s += `<line class="ref" x1="${X(lo).toFixed(1)}" y1="${Y(lo).toFixed(1)}" x2="${X(top).toFixed(1)}" y2="${Y(top).toFixed(1)}"/>`;
    s += `<text class="ttl" x="${((L + W - R) / 2).toFixed(1)}" y="${H - 6}" text-anchor="middle">${pe(c.x.title)}</text>`;
    s += `<text class="ttl" transform="translate(14 ${((T + H - B) / 2).toFixed(1)}) rotate(-90)" text-anchor="middle">${pe(c.y.title)}</text>`;
    for (const [g, plat, pl, est, a, b, ok] of c.points) {
      const k = cls[g] || 'base';
      s += `<line class="wh ${k}" x1="${X(pl).toFixed(1)}" x2="${X(pl).toFixed(1)}" y1="${Y(a).toFixed(1)}" y2="${Y(b).toFixed(1)}"/>`;
      s += `<circle class="pt ${k}" cx="${X(pl).toFixed(1)}" cy="${Y(est).toFixed(1)}" r="5.5"${tipAttr(`${g} restock, ${plat}: planted ${fix(pl, 2)}, recovered ${fix(est, 2)} (95% interval ${fix(a, 2)} to ${fix(b, 2)})${ok ? '' : ', misses'}`)}/>`;
    }
    return svgWrap(W, H, c.title, s) + legendHtml(c.groups.map(([g, k]) => [`${g} restock group`, k]).concat([['perfect recovery', 'dash']]));
  }
  function vizDumbbell(c) {
    const W = 560, rowH = 52, T = 20, B = 40, L = 150, R = 36, H = T + B + rowH * c.rows.length;
    const top = Math.max(...c.rows.flatMap(r => r[1])) * 1.15, ticks = niceTicks(0, top, 4), xmax = Math.max(top, ticks[ticks.length - 1]);
    const X = v => L + (W - L - R) * v / xmax, id = 'vz' + (++vizSeq);
    let s = gradDefs(id, L, W - R, T, H - B) + ticks.map(t => `<line class="g" x1="${X(t).toFixed(1)}" x2="${X(t).toFixed(1)}" y1="${T - 6}" y2="${H - B + 4}"/><text class="tk" x="${X(t).toFixed(1)}" y="${H - B + 20}" text-anchor="middle">${fix(t, 2)}</text>`).join('');
    c.rows.forEach(([label, v], i) => {
      const y = T + rowH * i + rowH / 2;
      s += `<text class="rlab strong" x="${L - 14}" y="${y + 4}" text-anchor="end">${pe(label)}</text>`;
      s += `<line class="db" style="stroke:url(#${id}-db)" x1="${X(Math.min(...v)).toFixed(1)}" x2="${X(Math.max(...v)).toFixed(1)}" y1="${y}" y2="${y}"/>`;
      v.forEach((x, j) => { s += `<circle class="pt ${c.marks[j][1]}" cx="${X(x).toFixed(1)}" cy="${y}" r="${c.marks[j][1] === 'ring' ? 7 : 6}"${tipAttr(`${label}, ${c.marks[j][0]}: ${fix(x, 3)}`)}/>`; });
    });
    s += `<text class="ttl" x="${((L + W - R) / 2).toFixed(1)}" y="${H - 6}" text-anchor="middle">response coefficient</text>`;
    return svgWrap(W, H, c.title, s) + legendHtml(c.marks);
  }
  function vizDonut(c) {
    const total = c.parts.reduce((a, p) => a + p[1], 0), r = 74, C = 2 * Math.PI * r, id = 'vz' + (++vizSeq);
    let off = 0, arcs = '';
    const defs = `<defs>${Object.entries(VCOL).map(([k, col]) => `<linearGradient id="${id}-d-${k}" x1="20" y1="20" x2="200" y2="200" gradientUnits="userSpaceOnUse">${stop(0, col, 1)}${stop(1, col, 0.55)}</linearGradient>`).join('')}</defs>`;
    for (const [label, v, cls] of c.parts) {
      const len = C * v / total;
      arcs += `<circle class="arc ${cls}" style="stroke:url(#${id}-d-${cls})" cx="110" cy="110" r="${r}" stroke-dasharray="${Math.max(0, len - 2).toFixed(2)} ${(C - Math.max(0, len - 2)).toFixed(2)}" stroke-dashoffset="${(-off).toFixed(2)}"${tipAttr(`${label}: ${int(v)} (${pct(v / total, 1)})`)}/>`;
      off += len;
    }
    const svg = `<svg class="viz-svg donut" viewBox="0 0 220 220" role="img" aria-label="${esc(plain(c.title))}">${defs}<g transform="rotate(-90 110 110)">${arcs}</g>
      <text class="dn-v" x="110" y="108" text-anchor="middle">${int(total)}</text><text class="dn-l" x="110" y="128" text-anchor="middle">pairs</text></svg>`;
    return `<div class="donut-wrap">${svg}<ul class="dn-list">${c.parts.map(([label, v, cls]) => `<li><i class="sw2 ${cls}"></i><span>${pe(label)}</span><b>${int(v)}</b><em>${pct(v / total, 1)}</em></li>`).join('')}</ul></div>`;
  }
  function chartFor(c) {
    if (!c) return '';
    const kinds = {lines: vizLines, columns: vizColumns, forest: vizForest, scatter: vizScatter, dumbbell: vizDumbbell, donut: vizDonut};
    try { return kinds[c.type] ? kinds[c.type](c) : ''; } catch (e) { return `<p class="note">This chart could not be drawn: ${esc(String((e && e.message) || e))}</p>`; }
  }

  /* ================================================================== product pictures
     A drawn packshot for every product: the pack's shape follows its name and category, its colour the category, and
     the label carries its brand and pack size. They are illustrations made from the product's own details, not
     photos. A product you add can carry a real photo instead. */
  const CAT_HUE = {'Beverages': 22, 'Personal Care': 188, 'Fruits & Vegetables': 104, 'Snacks & Munchies': 4, 'Frozen Foods': 204,
    'Other / General Merchandise': 266, 'Tea, Coffee & More': 28, 'Home & Cleaning': 172, 'Sweets & Chocolates': 334, 'Dairy, Bread & Eggs': 46,
    'Bakery & Biscuits': 36, 'Baby Care': 292, 'Staples & Grains': 40, 'Masala, Oil & More': 14, 'Instant & Ready to Eat': 10, 'Pet Supplies': 150,
    'Breakfast & Instant Food': 50, 'Dry Fruits & Nuts': 30, 'Health & Wellness': 140, 'Sauces, Spreads & Pickles': 0, 'Kitchen & Dining': 220,
    'Electronics & Stationery': 230, 'Fashion & Lifestyle': 310};
  const hashOf = s => { let h = 2166136261; for (const ch of String(s)) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; };
  const hueOf = (name, cat) => ((CAT_HUE[cat] != null ? CAT_HUE[cat] : hashOf(cat || name) % 360) + (hashOf(name) % 26) - 13 + 360) % 360;
  function packKind(name, cat) {
    const n = String(name || '').toLowerCase();
    if (/spray|deo\b|deodorant|freshener|mist|aerosol|perfume/.test(n)) return 'can';
    if (/candle|\bjar\b|\bjam\b|honey|ghee|spread|pickle|achar|diya|peanut butter/.test(n)) return 'jar';
    if (/curd|dahi|yog(h)?urt|\btub\b|paneer|butter|ice cream|shrikhand/.test(n)) return 'tub';
    if (/frozen|\bcorn\b|peas|nugget|fries/.test(n) || cat === 'Frozen Foods') return 'frozen';
    if (/drink|juice|water|soda|cola|shake|lassi|beverage|syrup|squash|\bltr\b|\bml\b|bottle|\boil\b/.test(n) || cat === 'Beverages') return 'bottle';
    if (/premix|sachet|gift|pack of|\bbox\b|tea bags|biscuit|cookie|cereal|flakes|\bpcs\b|soap|tissue/.test(n)) return 'box';
    if (cat === 'Fruits & Vegetables' && !/mix|chaat|dried|powder/.test(n)) return 'fresh';
    if (/chips|namkeen|bhujia|\bmix\b|sugar|atta|rice|\bdal\b|nuts|cashew|almond|pouch|makhana|seeds|kg\b|\bg\b/.test(n) || /Snacks|Staples|Fruits & Vegetables|Dry Fruits/.test(cat || '')) return 'pouch';
    return 'box';
  }
  function brandOf(name) {
    const w = String(name || '').replace(/[*()[\]]/g, ' ').split(/\s+/).filter(Boolean);
    let out = '';
    for (const x of w) { if ((out + ' ' + x).trim().length > 11) break; out = (out + ' ' + x).trim(); }
    return (out || w[0] || '').slice(0, 12);
  }
  let psSeq = 0;
  function packshot(name, cat, pack) {
    const id = 'ps' + (++psSeq), kind = packKind(name, cat), brand = brandOf(name), pk = String(pack || '').slice(0, 12);
    const label = (y, w) => {
      const fs = Math.min(13, (w - 10) / (0.62 * Math.max(brand.length, 1)));
      return `<text class="t1" x="120" y="${y}" text-anchor="middle" style="font-size:${fs.toFixed(1)}px">${esc(brand)}</text>` +
        (pk ? `<text class="t2" x="120" y="${y + 14}" text-anchor="middle">${esc(pk)}</text>` : '');
    };
    const body = `url(#${id})`;
    const shapes = {
      bottle: `<rect class="d" x="106" y="14" width="28" height="15" rx="4"/><path style="fill:${body}" d="M110 28h20v10c0 6 20 10 20 24v68a10 10 0 0 1-10 10H100a10 10 0 0 1-10-10V62c0-14 20-18 20-24z"/><rect class="l" x="90" y="78" width="60" height="42"/><rect class="gl" x="97" y="54" width="7" height="76" rx="3.5"/>${label(97, 60)}`,
      can: `<rect class="d" x="112" y="12" width="16" height="12" rx="3"/><rect class="d" x="104" y="22" width="32" height="11" rx="4"/><rect style="fill:${body}" x="92" y="32" width="56" height="108" rx="13"/><rect class="l" x="92" y="70" width="56" height="46"/><rect class="gl" x="99" y="40" width="7" height="92" rx="3.5"/>${label(91, 56)}`,
      jar: `<rect class="d" x="74" y="40" width="92" height="22" rx="8"/><rect style="fill:${body}" x="78" y="60" width="84" height="82" rx="18"/><rect class="l" x="78" y="80" width="84" height="42"/><rect class="gl" x="86" y="66" width="8" height="68" rx="4"/>${label(99, 84)}`,
      pouch: `<rect class="d" x="72" y="22" width="96" height="13" rx="5"/><path style="fill:${body}" d="M74 33h92c7 36 7 72-6 108H80c-13-36-13-72-6-108z"/><rect class="l" x="84" y="68" width="72" height="46" rx="11"/><rect class="gl" x="83" y="42" width="7" height="92" rx="3.5"/>${label(89, 72)}`,
      frozen: `<rect class="d" x="72" y="22" width="96" height="13" rx="5"/><path style="fill:${body}" d="M74 33h92c7 36 7 72-6 108H80c-13-36-13-72-6-108z"/><path class="fl" d="M120 44v18M112 49l16 8M128 49l-16 8"/><rect class="l" x="84" y="74" width="72" height="42" rx="11"/><rect class="gl" x="83" y="42" width="7" height="92" rx="3.5"/>${label(93, 72)}`,
      box: `<path class="d" d="M148 42l20-12v98l-20 12z"/><path class="tp" d="M78 42l20-12h70l-20 12z"/><rect style="fill:${body}" x="78" y="42" width="70" height="98" rx="4"/><rect class="l" x="78" y="72" width="70" height="42"/><rect class="gl" x="84" y="48" width="6" height="86" rx="3"/>${label(91, 70)}`,
      tub: `<path style="fill:${body}" d="M68 62h104l-11 78H79z"/><ellipse class="d" cx="120" cy="60" rx="53" ry="12"/><rect class="l" x="79" y="84" width="82" height="36"/>${label(99, 82)}`,
      fresh: `<path class="d" d="M106 48c4-12 14-18 26-18-2 12-12 18-26 18z"/><circle style="fill:${body}" cx="104" cy="92" r="34"/><circle class="b2" cx="142" cy="100" r="28"/><rect class="gl" x="86" y="70" width="8" height="30" rx="4"/><path class="tray" d="M62 118h116l-12 24H74z"/><text class="t1" x="120" y="135" text-anchor="middle" style="font-size:${Math.min(12, 92 / (0.62 * Math.max(brand.length, 1))).toFixed(1)}px">${esc(brand)}</text>`,
    };
    return `<svg class="ps-art" viewBox="0 0 240 160" role="img" aria-label="Illustration of ${esc(name)}"><defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1">` +
      `<stop offset="0" style="stop-color:hsl(var(--h) 72% 64%)"/><stop offset="1" style="stop-color:hsl(var(--h) 60% 44%)"/></linearGradient></defs>` +
      `<ellipse class="sh" cx="120" cy="147" rx="60" ry="7"/>${shapes[kind] || shapes.box}</svg>`;
  }
  /* a photo over the drawn packshot, which shows again if the photo cannot load (scripts/fetch_product_photos.py).
     Two sorts: the product itself, where Open Food Facts has it under a strict match, or a typical-look photo of the
     product's kind from Wikimedia Commons (ph.kind), which fills the tile and is labelled "Typical look" so it is never
     taken for this product's pack. The tooltip says what the photo shows and whose it is. */
  const photoOf = (name, pack) => { try { return (D('photos') || {})[`${name}|${pack || ''}`] || null; } catch (e) { return null; } };
  /* a photo shows once it has loaded and is removed if it fails, so the drawing under it is never covered by a blank */
  const photoTag = (src, kind) => `<img class="prod-photo${kind ? ' kind' : ''}" src="${esc(src)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" onload="this.classList.add('on')" onerror="this.remove()">`;
  const photoTip = ph => ph.kind
    ? `Typical look: ${ph.shows}, not this product's own pack. Photo by ${ph.credit}, ${ph.license}, Wikimedia Commons.`
    : `Photo: ${ph.shows}. ${ph.credit || 'Open Food Facts contributors'}, ${ph.license}.`;
  const photoImg = ph => photoTag(ph.image, ph.kind)
    + (ph.kind ? `<span class="photo-kind">Typical look</span>` : '')
    + `<span class="photo-credit" data-tip="${esc(photoTip(ph))}">${ico('camera')}</span>`;
  const pic = (name, cat, pack, inner) => { const ph = photoOf(name, pack);
    return `<span class="pic ps${ph ? ' has-photo' : ''}" style="--h:${hueOf(name, cat)}">${packshot(name, cat, pack)}${ph ? photoImg(ph) : ''}${inner || ''}</span>`; };
  const thumb = (name, cat, pack) => { const ph = photoOf(name, pack);
    return `<span class="thumb ps${ph ? ' has-photo' : ''}" style="--h:${hueOf(name, cat)}"${ph ? ` data-tip="${esc(photoTip(ph))}"` : ''}>${packshot(name, cat, pack)}${ph ? photoTag(ph.image, ph.kind) : ''}</span>`; };

  /* one listing as a product card: its Blinkit price, the best of the other three, and how fast it arrives */
  function productCard(c, i, pick) {
    const d = c.dec, best = Math.min(...P.slice(1).map(p => d.comp[p]));
    const tag = !d.inStock ? '<span class="pill bad tag">Out of stock</span>' : d.cheapest ? '<span class="pill deal tag">Cheapest of 4</span>' : '';
    const open = pick ? `<button class="pcard" type="button" data-pick="${i}" aria-pressed="${pick.selected === i}">` : `<a class="pcard" href="#listings" data-product="${esc(c.name)}">`;
    return `<div class="pwrap">${open}${pic(c.name, c.category, c.pack, `<span class="pill eta">${ico('bolt')}${d.eta} min</span>${tag}`)}
      <span class="nm">${esc(c.name)}</span><span class="pk">${esc(c.pack)} · ${esc(c.category)}</span>
      <span class="buy"><span class="price">${rs(d.price)}</span><span class="vs">others from ${rs(best)}</span></span>${pick ? '</button>' : '</a>'}${basketBtn('x:' + c.name, c.name)}</div>`;
  }
  /* the round button on a card's picture that puts the product in the basket (or takes it out) */
  function basketBtn(k, name) {
    const on = basket.has(k);
    return `<button type="button" class="bk-add" data-basket="${esc(k)}" aria-pressed="${on}" aria-label="${on ? 'Remove' : 'Add'} ${esc(name)} ${on ? 'from' : 'to'} the basket">${ico(on ? 'check' : 'plus')}</button>`;
  }
  /* four apps, one product: the price board */
  function board(c, head, foot) {
    const d = c.dec, low = Math.min(...P.map(p => d.comp[p]));
    return `<div class="board"><div class="head">${chip('SYNTHETIC')}<span class="fine">${head}</span></div>
      <div class="bd-top">${thumb(c.name, c.category, c.pack)}<div><p class="nm">${esc(c.name)}</p><p class="fine" style="margin:0">${esc(c.pack)} · ${esc(c.category)}</p></div></div>
      ${P.map((p, j) => `<div class="offer"><span>${pname(j)}</span>${d.comp[p] === low ? '<span class="pill deal">cheapest</span>' : '<span></span>'}<span class="price">${rs(d.comp[p])}</span></div>`).join('')}
      ${foot}</div>`;
  }
  const receipt = (title, lines, total) => `<div class="receipt"><h3>${esc(title)}</h3>${lines.map(([a, b]) => `<div class="ln"><span>${a}</span><span>${b}</span></div>`).join('')}<div class="ln total"><span>${total[0]}</span><span>${total[1]}</span></div></div>`;

  /* ================================================================== pages */
  const PAGES = {};

  /* what the observed day itself showed: four findings from the hand-collected Blinkit rows, none of them simulated.
     Home leads with them and the Findings page tells each in full (a tech lead's review, 2026-10-24: the striking
     numbers had been the Lab's, which only give back what the simulator was built with) */
  function obsFindings() {
    const F = D('findings'), S = D('reality').store, d = F.defect, ex = d.example;
    const unit = (/([a-z]+)\s*$/i.exec(ex.pack) || [])[1] || 'unit', qty = parseFloat(ex.pack) || 0;
    const sig = S.tests.filter(t => t.p < 0.05 / S.tests.length).length;
    const pw = (S.power || []).find(p => Math.abs(p.planted_eta_shift_minutes - 0.2) < 1e-9);
    return [
      {k: 'defect', big: `${Math.round(d.p_at_100 * 100)} / 100`, cap: 'top flags are one data defect',
        t: 'The anomaly detector found a data defect on its own',
        s: `${Math.round(d.p_at_100 * 100)} of its 100 most unusual listings share one known defect: a pack size stored as 1. ${ex.name} (${ex.pack}, ${rs(ex.price)}) then reads as ${rs(ex.unit_price)} per ${unit}${qty ? ` instead of ${rs(ex.price / qty)}` : ''}${ex.times ? `, ${int(ex.times)} times its category's median` : ''}. ${int(d.rows)} observed rows carry it; a random pick would land on one ${pct(d.base, 1)} of the time.`,
        why: 'Every "cheapest per kg" comparison silently breaks on these rows. A check like this belongs where a catalog is loaded, before anything compares prices.', go: 'models', more: 'The detector, on Models'},
      {k: 'stock', big: `${fix(S.stock.lift, 1)}×`, cap: 'stock-outs cluster by product',
        t: 'Stock-outs come in clusters',
        s: `When one record of a product is out of stock, another record of the same product is out ${pct(S.stock.cond)} of the time, against ${pct(S.stock.rate)} for any record. Shuffling stock within each category gives ${pct(S.stock.cat)}, so the category is not the reason.`,
        why: 'Availability behaves like an event of the product, not of one listing. Whether those records are different stores or different moments, the source cannot say: that is the first thing to log next.', go: 'data', more: 'The numbers, on Data & trust'},
      {k: 'web', big: String(F.web.n), cap: 'prices were looked up, not seen',
        t: 'Prices labelled observed were looked up on the web',
        s: `The source workbook marks ${F.web.n} prices as web-researched: ${F.web.blinkit} from Blinkit's own pages and ${F.web.other} from other sites, among them ${F.web.sites.slice(0, 3).join(', ')}. The raw file had labelled every one of them observed.`,
        why: 'Provenance has to live on each value, not on the file. These are listed and left out of every statement about Blinkit prices.', go: 'data', more: 'The audit, on Data & trust'},
      {k: 'store', big: `${sig} / ${S.tests.length}`, cap: 'tests find any store effect',
        t: 'The store column carries no detectable information',
        s: `${S.tests.length} permutation tests, ${int(S.permutations)} shuffles each: ${sig ? sig : 'none'} departs from a store tag drawn at random. Records of one product share a store in ${pct(S.pair.obs)} of pairs; a random tag gives ${pct(S.pair.null)}.${pw ? ` The same test spots a 0.2-minute delivery shift planted in one small store ${pct(pw.detected_share_at_5pct, 0)} of the time, so this is not a lack of power.` : ''}`,
        why: 'Any store-level conclusion from this column would be a conclusion about noise. Test a key before you group by it.', go: 'data', more: 'Ten tests, on Data & trust'},
    ];
  }

  PAGES.home = v => {
    const M = D('meta'), W = D('whatif'), O = D('optimize'), E = D('analystEval');
    const obs = M.mix.reduce((s, m) => s + m.real, 0), sim = M.mix.reduce((s, m) => s + m.synthetic, 0);
    const a = W.cells['Blinkit|All|-3|strategic'], b = W.cells['Blinkit|All|-3|static'], oc = O.byCategory[0];
    const ev = E.browser ? E.browser.summary : null;
    const refN = ev ? ev.tuning.must_refuse + ev.holdout.must_refuse : null;
    const passN = ev ? ev.tuning.passed + ev.holdout.passed : E.python.tuning_set.passed + E.python.holdout_set.passed;
    const allN = ev ? ev.tuning.questions + ev.holdout.questions : E.python.tuning_set.questions + E.python.holdout_set.questions;
    const FX = obsFindings();
    const stops = [
      ['Collect', `${int(obs)} Blinkit listings`, 'collected by hand', 'data', false],
      ['Validate', M.contracts ? `${M.contracts.passed} of ${M.contracts.total} data contracts hold` : 'files hash-checked', `${M.run.passed} of ${M.run.tests} tests pass`, 'pipeline', false],
      ['Match', 'same product or not', 'accuracy waits on labels', 'models', true], ['Features', '109 columns', 'none may see the future', 'data', false],
      ['Predict', 'nine forecasting models', 'each against a baseline', 'models', false], ['Simulate', 'what if a price moves', 'checked on the status quo', 'simulate', false],
      ['Optimize', 'smallest move to a target', 'no demand, no profit', 'optimize', false], ['Analyst', 'answers with sources', `${passN} of ${allN} test questions`, 'analyst', false]];
    const days = Array.from({length: 31}, (_, i) => `<i class="${i ? 'sim' : 'obs'}"></i>`).join('');
    v.innerHTML = `
      <div class="hero">
        <div>
          <p class="eyebrow">${ico('bolt')}Price and stock intelligence for quick commerce</p>
          <h1>One day of Blinkit, collected by hand. Here is what it <mark>revealed</mark>.</h1>
          <p class="lede">Quick-commerce apps publish no data, so ${int(obs)} Blinkit listings in Bhubaneswar were logged by hand. The data itself turned up four things a platform team would want to know. One day cannot show how prices move, so a simulated 30-day market, the Lab, tests the forecasting and pricing engine that is ready for a longer record.</p>
          <div class="cta"><a class="btn pop" href="#findings">${ico('bulb')}See the findings</a><button class="btn ghost tour-btn" type="button" data-tour>${ico('play')}Take the tour</button><a class="btn ghost" href="#simulate">${ico('sliders')}Try a price move</a></div>
        </div>
        <a class="fxboard" href="#findings" aria-label="What the observed day revealed: open the findings">
          <div class="fx-head">${chip('REAL')}<b>What the observed day revealed</b></div>
          ${FX.map(f => `<div class="fx-row"><span class="fx-big">${esc(f.big)}</span><span class="fx-t"><b>${esc(f.t)}</b><i>${esc(f.cap)}</i></span></div>`).join('')}
          <span class="fx-go">All four, with the evidence ${ico('arrow')}</span>
        </a>
      </div>
      <div class="days-strip panel">
        <div class="ds-text"><b>1 day observed, 30 simulated</b><span>Every number on this site says which it is: ${chip('REAL')} came from Blinkit, ${chip('SYNTHETIC')} from the simulated market.</span></div>
        <div class="ds-cells" role="img" aria-label="31 days: the first observed by hand, the other 30 simulated">${days}</div>
        <div class="ds-legend"><span><i class="obs"></i>${int(obs)} listings collected by hand</span><span><i class="sim"></i>${int(sim)} simulated rows across 4 apps</span></div>
      </div>
      ${tiles([[int(obs), 'Blinkit listings, collected by hand'], [M.stores, 'stores mapped across 4 apps'], [M.contracts ? `${M.contracts.passed} of ${M.contracts.total}` : '-', 'data contracts hold'], [`${M.run.ok} of ${M.run.steps}`, 'pipeline steps passing']])}
      <h2>The engine, tested in the Lab ${chip('SYNTHETIC')}</h2>
      <p class="sub">What it does once there is more than one day. In the Lab its rules are known, so every answer can be checked against the truth.</p>
      <div class="modes">
        <a class="mode-card" href="#simulate"><span class="ico">${ico('sliders')}</span><span class="k">Simulate</span><p>Move a platform's prices, run a promo or take stock away, and see who ends up cheapest over the next twelve checks.</p>
          <span class="ex">Blinkit cuts 3%: ${sgn(a.d[0][1])} pp of cheapest-of-4 share once rivals react, ${sgn(b.d[0][1])} pp if they did not.</span><span class="go">Open Simulate ${ico('arrow')}</span></a>
        <a class="mode-card" href="#optimize"><span class="ico">${ico('target')}</span><span class="k">Optimize</span><p>Set a target and get the smallest price move that reaches it, with and without competitors responding. It never claims profit.</p>
          <span class="ex">Cheapest on ${pct(O.target, 0)} of ${esc(oc.category)}: a ${fix(oc.strategic, 1)}% cut, or ${fix(oc.static, 1)}% if rivals stayed put.</span><span class="go">Open Optimize ${ico('arrow')}</span></a>
        <a class="mode-card" href="#analyst"><span class="ico">${ico('chat')}</span><span class="k">Analyst</span><p>Ask in plain words. It answers from the project's documents and results, tags every claim with its source, and says no when the data cannot answer.</p>
          <span class="ex">${refN == null ? '' : `Says no to ${refN} of ${refN} questions it must. `}Passes ${passN} of ${allN} test questions.</span><span class="go">Open Analyst ${ico('arrow')}</span></a>
      </div>
      <div id="home-yours"></div>
      <h2>From shelf to answer</h2>
      <p class="sub">The pipeline, tracked like an order. A hollow stop is not finished.</p>
      <div class="tracker">${stops.map(([n, x, y, pg, wait]) => `<a class="stop${wait ? ' wait' : ''}" href="#${pg}"><b>${n}</b><span>${x}</span><i>${y}</i></a>`).join('')}</div>
      <h2>Good to know</h2>
      <div class="panel"><div class="lists">
        <div><h4>It can say</h4><ul><li>What Blinkit listed, at what price and stock status, on the day it was collected</li><li>What that day reveals about the data itself: the four findings above</li><li>That each method recovers what was planted in the Lab ${chip('SYNTHETIC')}</li></ul></div>
        <div><h4>It cannot say</h4><ul><li>Anything about demand, sales, revenue, margin or elasticity: there are no orders in the data</li><li>How the market itself moves over time: only one day was observed</li><li>Which store listed which product: the store column carries no detectable information</li></ul></div>
        <div><h4>What would change that</h4><ul><li>Logging a watchlist twice a day for two weeks, sized on the <a href="#plan">collection plan</a></li><li>People labelling the product pairs the matcher has queued</li><li>The collection record for the store column</li></ul></div>
      </div></div>
      <p class="foot-note"><b>ShelfPulse</b> · built ${esc(M.built)} from saved outputs of the quickcommerce-mi project. Portfolio project by Deepak, B.Tech CSE (Data Science with AI), LPU.</p>`;
    homeYours();
  };

  PAGES.findings = v => {
    const M = D('meta'), FX = obsFindings(), obs = M.mix.reduce((s, m) => s + m.real, 0);
    const det = (D('models').find(m => m.n === '6') || {}).chart;
    v.innerHTML = `<p class="eyebrow">${ico('bulb')}Findings</p><h1 class="page">What the observed day <mark>revealed</mark></h1>
      <p class="lede">Four findings from the ${int(obs)} Blinkit listings collected by hand. No simulation is involved in any of them, and each is rebuilt by the pipeline and tested. They are about the data a platform runs on: how it can be wrong, and what it says about availability.</p>
      <div class="findings">${FX.map((f, i) => `<article class="finding" id="f-${f.k}">
          <div class="fi-num"><span class="fi-i">${i + 1}</span><span class="fi-big">${esc(f.big)}</span><span class="fi-cap">${esc(f.cap)}</span>${chip('REAL')}</div>
          <div class="fi-body"><h3>${esc(f.t)}</h3><p>${esc(f.s)}</p>
            <p class="fi-why"><b>Why it matters</b>${esc(f.why)}</p>
            ${f.k === 'defect' && det ? `<figure class="mviz fi-viz"><figcaption><b>${pe(det.title)}</b><span>${pe(det.note || '')}</span></figcaption>${chartFor(det)}</figure>` : ''}
            ${f.k === 'stock' ? stockBars() : ''}
            <a class="fi-more" href="#${f.go}">${esc(f.more)} ${ico('arrow')}</a></div>
        </article>`).join('')}</div>
      <div class="panel mt"><h3>What one day cannot show</h3><p class="note">How prices respond to each other, how long stock-outs last, how delivery time moves with demand: all of that needs more than one day. The engine for it is built and checked in the Lab, where the rules are known. <a href="#simulate">Try a price move</a> or see <a href="#models">how each model is held to a baseline</a>. The <a href="#plan">collection plan</a> sizes the watchlist that would let it run on Blinkit itself.</p></div>`;
  };
  /* the stock-out clustering as three bars: any record out, another record of the same product out, the same shuffled */
  function stockBars() {
    const S = D('reality').store.stock;
    return `<div class="fi-bars">${[['Any record is out of stock', S.rate], ['Another record of the same product, given one is out', S.cond], ['The same, with stock shuffled within its category', S.cat]]
      .map(([l, val], i) => `<div class="row"><div class="lab">${l}</div><div class="track"><i class="fill${i === 1 ? ' hot' : ' ink'}" style="width:${Math.min(100, 100 * val / 0.6)}%"${tipAttr(`${l}: ${pct(val)}`)}></i></div><div class="num">${pct(val)}</div></div>`).join('')}</div>`;
  }

  PAGES.data = v => {
    const M = D('meta'), S = D('reality').store, max = Math.max(...M.mix.map(m => m.real + m.synthetic));
    const x = z => 100 * (clamp(z, -4, 4) + 4) / 8;
    const f = n => Math.abs(n) >= 100 ? int(n) : Math.abs(n) >= 1 ? fix(n, 1) : Math.abs(n) >= 0.01 ? fix(n, 3) : fix(n, 5);
    v.innerHTML = `
      <p class="eyebrow">${ico('shield')}Data &amp; trust</p>
      <h1 class="page">One observed day, thirty <mark>simulated</mark> ones</h1>
      <p class="lede">These apps have no public data feed. One day of Blinkit was collected by hand: those numbers are tagged Observed. The rest was simulated so the pipeline has something to run on: that is the <b>Lab</b>. A Lab result shows a method works. It is not a market finding, and the site tags it every time.</p>
      <div class="grid2">
        <div class="panel"><h3>Rows by platform</h3><p class="note">Solid was observed. Hatched was simulated.</p>
          <div class="legend"><span><i class="sw solid"></i>Collected on Blinkit</span><span><i class="sw hatch"></i>Lab</span></div>
          ${M.mix.map(m => `<div class="row" style="grid-template-columns:minmax(0,.8fr) minmax(0,2fr) minmax(110px,auto)"><div class="lab">${esc(m.platform)}</div>
            <div class="split" style="margin:0;width:${100 * (m.real + m.synthetic) / max}%">${m.real ? `<i class="seg obs" style="flex:${m.real} 1 0"${tipAttr(`${m.platform}: ${int(m.real)} observed rows`)}></i>` : ''}<i class="seg sim" style="flex:${m.synthetic} 1 0"${tipAttr(`${m.platform}: ${int(m.synthetic)} simulated rows`)}></i></div>
            <div class="num">${m.real ? int(m.real) + ' + ' : ''}${int(m.synthetic)}</div></div>`).join('')}
        </div>
        <div class="panel"><h3>The tags, used everywhere</h3>
          <table class="t"><tbody>
            <tr><td>${chip('REAL')}</td><td>Collected by hand on Blinkit. The only rows that describe the market.</td></tr>
            <tr><td>${chip('SYNTHETIC')}</td><td>Simulated rows, and anything fitted to them. Shows the method, not the market.</td></tr>
            <tr><td>${chip('METHOD')}</td><td>How the project works: rules, definitions, assumptions.</td></tr>
            <tr><td>${chip('EXTERNAL')}</td><td>A cited public source. Context only, never checked against the data.</td></tr>
            <tr><td>${chip('UNVERIFIED')}</td><td>An observed row grouped by store. The store column cannot be told apart from a random tag.</td></tr>
          </tbody></table></div>
      </div>
      <h2>What the audits found</h2>
      <p class="sub">Three checks run on the data itself. Each one is rebuilt by the pipeline and tested.</p>
      <div class="grid3">
        <div class="panel"><h3>The store column is unverified ${chip('REAL')}</h3><p class="note">Records of one product share a store in ${pct(S.pair.obs)} of pairs. A tag unrelated to the product gives ${pct(S.pair.null)}; actual stores would give about 0%. The source file does not record how a product was tied to a store.</p></div>
        <div class="panel"><h3>${M.webPrices} prices were looked up, not seen ${chip('REAL')}</h3><p class="note">The source marks them as web-researched, some from sites other than Blinkit. They are listed, and a filter leaves them out of any statement about Blinkit prices.</p></div>
        <div class="panel"><h3>Doc numbers match saved results</h3><p class="note">${M.ledger.numbers} headline numbers in ${M.ledger.claims} claims are checked against the output each came from. Stale now: ${M.ledger.stale}. Tests passing: ${M.run.passed} of ${M.run.tests}.</p></div>
      </div>
      <h2>Ten tests of the store column ${chip('REAL')}</h2>
      <p class="sub">Each dot is one test on the ${int(S.rows)} observed rows: how far the data sits from ${int(S.permutations)} shuffles of the store tag, in standard deviations. A store effect would put a dot far to the right. None is.</p>
      <div class="panel">
        <div class="legend"><span><i class="sw"></i>the observed day</span><span><i class="sw band"></i>where 95% of shuffles fall</span></div>
        ${S.tests.map(t => `<div class="row"><div class="lab">${pe(t.name)}</div><div class="track"><i class="band" style="left:${x(-1.96)}%;width:${x(1.96) - x(-1.96)}%"></i><i class="mid" style="left:50%"></i>
          <i class="dot" style="left:${x(t.z)}%"${tipAttr(`${t.name}: observed ${f(t.obs)}, shuffled mean ${f(t.null)}, ${sgn(t.z, 2)} sd, p ${fix(t.p, 3)}`)}></i></div><div class="num">p ${fix(t.p, 3)}</div></div>`).join('')}
        ${ticks([0, 2, 4, 6, 8], 8, t => sgn(t - 4, 0), 'standard deviations from the shuffled mean')}
      </div>
      <div class="grid2 mt">
        <div class="panel"><h3>Could the test have seen a store effect?</h3>
          <table class="t"><tbody>${S.power.filter(p => p.planted_eta_shift_minutes >= 0.1 && p.planted_eta_shift_minutes <= 0.2).map(p => `<tr><td>A ${p.planted_eta_shift_minutes}-minute delivery-time shift planted in one small store</td><td class="n">found ${pct(p.detected_share_at_5pct, 0)} of the time</td></tr>`).join('')}
          <tr><td>Share of delivery-time variance between stores, in the Lab ${chip('SYNTHETIC')}</td><td class="n">${fix(S.eta.syn, 2)}</td></tr>
          <tr class="hi"><td>The same on the observed day ${chip('REAL')}</td><td class="n">${fix(S.eta.real, 5)}</td></tr></tbody></table></div>
        <div class="panel"><h3>What the observed day does say ${chip('REAL')}</h3><p class="note">Records of the same product run out together: ${fix(S.stock.lift, 1)} times the base rate. Category explains little of it.</p>
          ${[['Any record is out of stock', S.stock.rate], ['Another record of the same product is out, given one is', S.stock.cond], ['The same, with stock shuffled within category', S.stock.cat]]
            .map(([l, val]) => `<div class="row"><div class="lab">${l}</div><div class="track"><i class="fill ink" style="width:${160 * val}%"${tipAttr(`${l}: ${pct(val)}`)}></i></div><div class="num">${pct(val)}</div></div>`).join('')}</div>
      </div>
      ${photoCredits()}`;
  };
  /* where the product photos come from, each one linked: CC BY-SA asks for credit, and a reader should be able to check */
  function photoCredits() {
    let ph = {};
    try { ph = D('photos') || {}; } catch (e) { ph = {}; }
    const all = Object.values(ph), exact = all.filter(x => !x.kind);
    const kinds = [...new Map(all.filter(x => x.kind).map(x => [x.image, {...x, n: all.filter(y => y.image === x.image).length}])).values()];
    const row = (x, note) => `<li><span class="thumb ps has-photo">${photoTag(x.image, x.kind)}</span><span>${esc(x.shows)}${note}<span class="fine"> · ${esc(x.credit || 'Open Food Facts contributors')}, ${esc(x.license || 'CC BY-SA 3.0')} · <a href="${esc(x.source)}" target="_blank" rel="noopener noreferrer">source</a></span></span></li>`;
    return `<h2>Product photos ${chip('EXTERNAL')}</h2>
      <p class="sub">${exact.length ? `${exact.length} product${exact.length === 1 ? ' shows its own photo' : 's show their own photo'}` : 'No product shows its own photo yet'}, from <a href="https://world.openfoodfacts.org" target="_blank" rel="noopener noreferrer">Open Food Facts</a>, an open database whose photos anyone may reuse with credit (CC BY-SA 3.0). Such a photo is used only when the brand and the product name match ours closely; its caption says exactly what it shows, which can be another pack size of the same product.</p>
      ${exact.length ? `<div class="panel"><ul class="credits">${exact.map(x => row(x, x.same_pack ? '' : ' <span class="pill">another pack size</span>')).join('')}</ul></div>` : ''}
      <p class="sub">${all.length - exact.length} more products show a <b>typical look</b>: a photo of their kind (kaju katli, marigold garlands, sweet corn) from <a href="https://commons.wikimedia.org" target="_blank" rel="noopener noreferrer">Wikimedia Commons</a>, under each photo's own free licence. The photo is labelled "Typical look" and is not the product's own pack. Each one was chosen by eye, with no brand on it; a kind whose free photos all show another brand keeps the drawn picture, as does everything else. Photos from Google Images or from the apps themselves are not used: they belong to the brands and the apps, and copying them is not allowed.</p>
      ${kinds.length ? `<div class="panel"><ul class="credits">${kinds.map(x => row(x, ` <span class="pill">${x.n} product${x.n === 1 ? '' : 's'}</span>`)).join('')}</ul></div>` : ''}`;
  }

  PAGES.models = v => {
    const M = D('models');
    const st = {f: mem.get('mfilter', 'all')};
    if (!['all', 'REAL', 'SYNTHETIC'].includes(st.f)) st.f = 'all';
    /* a model as a wide row: what it answers and whether the data backs it on one side, its chart on the other */
    const row = m => `<article class="mrow">
        <div class="mtext">
          <div class="head"><span class="no">${esc(m.n)}</span><h3>${pe(m.name)}</h3>${chip(m.data)}${m.storeLevel ? chip('UNVERIFIED') : ''}</div>
          <p class="q">${pe(m.q)}</p>
          <p class="res">${pe(m.result)}${m.detail ? ' ' + pe(m.detail) : ''}</p>
          ${/^In the Lab only\.?$/.test(m.supported) ? '' : `<p class="sup"><b>Does the data back it?</b> ${pe(m.supported.replace(/^In the Lab only\.\s*/, ''))}</p>`}
          ${m.next ? `<p class="next">${ico('arrow')}<span>${pe(m.next)}</span></p>` : ''}
        </div>
        ${m.chart ? `<figure class="mviz"><figcaption><b>${pe(m.chart.title)}</b><span>${pe(m.chart.note || '')}</span></figcaption>${chartFor(m.chart)}</figure>` : ''}
      </article>`;
    const seen = M.filter(m => m.data === 'REAL').length, lab = M.length - seen;
    // the models on the observed day come first: they are the ones that say something about Blinkit's data
    const order = M.slice().sort((a, b) => (a.data === 'REAL' ? 0 : 1) - (b.data === 'REAL' ? 0 : 1));
    v.innerHTML = `<p class="eyebrow">${ico('chart')}Models</p><h1 class="page">${M.length} models, each held to a <mark>baseline</mark></h1>
      <p class="lede">${seen} work on the Blinkit day that was collected by hand ${chip('REAL')} and come first. ${lab} run in the Lab ${chip('SYNTHETIC')}, where a good score means the method recovers what was planted in the simulated market; none of those is validated on how Blinkit behaves over time, because only one day was observed. Hover a chart for its numbers.</p>
      <div class="mfilter">${segs('m-filter', [['all', `All ${M.length}`], ['SYNTHETIC', `Lab models · ${lab}`], ['REAL', `Blinkit data · ${seen}`]], st.f)}</div>
      <div class="mrows" id="m-rows"></div>`;
    const draw = () => {
      $('#m-rows').innerHTML = order.filter(m => st.f === 'all' || m.data === st.f).map(row).join('');
      $$('#m-filter button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.v === st.f)));
      mem.set('mfilter', st.f);
    };
    onSeg('m-filter', val => { st.f = ['all', 'REAL', 'SYNTHETIC'].includes(val) ? val : 'all'; draw(); });
    draw();
  };

  /* ---------------------------------------------------------------- simulate */
  /* ---- the plain-language layer of Simulate and Optimize: ask by tapping, answer in one big number and a sentence */
  const per100 = x => Math.round(100 * clamp(+x || 0, 0, 1));
  const optSel = (id, opts, cur, label) => `<select id="${id}" class="inline" aria-label="${esc(label)}">${opts.map(([v, l]) => `<option value="${esc(v)}"${String(v) === String(cur) ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
  /* the easy way in (owner, 2026-10-24: "I can't tell what to do here"): one question at a time, answered by tapping a
     big button; the finer choices wait under "More options" */
  const pickRow = (id, n, q, opts, cur) => `<div class="pick"><p class="pick-q"><span>${n}</span>${q}</p>
    <div class="pick-opts" id="${id}" role="group" aria-label="${esc(q)}">${opts.map(([v, l, c]) => `<button type="button" data-v="${esc(v)}" aria-pressed="${String(v) === String(cur)}">${c != null ? `<i class="pdot c${c}"></i>` : ''}${esc(l)}</button>`).join('')}</div></div>`;
  const pressed = (id, v) => $$(`#${id} button`).forEach(b => b.setAttribute('aria-pressed', String(b.dataset.v === String(v))));
  const whatIs = body => `<div class="whatis"><b>${ico('spark')}What is this?</b><p>${body}</p></div>`;
  const labNote = s => `<p class="lab-note">${chip('SYNTHETIC')}<span>${s}</span></p>`;
  /* out of 100 products, how many each app is the cheapest for: faded today, solid after */
  const cmpBars = (rows, label) => `<div class="cmp" role="img" aria-label="${esc(rows.map(r => `${r.name}: ${r.a} of 100 products, ${r.b} today`).join('; '))}">
    <div class="legend"><span><i class="sw ghost-sw"></i>today</span><span><i class="sw"></i>${esc(label || 'after the change')}</span></div>
    ${rows.map(r => `<div class="cmp-row${r.hi ? ' hi' : ''}"><span class="lab"><i class="pdot c${r.c}"></i>${esc(r.name)}</span>
      <div class="cmp-track"><i class="ghost" style="width:${r.b}%"></i><i class="fill c${r.c}" style="width:${r.a}%"></i></div>
      <span class="num">${r.a === r.b ? r.a : `${r.b} → <b>${r.a}</b>`}</span></div>`).join('')}
    <p class="fine" style="margin:0">Out of every 100 products; a tie counts for every tied app.</p></div>`;
  const GLOSSARY = [
    ['Cheapest app for a product', 'Of the four apps, the one with the lowest price for it. "18 of every 100 products" means it is cheapest on 18 in 100.'],
    ['The other apps follow', 'When one app moves its price, the others move theirs part of the way, as they do in the Lab. "Stay put" means they do not react at all.'],
    ['A check', 'One look at every app\'s prices and stock. The Lab looks twice a day, morning and evening, so twelve checks are six days.'],
    ['pp (percentage points)', 'The plain difference between two percentages: going from 18% to 24% is +6 pp.'],
    ['90% of runs', 'Each answer was simulated many times with different luck. Nine runs in ten land inside this range.'],
    ['Lab', 'The simulated 30-day market the models were fitted on. It shows what those fitted rules imply, not what the market will actually do.'],
  ];
  const glossary = () => `<details class="gloss"><summary>${ico('book')}What do these words mean?</summary><dl>${GLOSSARY.map(([k, d]) => `<dt>${esc(k)}</dt><dd>${esc(d)}</dd>`).join('')}</dl></details>`;
  const plainLine = s => `<p class="plain">${ico('spark')}<span>${s}</span></p>`;

  PAGES.simulate = v => {
    const W = D('whatif'), X = D('explorer');
    const st = Object.assign({tab: 'move', mover: 0, group: 'All', move: -3, react: true, pcat: Object.keys(W.frontier)[0], pcut: 5, li: 0, rung: null}, mem.get('sim', {}));
    if (!W.groups.includes(st.group)) st.group = 'All';
    st.mover = clamp(st.mover | 0, 0, 3); st.move = clamp(Math.round(+st.move) || 0, -10, 10); st.pcut = clamp(st.pcut | 0, 0, 10);
    st.li = st.li | 0; st.react = st.react !== false;
    const save = () => mem.set('sim', st);
    v.innerHTML = `<p class="eyebrow">${ico('sliders')}Mode · Simulate</p><h1 class="page">What if an app changes its <mark>prices</mark>?</h1>
      ${whatIs('For every product, one of the four apps is the cheapest. Pretend one app makes its prices cheaper or dearer, and see for how many products it would then be the cheapest. <b>Tap an app, then tap a change.</b>')}
      ${tabsHtml('sim-tabs', [['move', 'Change prices'], ['promo', 'Sale or lower price?'], ['outage', 'An app runs out'], ['listing', 'One product']], st.tab)}<div id="sim-body"></div>
      ${labNote('Worked out in advance in the Lab, a practice market built from the data. It shows what the fitted rules imply, not what the apps will actually do, and never sales or profit.')}
      ${glossary()}`;
    const body = $('#sim-body');
    const PRESETS = [['Diwali sale: Blinkit cuts 5%', 0, -5, 'All'], ['Price war: Flipkart cuts 10%', 2, -10, 'All'], ['Blinkit raises 3%', 0, 3, 'All'],
      ['Instamart cuts snacks 5%', 1, -5, 'Snacks & Munchies'], ['BigBasket cuts staples 7%', 3, -7, 'Staples & Grains']];
    const draw = {
      move() {
        const CHANGES = [[-10, 'Cut 10%'], [-5, 'Cut 5%'], [-3, 'Cut 3%'], [3, 'Raise 3%'], [5, 'Raise 5%'], [10, 'Raise 10%']];
        body.innerHTML = `<div class="ask-card">
            ${pickRow('s-app', 1, 'Which app changes its prices?', P.map((p, i) => [i, p, i]), st.mover)}
            ${pickRow('s-change', 2, 'What does it do?', CHANGES, st.move)}
            <details class="more-opts"><summary>More options: other sizes, one category, rivals</summary><div class="opt-grid">
              <label>Exact change ${optSel('s-move', Array.from({length: 21}, (_, i) => i - 10).map(x => [x, x === 0 ? 'no change' : `${x < 0 ? 'cut' : 'raise'} ${Math.abs(x)}%`]), st.move, 'Exact change')}</label>
              <label>Which products ${optSel('s-group', W.groups.map(g => [g, g === 'All' ? 'all products' : g]), st.group, 'Which products')}</label>
              <label>Do the other apps react? ${optSel('s-react', [['yes', 'yes, they follow (as in the Lab)'], ['no', 'no, they stay put']], st.react ? 'yes' : 'no', 'Do the others react')}</label>
            </div></details>
            <div class="sugg presets"><span class="fine">Or try:</span>${PRESETS.map((x, i) => `<button type="button" data-preset="${i}">${esc(x[0])}</button>`).join('')}</div>
          </div>
          <div id="s-out"></div>`;
        const out = $('#s-out');
        const render = () => {
          const m = st.mover, mv = st.move;
          const view = st.react ? 'strategic' : 'static', ov = st.react ? 'static' : 'strategic';
          const c = W.cells[`${P[m]}|${st.group}|${mv || -1}|${view}`], o = W.cells[`${P[m]}|${st.group}|${mv || -1}|${ov}`];
          if (!c) { out.innerHTML = '<p class="note">No run was saved for this combination.</p>'; return; }
          const after = mv === 0 ? c.b : c.s, d = mv === 0 ? [0, 0, 0] : c.d[m], od = mv === 0 ? 0 : o.d[m][1];
          const path = mv === 0 ? c.bp : c.mp, lo = Math.min(...c.bp, ...path), hi = Math.max(...c.bp, ...path), pad = Math.max(0.01, (hi - lo) * 0.15);
          const nb = per100(c.b[m]), na = per100(after[m]), other = per100((mv === 0 ? c.b : o.s)[m]), who = esc(P[m]);
          const where = st.group === 'All' ? 'products' : `${esc(st.group)} products`;
          const verb = mv === 0 ? 'keeps its prices' : `${mv < 0 ? 'cuts' : 'raises'} its prices by ${Math.abs(mv)}%`;
          const answer = mv === 0
            ? `Today ${who} is the cheapest app for <b>${nb} of every 100</b> ${where}. Tap a change above to see what moves.`
            : `If ${who} ${verb}, it is the cheapest app for <b>${na} of every 100</b> ${where}, ${na === nb ? 'the same as today' : `${na > nb ? 'up' : 'down'} from ${nb} today`}.`;
          const why = mv === 0 ? '' : st.react
            ? `This assumes the other apps follow part of the way, as they do in the Lab. If they did nothing, it would be ${other} of 100.`
            : `This assumes the other apps do nothing. In the Lab they follow part of the way, which would make it ${other} of 100.`;
          out.innerHTML = `<div class="answer-card">${chip('SYNTHETIC')}
              <div class="big-ans" aria-hidden="true"><span class="from">${nb}</span>${mv === 0 ? '' : `<span class="arrow">→</span><span class="to c${m}">${na}</span>`}<span class="cap">of every 100 ${where},<br>${who} is the cheapest</span></div>
              <p class="answer">${answer}</p>${why ? `<p class="fine" style="margin:0">${why}</p>` : ''}
              ${cmpBars(P.map((p, j) => ({name: p, c: j, b: per100(c.b[j]), a: per100(after[j]), hi: j === m})))}</div>
            <details class="more"><summary>For experts: numbers, uncertainty and the next six days</summary>` + tiles([[`${pct(c.b[m])} → ${pct(after[m])}`, `${esc(P[m])}: share of products where it is the cheapest of four`],
              [`${sgn(d[1])} pp`, `change, 90% of runs between ${sgn(d[0])} and ${sgn(d[2])}`],
              [`${sgn(od)} pp`, st.react ? 'if competitors did not react' : 'if competitors did react'], [int(c.n), 'products on all four platforms']]) +
            `<div class="panel"><h3>${esc(P[m])} over the next twelve checks</h3><p class="note">${m === 0 ? 'When Blinkit moves and rivals react, they close part of the gap from the next check on.' : 'Nobody follows this platform in the fitted dynamics, so both views agree.'}</p>
              <div class="legend"><span><i class="sw dash"></i>no move</span><span><i class="sw line"></i>with the move</span></div>
              ${lineChart([{cls: 'lb', pts: c.bp.map((y, i) => [i + 1, y])}, {cls: 'l0', pts: path.map((y, i) => [i + 1, y])}],
                {xmax: 12.4, xticks: [1, 3, 6, 9, 12], xfmt: t => t, ymin: lo - pad, ymax: hi + pad, yfmt: t => pct(t, 0), label: 'Share by check'})}</div></details>`;
          save();
        };
        const sync = () => { pressed('s-app', st.mover); pressed('s-change', st.move); const e = $('#s-move'); if (e) e.value = String(st.move); };
        onSeg('s-app', val => { st.mover = clamp(+val | 0, 0, 3); sync(); render(); });
        onSeg('s-change', val => { st.move = clamp(Math.round(+val) || 0, -10, 10); sync(); render(); });
        $('#s-move').addEventListener('change', e => { st.move = clamp(Math.round(+e.target.value) || 0, -10, 10); sync(); render(); });
        $('#s-group').addEventListener('change', e => { if (W.groups.includes(e.target.value)) st.group = e.target.value; render(); });
        $('#s-react').addEventListener('change', e => { st.react = e.target.value !== 'no'; render(); });
        body.querySelector('.presets').addEventListener('click', e => {
          const b = e.target.closest('[data-preset]'), x = b && PRESETS[+b.dataset.preset];
          if (!x) return;
          Object.assign(st, {mover: x[1], move: x[2], group: W.groups.includes(x[3]) ? x[3] : 'All', react: true});
          draw.move();
        });
        render();
      },
      promo() {
        const cats = Object.keys(W.frontier);
        if (!cats.includes(st.pcat)) st.pcat = cats[0];
        body.innerHTML = `${plainLine('A <b>sale</b> (a short promo) and a <b>lower everyday price</b> both make Blinkit cheaper. In the Lab a sale also makes products sell out a little sooner. Pick a category and a discount to compare the two.')}<div class="controls"><div class="ctl"><label for="p-cat">Category</label>${select('p-cat', cats, st.pcat, 'Category')}</div>
          <div class="ctl"><label for="p-cut">Blinkit price cut <b id="p-cut-v"></b></label><input type="range" id="p-cut" min="0" max="10" step="1" value="${st.pcut}"></div></div><div id="p-out"></div>`;
        const render = () => {
          const F = W.frontier[st.pcat], k = st.pcut;
          $('#p-cut-v').textContent = k + '%';
          $('#p-out').innerHTML = tiles([[pct(F.acL[k]), 'cheapest and in stock, as a list-price cut'], [pct(F.acP[k]), 'cheapest and in stock, as a promo'],
              [`${sgn(F.oos[k], 2)} pp`, `stock-outs a promo adds (90% of runs ${fix(F.lo[k], 2)} to ${fix(F.hi[k], 2)})`], [`${sgn(F.eta[k], 2)} min`, 'delivery time a promo adds']]) +
            `<div class="grid2"><div class="panel" style="--num:112px"><h3>Same cut, two ways to deliver it</h3><p class="note">A list-price cut changes price position only. A promo deepens the discount, and in the fitted dynamics a deeper discount brings stock-outs sooner. That link is an assumption built into the Lab.</p>
              <div class="legend"><span><i class="sw"></i>list-price cut</span><span><i class="sw orange"></i>promo</span></div>
              ${F.cut.map(c => `<div class="row"><div class="lab">${c}% cut${c === k ? ' <span class="pill deal">selected</span>' : ''}</div><div class="track"><i class="fill" style="width:${200 * F.acL[c]}%;bottom:12px"${tipAttr(`${c}% as a list-price cut: ${pct(F.acL[c])}`)}></i><i class="fill orange" style="width:${200 * F.acP[c]}%;top:12px"${tipAttr(`${c}% as a promo: ${pct(F.acP[c])}`)}></i></div><div class="num">${pct(F.acL[c])} / ${pct(F.acP[c])}</div></div>`).join('')}
              ${ticks([0, 10, 20, 30, 40, 50], 50, t => t + '%', 'Blinkit cheapest and in stock')}</div>
            <div class="panel"><h3>Stock-outs a promo adds</h3><p class="note">Percentage points of Blinkit listings out of stock, with the range that holds 90% of runs. ${F.listings} Blinkit listings in this category.</p>
              ${F.cut.slice(1).map(c => `<div class="row"><div class="lab">${c}% promo</div><div class="track"><i class="whisk" style="left:${50 * F.lo[c]}%;width:${50 * (F.hi[c] - F.lo[c])}%"></i><i class="dot" style="left:${50 * F.oos[c]}%"${tipAttr(`${c}% promo: ${sgn(F.oos[c], 2)} pp, 90% of runs ${fix(F.lo[c], 2)} to ${fix(F.hi[c], 2)}`)}></i><i class="mark" style="left:${50 * W.budget}%"></i></div><div class="num">${sgn(F.oos[c], 2)} pp</div></div>`).join('')}
              ${ticks([0, 0.5, 1, 1.5, 2], 2, t => t, `percentage points; dashed line marks a ${W.budget} pp budget`)}</div></div>`;
          save();
        };
        $('#p-cat').addEventListener('change', e => { if (W.frontier[e.target.value]) st.pcat = e.target.value; render(); });
        $('#p-cut').addEventListener('input', e => { st.pcut = clamp(+e.target.value | 0, 0, 10); render(); });
        render();
      },
      outage() {
        const O = X.outage, top = Math.max(...O.lengths.map(l => Math.abs(l[1])));
        body.innerHTML = `${plainLine('When one app runs out of stock it cannot be the cheapest choice, so the other apps pick up those products. Each row is one app running out; each number is how much another app gains (blue) or the app itself loses (orange).')}<p class="note" style="max-width:76ch">A platform that is out of stock cannot be the cheapest option. Each run takes every listing of one platform out of stock now, for a length drawn from the fitted restock model, and follows ${O.horizon} checks.</p>
          <div class="grid2"><div class="panel"><h3>Who picks up the wins</h3><p class="note">Change in cheapest-and-in-stock share, percentage points. Rows: the platform that runs out. Outlined: its own loss.</p>
            <div class="tbl"><table class="heat"><thead><tr><th class="r">runs out ↓ gains →</th>${P.map(p => `<th>${esc(p.split(' ').pop())}</th>`).join('')}</tr></thead><tbody>
            ${P.map(r => `<tr><th class="r">${esc(r)}</th>${P.map(c => { const d = O.matrix[r][c]; return `<td class="${r === c ? 'self' : ''}" style="cursor:default;background:var(--soft);background:color-mix(in srgb, var(--${d[1] < 0 ? 'orange' : 'blue'}) ${Math.round(clamp(Math.abs(d[1]) * 7, 0, 60))}%, var(--card))"${tipAttr(`${r} out: ${c} ${sgn(d[1], 2)} pp (90% of runs ${sgn(d[0], 2)} to ${sgn(d[2], 2)})`)}>${sgn(d[1], 1)}</td>`; }).join('')}</tr>`).join('')}</tbody></table></div></div>
          <div class="panel"><h3>What waiting costs Blinkit</h3><p class="note">Blinkit's change by how many checks the outage lasts. Back before the next check is a small gain: the listing returns with a fresh in-stock clock.</p>
            ${O.lengths.map(([len, val]) => `<div class="row"><div class="lab">${len === 0 ? 'Back before the next check' : `Out for ${len} check${len > 1 ? 's' : ''}`}</div><div class="track"><i class="mid" style="left:10%"></i><i class="fill ${val < 0 ? 'orange' : ''}" style="left:10%;width:${85 * Math.abs(val) / top}%;border-radius:6px"${tipAttr(`${sgn(val, 2)} pp`)}></i></div><div class="num">${sgn(val, 2)} pp</div></div>`).join('')}</div></div>
          <div class="panel mt"><h3>A Blinkit outage, by category</h3><p class="note">The tag is the restock speed planted in the Lab. Fast-restocking categories lose least.</p>
            ${O.cats.map(c => `<div class="row"><div class="lab">${esc(c.c)} <span class="pill">${esc(c.grp.toLowerCase())}</span></div><div class="track"><i class="fill orange" style="width:${28 * Math.abs(c.v)}%"${tipAttr(`${c.c}: ${sgn(c.v, 2)} pp, ${c.skus} products`)}></i></div><div class="num">${sgn(c.v, 2)} pp</div></div>`).join('')}</div>`;
      },
      listing() {
        const C = X.chains;
        st.li = clamp(st.li, 0, C.length - 1);
        body.innerHTML = `${plainLine('Pick one product and slide through every price it could charge. Each bar shows how often Blinkit would be the cheapest app at that price over the next six days.')}<div class="controls"><div class="ctl"><label for="l-pick">Product</label>${select('l-pick', C.map(c => `${c.name} · ${c.store}`), `${C[st.li].name} · ${C[st.li].store}`, 'Product')}</div>
          <div class="ctl"><label for="l-rung">Candidate price <b id="l-rung-v"></b></label><input type="range" id="l-rung" min="0" step="1"></div></div><div id="l-out"></div>`;
        const render = () => {
          const c = C[st.li], L = c.ladder.slice().sort((a, b) => a.p - b.p), hold = L.findIndex(r => r.k === 'hold');
          const sl = $('#l-rung'); sl.max = L.length - 1;
          if (st.rung == null || !(st.rung >= 0 && st.rung <= L.length - 1)) st.rung = hold;
          sl.value = st.rung;
          const r = L[st.rung];
          $('#l-rung-v').textContent = `${rs(r.p)} (${r.k === 'hold' ? 'hold' : sgn(r.m, 1) + '%'})`;
          $('#l-out').innerHTML = tiles([[rs(r.p), r.k === 'hold' ? 'the current price, held' : `${r.k === 'cut' ? 'cut' : 'raise'} of ${rs(Math.abs(r.p - L[hold].p))}`],
              [pct(r.s), `cheapest of four with rivals reacting (90% of runs ${pct(r.sb[0], 0)} to ${pct(r.sb[1], 0)})`], [pct(r.t), 'if rivals did not react'],
              [`${sgn(r.oos, 2)} pp`, r.mode === 'none' ? 'no promo change' : `stock-out chance if taken by ${r.mode === 'deepen' ? 'deepening' : 'withdrawing'} the promo`]]) +
            `<div class="panel"><h3>${esc(c.name)} at every price it can post</h3><p class="note">Prices sit on this listing's own grid: ₹${c.grid.step} steps, read off its past prices. Height: share of the next twelve checks in which Blinkit is the cheapest of four, with rivals reacting. Tap a bar.</p>
              <div class="cols">${L.map((g, i) => `<i class="col${i === st.rung ? ' sel' : g.k === 'hold' ? ' hold' : ''}" data-i="${i}" style="height:${Math.max(2, 100 * g.s)}%"${tipAttr(`${rs(g.p)}: ${pct(g.s)} with rivals reacting, ${pct(g.t)} without`)}></i>`).join('')}</div>
              <div style="display:flex;justify-content:space-between;margin-top:6px" class="fine"><span>${rs(L[0].p)}</span><span>now ${rs(L[hold].p)}</span><span>${rs(L[L.length - 1].p)}</span></div>
              <p class="note" style="margin-top:16px">Baseline check: the simulator replayed this listing's last ${c.base.n} test checks and ${c.base.passed ? 'reproduced what happened, so its what-ifs are shown.' : 'did not reproduce them, so no recommendation is made.'} <a href="#optimize" data-opt-listing="${st.li}">Find the smallest move for a target</a></p></div>`;
          save();
        };
        $('#l-pick').addEventListener('change', e => { st.li = clamp(e.target.selectedIndex | 0, 0, C.length - 1); st.rung = null; render(); });
        $('#l-rung').addEventListener('input', e => { st.rung = clamp(+e.target.value | 0, 0, C[st.li].ladder.length - 1); render(); });
        $('#l-out').addEventListener('click', e => {
          const col = e.target.closest('.col'); if (col) { st.rung = clamp(+col.dataset.i | 0, 0, C[st.li].ladder.length - 1); render(); }
          const o = e.target.closest('[data-opt-listing]'); if (o) mem.set('opt', Object.assign(mem.get('opt', {}), {tab: 'listing', li: st.li}));
        });
        render();
      },
    };
    const go = t => { st.tab = draw[t] ? t : 'move'; $$('#sim-tabs button').forEach(b => b.setAttribute('aria-selected', String(b.dataset.v === st.tab))); draw[st.tab](); save(); };
    $('#sim-tabs').addEventListener('click', e => { const b = e.target.closest('button'); if (b) go(b.dataset.v); });
    go(st.tab);
  };

  /* ---------------------------------------------------------------- optimize */
  PAGES.optimize = v => {
    const W = D('whatif'), X = D('explorer'), O = D('optimize');
    const st = Object.assign({tab: 'target', mover: 0, group: 'All', target: 40, li: 0, ltarget: 50, cap: 1}, mem.get('opt', {}));
    if (!W.groups.includes(st.group)) st.group = 'All';
    st.mover = clamp(st.mover | 0, 0, 3); st.target = clamp(+st.target || 40, 10, 75); st.ltarget = clamp(+st.ltarget || 50, 10, 90); st.li = st.li | 0; st.cap = +st.cap || 1;
    v.innerHTML = `<p class="eyebrow">${ico('target')}Mode · Optimize</p><h1 class="page">How much should an app <mark>cut its prices</mark>?</h1>
      ${whatIs('Set a goal, like <i>"Blinkit should be the cheapest app for 40 of every 100 products"</i>, and get the smallest price cut that reaches it. <b>Tap an app, then tap a goal.</b>')}
      ${tabsHtml('opt-tabs', [['target', 'Reach a goal'], ['listing', 'Best price for one product'], ['restock', 'What to restock first']], st.tab)}<div id="opt-body"></div>
      ${labNote('Worked out in the Lab, a practice market built from the data. The goal is being cheapest or in stock, never profit: there is no cost or sales data to compute profit from.')}
      ${glossary()}`;
    const body = $('#opt-body');
    const draw = {
      target() {
        const goals = Array.from({length: 14}, (_, i) => 10 + 5 * i), QUICK = [20, 25, 30, 40, 50, 60];
        if (!goals.includes(st.target)) st.target = goals.reduce((a, b) => (Math.abs(b - st.target) < Math.abs(a - st.target) ? b : a));
        body.innerHTML = `<div class="ask-card">
            ${pickRow('o-app', 1, 'Which app?', P.map((p, i) => [i, p, i]), st.mover)}
            ${pickRow('o-goal', 2, 'It should be the cheapest app for how many of every 100 products?', QUICK.map(g => [g, `${g} of 100`]), st.target)}
            <details class="more-opts"><summary>More options: another goal, one category</summary><div class="opt-grid">
              <label>Exact goal ${optSel('o-target', goals.map(g => [g, g + ' of every 100']), st.target, 'How often')}</label>
              <label>Which products ${optSel('o-group', W.groups.map(g => [g, g === 'All' ? 'all products' : g]), st.group, 'Which products')}</label>
            </div></details></div>
          <div id="o-out"></div>
          <details class="more"><summary>For experts: the saved optimiser run</summary><p class="sub">It searched to a ${pct(O.maxCut, 0)} cut for Blinkit at a ${pct(O.target, 0)} target, by bisection. The answer above reads a coarser grid of whole-percent cuts, so it can differ by a few tenths.</p>
          <div class="panel" style="--num:112px"><div class="legend"><span><i class="sw ring" style="border-color:var(--orange)"></i>rivals do not react</span><span><i class="sw"></i>rivals react</span></div>
            ${O.byCategory.map(r => `<div class="row"><div class="lab">${esc(r.category)}<small>${r.skus} products</small></div><div class="track"><i class="link" style="left:${100 * r.static / 12}%;width:${100 * (r.strategic - r.static) / 12}%"></i><i class="dot ring" style="left:${100 * r.static / 12}%"${tipAttr(`${r.category}: ${fix(r.static, 2)}% cut if rivals did not react`)}></i><i class="dot" style="left:${100 * r.strategic / 12}%"${tipAttr(`${r.category}: ${fix(r.strategic, 2)}% cut with rivals reacting`)}></i></div><div class="num">${fix(r.static, 1)}% → ${fix(r.strategic, 1)}%</div></div>`).join('')}
            ${ticks([0, 3, 6, 9, 12], 12, t => t + '%', 'smallest cut that reaches the target')}
            <p class="note" style="margin-top:12px">Ignoring the response understates the cut needed: ${fix(O.ratio, 2)} times deeper once followers react (median across categories).</p></div></details>`;
        const render = () => {
          const m = st.mover, T = st.target / 100;
          const curve = view => { const base = W.cells[`${P[m]}|${st.group}|-1|${view}`]; return [base.b[m]].concat(W.cuts.map(c => W.cells[`${P[m]}|${st.group}|${-c}|${view}`].s[m])); };
          const need = ys => { if (ys[0] >= T) return 0; for (let c = 1; c < ys.length; c++) if (ys[c] >= T) return (c - 1) + (T - ys[c - 1]) / (ys[c] - ys[c - 1]); return null; };
          const S = curve('strategic'), N = curve('static'), ns = need(S), nn = need(N);
          const say = n => n == null ? 'not within a 10% cut' : n === 0 ? 'already there' : fix(n, 1) + '% cut';
          const marks = [];
          if (ns) marks.push([ns, T, 'blue', `With rivals reacting: ${fix(ns, 2)}% cut`]);
          if (nn) marks.push([nn, T, 'orange', `If rivals did not react: ${fix(nn, 2)}% cut`]);
          const who = esc(P[m]), where = st.group === 'All' ? 'products' : `${esc(st.group)} products`, nb = per100(S[0]);
          const big = ns === 0 ? `<span class="to c${m}">0%</span><span class="cap">no cut needed:<br>already there</span>`
            : ns == null ? `<span class="from">&gt;10%</span><span class="cap">more than this page<br>can work out</span>`
            : `<span class="to c${m}">${fix(ns, 1)}%</span><span class="cap">price cut for ${who}</span>`;
          const answer = ns === 0 ? `${who} is already the cheapest app for <b>${nb} of every 100</b> ${where}, so no cut is needed for this goal.`
            : ns == null ? `No cut of up to 10% gets ${who} there once the other apps follow. Try a smaller goal: larger cuts were not simulated.`
            : `Cut ${who}'s prices by about <b>${fix(ns, 1)}%</b> to be the cheapest app for ${st.target} of every 100 ${where}. Today it is ${nb}.`;
          const why = ns && nn != null && nn > 0 ? `That allows for the other apps following part of the way, as they do in the Lab. If they did nothing, ${fix(nn, 1)}% would be enough.` : '';
          const bars = cmpBars([{name: P[m], c: m, b: nb, a: Math.max(nb, st.target), hi: true}], 'your goal');
          $('#o-out').innerHTML = `<div class="answer-card">${chip('SYNTHETIC')}<div class="big-ans" aria-hidden="true">${big}</div>
              <p class="answer">${answer}</p>${why ? `<p class="fine" style="margin:0">${why}</p>` : ''}${bars}</div>
            <details class="more"><summary>For experts: the curve and the numbers</summary>` +
            (ns == null ? `<p class="banner warn">${ico('alert')}<span>No cut of up to 10% reaches ${st.target}% with rivals reacting. No answer is reported, because larger cuts were not simulated for this page.</span></p>` : '') +
            `<div class="side">${receipt('Your target', [[`${esc(P[m])} is cheapest now on`, pct(S[0])], ['Target', st.target + '%'], ['If rivals did not react', say(nn)],
                ['How much deeper the response makes it', ns && nn ? fix(ns / nn, 2) + '×' : '—']], ['Smallest cut, rivals reacting', say(ns)])}
            <div class="panel"><h3>Share of products where ${esc(P[m])} is cheapest, by size of cut</h3><p class="note">${m === 0 ? 'Followers track Blinkit, so the two curves part.' : 'Nobody follows this platform in the fitted dynamics, so the curves coincide.'}</p>
              ${lineChart([{cls: 'l1', pts: N.map((y, i) => [i, y]), label: 'rivals frozen', dy: -6}, {cls: 'l0', pts: S.map((y, i) => [i, y]), label: 'rivals react', dy: 14}],
                {xmax: 10, xticks: [0, 2, 4, 6, 8, 10], xfmt: t => t + '%', ymin: 0, ymax: Math.max(0.8, T + 0.05), yfmt: t => pct(t, 0), target: T, marks, label: 'Cheapest share by cut'})}</div></div></details>`;
          mem.set('opt', st);
        };
        const sync = () => { pressed('o-app', st.mover); pressed('o-goal', st.target); const e = $('#o-target'); if (e) e.value = String(st.target); };
        const goal = val => clamp(Math.round((+val || 40) / 5) * 5, 10, 75);
        onSeg('o-app', val => { st.mover = clamp(+val | 0, 0, 3); sync(); render(); });
        onSeg('o-goal', val => { st.target = goal(val); sync(); render(); });
        $('#o-target').addEventListener('change', e => { st.target = goal(e.target.value); sync(); render(); });
        $('#o-group').addEventListener('change', e => { if (W.groups.includes(e.target.value)) st.group = e.target.value; render(); });
        render();
      },
      listing() {
        const C = X.chains;
        st.li = clamp(st.li, 0, C.length - 1);
        body.innerHTML = `${plainLine('Pick a product and how often it should be the cheapest app. The answer is the price to post: the smallest cut that gets there, or the highest price that still does.')}<div class="controls"><div class="ctl"><label for="ol-pick">Product</label>${select('ol-pick', C.map(c => `${c.name} · ${c.store}`), `${C[st.li].name} · ${C[st.li].store}`, 'Product')}</div>
          <div class="ctl"><label for="ol-target">Target: cheapest in <b id="ol-target-v"></b> of the next 12 checks</label><input type="range" id="ol-target" min="10" max="90" step="5" value="${st.ltarget}"></div></div><div id="ol-out"></div>`;
        const render = () => {
          const c = C[st.li], T = st.ltarget / 100, L = c.ladder.slice().sort((a, b) => b.p - a.p), h = L.findIndex(r => r.k === 'hold'), now = L[h].p;
          $('#ol-target-v').textContent = st.ltarget + '%';
          const solve = key => {
            if (L[h][key] >= T) { let best = h; for (let i = h - 1; i >= 0; i--) { if (L[i][key] >= T) best = i; else break; } return {i: best, dir: best === h ? 'hold' : 'raise'}; }
            for (let i = h + 1; i < L.length; i++) if (L[i][key] >= T) return {i, dir: 'cut'};
            return null;
          };
          const a = solve('s'), b = solve('t');
          const priceOf = x => (x ? rs(L[x.i].p) : 'none');
          const moveOf = x => !x ? 'no price on the grid reaches it' : x.dir === 'hold' ? 'hold' : `${x.dir} ${rs(Math.abs(L[x.i].p - now))} (${sgn(L[x.i].m, 1)}%)`;
          $('#ol-out').innerHTML = (c.base.passed ? '' : `<p class="banner warn">${ico('alert')}<span>The simulator did not reproduce this listing's recent history, so no recommendation is made.</span></p>`) +
            (!a ? `<p class="banner warn">${ico('alert')}<span>No feasible price: within 30% either side on this grid, nothing makes Blinkit cheapest in ${st.ltarget}% of checks once rivals react.</span></p>` : '') +
            `<div class="side">${receipt('Your move', [['Price now', rs(now)], ['Position now', c.dec.cheapest ? 'cheapest of four' : 'not the cheapest'], ['Price grid', `₹${c.grid.step} steps`],
                ['Move', moveOf(a)], ['Cheapest share after', a ? pct(L[a.i].s) : '—'], ['If rivals did not react', `${priceOf(b)}${b && b.dir !== 'hold' ? ', ' + moveOf(b) : ''}`]], ['Price to post', priceOf(a)])}
            <div class="panel"><h3>${esc(c.name)} ${esc(c.pack)}, every price on its grid</h3>
              <div class="tbl"><table class="t"><thead><tr><th>Price</th><th class="n">Move</th><th class="n">Rivals react</th><th class="n">Rivals frozen</th><th class="n">Stock-out, as promo</th><th></th></tr></thead><tbody>
              ${L.map((r, i) => `<tr class="${a && a.i === i ? 'hi' : ''}"><td>${rs(r.p)}${r.k === 'hold' ? ' <span class="pill">now</span>' : ''}</td><td class="n">${r.k === 'hold' ? '—' : sgn(r.m, 1) + '%'}</td><td class="n">${pct(r.s)}</td><td class="n">${pct(r.t)}</td><td class="n">${r.mode === 'none' ? '—' : sgn(r.oos, 2) + ' pp'}</td><td>${a && a.i === i ? '<span class="pill deal">chosen</span>' : ''}${b && b.i === i && !(a && a.i === i) ? '<span class="pill">if rivals frozen</span>' : ''}</td></tr>`).join('')}</tbody></table></div>
              <p class="note" style="margin-top:16px">The saved run for this listing used a 50% target: ${pe(c.opt.verdict)}.</p></div></div>`;
          mem.set('opt', st);
        };
        $('#ol-pick').addEventListener('change', e => { st.li = clamp(e.target.selectedIndex | 0, 0, C.length - 1); render(); });
        $('#ol-target').addEventListener('input', e => { st.ltarget = clamp(+e.target.value || 50, 10, 90); render(); });
        render();
      },
      restock() {
        const R = W.restock, caps = [...new Set(R.rows.map(r => r.capacity_pct))].sort((a, b) => a - b);
        if (!caps.includes(st.cap)) st.cap = 1;
        const NAMES = {random: 'Random', longest_out_first: 'Longest out first', index_restock_only: 'Priority index, restock only', priority_index: 'Priority index', clairvoyant_oracle: 'Clairvoyant benchmark'};
        body.innerHTML = `${plainLine('A store can only restock a few products at a time. This compares ways of choosing which ones first: the priority index removes the most out-of-stock time, and "whatever has been out longest" is no better than picking at random.')}<div class="controls"><div class="ctl"><span>Listings a store can act on per check</span>${segs('r-cap', caps.map(c => [c, c + '%']), st.cap)}</div></div><div id="r-out"></div>`;
        const render = () => {
          $$('#r-cap button').forEach(b => b.setAttribute('aria-pressed', String(+b.dataset.v === st.cap)));
          const rows = R.rows.filter(r => r.capacity_pct === st.cap).sort((a, b) => a.reduction_pct - b.reduction_pct), max = Math.max(...R.rows.map(r => r.reduction_p95)) * 1.05;
          const idx = rows.find(r => r.policy === 'priority_index');
          const share = R.shareOfOracle[String(st.cap)] != null ? R.shareOfOracle[String(st.cap)] : R.shareOfOracle[st.cap.toFixed(1)];
          $('#r-out').innerHTML = tiles([[fix(idx.reduction_pct, 1) + '%', 'out-of-stock exposure the priority index removes'], [pct(share, 0), 'of what a clairvoyant could remove'],
              [fix(idx.saved_per_action, 2), 'out-of-stock checks saved per action'], [int(idx.actions), 'actions over twelve checks']]) +
            `<div class="panel"><h3>Which listing to restock first</h3><p class="note">Out-of-stock exposure removed against doing nothing, with the range that holds 90% of runs. The clairvoyant knows how long every outage will last, which no operator does: it is a ceiling, not a policy.</p>
              ${rows.map(r => `<div class="row"><div class="lab">${esc(NAMES[r.policy] || r.policy)}</div><div class="track"><i class="fill ${r.policy === 'priority_index' ? '' : 'neutral'}" style="width:${100 * r.reduction_pct / max}%"${tipAttr(`${NAMES[r.policy] || r.policy}: ${fix(r.reduction_pct, 1)}% (90% of runs ${fix(r.reduction_p05, 1)} to ${fix(r.reduction_p95, 1)})`)}></i><i class="whisk" style="left:${100 * r.reduction_p05 / max}%;width:${100 * (r.reduction_p95 - r.reduction_p05) / max}%"></i></div><div class="num">${fix(r.reduction_pct, 1)}%</div></div>`).join('')}
              <p class="note" style="margin-top:16px">"Longest out first" does no better than picking at random: in the fitted dynamics a listing that has been out a long time is about to come back anyway.</p></div>`;
          mem.set('opt', st);
        };
        onSeg('r-cap', val => { if (caps.includes(+val)) st.cap = +val; render(); });
        render();
      },
    };
    const go = t => { st.tab = draw[t] ? t : 'target'; $$('#opt-tabs button').forEach(b => b.setAttribute('aria-selected', String(b.dataset.v === st.tab))); draw[st.tab](); mem.set('opt', st); };
    $('#opt-tabs').addEventListener('click', e => { const b = e.target.closest('button'); if (b) go(b.dataset.v); });
    go(st.tab);
  };

  /* ---------------------------------------------------------------- analyst */
  PAGES.analyst = v => {
    const A = D('analyst'), E = D('analystEval'), B = E.browser ? E.browser.summary : null;
    const row = (name, s) => s ? `<tr><td>${name}</td><td class="n">${s.tuning.passed} / ${s.tuning.questions}</td><td class="n">${s.holdout.passed} / ${s.holdout.questions}</td></tr>` : '';
    v.innerHTML = `<p class="eyebrow">${ico('chat')}Mode · Analyst</p><h1 class="page">Ask the project <mark>anything</mark></h1>
      <p class="lede">It reads ${int(A.passages.length)} passages from the project's documents and saved results. Every claim carries a tag, a source and a date. It says no to questions about demand, revenue or customers before it looks anything up, because the data has none.</p>
      <div class="side main">
        <div style="min-width:0"><form class="ask" id="a-form" autocomplete="off"><input id="a-input" type="text" placeholder="Ask about prices, stock, delivery or the models" aria-label="Question for the analyst"><button class="btn" type="submit">Ask</button></form>
          ${sugg(20)}
          <div data-thread data-empty='<p class="note" style="margin-top:24px">Pick a question above, or type your own. Try one it has to turn down.</p>'></div></div>
        <div class="stack" style="align-content:start;min-width:0">
          <div class="panel"><h3>How it answers</h3><ul class="cav" style="font-size:13.5px;color:var(--ink-2);margin:6px 0 0">
            <li>The rules for what it must turn down run first.</li><li>A what-if question reads the simulator's saved runs.</li><li>A question about what Blinkit listed reads the observed rows.</li>
            <li>Anything else searches the documents and results.</li><li>A number that is not in the retrieved evidence is flagged.</li></ul>
            <p class="note" style="margin-top:16px">Served from this machine, questions go to the project's own analyst. Opened as a plain file, the same rules run inside the page.</p></div>
          <div class="panel"><h3>How it scores</h3><p class="note">The project's two question sets, graded by the same rules. The engine in the page is scored with its saved answers switched off.</p>
            <table class="t"><thead><tr><th></th><th class="n">Tuning set</th><th class="n">Held-out set</th></tr></thead><tbody>
            ${row('Engine in this page', B)}<tr><td>Project analyst</td><td class="n">${E.python.tuning_set.passed} / ${E.python.tuning_set.questions}</td><td class="n">${E.python.holdout_set.passed} / ${E.python.holdout_set.questions}</td></tr></tbody></table>
            ${B ? `<p class="note" style="margin-top:12px">Turned down ${B.tuning.refused_when_it_must + B.holdout.refused_when_it_must} of ${B.tuning.must_refuse + B.holdout.must_refuse} questions it must; ${B.tuning.false_refusals + B.holdout.false_refusals} turned down wrongly. A pass means the rule held on these questions, not on every question.</p>` : ''}</div>
        </div></div>`;
    $('#a-form').addEventListener('submit', e => { e.preventDefault(); const i = $('#a-input'); ask(i.value); i.value = ''; });
    renderThreads();
  };

  /* ---------------------------------------------------------------- products */
  PAGES.listings = v => {
    const X = D('explorer'), C = X.chains;
    let li = Math.max(0, C.findIndex(c => c.name === mem.get('listing', '')));
    const pf = pfState;
    Object.assign(pf, mem.get('pf', {}));
    pf.q = String(pf.q || '').slice(0, 80); if (!['feat', 'low', 'high', 'eta', 'cheap'].includes(pf.sort)) pf.sort = 'feat';
    const cats = [...new Set((D('analyst').categories || []).concat(C.map(c => c.category)))].sort();
    if (pf.cat && !cats.includes(pf.cat)) pf.cat = '';
    const sorts = [['feat', 'Featured'], ['low', 'Price: low to high'], ['high', 'Price: high to low'], ['eta', 'Fastest delivery'], ['cheap', 'Cheapest of 4 first']];
    v.innerHTML = `<p class="eyebrow">${ico('grid')}Products</p><h1 class="page">Tap a product. See <mark>every layer</mark>.</h1>
      <p class="lede">${C.length} Blinkit listings followed end to end: what was seen, which models apply, what they predicted, the prices it can post, the simulation, the move it recommends and why. Selling something else? Add it further down, with a photo.</p>
      <div class="toolbar"><label class="tb-search">${ico('search')}<input id="pf-q" type="search" value="${esc(pf.q)}" placeholder="Search products by name" aria-label="Search products"></label>
        <select id="pf-cat" aria-label="Category"><option value="">All categories</option>${cats.map(c => `<option${c === pf.cat ? ' selected' : ''}>${esc(c)}</option>`).join('')}</select>
        <select id="pf-sort" aria-label="Sort">${sorts.map(([k, l]) => `<option value="${k}"${k === pf.sort ? ' selected' : ''}>${l}</option>`).join('')}</select>
        <span class="fine" id="pf-n"></span></div>
      <div class="sec-head first"><h2>Followed listings ${chip('SYNTHETIC')}</h2><span class="fine">Tap a card for its full story</span></div>
      <div class="shelf" id="x-shelf"></div>
      <div class="sec-head"><h2>Your products ${chip('USER')}</h2><span class="sec-acts">
        <button class="btn ghost" type="button" id="up-export" title="Save your products, photos included, to a file">${ico('download')}Export</button>
        <button class="btn ghost" type="button" id="up-import" title="Add products from a file you exported">${ico('upload')}Import</button>
        <button class="btn ghost" type="button" id="ap-open">${ico('plus')}Add a product</button>
        <input type="file" id="up-file" accept="application/json,.json" hidden></span></div>
      <p class="sub" id="up-where">Your own entries: kept apart from the project data, and no model reads them.</p>
      <div id="up-list"></div>
      <div id="x-out"></div>
      ${addSheet()}`;
    const drawShelf = () => {
      let idx = C.map((c, i) => i).filter(i => fitsFilter(C[i].name, C[i].category));
      const key = {low: i => C[i].dec.price, high: i => -C[i].dec.price, eta: i => C[i].dec.eta, cheap: i => (C[i].dec.cheapest ? 0 : 1)}[pf.sort];
      if (key) idx = idx.slice().sort((a, b) => key(a) - key(b) || a - b);
      $('#x-shelf').innerHTML = idx.length ? idx.map(i => productCard(C[i], i, {selected: li})).join('')
        : '<p class="note">No followed listing matches. Clear the search or pick another category.</p>';
      const n = $('#pf-n'); if (n) n.textContent = `${idx.length} of ${C.length} followed listings`;
    };
    const refilter = () => { mem.set('pf', pf); drawShelf(); drawUserProducts(); };
    const render = () => {
      const c = C[li], d = c.dec, o = c.opt;
      mem.set('listing', c.name);
      drawShelf();
      const view = (key, label) => {
        if (o.dir === 'raise') {
          const x = o.raise && o.raise[key];
          if (!x || !x.target_met_at_current_price) return `${label}: the current price does not meet the target`;
          return x.raise_rs > 0 ? `${label}: ${rs(x.price)} (raise ${rs(x.raise_rs)}, ${fix(x.raise_pct, 1)}%), still cheapest in ${pct(x.mean_cheapest_share)} of checks`
            : `${label}: hold at ${rs(x.price)}, cheapest in ${pct(x.mean_cheapest_share)} of checks; no raise keeps the target`;
        }
        const x = o[key];
        return x && x.reachable_within_30pct ? `${label}: ${rs(x.price)} (cut ${rs(x.cut_rs)}, ${fix(x.cut_pct, 1)}%), cheapest in ${pct(x.mean_cheapest_share)} of checks` : `${label}: no price within 30% reaches the target`;
      };
      const seen = `<p class="note" style="margin-top:16px"><span class="pill">${ico('bolt')}${d.eta} min</span> <span class="pill ${d.inStock ? 'yes' : 'bad'}">${d.inStock ? 'in stock' : 'out of stock'}</span> ${d.promo ? `<span class="pill deal">${fix(d.disc, 1)}% off</span>` : ''}</p>
        ${c.real ? `<p class="note">${X.storeUnverified ? chip('UNVERIFIED') + ' ' : ''}On Blinkit: ${rs(c.real.price)}, ${esc(String(c.real.stock).toLowerCase())}, ${c.real.eta[0]} min. Context only: no model uses it. Its price and stock are checked against the source; that it belongs to this store is not.</p>` : ''}`;
      $('#x-out').innerHTML = `<h2>${esc(c.name)} <span style="font-weight:500;color:var(--ink-2)">${esc(c.pack)}</span></h2>
        <p class="sub">${esc(c.storeName)} · ${esc(c.store)} · ${esc(c.category)} &nbsp; <button class="btn ghost" type="button" id="x-ask">${ico('chat')}Ask the analyst to explain it</button></p>
        <p class="buy-on"><span class="fine">Buy it today on</span> ${P.map(p => shopLink(p, {name: c.name, pack: c.pack}, esc(p))).join('')}</p>
        <div class="grid2">
          ${board(c, `1 · seen at ${esc(d.at)}`, seen)}
          <div class="panel"><h3>2 · Which models apply</h3><p class="note">A model with no valid prediction for this listing is skipped, with the reason. Nothing is forced. Hover a tag to see why.</p>
            <div style="display:flex;flex-wrap:wrap;gap:6px">${c.app.map(a => `<span class="pill ${a.on ? 'yes' : 'na'}"${tipAttr(a.why)}>${a.on ? ico('check') : ''}${esc(a.k)} · ${pe(a.name)}${a.on ? '' : ' · skipped'}</span>`).join('')}</div></div>
        </div>
        <div class="panel mt"><h3>3 · What they predicted, next to what happened</h3>
          <div class="tbl"><table class="t"><thead><tr><th>Model</th><th>Predicted</th><th>Actual</th><th></th></tr></thead><tbody>${c.pred.map(r => `<tr><td>${pe(r[0])}</td><td>${pe(r[1])}</td><td>${pe(r[2])}</td><td>${chip(r[3])}</td></tr>`).join('')}</tbody></table></div></div>
        <div class="grid2 mt">
          <div class="panel"><h3>4–5 · Price grid and simulation ${chip('SYNTHETIC')}</h3><p class="note">Grid: ₹${c.grid.step} steps, from ${pe(c.grid.from)}. Baseline check ${c.base.passed ? 'passed' : 'failed'}: the status quo replayed over ${c.base.n} checks put the observed share ${pct(c.base.obs, 0)} inside the simulated range ${pct(c.base.range[0], 0)} to ${pct(c.base.range[1], 0)}.</p>
            <p class="note">If it keeps its own price process, Blinkit is cheapest of four in ${pct(c.sq.s)} of the next twelve checks.</p><a class="btn ghost" href="#simulate" data-sim-listing="${li}">${ico('sliders')}Try other prices</a></div>
          <div class="panel"><h3>6 · Recommended move ${chip('SYNTHETIC')}</h3><p class="note">Target: cheapest of four in ${pct(o.target, 0)} of the next twelve checks.</p>
            <p style="margin:0 0 6px;font-weight:800">${pe(o.verdict.charAt(0).toUpperCase() + o.verdict.slice(1))}.</p>
            <p class="note">${esc(view('strategic', 'With rivals reacting'))}. ${esc(view('static', 'If they did not'))}.</p><a class="btn pop" href="#optimize" data-opt-listing="${li}">${ico('target')}Change the target</a></div>
        </div>
        <div class="panel mt"><h3>7 · The explanation, claim by claim</h3><ul class="claims" style="margin-top:12px">${c.claims.map(k => claimHtml({provenance: k.prov, text: k.text, source_file: k.src, stage: k.stage, store_label: X.storeUnverified && k.prov === 'REAL' && k.stage === '1_observe' ? 'UNVERIFIED' : null})).join('')}</ul></div>`;
    };
    $('#x-shelf').addEventListener('click', e => {
      const b = e.target.closest('[data-pick]');
      if (!b) return;
      li = clamp(+b.dataset.pick | 0, 0, C.length - 1); render();
      const out = $('#x-out'); if (out.scrollIntoView) out.scrollIntoView({behavior: 'smooth', block: 'start'});
    });
    $('#x-out').addEventListener('click', e => {
      if (e.target.closest('#x-ask')) { openDock(); ask(`Explain the ${C[li].name} listing`); return; }
      const o = e.target.closest('[data-opt-listing]'); if (o) mem.set('opt', Object.assign(mem.get('opt', {}), {tab: 'listing', li: clamp(+o.dataset.optListing | 0, 0, C.length - 1)}));
      const s = e.target.closest('[data-sim-listing]'); if (s) mem.set('sim', Object.assign(mem.get('sim', {}), {tab: 'listing', li: clamp(+s.dataset.simListing | 0, 0, C.length - 1), rung: null}));
    });
    $('#pf-q').addEventListener('input', e => { pf.q = String(e.target.value || '').slice(0, 80); refilter(); });
    $('#pf-cat').addEventListener('change', e => { pf.cat = cats.includes(e.target.value) ? e.target.value : ''; refilter(); });
    $('#pf-sort').addEventListener('change', e => { pf.sort = sorts.some(x => x[0] === e.target.value) ? e.target.value : 'feat'; refilter(); });
    render();
    wireAddSheet();
    drawUserProducts();
    if (mem.get('openAdd', 0)) { mem.set('openAdd', 0); openAddSheet(); }
  };

  /* your products, wherever they belong: first on the home shelf, and in the festive planner when one is in season */
  async function homeYours() {
    try {
      const list = (await userStore.list()).slice().reverse();
      userCache = list;
      const box = $('#home-yours');
      if (box && list.length) box.innerHTML = `<p class="yours-k">${chip('USER')} Your products</p><div class="shelf yours">${list.slice(0, 5).map(x => userCard(x, true)).join('')}</div>`;
    } catch (e) { /* the shelf still shows the followed listings */ }
  }
  async function festYours() {
    try {
      const list = (await userStore.list()).slice().reverse(), box = $('#f-yours');
      userCache = list;
      const hits = list.map(x => {
        const fm = festMatch(`${x.name} ${x.category || ''}`), f = fm.groups.length ? upcoming().find(ff => ff.groups.some(k => fm.groups.includes(k))) : null;
        return f ? [x, f] : null;
      }).filter(Boolean);
      if (box) box.innerHTML = hits.length ? `<h2>Your products in season ${chip('USER')}</h2><p class="sub">Matched to the festival calendar by name. Each card shows the next festival that calls for it.</p><div class="shelf">${hits.map(([x]) => userCard(x, true)).join('')}</div>` : '';
    } catch (e) { /* the planner works without them */ }
  }

  /* ================================================================== products a person adds
     Served from this machine they are saved by the local server in data/user_added/; opened from disk they stay in this
     browser. Either way they carry the "Added by you" tag and nothing else in the project reads them. */
  const pfState = {q: '', cat: '', sort: 'feat'};       // the Products page search, category and sort
  let userCache = [], editing = null, editPhoto0 = null;
  function fitsFilter(name, cat) {
    const words = String(pfState.q || '').toLowerCase().split(/\s+/).filter(Boolean), n = String(name || '').toLowerCase();
    return words.every(w => n.includes(w)) && (!pfState.cat || cat === pfState.cat);
  }
  const memTry = (k, v) => { try { localStorage.setItem('qcmi-' + k, JSON.stringify(v)); return true; } catch (e) { return false; } };
  const hexId = () => Array.from({length: 12}, () => '0123456789abcdef'[Math.floor(Math.random() * 16)]).join('');
  const imgSrc = s => (/^(data:image\/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+|api\/products\/[0-9a-f]{12}\/image)$/.test(String(s || '')) ? String(s) : '');
  function checkProduct(p) {
    const name = String(p.name || '').trim();
    if (!name) throw new Error('Give the product a name.');
    if (name.length > 120) throw new Error('The name is longer than 120 characters.');
    for (const [plat, x] of Object.entries(p.prices)) if (!(x > 0 && x <= 100000)) throw new Error(`The ${plat} price must be between ₹0.01 and ₹1,00,000.`);
    if (p.eta != null && !(p.eta >= 1 && p.eta <= 240)) throw new Error('The delivery time must be 1 to 240 minutes.');
  }
  const userStore = {
    async list() {
      if (await serverKeeps()) {
        const r = await fetch('api/products');
        if (!r.ok) throw new Error('The server did not return your list.');
        return (await r.json()).products || [];
      }
      return (mem.get('products', []) || []).filter(p => p && /^[0-9a-f]{12}$/.test(p.id));
    },
    async add(p) {
      checkProduct(p);
      if (await serverKeeps()) {
        const r = await fetch('api/products', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(p)});
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(j.error ? j.error.charAt(0).toUpperCase() + j.error.slice(1) + '.' : 'The product was not saved.');
        return j;
      }
      const list = mem.get('products', []) || [];
      const rec = Object.assign({}, p, {id: hexId(), added: new Date().toISOString(), provenance: 'USER'});
      list.push(rec);
      if (!memTry('products', list)) throw new Error('This browser has no room left for that photo. Try a smaller one, or run the site with python scripts/serve_site.py to save it on this computer.');
      return rec;
    },
    async update(id, p) {
      checkProduct(p);
      if (await serverKeeps()) {
        const r = await fetch('api/products/' + encodeURIComponent(id), {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(p)});
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(j.error ? j.error.charAt(0).toUpperCase() + j.error.slice(1) + '.' : 'The changes were not saved.');
        return j;
      }
      const list = mem.get('products', []) || [], i = list.findIndex(x => x.id === id);
      if (i < 0) throw new Error('That product is no longer on the list.');
      const old = list[i], upd = Object.assign({}, old, p, {id, added: old.added, provenance: 'USER', updated: new Date().toISOString()});
      if (p.remove_image) upd.image = null; else if (p.image === undefined) upd.image = old.image;
      delete upd.remove_image;
      list[i] = upd;
      if (!memTry('products', list)) throw new Error('This browser has no room left for that photo. Try a smaller one.');
      return upd;
    },
    async remove(id) {
      if (await serverKeeps()) {
        const r = await fetch('api/products/' + encodeURIComponent(id), {method: 'DELETE'});
        if (!r.ok) throw new Error('The product was not removed.');
        return true;
      }
      memTry('products', (mem.get('products', []) || []).filter(p => p.id !== id));
      return true;
    },
  };
  function userCard(p, compact) {
    const prices = Object.entries(p.prices || {}).filter(([, x]) => x > 0), low = prices.length ? Math.min(...prices.map(x => x[1])) : null;
    const best = prices.filter(x => x[1] === low).map(x => x[0]);
    const fm = festMatch(`${p.name} ${p.category || ''}`), fs = fm.groups.length ? upcoming().find(f => f.groups.some(k => fm.groups.includes(k))) : null;
    const src = imgSrc(p.image), fd = fs ? Math.max(0, daysTo(fs.start)) : 0;
    const badges = `${p.eta ? `<span class="pill eta">${ico('bolt')}${esc(p.eta)} min</span>` : ''}${fs ? `<span class="pill deal tag">${esc(fs.name)} ${fd > 0 ? `in ${fd} d` : 'now'}</span>` : ''}`;
    const open = compact ? '<a class="pcard ucard" href="#listings">' : '<div class="pcard ucard">';
    const foot = compact ? `${chip('USER')}<span class="pill ${p.in_stock === false ? 'bad' : 'yes'}">${p.in_stock === false ? 'out of stock' : 'in stock'}</span>`
      : `<span class="pill ${p.in_stock === false ? 'bad' : 'yes'}">${p.in_stock === false ? 'out of stock' : 'in stock'}</span><span class="uc-acts"><button type="button" class="linkish" data-edit="${esc(p.id)}">Edit</button><button type="button" class="linkish" data-remove="${esc(p.id)}">Remove</button></span>`;
    return `<div class="pwrap">${open}${src ? `<span class="pic"><img src="${esc(src)}" alt="${esc(p.name)}" loading="lazy">${badges}</span>` : pic(p.name, p.category, p.pack, badges)}
      <span class="nm">${esc(p.name)}</span><span class="pk">${esc([p.brand, p.pack, p.category].filter(Boolean).join(' · ') || 'no details yet')}</span>
      <span class="buy"><span class="price">${low != null ? rs(low) : '—'}</span><span class="vs">${low == null ? 'no price yet' : prices.length > 1 ? 'cheapest on ' + esc(best.join(', ')) : 'on ' + esc(best[0])}</span></span>
      <span class="uc-foot">${foot}</span>${compact ? '</a>' : '</div>'}${low != null ? basketBtn('u:' + p.id, p.name) : ''}</div>`;
  }
  async function drawUserProducts() {
    const box = $('#up-list');
    try {
      const all = (await userStore.list()).slice().reverse();
      userCache = all;
      const low = x => { const v = Object.values(x.prices || {}).filter(y => y > 0); return v.length ? Math.min(...v) : Infinity; };
      let list = all.filter(x => fitsFilter(x.name, x.category));
      if (pfState.sort === 'low') list = list.slice().sort((a, b) => low(a) - low(b));
      if (pfState.sort === 'high') list = list.slice().sort((a, b) => (low(b) === Infinity ? -1 : low(b)) - (low(a) === Infinity ? -1 : low(a)));
      if (pfState.sort === 'eta') list = list.slice().sort((a, b) => (a.eta || 999) - (b.eta || 999));
      if (all.length && !list.length) { box.innerHTML = '<p class="note">None of your products matches the search.</p>'; return; }
      const where = $('#up-where');
      if (where) where.textContent = (await serverKeeps() ? 'Saved on this computer. ' : 'Saved in this browser only. ')
        + 'Your own entries: kept apart from the project data, and no model reads them.';
      box.innerHTML = list.length ? `<div class="shelf">${list.map(x => userCard(x)).join('')}</div>`
        : `<div class="add-promo"><span class="ap-ico">${ico('camera')}</span>
            <span class="ap-txt"><b>Selling something we do not track?</b><span>Snap a photo or upload one, add its price on each app, and it joins your list in seconds.</span></span>
            <span class="ap-btns"><button type="button" class="btn pop" data-add-via="camera">${ico('camera')}Take a picture</button><button type="button" class="btn ghost" data-add-via="upload">${ico('upload')}Upload a photo</button></span></div>`;
    } catch (e) {
      box.innerHTML = `<p class="banner warn">${ico('alert')}<span>${esc(String((e && e.message) || e))}</span></p>`;
    }
  }
  function addSheet() {
    const cats = (D('analyst').categories || []).concat(['Other']);
    return `<div class="sheet" id="ap" hidden role="dialog" aria-modal="true" aria-labelledby="ap-title"><div class="sheet-card">
      <header><div><h3 id="ap-title">Add a product</h3><p class="fine" style="margin:0">A photo first, then the details. Only the name is required.</p></div><button type="button" class="btn ghost" id="ap-close">Close</button></header>
      <div class="ap-photo">
        <div class="ap-pick" id="ap-pick">
          <button type="button" class="ap-opt" id="ap-cam"><span class="gi">${ico('camera')}</span><b>Take a picture</b><span>With this device's camera</span></button>
          <button type="button" class="ap-opt" id="ap-up"><span class="gi">${ico('upload')}</span><b>Upload a photo</b><span>JPEG, PNG or WebP</span></button>
        </div>
        <div class="ap-live" id="ap-live" hidden><video id="ap-video" autoplay playsinline muted></video>
          <div class="acts"><button class="btn pop" id="ap-snap" type="button">${ico('camera')}Capture</button><button class="btn ghost" id="ap-cancel" type="button">Cancel</button></div></div>
        <div class="ap-prev" id="ap-prev" hidden><img id="ap-img" alt="The product photo"><button type="button" class="btn ghost" id="ap-redo">Change photo</button></div>
        <input type="file" id="ap-file" accept="image/jpeg,image/png,image/webp" hidden>
        <input type="file" id="ap-cam-file" accept="image/*" capture="environment" hidden>
      </div>
      <form id="ap-form" class="ap-form" autocomplete="off" novalidate>
        <label class="f wide"><span>Product name *</span><input id="ap-name" maxlength="120" placeholder="Handmade clay diya, set of 12"></label>
        <label class="f"><span>Brand</span><input id="ap-brand" maxlength="60"></label>
        <label class="f"><span>Pack size</span><input id="ap-pack" maxlength="40" placeholder="12 pcs"></label>
        <label class="f"><span>Category</span><select id="ap-cat"><option value="">Choose a category</option>${cats.map(c => `<option>${esc(c)}</option>`).join('')}</select></label>
        <label class="f"><span>Delivery time, minutes</span><input id="ap-eta" type="number" min="1" max="240" inputmode="numeric"></label>
        <fieldset class="f wide"><legend>Price on each app, ₹</legend><div class="ap-prices">${P.map((p, i) => `<label><span>${pname(i)}</span><input data-plat="${esc(p)}" type="number" min="0" step="0.5" inputmode="decimal" placeholder="—"></label>`).join('')}</div></fieldset>
        <label class="toggle wide"><input type="checkbox" id="ap-stock" checked> In stock</label>
        <label class="f wide"><span>Notes</span><textarea id="ap-notes" maxlength="300" rows="2"></textarea></label>
        <p class="ap-season wide" id="ap-season"></p>
        <p class="banner warn wide" id="ap-err" hidden></p>
        <div class="wide acts"><button class="btn pop" type="submit" id="ap-save">${ico('check')}Add to my list</button></div>
      </form></div></div>`;
  }
  let camStream = null, photo = null;
  function stopCamera() { if (camStream) { camStream.getTracks().forEach(t => t.stop()); camStream = null; } }
  function showPhoto(url) {
    photo = url;
    $('#ap-live').hidden = true; $('#ap-pick').hidden = !!url; $('#ap-prev').hidden = !url;
    if (url) $('#ap-img').src = url;
  }
  function apError(msg) { const e = $('#ap-err'); e.hidden = !msg; e.textContent = msg || ''; }
  function openAddSheet(p) {
    const s = $('#ap'); if (!s) return;
    editing = p && p.id ? p.id : null;
    const f = $('#ap-form'); if (f.reset) f.reset();
    $('#ap-title').textContent = editing ? 'Edit product' : 'Add a product';
    $('#ap-save').innerHTML = `${ico('check')}${editing ? 'Save changes' : 'Add to my list'}`;
    if (editing) {
      const set = (id, val) => { const el = $(id); if (el) el.value = val == null ? '' : String(val); };
      set('#ap-name', p.name); set('#ap-brand', p.brand); set('#ap-pack', p.pack); set('#ap-eta', p.eta); set('#ap-notes', p.notes);
      const cs = $('#ap-cat'); if (cs) cs.value = p.category || '';
      for (const i of $$('#ap-form [data-plat]')) i.value = (p.prices || {})[i.dataset.plat] != null ? String(p.prices[i.dataset.plat]) : '';
      $('#ap-stock').checked = p.in_stock !== false;
    }
    editPhoto0 = editing ? (imgSrc(p.image) || null) : null;
    s.hidden = false; document.body.classList.add('noscroll'); showPhoto(editPhoto0); apError(''); seasonHint();
    const n = $('#ap-name'); if (n && n.focus) n.focus();
  }
  function closeAddSheet() { stopCamera(); const s = $('#ap'); if (s) s.hidden = true; document.body.classList.remove('noscroll'); }
  /* a photo is shrunk in the browser before it is sent: the longest side at most 1000 px, as JPEG */
  function shrink(src) {
    return new Promise((res, rej) => {
      const im = new Image();
      im.onload = () => {
        const k = Math.min(1, 1000 / Math.max(im.naturalWidth || 1, im.naturalHeight || 1)), c = document.createElement('canvas');
        c.width = Math.max(1, Math.round(im.naturalWidth * k)); c.height = Math.max(1, Math.round(im.naturalHeight * k));
        c.getContext('2d').drawImage(im, 0, 0, c.width, c.height);
        res(c.toDataURL('image/jpeg', 0.84));
      };
      im.onerror = () => rej(new Error('That file is not a photo this browser can read.'));
      im.src = src;
    });
  }
  function fromFile(input) {
    const f = input.files && input.files[0];
    input.value = '';
    if (!f || typeof FileReader === 'undefined') return;
    if (!/^image\//.test(f.type)) { apError('Pick a photo: a JPEG, PNG or WebP file.'); return; }
    if (f.size > 15 * 1024 * 1024) { apError('That photo is larger than 15 MB.'); return; }
    const r = new FileReader();
    r.onload = () => shrink(r.result).then(u => { apError(''); showPhoto(u); }).catch(e => apError(e.message));
    r.onerror = () => apError('That file could not be read.');
    r.readAsDataURL(f);
  }
  async function startCamera() {
    apError('');
    const md = typeof navigator !== 'undefined' && navigator.mediaDevices;
    if (!md || !md.getUserMedia) { $('#ap-cam-file').click(); return; }      // a phone opens its camera app instead
    try {
      camStream = await md.getUserMedia({video: {facingMode: 'environment', width: {ideal: 1280}}, audio: false});
      $('#ap-video').srcObject = camStream; $('#ap-pick').hidden = true; $('#ap-live').hidden = false;
    } catch (e) {
      apError('The camera is not available here (no camera, or permission was not given). Upload a photo instead.');
    }
  }
  function capture() {
    const vd = $('#ap-video');
    if (!camStream || !vd.videoWidth) return;
    const c = document.createElement('canvas'); c.width = vd.videoWidth; c.height = vd.videoHeight;
    c.getContext('2d').drawImage(vd, 0, 0);
    stopCamera();
    shrink(c.toDataURL('image/jpeg', 0.9)).then(showPhoto).catch(e => apError(e.message));
  }
  function readForm() {
    const num = id => { const x = String($(id).value || '').trim(); return x === '' ? null : Number(x); };
    const prices = {};
    for (const i of $$('#ap-form [data-plat]')) { const x = String(i.value || '').trim(); if (x !== '') prices[i.dataset.plat] = Number(x); }
    return {name: String($('#ap-name').value || '').trim(), brand: String($('#ap-brand').value || '').trim() || null, pack: String($('#ap-pack').value || '').trim() || null,
      category: String($('#ap-cat').value || '') || null, prices, in_stock: !!$('#ap-stock').checked, eta: num('#ap-eta'),
      notes: String($('#ap-notes').value || '').trim() || null, image: photo};
  }
  function seasonHint() {
    const el = $('#ap-season'); if (!el) return;
    const fm = festMatch(`${$('#ap-name').value || ''} ${$('#ap-cat').value || ''}`);
    const fs = fm.groups.length ? firstOfEach(upcoming(366)).filter(f => f.groups.some(k => fm.groups.includes(k))) : [];
    el.innerHTML = fs.length ? `${ico('lamp')}<span>In season for ${fs.slice(0, 3).map(f => `<b>${esc(f.name)}</b> (${esc(fmtD(dOf(f.day)))})`).join(', ')}. See the <a href="#festive">Festive planner</a>.</span>` : '';
  }
  /* ---- your products travel as a file: export them (photos included), import them in another browser or device */
  const UP_FIELDS = ['name', 'brand', 'pack', 'category', 'in_stock', 'eta'];
  async function asDataUrl(src) {                 // a photo the server keeps, as a data URL that can travel in the file
    if (!src || /^data:/.test(src)) return src || null;
    try {
      const b = await (await fetch(API + src)).blob();
      return await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(b); });
    } catch (e) { return null; }
  }
  async function exportProducts() {
    try {
      const list = await userStore.list();
      if (!list.length) { toast('You have no products to export yet', 'alert'); return; }
      const products = [];
      for (const p of list) {
        const out = {prices: Object.assign({}, p.prices || {})};
        UP_FIELDS.forEach(k => { if (p[k] != null) out[k] = p[k]; });
        out.image = await asDataUrl(imgSrc(p.image));
        products.push(out);
      }
      if (typeof Blob !== 'function' || typeof URL === 'undefined' || !URL.createObjectURL || typeof document.createElement !== 'function') return;
      const doc = {app: 'ShelfPulse', kind: 'your-products', version: 1, exported: new Date().toISOString(), products};
      const url = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 1)], {type: 'application/json'}));
      const a = document.createElement('a');
      a.href = url; a.download = `shelfpulse-products-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      toast(`Exported ${products.length} product${products.length === 1 ? '' : 's'}`, 'download');
    } catch (e) { toast('The export did not work: ' + ((e && e.message) || e), 'alert'); }
  }
  async function importProducts(input) {
    const file = input && input.files && input.files[0];
    if (!file) return;
    try {
      if (file.size > 25 * 1024 * 1024) throw new Error('That file is larger than 25 MB.');
      const doc = JSON.parse(await file.text());
      const list = doc && doc.kind === 'your-products' && Array.isArray(doc.products) ? doc.products : null;
      if (!list) throw new Error('That is not a file of ShelfPulse products.');
      const key = p => (String(p.name || '').trim() + '|' + String(p.pack || '').trim()).toLowerCase();
      const have = new Set(userCache.map(key));
      let added = 0, skipped = 0;
      for (const raw of list.slice(0, 200)) {
        const p = {prices: {}};
        UP_FIELDS.forEach(k => { if (raw && raw[k] != null) p[k] = raw[k]; });
        P.forEach(pl => { const v = +((raw && raw.prices) || {})[pl]; if (v > 0) p.prices[pl] = v; });
        if (raw && typeof raw.image === 'string' && /^data:image\/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+$/.test(raw.image)) p.image = raw.image;
        if (have.has(key(p))) { skipped++; continue; }                 // already on the list: importing twice adds nothing
        try { await userStore.add(p); have.add(key(p)); added++; } catch (e) { skipped++; }
      }
      toast(`Imported ${added} product${added === 1 ? '' : 's'}${skipped ? `; ${skipped} skipped (already here, or not valid)` : ''}`, 'upload');
      await drawUserProducts();
    } catch (e) { toast(String((e && e.message) || e), 'alert'); } finally { try { input.value = ''; } catch (e) { /* a read-only stand-in */ } }
  }

  function wireAddSheet() {
    $('#up-export').addEventListener('click', exportProducts);
    $('#up-import').addEventListener('click', () => { const f = $('#up-file'); if (f && f.click) f.click(); });
    $('#up-file').addEventListener('change', e => importProducts(e.target));
    $('#ap-open').addEventListener('click', () => openAddSheet());
    $('#ap-close').addEventListener('click', closeAddSheet);
    $('#ap').addEventListener('click', e => { if (e.target && e.target.id === 'ap') closeAddSheet(); });
    $('#ap').addEventListener('keydown', e => { if (e.key === 'Escape') closeAddSheet(); });
    $('#ap-cam').addEventListener('click', startCamera);
    $('#ap-up').addEventListener('click', () => $('#ap-file').click());
    $('#ap-file').addEventListener('change', e => fromFile(e.target));
    $('#ap-cam-file').addEventListener('change', e => fromFile(e.target));
    $('#ap-snap').addEventListener('click', capture);
    $('#ap-cancel').addEventListener('click', () => { stopCamera(); showPhoto(null); });
    $('#ap-redo').addEventListener('click', () => showPhoto(null));
    $('#ap-name').addEventListener('input', seasonHint);
    $('#ap-cat').addEventListener('change', seasonHint);
    $('#ap-form').addEventListener('submit', async e => {
      e.preventDefault();
      const btn = $('#ap-save'); btn.disabled = true;
      try {
        const f = readForm();
        if (editing) {
          if (photo === editPhoto0) delete f.image; else if (!photo) { delete f.image; f.remove_image = true; }
          await userStore.update(editing, f);
        } else {
          await userStore.add(f);
        }
        editing = null; closeAddSheet(); await drawUserProducts();
      } catch (err) { apError(String((err && err.message) || err)); } finally { btn.disabled = false; }
    });
    $('#up-list').addEventListener('click', async e => {
      const via = e.target.closest('[data-add-via]');
      if (via) {                                    // straight to the camera or the file picker, inside the same click
        openAddSheet();
        if (via.dataset.addVia === 'camera') startCamera(); else { const f = $('#ap-file'); if (f.click) f.click(); }
        return;
      }
      const ed = e.target.closest('[data-edit]');
      if (ed) { const it = userCache.find(x => x.id === ed.dataset.edit); if (it) openAddSheet(it); return; }
      const b = e.target.closest('[data-remove]');
      if (!b) return;
      if (b.dataset.armed !== '1') { b.dataset.armed = '1'; b.textContent = 'Remove it?'; setTimeout(() => { b.dataset.armed = ''; b.textContent = 'Remove'; }, 4000); return; }
      try { await userStore.remove(b.dataset.remove); await drawUserProducts(); } catch (err) { b.textContent = 'Not removed'; }
    });
  }

  /* ---------------------------------------------------------------- festive planner */
  PAGES.festive = v => {
    const F = D('festive'), G = F.groups, up = upcoming(366);                 // the next twelve months
    const st = Object.assign({fest: up.length ? up[0].key : null, lead: 10, q: ''}, mem.get('festive', {}));
    st.lead = clamp(Math.round(+st.lead) || 10, 1, 30);
    st.q = String(st.q || '').slice(0, 120);
    if (!up.some(f => f.key === st.fest)) st.fest = up.length ? up[0].key : null;
    const save = () => mem.set('festive', st);
    v.innerHTML = `<p class="eyebrow">${ico('lamp')}Festive planner</p><h1 class="page">Know the season. <mark>Stock up</mark> before it.</h1>
      <p class="lede">Festivals and special days decide what goes in the basket: diyas before Diwali, rakhis before Raksha Bandhan, til and jaggery before Sankranti, a grooming kit or perfume before Father's Day. Here is every festival and special day of the next twelve months (the calendar keeps itself up to date for years ahead), what is traditionally bought for it, and what Blinkit had on the shelf on the one day it was observed. It tells you <b>when</b> to have stock ready. It cannot tell you <b>how much</b> more will sell: there are no orders in the data.</p>
      ${up.length ? '' : `<p class="banner warn">${ico('alert')}<span>The calendar runs to ${esc(F.festivals[F.festivals.length - 1].end)} and every festival in it has passed. Extend it in src/seasonal/festive.py.</span></p>`}
      <div class="side fest-top"><div id="f-next"></div>
        <div class="panel" id="f-look"><h3>${ico('search')}When is a product in season?</h3><p class="note">Type a product or a festival. The answer comes from the festival calendar.</p>
          <form class="ask" id="f-form" autocomplete="off"><input id="f-q" type="text" value="${esc(st.q)}" placeholder="handmade diya, scented candle, kaju katli, rakhi" aria-label="Product or festival"><button class="btn" type="submit">Check</button></form>
          <div class="sugg">${['Handmade diya', 'Rakhi', 'Perfume gift set', 'Razor', 'Chocolates', 'Kaju katli', 'Plum cake', 'Balloons'].map(x => `<button type="button" data-fq="${esc(x)}">${esc(x)}</button>`).join('')}</div>
          <div id="f-out"></div></div></div>
      <div class="controls mt"><div class="ctl"><label for="f-lead">Have stock on the shelf <b id="f-lead-v"></b> before a festival</label><input type="range" id="f-lead" min="1" max="30" step="1" value="${st.lead}"></div>
        <p class="fine" style="margin:0;max-width:56ch">Your assumption, not a model output: how long your store takes to order, receive and shelve stock. Every "stock up by" date on this page moves with it.</p></div>
      <h2>Coming up</h2><p class="sub">Dates up to Oct 2027 come from public panchang and holiday calendars ${chip('EXTERNAL')}, checked ${esc(F.calendar_checked)}. Every other date is computed for Bhubaneswar from the positions of the sun and moon ${chip('METHOD')}, the way a panchang does; that method gives back all ${F.almanac_check ? F.almanac_check.same_day : 19} cited dates exactly. Lunar dates can differ by a day between panchangs. Tap one to see what to stock.</p>
      <div class="fest-list" id="f-list"></div>
      <div id="f-detail"></div>
      <div id="f-yours"></div>
      <h2>In season, month by month</h2><p class="sub">Which product types each month's festivals call for, read off the calendar. A filled cell is a festival, not a measured sales peak.</p>
      <div class="panel"><div class="tbl" id="f-season"></div></div>
      <div class="panel mt"><div class="lists">
        <div><h4>What this page knows</h4><ul><li>When each festival and special day falls: cited calendars to Oct 2027 ${chip('EXTERNAL')}, computed for every year after ${chip('METHOD')}</li><li>Which product types are traditionally bought for it: a rule of the planner ${chip('METHOD')}</li><li>Which matching products Blinkit listed, at what price, in or out of stock, on the day it was collected</li></ul></div>
        <div><h4>What it does not know</h4><ul><li>How much more anything sells at a festival, or for how long: there are no orders in the data</li><li>How festive stock behaves: the one observed day, in July, was not a festival</li><li>How much to stock: that is yours to set, from your own sales</li></ul></div>
        <div><h4>What would change that</h4><ul><li>Logging these products daily through Diwali, sized on <a href="#plan">Plan the panel</a></li><li>A store's own sales history, which this project does not have</li></ul></div>
      </div></div>`;
    if (!up.length) return;
    const groupNames = f => f.groups.map(k => G[k].label);
    const drawNext = () => {
      const f = up[0], s = festState(f, st.lead);
      $('#f-next').innerHTML = `<div class="fest-next"><div class="fn-top"><span class="pill ${s.cls}">${esc(s.tag)}</span>${f.local ? '<span class="pill">big in Odisha</span>' : ''}</div>
        <p class="fn-k">Next up</p><p class="fn-name">${esc(f.name)}</p>
        <p class="fn-date">${esc(fmtD(dOf(f.day), {weekday: 'long'}))}${f.start !== f.end ? ` · ${esc(fmtD(dOf(f.start)))} to ${esc(fmtD(dOf(f.end)))}` : ''}</p>
        <div class="fn-count"><b>${Math.max(0, s.s)}</b><span>${s.s > 0 ? (s.s === 1 ? 'day to go' : 'days to go') : 'it has started'}</span></div>
        <p class="fn-stock">Have on the shelf ${s.left > 0 ? `by <b>${esc(fmtD(s.by))}</b>` : '<b>now</b>'}: ${esc(groupNames(f).slice(0, 4).join(', '))}${f.groups.length > 4 ? ' and more' : ''}.</p>
        <button class="btn" type="button" data-fest="${esc(f.key)}">See what to stock ${ico('arrow')}</button></div>`;
    };
    const drawList = () => {
      $('#f-list').innerHTML = up.map(f => {
        const s = festState(f, st.lead), d = dOf(f.day);
        return `<button type="button" class="fcard${s.s <= 14 ? ' soon' : ''}" data-fest="${esc(f.key)}" aria-pressed="${f.key === st.fest}">
          <span class="fd"><b>${d.getDate()}</b><i>${esc(d.toLocaleDateString('en-IN', {month: 'short'}))}</i></span>
          <span class="fi"><span class="nm">${esc(f.name)}</span><span class="fine">${s.s <= 0 ? 'on now' : `in ${s.s} day${s.s === 1 ? '' : 's'}`} · ${esc(s.tag)}</span></span></button>`;
      }).join('');
    };
    const groupCard = (k, f) => {
      const g = G[k];
      const body = g.listings ? `<p class="note">${g.products} product${g.products === 1 ? '' : 's'} in ${g.listings} Blinkit listings · ${pct(g.out_of_stock_share, 0)} out of stock${g.median_price != null ? ` · typical price ${rs(g.median_price)}` : ''}</p>
          <ul class="mini">${g.examples.slice(0, 4).map(e => `<li>${thumb(e.name, e.category, e.pack)}<span>${esc(e.name)}${e.pack ? ` <i>${esc(e.pack)}</i>` : ''}</span><b>${e.price != null ? rs(e.price) : '—'}</b><span class="pill ${e.in_stock ? 'yes' : 'bad'}">${e.in_stock ? 'in stock' : 'out'}</span></li>`).join('')}</ul>`
        : `<p class="note"><b>None listed on Blinkit.</b> Nothing on the shelf matched. A gap to fill before ${esc(f.name)}, or a product the shelf simply did not carry yet.</p>`;
      return `<div class="panel fgroup"><h3><span class="gi">${ico(g.icon)}</span>${esc(g.label)} ${chip('REAL')}</h3>${body}</div>`;
    };
    const drawDetail = () => {
      const f = up.find(x => x.key === st.fest) || up[0], s = festState(f, st.lead);
      const src = f.provenance === 'METHOD' ? `${chip('METHOD')} computed${f.approximate ? ', approximate' : ''}`
        : f.sources.length ? f.sources.map((u, i) => `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">source ${i + 1}</a>`).join(' · ') : 'fixed date';
      $('#f-detail').innerHTML = `<h2>What to stock for ${esc(f.name)} <span class="pill ${s.cls}">${esc(s.tag)}</span></h2>
        <p class="sub">${esc(fmtD(dOf(f.day), {weekday: 'long'}))}${s.s > 0 ? `, ${s.s} day${s.s === 1 ? '' : 's'} away` : ''}. ${esc(f.note)} <span class="fine">${src}</span></p>
        <div class="grid3">${f.groups.map(k => groupCard(k, f)).join('')}</div>`;
    };
    const drawSeason = () => {
      const t = today0(), months = Array.from({length: 12}, (_, i) => new Date(t.getFullYear(), t.getMonth() + i, 1));
      const inMonth = (f, m) => { const a = dOf(f.start), b = dOf(f.end); return (a.getFullYear() === m.getFullYear() && a.getMonth() === m.getMonth()) || (b.getFullYear() === m.getFullYear() && b.getMonth() === m.getMonth()); };
      const head = months.map((m, i) => `<th class="${i === 0 ? 'cur' : ''}">${esc(m.toLocaleDateString('en-IN', {month: 'short'}))}${m.getMonth() === 0 || i === 0 ? `<small>${m.getFullYear()}</small>` : ''}</th>`).join('');
      const rows = Object.keys(G).map(k => `<tr><th class="r">${ico(G[k].icon)}${esc(G[k].label)}</th>${months.map((m, i) => {
        const fs = up.filter(f => f.groups.includes(k) && inMonth(f, m));
        return `<td class="${fs.length ? 'on' : ''}${i === 0 ? ' cur' : ''}"${fs.length ? tipAttr(`${G[k].label}: ${fs.map(f => `${f.name} ${fmtD(dOf(f.day))}`).join(', ')}`) : ''}>${fs.length ? esc(fs.map(f => f.name.split(' ')[0]).join(' · ')) : ''}</td>`;
      }).join('')}</tr>`).join('');
      $('#f-season').innerHTML = `<table class="season"><thead><tr><th class="r">Product type</th>${head}</tr></thead><tbody>${rows}</tbody></table>`;
    };
    const look = () => {
      const out = $('#f-out');
      if (!st.q) { out.innerHTML = ''; return; }
      const r = festMatch(st.q);
      if (!r.groups.length && !r.fests.length) {
        out.innerHTML = `<div class="look"><p class="note"><b>No festival tie for <q class="echo">${esc(st.q)}</q> in this calendar.</b> It covers ${esc(Object.values(G).map(g => g.label.toLowerCase()).join(', '))}.</p></div>`;
        return;
      }
      const pick = r.fests.length ? up.filter(f => r.fests.includes(f.key) && (!r.groups.length || f.groups.some(k => r.groups.includes(k))))[0] || up.find(f => r.fests.includes(f.key))
        : up.find(f => f.groups.some(k => r.groups.includes(k)));
      const parts = r.groups.slice(0, 2).map(k => {
        const fs = up.filter(f => f.groups.includes(k));
        if (!fs.length) return `<p class="note"><b>${esc(G[k].label)}</b>: no festival in the next twelve months calls for it.</p>`;
        const s = festState(fs[0], st.lead);
        return `<p class="lk"><span class="gi">${ico(G[k].icon)}</span><span><b>${esc(G[k].label)}</b> are in season for ${fs.map(f => `${esc(f.name)} (${esc(fmtD(dOf(f.day)))})`).join(', ')}.
          <span class="fine">Next: ${esc(fs[0].name)}, ${s.s > 0 ? `${s.s} days away` : 'on now'}. Have stock on the shelf ${s.left > 0 ? 'by ' + esc(fmtD(s.by)) : 'now'}.</span></span></p>`;
      });
      if (!r.groups.length && pick) parts.push(`<p class="lk"><span class="gi">${ico('lamp')}</span><span><b>${esc(pick.name)}</b>, ${esc(fmtD(dOf(pick.day), {weekday: 'short'}))}: ${esc(groupNames(pick).join(', '))}.</span></p>`);
      out.innerHTML = `<div class="look">${parts.join('')}</div>`;
      if (pick && pick.key !== st.fest) { st.fest = pick.key; drawList(); drawDetail(); }
    };
    const redraw = () => { $('#f-lead-v').textContent = st.lead + (st.lead === 1 ? ' day' : ' days'); drawNext(); drawList(); drawDetail(); drawSeason(); look(); save(); };
    const choose = (key, scroll) => {
      if (!up.some(f => f.key === key)) return;
      st.fest = key; drawList(); drawDetail(); save();
      if (scroll) { const d = $('#f-detail'); if (d.scrollIntoView) d.scrollIntoView({behavior: 'smooth', block: 'start'}); }
    };
    $('#f-list').addEventListener('click', e => { const b = e.target.closest('[data-fest]'); if (b) choose(b.dataset.fest, false); });
    $('#f-next').addEventListener('click', e => { const b = e.target.closest('[data-fest]'); if (b) choose(b.dataset.fest, true); });
    $('#f-look').addEventListener('click', e => { const b = e.target.closest('[data-fq]'); if (b) { st.q = String(b.dataset.fq || '').slice(0, 120); $('#f-q').value = st.q; look(); save(); } });
    $('#f-form').addEventListener('submit', e => { e.preventDefault(); st.q = String($('#f-q').value || '').trim().slice(0, 120); look(); save(); });
    $('#f-lead').addEventListener('input', e => { st.lead = clamp(Math.round(+e.target.value) || 10, 1, 30); redraw(); });
    redraw();
    festYours();
  };

  /* ---------------------------------------------------------------- plan the panel */
  PAGES.plan = v => {
    const R = D('reality').plan;
    const st = Object.assign({di: R.days.indexOf(14), pi: R.products.indexOf(R.watch), per: 2, sec: R.seconds, q: 'oos_rate'}, mem.get('plan', {}));
    if (!R.days[st.di]) st.di = R.days.indexOf(14);
    if (!R.products[st.pi]) st.pi = R.products.indexOf(R.watch);
    if (!R.q.some(x => x.key === st.q)) st.q = 'oos_rate';
    if (st.per !== 1 && st.per !== 2) st.per = 2;
    st.sec = clamp(+st.sec || R.seconds, 5, 60);
    const cell = (q, di, pi) => R.cells[q][String(st.per)][di == null ? st.di : di][pi == null ? st.pi : pi];
    const unit = q => q.unit ? ' ' + plain(q.unit) : '';
    v.innerHTML = `<p class="eyebrow">${ico('calendar')}Plan the panel</p><h1 class="page">How much hand-logged data would be <mark>enough</mark>?</h1>
      <p class="lede">${chip('SYNTHETIC')} A market panel has to be logged by hand. Pick a size a person could log: the simulated panel is cut down to it 200 times and each cut is estimated the plain way. A quantity counts as identified when 9 cuts in 10 land within its target. This is a planning guess: it holds if the market is about as noisy as the Lab.</p>
      <div class="controls"><div class="ctl"><span>Products, on all four apps</span>${segs('n-prod', R.products.map((p, i) => [i, p + (p === R.watch ? ' · watchlist' : '')]), st.pi)}</div>
        <div class="ctl"><label for="n-days">Days <b id="n-days-v"></b></label><input type="range" id="n-days" min="0" max="${R.days.length - 1}" step="1" value="${st.di}"></div>
        <div class="ctl"><span>Checks a day</span>${segs('n-per', [[2, 'Morning and evening'], [1, 'Morning only']], st.per)}</div>
        <div class="ctl"><label for="n-sec">Seconds per observation, assumed <b id="n-sec-v"></b></label><input type="range" id="n-sec" min="5" max="60" step="5" value="${st.sec}"></div></div>
      <div id="n-tiles"></div>
      <div class="grid2"><div class="panel"><h3>What this panel pins down</h3><p class="note">How many of the 200 cuts land within each target. Tap a row to see it across every panel size.</p><div id="n-rows"></div></div>
        <div class="panel"><h3 id="n-title"></h3><p class="note" id="n-note"></p><div class="tbl" id="n-heat"></div><p class="note" id="n-transfer" style="margin-top:12px"></p></div></div>
      <div class="panel mt"><h3>Four things to take from it</h3><div class="lists" style="margin-top:16px">
        <div><h4>Days and products buy different things</h4><ul><li>The price gap and the cheapest-of-4 share are limited by products. More days barely help.</li><li>The evening delivery time is limited by days.</li></ul></div>
        <div><h4>A short panel is precisely wrong about restocking</h4><ul><li>A window only holds spells shorter than itself. The mean out-of-stock spell reads ${fix(-R.bias['2'], 2)} checks too short in a 2-day panel and ${fix(-R.bias['14'], 2)} at 14, while looking just as tight.</li></ul></div>
        <div><h4>Once a day keeps the cross-section only</h4><ul><li>Mornings only halves the work and still gives the price gap. It cannot estimate anything that needs the half-day step.</li></ul></div>
        <div><h4>One observed fact widens the stock-out answer</h4><ul><li>${R.cluster.real == null ? 'Run the store audit to fill this in.' : `On the observed day, records of one product run out together at ${fix(R.cluster.real, 1)} times the base rate. The Lab plants ${fix(R.cluster.syn, 2)} times.`}</li></ul></div></div></div>`;
    const draw = () => {
      const d = R.days[st.di], p = R.products[st.pi], obs = d * st.per * 4 * p, hrs = obs * st.sec / 3600;
      $('#n-days-v').textContent = d + (d === 1 ? ' day' : ' days'); $('#n-sec-v').textContent = st.sec + ' s';
      $$('#n-prod button').forEach(b => b.setAttribute('aria-pressed', String(+b.dataset.v === st.pi)));
      $$('#n-per button').forEach(b => b.setAttribute('aria-pressed', String(+b.dataset.v === st.per)));
      $('#n-tiles').innerHTML = tiles([[int(obs), 'observations to log'], [fix(hrs / d, 1) + ' h', `a day, at ${st.sec} s each`], [fix(hrs, 0) + ' h', 'in total'],
        [`${R.q.filter(q => cell(q.key)[3]).length} of ${R.q.length}`, 'quantities identified']]);
      $('#n-rows').innerHTML = R.q.map(q => {
        const c = cell(q.key), na = q.both && st.per === 1;
        return `<button type="button" class="row" data-q="${q.key}" style="width:100%;text-align:left;background:${q.key === st.q ? 'var(--soft)' : 'none'};border:0;border-bottom:1px solid var(--line);border-radius:8px;cursor:pointer;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr) auto;padding-inline:8px">
          <span class="lab">${pe(q.label)}<small>full panel: ${fix(q.full, q.tol < 0.1 ? 3 : 2)}${pe(q.suffix)}</small></span><span class="fine">${na || c[0] == null ? 'cannot be estimated' : `${pct(c[1], 0)} of cuts within ±${q.tol}${unit(q)}`}</span>
          ${na ? '<span class="pill na">needs both checks</span>' : c[3] ? '<span class="pill yes">identified</span>' : '<span class="pill no">not yet</span>'}</button>`;
      }).join('');
      const q = R.q.find(x => x.key === st.q), na = q.both && st.per === 1;
      $('#n-title').textContent = plain(q.label) + ', across every panel size';
      $('#n-note').textContent = `Each cell: the share of 200 cuts within ±${q.tol}${unit(q)} of the full-panel value, ${st.per === 2 ? 'logging morning and evening' : 'logging mornings only'}. Outlined in blue: identified. Tap a cell to choose that panel.`;
      $('#n-heat').innerHTML = `<table class="heat"><thead><tr><th class="r">products ↓ days →</th>${R.days.map(x => `<th>${x}</th>`).join('')}</tr></thead><tbody>` + R.products.map((pp, pi) => `<tr><th class="r">${pp}</th>` + R.days.map((dd, di) => {
        const c = cell(q.key, di, pi);
        if (na || c[0] == null) return `<td class="na"${tipAttr(`${dd} days, ${pp} products: cannot be estimated`)}>–</td>`;
        return `<td class="${c[3] ? 'id ' : ''}${di === st.di && pi === st.pi ? 'sel' : ''}" data-di="${di}" data-pi="${pi}" style="background:var(--soft);background:color-mix(in srgb, var(--blue) ${Math.round(55 * c[1])}%, var(--card))"${tipAttr(`${dd} days, ${pp} products: ${pct(c[1], 0)} of cuts within target; half-width ±${fix(c[0], 2)}${unit(q)}; bias ${sgn(c[2], 2)}`)}>${Math.round(100 * c[1])}</td>`;
      }).join('') + '</tr>').join('') + '</tbody></table>';
      $('#n-transfer').textContent = 'What carries over to the market: ' + plain(q.transfer);
      mem.set('plan', st);
    };
    onSeg('n-prod', val => { st.pi = clamp(+val | 0, 0, R.products.length - 1); draw(); });
    onSeg('n-per', val => { st.per = +val === 1 ? 1 : 2; draw(); });
    $('#n-days').addEventListener('input', e => { st.di = clamp(+e.target.value | 0, 0, R.days.length - 1); draw(); });
    $('#n-sec').addEventListener('input', e => { st.sec = clamp(+e.target.value || R.seconds, 5, 60); draw(); });
    $('#n-rows').addEventListener('click', e => { const b = e.target.closest('[data-q]'); if (b && R.q.some(x => x.key === b.dataset.q)) { st.q = b.dataset.q; draw(); } });
    const pick = e => { const c = e.target.closest('td[data-di]'); if (c) { st.di = clamp(+c.dataset.di | 0, 0, R.days.length - 1); st.pi = clamp(+c.dataset.pi | 0, 0, R.products.length - 1); $('#n-days').value = st.di; draw(); } };
    $('#n-heat').addEventListener('click', pick);
    $('#n-heat').addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(e); } });
    draw();
  };

  /* ---------------------------------------------------------------- pipeline */
  PAGES.pipeline = v => {
    const R = D('pipeline'), M = D('meta'), max = Math.max(...R.steps.map(s => s.seconds), 1);
    const secs = s => s >= 90 ? fix(s / 60, 1) + ' min' : fix(s, 1) + ' s';
    const groups = Object.entries(R.groups).filter(([g]) => R.steps.some(s => s.group === g));
    const GROUP = {audit: 'Audits of the observed day', planner: 'Planning the hand-logged panel'};
    const K = R.contracts, needs = R.needs || {};
    const state = s => s.ok ? ['ok', 'OK'] : s.blocked_by ? ['wait', 'BLOCKED'] : s.timed_out ? ['bad', 'TIMEOUT'] : ['bad', 'FAIL'];
    v.innerHTML = `<p class="eyebrow">${ico('route')}Pipeline</p><h1 class="page">One command runs <mark>all of it</mark></h1>
      <p class="lede">Every step below is a run of the documented command, in dependency order. Each step names the steps it needs: when one fails, everything downstream is blocked instead of running on stale inputs. This site is the last step: it is rebuilt from the outputs the others saved. <code>python scripts/run_all.py</code></p>
      ${tiles([[`${M.run.ok} of ${M.run.steps}`, 'steps passing'], [`${M.run.passed} of ${M.run.tests}`, 'tests passing'], K ? [`${K.passed} of ${K.passed + K.failed}`, 'data contracts holding'] : null, [`${M.ledger.numbers}`, 'doc numbers checked against outputs'], [esc((M.run.finished || '').slice(0, 10)), 'last run recorded']].filter(Boolean))}
      ${K ? `<h2>Data contracts ${chip('METHOD')}</h2>
      <p class="sub">The invariants every model relies on, checked as one gate right after the data layer is built (${esc(String(K.seconds))} s on ${esc((K.checked || '').slice(0, 10))}). Each one has a planted-violation test that it must catch. <code>python -m src.pipeline.contracts</code></p>
      <div class="contracts">${K.items.map(c => `<div class="ct" title="${esc(c.id)}"><span class="pill ${c.ok ? 'ok' : 'bad'}">${c.ok ? ico('check') + 'Holds' : 'Broken'}</span><span class="ct-r">${pe(c.rule)}</span><small>${pe(c.observed)}<br><span class="ct-ref">${esc(c.id)} · ${pe(c.ref)}</span></small></div>`).join('')}</div>` : ''}
      <div class="legend" style="margin-top:var(--s6)"><span><b>No tag</b>: built only from the Blinkit data</span><span>${chip('SYNTHETIC')} uses the simulated panel</span></div>
      ${groups.map(([g, label]) => `<h2>${pe(GROUP[g] || label)}</h2><div class="panel" style="padding:8px var(--pad)">${R.steps.filter(s => s.group === g).map(s => `<details class="step"><summary>
          <span class="pill ${state(s)[0]}">${state(s)[1]}</span><span class="nm" title="${esc(s.step)}">${pe(s.step)}</span><span class="wh">${pe(s.what.replace(/\s*\((REAL|SYNTHETIC)[^)]*\)/g, ''))} ${s.outputs.map(o => o.scope ? chip(o.scope) : '').filter((x, i, a) => a.indexOf(x) === i).join(' ')}</span>
          <span class="tm"><i><b style="width:${Math.max(2, 100 * Math.sqrt(s.seconds / max))}%"></b></i><span>${secs(s.seconds)}</span></span></summary>
          <p class="fine" style="margin:0 0 4px 4px">${esc(s.command)}${s.reused ? ' · recorded in an earlier pass' : ''}</p>
          ${(needs[s.step] || []).length ? `<p class="needs"><span class="fine">needs</span>${needs[s.step].map(n => `<code title="${esc(n)}">${pe(n)}</code>`).join('')}</p>` : ''}
          ${s.tail.length ? `<pre class="log">${pe(s.tail.join('\n'))}</pre>` : ''}<div style="height:10px"></div></details>`).join('')}</div>`).join('')}
      <h2>Tests</h2><p class="sub">${pe(R.summary)}</p>
      <div class="panel"><div class="tbl"><table class="t"><thead><tr><th>Test file</th><th class="n">Passed</th><th class="n">Failed</th></tr></thead><tbody>
      ${R.tests.map(t => `<tr><td title="${esc(t.file)}">${pe(t.file)}</td><td class="n">${t.passed}</td><td class="n">${t.failed}</td></tr>`).join('')}</tbody></table></div></div>
      <p class="foot-note">Not run by the pipeline, on purpose: the panel simulator and the raw-data patches (the raw files are frozen and hash-checked by the first step), and the labelling tools, which need a person. Log lines and file names are shown in this site's wording for the two data tags; hover a name for the exact one.</p>`;
  };

  /* ================================================================== the basket: which app is cheapest for all of it
     A followed listing is priced at its one Lab check; a product you added, at the prices you entered. Every line keeps
     its tag, a total that mixes the two says so, and an app without a price for some line is shown but not ranked. */
  const basket = {
    items() {
      const b = mem.get('basket', []);
      return Array.isArray(b) ? b.filter(x => x && typeof x.k === 'string' && +x.q > 0).map(x => ({k: x.k, q: clamp(Math.round(+x.q) || 1, 1, 99)})) : [];
    },
    save(list) { mem.set('basket', list.slice(0, 60)); basketSync(); },
    has(k) { return this.items().some(x => x.k === k); },
    add(k) { const l = this.items(), it = l.find(x => x.k === k); if (it) it.q = clamp(it.q + 1, 1, 99); else l.push({k, q: 1}); this.save(l); },
    set(k, q) { const l = this.items(), it = l.find(x => x.k === k); if (!it) return; if (q <= 0) this.save(l.filter(x => x.k !== k)); else { it.q = clamp(q, 1, 99); this.save(l); } },
    remove(k) { this.save(this.items().filter(x => x.k !== k)); },
    clear() { this.save([]); },
  };
  /* what a basket key stands for now: a followed listing (x:name) or one of your products (u:id); null once it is gone */
  function basketLine(k) {
    k = String(k || '');
    if (k.indexOf('x:') === 0) {
      const c = D('explorer').chains.find(x => x.name === k.slice(2));
      return c ? {k, name: c.name, cat: c.category, pack: c.pack, prov: 'SYNTHETIC', prices: c.dec.comp, at: c.dec.at} : null;
    }
    if (k.indexOf('u:') === 0) {
      const p = userCache.find(x => x.id === k.slice(2));
      if (!p) return null;
      const prices = {};
      P.forEach(pl => { const v = +((p.prices || {})[pl]); if (v > 0) prices[pl] = v; });
      return {k, name: p.name, cat: p.category, pack: p.pack, prov: 'USER', prices, img: imgSrc(p.image)};
    }
    return null;
  }
  function basketTotals(lines) {
    return P.map((pl, i) => {
      let total = 0, missing = 0;
      for (const ln of lines) { const v = +ln.prices[pl]; if (v > 0) total += v * ln.q; else missing += 1; }
      return {pl, i, total: Math.round(total * 100) / 100, missing};
    });
  }
  function drawBasket() {
    const body = $('#bk-body');
    if (!body) return;
    const lines = basket.items().map(x => { const ln = basketLine(x.k); return ln ? Object.assign(ln, {q: x.q}) : null; }).filter(Boolean);
    if (!lines.length) {
      body.innerHTML = `<div class="bk-empty"><span class="gi">${ico('cart')}</span><b>Your basket is empty</b>
        <p class="note">Press <span class="kb-plus">${ico('plus')}</span> on a product to add it, then see which of the four apps would charge least for all of it.</p>
        <a class="btn pop" href="#listings" data-bk-close>${ico('grid')}Browse products</a></div>`;
      return;
    }
    const T = basketTotals(lines), ranked = T.filter(t => !t.missing);
    const low = ranked.length ? Math.min(...ranked.map(t => t.total)) : null, high = ranked.length ? Math.max(...ranked.map(t => t.total)) : null;
    const max = Math.max(...T.map(t => t.total), 1), best = ranked.filter(t => t.total === low);
    const provs = new Set(lines.map(l => l.prov)), n = lines.reduce((s, l) => s + l.q, 0);
    const verdict = !ranked.length ? 'No app has a price for every line yet. Add the missing prices to your products to compare them.'
      : ranked.length === 1 ? `Only <b>${esc(ranked[0].pl)}</b> has a price for every line: ${rs(ranked[0].total)}.`
      : best.length === ranked.length ? `Every app costs the same for this basket: ${rs(low)}.`
      : `<b>${esc(best.map(t => t.pl).join(' and '))}</b> is cheapest for this basket, ${rs(high - low)} (${pct((high - low) / high)}) below the dearest app.`;
    const at = (lines.find(l => l.at) || {}).at;
    body.innerHTML = `<p class="bk-verdict">${verdict}</p>
      <div class="bk-apps">${T.map(t => {
        const top = !t.missing && t.total === low && ranked.length > 1 && best.length < ranked.length;
        return `<div class="bk-app${top ? ' best' : ''}"><span class="bk-pl">${pname(t.i)}${top ? '<span class="pill deal">cheapest</span>' : ''}</span>
          <b>${t.missing ? `<span class="fine">${t.missing} line${t.missing === 1 ? '' : 's'} without a price</span>` : rs(t.total)}</b>
          <span class="bk-meter"><i class="c${t.i}" style="width:${t.missing ? 0 : (100 * t.total / max).toFixed(1)}%"></i></span></div>`;
      }).join('')}</div>
      <h3 class="bk-h">${n} item${n === 1 ? '' : 's'}</h3>
      <div class="bk-lines">${lines.map(l => `<div class="bk-line">${l.img ? `<span class="thumb"><img src="${esc(l.img)}" alt=""></span>` : thumb(l.name, l.cat, l.pack)}
        <span class="bk-nm"><b>${esc(l.name)}</b><span>${chip(l.prov)} ${esc(l.pack || '')}</span></span>
        <span class="qty"><button type="button" data-bq="${esc(l.k)}" data-d="-1" aria-label="One fewer ${esc(l.name)}">${ico('minus')}</button><span>${l.q}</span><button type="button" data-bq="${esc(l.k)}" data-d="1" aria-label="One more ${esc(l.name)}">${ico('plus')}</button></span></div>`).join('')}</div>
      <p class="fine bk-note">${provs.has('SYNTHETIC') ? `${chip('SYNTHETIC')} Followed listings are priced at one check in the Lab${at ? ` (${esc(at)})` : ''}, not at today's shop price. ` : ''}${provs.has('USER') ? `${chip('USER')} Your products use the prices you entered. ` : ''}${provs.size > 1 ? 'This basket mixes the two. ' : ''}Delivery fees and coupons are not included.</p>
      ${shopPanel(lines, best.length && best.length < ranked.length ? best[0].pl : (ranked[0] || T[0]).pl)}
      <div class="bk-acts"><button type="button" class="btn ghost" data-bk-clear>Empty the basket</button><a class="btn pop" href="#listings" data-bk-close>${ico('plus')}Add more</a></div>`;
  }
  /* ---- from the basket to the app: each line opens the app's own search for that product, where it goes in the cart.
     No outside site can fill a Blinkit, Instamart, Flipkart or BigBasket cart: they offer no way to, by design. */
  const SHOP = {
    'Blinkit': q => 'https://blinkit.com/s/?q=' + encodeURIComponent(q),
    'Swiggy Instamart': q => 'https://www.swiggy.com/instamart/search?custom_back=true&query=' + encodeURIComponent(q),
    'Flipkart Minutes': q => 'https://www.flipkart.com/search?q=' + encodeURIComponent(q) + '&marketplace=HYPERLOCAL',
    'BigBasket': q => 'https://www.bigbasket.com/ps/?q=' + encodeURIComponent(q),
  };
  const shopQuery = l => String(l.name || '').replace(/\*+/g, '').replace(/\s+/g, ' ').trim() + (l.pack ? ' ' + String(l.pack).replace(/\*+/g, '').trim() : '');
  const shopLink = (app, l, label) => `<a class="shop-link" href="${esc(SHOP[app](shopQuery(l)))}" target="_blank" rel="noopener noreferrer"
    title="Opens ${esc(app)}'s search for this product in a new tab">${label || 'Find on ' + esc(app)} <svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg></a>`;
  let shopApp = null;
  function shopPanel(lines, cheapest) {
    const app = P.includes(shopApp) ? shopApp : cheapest;
    return `<div class="shop" id="bk-shop"><div class="shop-head"><b>${ico('cart')}Shop it on ${esc(app)}</b>${app === cheapest ? '<span class="pill deal">cheapest here</span>' : ''}</div>
      <div class="segs shop-apps" role="group" aria-label="Which app">${P.map((p, i) => `<button type="button" data-shop-app="${esc(p)}" aria-pressed="${p === app}"><i class="pdot c${i}"></i>${esc(p.split(' ')[0])}</button>`).join('')}</div>
      <ol class="shop-list">${lines.map(l => `<li><span>${l.q} × ${esc(l.name)}</span>${shopLink(app, l, 'Add on ' + esc(app.split(' ')[0]))}</li>`).join('')}</ol>
      <p class="fine" style="margin:0">Each link opens ${esc(app)}'s own search for that product in a new tab, where you add it to your cart. The app may first ask where to deliver or ask you to sign in, as it would on its own site. ShelfPulse cannot fill another app's cart, and the price there is today's, which can differ from the one above.</p></div>`;
  }
  function basketSync() {
    const items = basket.items(), cnt = $('#bk-count'), keys = new Set(items.map(x => x.k));
    const n = items.reduce((s, x) => s + (basketLine(x.k) ? x.q : 0), 0);          // a product removed since is not counted
    if (cnt) { cnt.textContent = String(n); cnt.hidden = !n; }
    $$('[data-basket]').forEach(b => {
      const on = keys.has(b.dataset.basket);
      if (b.getAttribute('aria-pressed') !== String(on)) { b.setAttribute('aria-pressed', String(on)); b.innerHTML = ico(on ? 'check' : 'plus'); }
    });
    const box = $('#basket');
    if (box && !box.hidden) drawBasket();
  }
  function openBasket() {
    const box = $('#basket');
    if (!box) return;
    palClose();
    box.hidden = false; document.body.classList.add('noscroll');
    drawBasket();
    const c = $('#bk-close'); if (c && c.focus) c.focus();
  }
  function closeBasket() { const box = $('#basket'); if (box && !box.hidden) { box.hidden = true; document.body.classList.remove('noscroll'); } }
  function bump(el) { if (!el || !el.classList) return; el.classList.remove('bump'); void el.offsetWidth; el.classList.add('bump'); }
  $('#bk-btn').addEventListener('click', openBasket);
  $('#bk-close').addEventListener('click', closeBasket);
  $('#basket').addEventListener('click', e => { if (e.target === $('#basket')) closeBasket(); });
  document.addEventListener('click', e => {
    const t = e.target;
    if (!t || !t.closest) return;
    const add = t.closest('[data-basket]');
    if (add) {
      e.preventDefault();
      const k = add.dataset.basket, ln = basketLine(k), on = basket.has(k);
      if (!ln) { toast('That product is no longer on the list', 'alert'); return; }
      if (on) basket.remove(k); else basket.add(k);
      toast(on ? `Took ${ln.name} out of the basket` : `Added ${ln.name} to the basket`, on ? 'minus' : 'cart');
      bump($('#bk-btn'));
      return;
    }
    const q = t.closest('[data-bq]');
    if (q) { const it = basket.items().find(x => x.k === q.dataset.bq); if (it) basket.set(it.k, it.q + (+q.dataset.d || 0)); return; }
    const sa = t.closest('[data-shop-app]');
    if (sa) { if (P.includes(sa.dataset.shopApp)) { shopApp = sa.dataset.shopApp; drawBasket(); } return; }
    if (t.closest('[data-bk-clear]')) { basket.clear(); toast('The basket is empty', 'cart'); return; }
    if (t.closest('[data-bk-close]')) closeBasket();
  });

  /* ================================================================== a toast, and sharing the page you are on */
  let toastTimer = null;
  function toast(msg, icon) {
    const t = $('#toast');
    if (!t) return;
    t.innerHTML = `${ico(icon || 'check')}<span>${esc(msg)}</span>`;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 2600);
  }
  const touch = () => typeof matchMedia === 'function' && matchMedia('(pointer: coarse)').matches;
  function shareLink() {
    const url = String(location.href || '');
    const nav = typeof navigator !== 'undefined' ? navigator : null;
    try {
      if (nav && nav.share && touch()) { nav.share({title: document.title, url}).catch(() => null); return; }
      if (nav && nav.clipboard && nav.clipboard.writeText) {
        nav.clipboard.writeText(url).then(() => toast('Link to this page copied', 'link'), () => toast('Copy this link: ' + url, 'link'));
        return;
      }
    } catch (e) { /* fall through to showing the link */ }
    toast('Copy this link: ' + url, 'link');
  }
  $('#share').addEventListener('click', shareLink);

  /* ================================================================== go anywhere: Ctrl K (or /) opens a command palette */
  let palItems = [], palSel = 0;
  const palOpenNow = () => { const p = $('#pal'); return !!p && !p.hidden; };
  function palIndex() {
    const out = NAV.map(([p, l, i]) => ({kind: 'Page', name: l, meta: 'Go to ' + l, icon: i, go: () => goTo(p)}));
    out.push({kind: 'Action', name: 'Take the tour', meta: 'Seven stops through what the site can do', icon: 'play', go: () => tourShow(0)},
      {kind: 'Action', name: 'Open the basket', meta: 'Which app is cheapest for everything you picked', icon: 'cart', go: openBasket},
      {kind: 'Action', name: 'Switch light or dark', meta: 'Theme', icon: 'moon', go: toggleTheme},
      {kind: 'Action', name: 'Share this page', meta: 'Copy a link to what you are looking at', icon: 'share', go: shareLink},
      {kind: 'Action', name: 'Ask the analyst', meta: 'Open the chat', icon: 'chat', go: openDock});
    for (const it of searchIndex()) {
      out.push({kind: {listing: 'Product', yours: 'Yours', festival: 'Festival', item: 'Festive item'}[it.kind] || 'Product', name: it.name,
        meta: it.meta, cat: it.cat, pack: it.pack, icon: it.kind === 'festival' ? 'lamp' : null, go: it.go});
    }
    for (const q of D('meta').suggested) out.push({kind: 'Ask', name: q, meta: 'Ask the analyst', icon: 'chat', go: () => { openDock(); ask(q); }});
    return out;
  }
  function palDraw() {
    const raw = String(($('#pal-q') || {}).value || '').trim(), q = raw.toLowerCase(), words = q.split(/\s+/).filter(Boolean);
    let list = palIndex();
    if (words.length) {
      list = list.filter(it => words.every(w => (it.name + ' ' + (it.meta || '') + ' ' + it.kind).toLowerCase().includes(w)))
        .map((it, i) => [it.name.toLowerCase().indexOf(q) === 0 ? 0 : it.name.toLowerCase().includes(q) ? 1 : 2, i, it]).sort((a, b) => a[0] - b[0] || a[1] - b[1]).map(x => x[2]);
    } else list = list.filter(it => it.kind !== 'Festive item' && it.kind !== 'Product');
    list = list.slice(0, 12);
    if (raw) list.push({kind: 'Ask', name: 'Ask the analyst', meta: raw, icon: 'chat', go: () => { openDock(); ask(raw); }});
    palItems = list; palSel = 0;
    const box = $('#pal-list');
    if (box) box.innerHTML = list.map((it, i) => `<button type="button" class="pal-it" role="option" data-pi="${i}" aria-selected="${i === 0}">${it.icon ? `<span class="pi">${ico(it.icon)}</span>` : thumb(it.name, it.cat, it.pack)}<span class="pt"><b>${esc(it.name)}</b><i>${esc(it.meta || '')}</i></span><em>${esc(it.kind)}</em></button>`).join('');
  }
  function palMove(d) {
    if (!palItems.length) return;
    palSel = (palSel + d + palItems.length) % palItems.length;
    $$('#pal-list .pal-it').forEach((b, i) => { b.setAttribute('aria-selected', String(i === palSel)); if (i === palSel && b.scrollIntoView) b.scrollIntoView({block: 'nearest'}); });
  }
  function palPick(i) { const it = palItems[i]; palClose(); if (it) it.go(); }
  function palOpen() {
    const p = $('#pal'), inp = $('#pal-q');
    if (!p) return;
    closeBasket();
    p.hidden = false; document.body.classList.add('noscroll');
    if (inp) inp.value = '';
    palDraw();
    if (inp && inp.focus) inp.focus();
  }
  function palClose() { const p = $('#pal'); if (p && !p.hidden) { p.hidden = true; document.body.classList.remove('noscroll'); } }
  $('#pal-btn').addEventListener('click', palOpen);
  $('#pal-q').addEventListener('input', palDraw);
  $('#pal-q').addEventListener('keydown', e => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); palMove(e.key === 'ArrowDown' ? 1 : -1); }
    else if (e.key === 'Enter') { e.preventDefault(); palPick(palSel); }
  });
  $('#pal-list').addEventListener('click', e => { const b = e.target.closest('[data-pi]'); if (b) palPick(+b.dataset.pi); });
  $('#pal').addEventListener('click', e => { if (e.target === $('#pal')) palClose(); });
  document.addEventListener('keydown', e => {
    const tag = String((e.target && e.target.tagName) || ''), typing = /^(INPUT|TEXTAREA|SELECT)$/.test(tag) || (e.target && e.target.isContentEditable);
    if ((e.ctrlKey || e.metaKey) && String(e.key).toLowerCase() === 'k') { e.preventDefault(); if (palOpenNow()) palClose(); else palOpen(); return; }
    if (e.key === '/' && !typing && !palOpenNow()) { e.preventDefault(); palOpen(); return; }
    if (e.key === 'Escape') { palClose(); closeBasket(); }
  });

  /* ================================================================== motion: reveal on scroll, count-up, the reading bar
     All of it is decoration. It is off for anyone who asked for reduced motion and for automated browsers (the
     browser check and the screenshots must see every element in its final state), and the page is complete without it. */
  const mq = s => typeof matchMedia === 'function' && matchMedia(s).matches;
  const automated = typeof navigator !== 'undefined' && (navigator.webdriver || /HeadlessChrome/.test(String(navigator.userAgent || '')));
  if (automated) root.classList.add('still');                // CSS animations off too, so screenshots are never mid-sweep
  const canMotion = () => !mq('(prefers-reduced-motion: reduce)') && typeof matchMedia === 'function' && !automated;
  const canHover = () => mq('(hover: hover) and (pointer: fine)');
  let revealer = null;
  function countUp(tile) {
    const v = tile.querySelector('.v'), raf = typeof requestAnimationFrame === 'function' ? requestAnimationFrame : null;
    if (!v || !raf) return;
    const txt = v.textContent, m = /^([\d,]+)$/.exec(String(txt).trim());
    if (!m) return;
    const end = +m[1].replace(/,/g, '');
    if (!(end >= 20)) return;
    const t0 = performance.now(), dur = 950;
    const step = now => {
      const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      v.textContent = p < 1 ? Math.round(end * e).toLocaleString('en-IN') : txt;
      if (p < 1) raf(step);
    };
    raf(step);
  }
  function reveal(scope) {
    if (!canMotion() || typeof IntersectionObserver !== 'function') return;
    if (!revealer) {
      revealer = new IntersectionObserver(entries => entries.forEach(en => {
        if (!en.isIntersecting) return;
        const el = en.target, d = parseFloat(el.style.getPropertyValue('--rv-d')) || 0;
        revealer.unobserve(el);
        el.classList.add('in');
        if (el.classList.contains('tile')) countUp(el);
        setTimeout(() => { el.classList.remove('rv', 'in'); el.style.removeProperty('--rv-d'); }, 760 + d * 1000);   // hover effects take over again
      }), {rootMargin: '0px 0px -6% 0px', threshold: 0.06});
    }
    const groups = new Map();
    $$('.tile, .mode-card, .shelf > .pwrap, .panel, .mrow, .fcard, .tracker, .board, .receipt, .fest-banner, .add-promo, .ct, .fest-next', scope).forEach(el => {
      if (el.parentNode && el.parentNode.closest && el.parentNode.closest('.rv')) return;   // its parent already moves
      const n = groups.get(el.parentNode) || 0;
      groups.set(el.parentNode, n + 1);
      el.style.setProperty('--rv-d', (Math.min(n, 7) * 0.06).toFixed(2) + 's');
      el.classList.add('rv');
      revealer.observe(el);
    });
  }
  (function scrollUi() {
    const bar = $('#progress'), up = $('#totop');
    let ticking = false;
    const update = () => {
      ticking = false;
      const de = document.documentElement, y = window.scrollY || de.scrollTop || 0;
      const max = Math.max(1, (de.scrollHeight || 0) - (window.innerHeight || 0));
      if (bar && bar.style && bar.style.setProperty) bar.style.setProperty('--p', clamp(y / max, 0, 1).toFixed(4));
      if (up) up.hidden = y < 900;
    };
    window.addEventListener('scroll', () => { if (!ticking) { ticking = true; (typeof requestAnimationFrame === 'function' ? requestAnimationFrame : setTimeout)(update); } }, {passive: true});
    window.addEventListener('resize', update, {passive: true});
    if (up) up.addEventListener('click', () => { window.scrollTo({top: 0, behavior: canMotion() ? 'smooth' : 'auto'}); const n = $('#nav a[aria-current]'); if (n && n.focus) n.focus({preventScroll: true}); });
    update();
  })();
  /* a light that follows the pointer on the mode cards, and the price board on Home tilting toward it */
  if (canHover()) {
    document.addEventListener('pointermove', e => {
      const t = e.target && e.target.closest ? e.target : null;
      if (!t) return;
      const glow = t.closest('.mode-card, .ct, .fest-banner');
      if (glow) { const r = glow.getBoundingClientRect(); glow.style.setProperty('--mx', (e.clientX - r.left).toFixed(0) + 'px'); glow.style.setProperty('--my', (e.clientY - r.top).toFixed(0) + 'px'); }
      const bd = canMotion() ? t.closest('.hero .board') : null;
      if (bd) {
        const r = bd.getBoundingClientRect(), x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
        bd.style.setProperty('--ry', (x * 6).toFixed(2) + 'deg'); bd.style.setProperty('--rx', (-y * 6).toFixed(2) + 'deg');
      }
    }, {passive: true});
    document.addEventListener('pointerout', e => {
      const bd = e.target && e.target.closest ? e.target.closest('.hero .board') : null;
      if (bd && !(e.relatedTarget && bd.contains(e.relatedTarget))) { bd.style.removeProperty('--rx'); bd.style.removeProperty('--ry'); }
    });
  }
  /* offline once loaded: on https (the live site) and on localhost; opened from disk or over the Wi-Fi, it runs without */
  try {
    const secure = typeof location !== 'undefined' && (location.protocol === 'https:' || /^(localhost|127\.0\.0\.1|\[::1\])$/.test(String(location.hostname)));
    if (secure && typeof navigator !== 'undefined' && navigator.serviceWorker) {
      window.addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => null));
    }
  } catch (e) { /* offline support is optional */ }

  /* ================================================================== the tour: a guided walk for presenting the site
     Seven stops. Each opens its page, does one thing on it (a preset, a question), dims everything but the part that
     matters and says in one line why it matters. Arrow keys or Enter move on, Esc ends. Started by the button on Home,
     from Ctrl K, or by opening the site with ?tour in the address. The page stays usable underneath: the dimming does
     not catch clicks. Captions use the project's own saved numbers, never typed-in ones. */
  const TOUR = () => {
    const M = D('meta'), obs = M.mix.reduce((s, m) => s + m.real, 0);
    const first = sel => () => $(sel);
    return [
      {page: 'home', el: first('.hero'), t: 'One day of Blinkit, collected by hand',
        x: `Quick-commerce apps publish no data, so ${int(obs)} Blinkit listings were logged by hand. Everything on the site says whether it was observed or simulated in the Lab.`},
      {page: 'findings', el: first('.findings'), t: 'What the data itself revealed',
        x: 'Four findings, none simulated: a data defect the anomaly detector caught on its own, stock-outs that cluster by product, prices labelled observed that were looked up on the web, and a store column that carries no information.'},
      {page: 'listings', el: first('#x-shelf'), t: 'Every product, every layer',
        x: 'Each card is one listing followed end to end: the observed price, the same product matched on the other apps, what each model predicts, the prices it can post, a simulation and the move it recommends, with the reason.'},
      {page: 'simulate', act: () => { const b = $('[data-preset="0"]'); if (b) b.click(); }, el: first('#s-out'), t: 'What if Blinkit runs a Diwali sale?',
        x: 'Pick an app and a price change. Rivals follow a leader, so the gain is smaller than the naive estimate; both are shown. Answered instantly from runs worked out in advance, not guessed in the browser.'},
      {page: 'optimize', el: first('#opt-body'), t: 'The smallest cut that reaches a goal',
        x: 'Set a goal such as cheapest for 40 of every 100 products, and get the smallest price cut that reaches it, with and without competitors responding. It never claims profit: there is no cost or sales data.'},
      {page: 'analyst', act: () => ask('What is Blinkit revenue?'), el: first('[data-thread]'), t: 'An analyst that knows what it does not know',
        x: 'Ask in plain words. Every claim carries its source and date, and a question the data cannot answer, like revenue or demand, is turned down before anything is looked up.'},
      {page: 'data', el: () => $('#view .panel'), t: 'Every number says where it came from',
        x: `One observed day, thirty simulated ones, and the site never blurs them. ${M.contracts ? `${M.contracts.passed} of ${M.contracts.total} data contracts` : 'Data contracts'} and ${M.run.passed} of ${M.run.tests} tests gate every run.`},
    ];
  };
  let tourAt = -1, tourSteps = null, tourRaf = 0;
  const tourOn = () => tourAt >= 0;
  function tourPlace() {
    tourRaf = 0;
    const s = tourSteps && tourSteps[tourAt], spot = $('#tour-spot');
    if (!s || !spot) return;
    const el = s.el && s.el();
    if (!el || !el.getBoundingClientRect) { spot.classList.add('none'); return; }
    // the lit area sits between the sticky header and the caption card, so the card never covers what it points at
    const r = el.getBoundingClientRect(), vh = window.innerHeight || 800, pad = 10;
    const hd = $('header.top'), card = $('#tour-card');
    const ceil = hd && hd.getBoundingClientRect ? Math.max(8, hd.getBoundingClientRect().bottom + 6) : 8;
    const floor = card && !card.hidden && card.getBoundingClientRect ? card.getBoundingClientRect().top - 12 : vh - 8;
    const top = Math.max(r.top - pad, ceil), bottom = Math.min(r.bottom + pad, floor);
    spot.classList.toggle('none', bottom - top < 24);
    spot.style.cssText = `top:${top}px;left:${r.left - pad}px;width:${r.width + 2 * pad}px;height:${Math.max(0, bottom - top)}px`;
  }
  const tourQueue = () => { if (tourOn() && !tourRaf) tourRaf = (typeof requestAnimationFrame === 'function' ? requestAnimationFrame : setTimeout)(tourPlace); };
  function tourShow(i) {
    if (!tourOn() && i === 0) tourSteps = null;                 // a fresh tour does each stop's action again
    tourSteps = tourSteps || TOUR();
    tourAt = clamp(i, 0, tourSteps.length - 1);
    const s = tourSteps[tourAt], card = $('#tour-card');
    document.body.classList.add('touring');
    closeDock(); palClose(); closeBasket();
    if (location.hash.slice(1) !== s.page) goTo(s.page);
    const n = tourSteps.length, last = tourAt === n - 1;
    card.innerHTML = `<div class="tc-main"><div class="tc-top"><span class="tc-n">${tourAt + 1} / ${n}</span><span class="tc-dots">${tourSteps.map((_, k) => `<i${k === tourAt ? ' class="on"' : ''}></i>`).join('')}</span></div>
      <h3>${esc(s.t)}</h3><p>${esc(s.x)}</p></div>
      <div class="tc-side"><button type="button" class="tc-x" id="tour-x" aria-label="End the tour">${ico('x')}</button>
        <div class="tc-acts"><button type="button" class="btn ghost" id="tour-back"${tourAt ? '' : ' disabled'}>Back</button>
        <button type="button" class="btn pop" id="tour-next">${last ? 'Finish' : 'Next'}${last ? '' : ico('arrow')}</button></div>
        <p class="tc-keys"><kbd>←</kbd> <kbd>→</kbd> · <kbd>Esc</kbd></p></div>`;
    card.hidden = false; $('#tour-spot').hidden = false;
    $('#tour-x').addEventListener('click', tourEnd);
    $('#tour-back').addEventListener('click', () => tourShow(tourAt - 1));
    $('#tour-next').addEventListener('click', () => (last ? tourEnd() : tourShow(tourAt + 1)));
    // the page redraws on the next tick after the address changes: act on it then, let an answer arrive, then bring
    // the part that matters into view and light it. A stop's action runs once per tour, so Back does not repeat it.
    const at = tourAt;
    setTimeout(() => {
      if (tourAt !== at) return;
      try { if (s.act && !s.done) { s.done = true; s.act(); } } catch (e) { /* the stop still shows */ }
      setTimeout(() => {
        if (tourAt !== at) return;
        const el = s.el && s.el(), hd = $('header.top');
        if (el && el.getBoundingClientRect && typeof window.scrollTo === 'function') {
          const head = hd && hd.getBoundingClientRect ? hd.getBoundingClientRect().bottom : 0;
          window.scrollTo({top: Math.max(0, (window.scrollY || 0) + el.getBoundingClientRect().top - head - 22), behavior: canMotion() ? 'smooth' : 'auto'});
        }
        tourQueue(); setTimeout(tourQueue, 450); setTimeout(tourQueue, 900);
      }, s.act ? 300 : 30);
    }, 80);
    const nb = $('#tour-next'); if (nb && nb.focus) nb.focus({preventScroll: true});
  }
  function tourEnd() {
    tourAt = -1;
    const card = $('#tour-card'), spot = $('#tour-spot');
    if (card) card.hidden = true; if (spot) spot.hidden = true;
    document.body.classList.remove('touring');
    try { if (/[?&]tour\b/.test(String(location.search))) history.replaceState(null, '', location.pathname + location.hash); } catch (e) { /* the address keeps it */ }
  }
  window.addEventListener('scroll', tourQueue, {passive: true});
  window.addEventListener('resize', tourQueue, {passive: true});
  document.addEventListener('keydown', e => {
    if (!tourOn()) return;
    const tag = String((e.target && e.target.tagName) || '');
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag)) return;
    if (e.key === 'Escape') { e.preventDefault(); tourEnd(); }
    else if (e.key === 'ArrowRight' || (e.key === 'Enter' && !(e.target && e.target.closest && e.target.closest('button, a')))) { e.preventDefault(); if (tourAt < tourSteps.length - 1) tourShow(tourAt + 1); else tourEnd(); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); tourShow(tourAt - 1); }
  });
  document.addEventListener('click', e => { if (e.target.closest && e.target.closest('[data-tour]')) { e.preventDefault(); tourShow(0); } });

  /* ================================================================== ticker, router */
  (function ticker() {
    // observed findings first: the Lab's cheapest-of-four shares only give back what the simulator was built with
    const M = D('meta'), E = D('analystEval');
    const ev = E.browser ? E.browser.summary : null;
    const items = [
      `<b>Blinkit</b> ${int(M.mix.reduce((s, m) => s + m.real, 0))} listings collected by hand`,
      ...obsFindings().map(f => `<b>${esc(f.big)}</b> ${esc(f.cap)}`),
      `<b>${M.run.passed} of ${M.run.tests}</b> tests passing`,
      ev ? `<b>Analyst</b> turns down ${ev.tuning.refused_when_it_must + ev.holdout.refused_when_it_must} of ${ev.tuning.must_refuse + ev.holdout.must_refuse} questions it must` : '<b>Analyst</b> answers with its sources',
      `<b>${M.ledger.numbers}</b> doc numbers checked against saved results`,
    ].filter(Boolean).map(t => `<span class="it">${t}</span>`).join('');
    $('#ticker').innerHTML = items + items;
  })();
  const view = $('#view');
  function route(first) {
    const h = location.hash.slice(1), page = PAGES[h] ? h : 'home';
    $$('.nav a, #more-menu a').forEach(a => { if (a.dataset.page === page) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
    const inMore = NAV.some(n => n[0] === page && n[4]);
    if (moreBtn) { moreBtn.classList.toggle('on', inMore); moreBtn.innerHTML = `${ico('more')}${inMore ? esc(NAV.find(n => n[0] === page)[1]) : 'More'}`; }
    moreClose();
    tip.hidden = true;
    try { PAGES[page](view); } catch (e) {
      view.innerHTML = `<h1 class="page">This page could not be drawn</h1><p class="lede">${esc(String((e && e.message) || e))}</p>`;
    }
    palClose(); closeBasket(); hideDrop();
    if (canMotion()) { view.classList.remove('enter'); void view.offsetWidth; view.classList.add('enter'); }
    reveal(view);
    basketSync();
    if (!first) { window.scrollTo(0, 0); view.focus({preventScroll: true}); }
    const cur = $('.nav a[aria-current]'); if (cur && cur.scrollIntoView) cur.scrollIntoView({block: 'nearest', inline: 'nearest'});
  }
  window.addEventListener('hashchange', () => { route(false); tourQueue(); });
  route(true);
  // ?tour in the address starts the tour: one link to open on the presenting screen (not in automated browsers,
  // whose checks must see the pages undimmed)
  try { if (/[?&]tour\b/.test(String(location.search)) && !automated) setTimeout(() => tourShow(0), 400); } catch (e) { /* no tour */ }
  /* what the checks need: the wording filter and the answer renderer, as the pages use them */
  window.QCSite = {plain, answerHtml, srcLabel, internal,
    basket: {add: k => basket.add(k), remove: k => basket.remove(k), set: (k, q) => basket.set(k, q), clear: () => basket.clear(),
             items: () => basket.items(), line: basketLine, totals: basketTotals, open: openBasket, close: closeBasket},
    palette: {open: palOpen, close: palClose, index: palIndex, draw: palDraw, pick: palPick}, toast, shareLink, toggleTheme};
})();
