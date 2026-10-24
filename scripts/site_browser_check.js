/*
 * site_browser_check.js — open the served site in a real browser (headless Chrome or Edge), use it, and take pictures.
 *
 *     python scripts/serve_site.py --no-open          (in another terminal)
 *     node scripts/site_browser_check.js [http://localhost:8000] [output folder]
 *
 * What site_smoke.js cannot see, this can: the page as drawn. For every page, in light and dark, on a desktop and a
 * phone width, it records JavaScript errors and whether the page scrolls sideways, presses each tab, asks the analyst
 * two questions (one it must turn down), and saves screenshots to outputs/site/screens. Exit code 1 on an error or a
 * sideways scroll. It needs node 22+ and an installed Chrome or Edge; nothing is downloaded. A person still has to
 * look at the pictures: it measures overflow and errors, not taste.
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const BASE = (process.argv[2] || 'http://localhost:8000').replace(/\/$/, '');
const OUT = path.resolve(process.argv[3] || path.join(__dirname, '..', 'outputs', 'site', 'screens'));
const BROWSERS = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', 'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe', 'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
];
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function main() {
  const exe = process.env.BROWSER_PATH || BROWSERS.find(p => fs.existsSync(p));
  if (!exe) { console.log('no Chrome or Edge found (set BROWSER_PATH): nothing was checked'); process.exit(0); }
  try { await (await fetch(BASE + '/api/health')).json(); } catch (e) { console.log(`the site is not running at ${BASE}: start it with python scripts/serve_site.py --no-open`); process.exit(1); }
  fs.mkdirSync(OUT, {recursive: true});
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'qcmi-browser-'));
  const port = 9300 + Math.floor(Math.random() * 400);
  const child = spawn(exe, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--hide-scrollbars',
    `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, 'about:blank'], {stdio: 'ignore'});
  const done = code => { try { child.kill(); } catch (e) { /* already gone */ } setTimeout(() => { try { fs.rmSync(profile, {recursive: true, force: true}); } catch (e) { /* the browser may still hold it */ } process.exit(code); }, 400); };
  try {
    let target = null;
    for (let i = 0; i < 60 && !target; i++) {
      await sleep(250);
      try { target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t => t.type === 'page'); } catch (e) { /* not up yet */ }
    }
    if (!target) throw new Error('the browser did not start');
    const ws = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('could not connect to the browser')); });
    let seq = 0;
    const waiting = new Map(), errors = [];
    let where = 'start';
    ws.onmessage = ev => {
      const m = JSON.parse(ev.data);
      if (m.id && waiting.has(m.id)) { const [res, rej] = waiting.get(m.id); waiting.delete(m.id); m.error ? rej(new Error(m.error.message)) : res(m.result); return; }
      if (m.method === 'Runtime.exceptionThrown') errors.push(`${where}: ${(m.params.exceptionDetails.exception && m.params.exceptionDetails.exception.description) || m.params.exceptionDetails.text}`.slice(0, 300));
      if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') errors.push(`${where}: console.error ${m.params.args.map(a => a.value || a.description || '').join(' ')}`.slice(0, 300));
    };
    const send = (method, params) => new Promise((res, rej) => { const id = ++seq; waiting.set(id, [res, rej]); ws.send(JSON.stringify({id, method, params: params || {}})); });
    const run = async js => {
      const r = await send('Runtime.evaluate', {expression: `(async () => { ${js} })()`, awaitPromise: true, returnByValue: true});
      if (r.exceptionDetails) throw new Error((r.exceptionDetails.exception && r.exceptionDetails.exception.description) || r.exceptionDetails.text);
      return r.result.value;
    };
    await send('Page.enable'); await send('Runtime.enable');

    const report = [], sideways = [];
    async function shot(name, opt) {
      opt = opt || {};
      // product photos load lazily from another host, which can take 5 s or more: wait up to 12 s so a capture shows them
      await run(`const ps = [...document.querySelectorAll('img.prod-photo')]; ps.forEach(i => { i.loading = 'eager'; });
        for (let t = 0; t < 120 && ps.some(i => i.isConnected && !i.classList.contains('on')); t++) await new Promise(r => setTimeout(r, 100));`);
      const {cssContentSize: size} = await send('Page.getLayoutMetrics');
      const m = await run(`const d = document.documentElement; return {sw: d.scrollWidth, cw: d.clientWidth, words: (document.body.innerText.match(/\\b(real|synthetic)\\b|snapshot/gi) || []).filter(w => w !== 'Real').length, drawn: !/could not be drawn/.test(document.getElementById('view').innerText)};`);
      if (m.sw > m.cw + 1) sideways.push(`${name}: content is ${m.sw}px wide in a ${m.cw}px window`);
      const csp = await run(`const v = (window.__csp || []).splice(0); return v;`);           // the security policy blocked something
      for (const v of csp || []) errors.push(`${name}: content security policy blocked ${v}`);
      if (m.words) errors.push(`${name}: ${m.words} label word(s) in the visible text`);
      if (!m.drawn) errors.push(`${name}: the page reported it could not be drawn`);
      const full = !opt.viewport;
      const png = await send('Page.captureScreenshot', {format: 'png', captureBeyondViewport: full,
        clip: full ? {x: 0, y: 0, width: Math.ceil(size.width), height: Math.min(Math.ceil(size.height), opt.maxHeight || 5200), scale: 1} : undefined});
      fs.writeFileSync(path.join(OUT, name + '.png'), Buffer.from(png.data, 'base64'));
      report.push(name);
    }
    async function setup(width, height, scheme, mobile) {
      await send('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: mobile ? 2 : 1, mobile: !!mobile});
      await send('Emulation.setEmulatedMedia', {features: [{name: 'prefers-color-scheme', value: scheme}]});
    }
    const go = async page => { where = page; await run(`location.hash = '#${page}'; await new Promise(r => setTimeout(r, 350)); window.scrollTo(0, 0);`); };
    const click = async sel => run(`const el = document.querySelector(${JSON.stringify(sel)}); if (!el) throw new Error('nothing matches ${sel.replace(/'/g, '')}'); el.click(); await new Promise(r => setTimeout(r, 300));`);
    const answered = async () => run(`for (let i = 0; i < 240; i++) { if (!document.querySelector('.typing') && document.querySelector('.ans')) return true; await new Promise(r => setTimeout(r, 250)); } throw new Error('the analyst did not answer within a minute');`);

    // ---- desktop, light
    await setup(1360, 900, 'light');
    where = 'load';
    // a blocked script, style, font or request is not an exception: listen for the policy's own event from the start
    await send('Page.addScriptToEvaluateOnNewDocument', {source: `window.__csp = []; document.addEventListener('securitypolicyviolation', function (e) { window.__csp.push(e.violatedDirective + ' ' + (e.blockedURI || 'inline')); });`});
    await send('Page.navigate', {url: BASE + '/'});
    await run(`for (let i = 0; i < 80 && !document.querySelector('.hero'); i++) await new Promise(r => setTimeout(r, 250)); if (!document.querySelector('.hero')) throw new Error('the home page did not draw'); await document.fonts.ready;`);
    const live = await run(`await new Promise(r => setTimeout(r, 600)); return document.getElementById('dock-mode').textContent;`);
    // offline once loaded: the service worker is running and holds the page itself
    const sw = await run(`if (!navigator.serviceWorker) return 'no service worker support';
      const reg = await Promise.race([navigator.serviceWorker.ready, new Promise(r => setTimeout(() => r(null), 8000))]);
      if (!reg || !reg.active) return 'the service worker did not start';
      for (let i = 0; i < 40; i++) { const hit = await caches.match('./'); if (hit && /QCAnalyst/.test(await hit.clone().text())) return 'ok'; await new Promise(r => setTimeout(r, 250)); }
      return 'the page is not in the offline cache';`);
    if (sw !== 'ok') errors.push(`offline: ${sw}`);
    await shot('01-home-light');
    await go('listings'); await shot('02-products-light');
    await click('#x-shelf [data-pick="6"]'); await shot('03-products-another-light', {maxHeight: 2600});
    // add a product the way a person would: open the sheet, upload a photo, fill the details, save; then remove it
    await go('listings');
    // a check stopped part-way leaves its test product behind; clear it, or this run finds two
    await run(`for (const card of [...document.querySelectorAll('#up-list .ucard')].filter(x => /browser check/.test(x.textContent))) {
        const b = card.querySelector('[data-remove]'); b.click(); b.click(); await new Promise(r => setTimeout(r, 500)); }`);
    await click('#ap-open'); await shot('45-add-sheet-light', {viewport: true});
    await run(`
      const c = document.createElement('canvas'); c.width = 640; c.height = 480; const g = c.getContext('2d');
      g.fillStyle = '#f6e3b4'; g.fillRect(0, 0, 640, 480); g.fillStyle = '#a0522d'; g.beginPath(); g.ellipse(320, 340, 210, 72, 0, 0, Math.PI * 2); g.fill();
      g.fillStyle = '#ff9a1f'; g.beginPath(); g.ellipse(320, 230, 34, 78, 0, 0, Math.PI * 2); g.fill();
      const blob = await new Promise(r => c.toBlob(r, 'image/png'));
      const dt = new DataTransfer(); dt.items.add(new File([blob], 'diya.png', {type: 'image/png'}));
      const inp = document.getElementById('ap-file'); inp.files = dt.files; inp.dispatchEvent(new Event('change', {bubbles: true}));
      for (let i = 0; i < 50 && document.getElementById('ap-prev').hidden; i++) await new Promise(r => setTimeout(r, 100));
      if (document.getElementById('ap-prev').hidden) throw new Error('the uploaded photo was not shown');
      const set = (id, v) => { const el = document.getElementById(id); el.value = v; el.dispatchEvent(new Event('input', {bubbles: true})); };
      set('ap-name', 'Handmade clay diya, set of 12 (browser check)'); set('ap-pack', '12 pcs'); set('ap-eta', '14');
      const pr = document.querySelectorAll('#ap-form [data-plat]'); pr[0].value = '149'; pr[3].value = '139';`);
    await shot('46-add-sheet-filled-light', {viewport: true});
    await run(`document.getElementById('ap-form').requestSubmit();
      for (let i = 0; i < 60 && !document.querySelector('#up-list .ucard'); i++) await new Promise(r => setTimeout(r, 100));
      if (!document.querySelector('#up-list .ucard')) throw new Error('the added product did not appear: ' + document.getElementById('ap-err').textContent);
      document.getElementById('up-list').scrollIntoView({block: 'center'}); await new Promise(r => setTimeout(r, 300));`);
    await shot('47-products-added-light', {viewport: true});
    // edit it: change the pack size, save, and the card changes
    await run(`[...document.querySelectorAll('#up-list .ucard')].find(x => /browser check/.test(x.textContent)).querySelector('[data-edit]').click();
      await new Promise(r => setTimeout(r, 200));
      document.getElementById('ap-pack').value = '24 pcs'; document.getElementById('ap-form').requestSubmit();
      const has = () => [...document.querySelectorAll('#up-list .ucard')].some(x => /24 pcs/.test(x.textContent));
      for (let i = 0; i < 60 && !has(); i++) await new Promise(r => setTimeout(r, 100));
      if (!has()) throw new Error('the edit did not show: ' + document.getElementById('ap-err').textContent);`);
    // search the products page, then the header suggestions
    await run(`window.scrollTo(0, 0); const q = document.getElementById('pf-q'); q.value = 'diya'; q.dispatchEvent(new Event('input', {bubbles: true})); await new Promise(r => setTimeout(r, 300));`);
    await shot('48-products-search-light', {viewport: true});
    await run(`const q = document.getElementById('pf-q'); q.value = ''; q.dispatchEvent(new Event('input', {bubbles: true}));
      const t = document.getElementById('top-q'); t.focus(); t.value = 'mango'; t.dispatchEvent(new Event('input', {bubbles: true})); await new Promise(r => setTimeout(r, 250));
      if (document.getElementById('top-drop').hidden) throw new Error('no suggestions under the header search');`);
    await shot('49-header-suggestions-light', {viewport: true});
    await run(`const t = document.getElementById('top-q'); t.value = ''; t.blur(); await new Promise(r => setTimeout(r, 250));`);
    await go('home'); await shot('50-home-with-your-product-light', {maxHeight: 2800});
    // the basket: two followed listings and the product just added, then which app is cheapest for all of it
    await go('listings');
    await run(`const pause = () => new Promise(r => setTimeout(r, 150)); localStorage.removeItem('qcmi-basket');
      document.querySelectorAll('#x-shelf [data-basket]')[0].click(); await pause();
      document.querySelectorAll('#x-shelf [data-basket]')[3].click(); await pause();
      const mine = [...document.querySelectorAll('#up-list .pwrap')].find(x => /browser check/.test(x.textContent));
      if (!mine || !mine.querySelector('[data-basket]')) throw new Error('your product has no basket button');
      mine.querySelector('[data-basket]').click(); await pause();
      if (document.getElementById('bk-count').textContent !== '3') throw new Error('the basket count reads ' + document.getElementById('bk-count').textContent);`);
    await click('#bk-btn');
    await run(`if (document.getElementById('basket').hidden) throw new Error('the basket did not open');
      if (document.querySelectorAll('.bk-app').length !== 4 || document.querySelectorAll('.bk-line').length !== 3) throw new Error('the basket does not show 4 apps and 3 lines');
      document.querySelector('[data-bq][data-d="1"]').click(); await new Promise(r => setTimeout(r, 150));
      if (document.getElementById('bk-count').textContent !== '4') throw new Error('one more did not count');`);
    await shot('51-basket-light', {viewport: true});
    await run(`const b = document.querySelector('#basket .bk-body'); if (!b || b.scrollWidth > b.clientWidth + 1) throw new Error('the basket runs past its edge: ' + (b && b.scrollWidth) + ' > ' + (b && b.clientWidth));`);   // a drawer scrolls inside itself: the page-wide check cannot see it
    await click('#bk-close');
    // go anywhere: Ctrl K, type, Enter
    await run(`document.dispatchEvent(new KeyboardEvent('keydown', {key: 'k', ctrlKey: true, bubbles: true})); await new Promise(r => setTimeout(r, 200));
      if (document.getElementById('pal').hidden) throw new Error('Ctrl K did not open the palette');
      const q = document.getElementById('pal-q'); q.value = 'diwali'; q.dispatchEvent(new Event('input', {bubbles: true})); await new Promise(r => setTimeout(r, 150));
      if (!document.querySelector('.pal-it')) throw new Error('the palette found nothing for diwali');`);
    await shot('52-palette-light', {viewport: true});
    await run(`document.getElementById('pal-q').dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true})); await new Promise(r => setTimeout(r, 450));
      if (!document.getElementById('pal').hidden || location.hash !== '#festive') throw new Error('Enter did not open the festival: ' + location.hash);`);
    // hover: a product card lifts, its picture turns, the basket button rises
    await go('home');
    const card = await run(`const el = document.querySelector('.shelf:not(.yours) .pcard'); el.scrollIntoView({block: 'center'}); await new Promise(r => setTimeout(r, 250));
      const b = el.getBoundingClientRect(); return {x: b.left + b.width / 2, y: b.top + b.height / 2};`);
    await send('Input.dispatchMouseEvent', {type: 'mouseMoved', x: card.x, y: card.y});
    await sleep(900);
    await shot('53-hover-light', {viewport: true});
    await send('Input.dispatchMouseEvent', {type: 'mouseMoved', x: 2, y: 2});
    // your products travel as a file: export (photo included), remove, import, and the product is back
    await go('listings');
    await run(`const pause = ms => new Promise(r => setTimeout(r, ms));
      const blobs = [], keep = [URL.createObjectURL, HTMLAnchorElement.prototype.click];
      URL.createObjectURL = b => { blobs.push(b); return 'blob:qcom-check'; }; HTMLAnchorElement.prototype.click = function () {};
      try { document.getElementById('up-export').click(); for (let i = 0; i < 40 && !blobs.length; i++) await pause(100); }
      finally { URL.createObjectURL = keep[0]; HTMLAnchorElement.prototype.click = keep[1]; }
      if (!blobs.length) throw new Error('Export produced no file');
      const doc = JSON.parse(await blobs[0].text()), mine = doc.products.find(p => /browser check/.test(p.name));
      if (doc.kind !== 'your-products' || !mine || !/^data:image\\/(png|jpeg|webp);base64,/.test(mine.image || '')) throw new Error('the exported file lacks the product or its photo');
      window.__qcomExport = JSON.stringify(doc);
      const card = [...document.querySelectorAll('#up-list .ucard')].find(x => /browser check/.test(x.textContent));
      const b = card.querySelector('[data-remove]'); b.click(); b.click(); await pause(500);
      if ([...document.querySelectorAll('#up-list .ucard')].some(x => /browser check/.test(x.textContent))) throw new Error('the product was not removed before the import');
      const dt = new DataTransfer(); dt.items.add(new File([window.__qcomExport], 'qcom-products.json', {type: 'application/json'}));
      const inp = document.getElementById('up-file'); inp.files = dt.files; inp.dispatchEvent(new Event('change', {bubbles: true}));
      for (let i = 0; i < 50 && ![...document.querySelectorAll('#up-list .ucard')].some(x => /browser check/.test(x.textContent)); i++) await pause(100);
      const back = [...document.querySelectorAll('#up-list .ucard')].find(x => /browser check/.test(x.textContent));
      if (!back || !back.querySelector('img')) throw new Error('Import did not bring the product back with its photo');`);
    await go('listings');
    await run(`for (const card of [...document.querySelectorAll('#up-list .ucard')].filter(x => /browser check/.test(x.textContent))) {
        const b = card.querySelector('[data-remove]'); b.click(); b.click(); await new Promise(r => setTimeout(r, 500)); }
      if ([...document.querySelectorAll('#up-list .ucard')].some(x => /browser check/.test(x.textContent))) throw new Error('the test product was not removed');`);
    await go('festive'); await shot('40-festive-light');
    await click('#f-look [data-fq="Handmade diya"]'); await shot('41-festive-lookup-light', {viewport: true});
    await go('simulate'); await click('#sim-tabs [data-v="move"]'); await shot('04-simulate-move-light');
    await run(`const pick = (id, v) => { const s = document.getElementById(id); s.value = v; s.dispatchEvent(new Event('change', {bubbles: true})); };
      pick('s-dir', 'raise'); pick('s-size', '5'); pick('s-react', 'no'); await new Promise(r => setTimeout(r, 200));
      const a = document.querySelector('#s-out .answer');
      if (!a || !/raises its prices by 5%.*of every 100/s.test(a.textContent)) throw new Error('the sentence did not answer: ' + (a && a.textContent));`);
    await shot('05-simulate-raise-frozen-light', {maxHeight: 1400});
    for (const [t, n] of [['promo', '06'], ['outage', '07'], ['listing', '08']]) { await click(`#sim-tabs [data-v="${t}"]`); await shot(`${n}-simulate-${t}-light`); }
    await go('optimize');
    for (const [t, n] of [['target', '09'], ['listing', '10'], ['restock', '11']]) { await click(`#opt-tabs [data-v="${t}"]`); await shot(`${n}-optimize-${t}-light`); }
    await go('analyst');
    await run(`const b = [...document.querySelectorAll('#view .sugg button')].find(x => /cuts prices/.test(x.textContent)); b.click();`);
    await answered();
    await run(`const i = document.getElementById('a-input'); i.value = 'What is Blinkit revenue?'; document.getElementById('a-form').requestSubmit();`);
    await sleep(300); await answered();
    await shot('12-analyst-light');
    for (const [p, n] of [['models', '13'], ['data', '14'], ['plan', '15'], ['pipeline', '16']]) { await go(p); await shot(`${n}-${p}-light`); }
    await go('home'); await click('#fab');
    await run(`const i = document.getElementById('dock-input'); i.value = 'Out-of-stock rate by category on 10 Jul'; document.getElementById('dock-form').requestSubmit();`);
    await sleep(300); await answered();
    await shot('17-floating-analyst-light', {viewport: true});
    await click('#dock-close');
    await run(`const i = document.getElementById('top-q'); i.value = 'How much can Blinkit raise prices without losing position?'; document.getElementById('top-search').requestSubmit();`);
    await sleep(300); await answered();
    await shot('18-search-box-asks-light', {viewport: true});
    await click('#dock-close');

    // ---- tablets and a small phone, with touch: iPad upright and sideways, an Android tablet, a 360 px Android phone
    await send('Emulation.setTouchEmulationEnabled', {enabled: true, maxTouchPoints: 5});
    for (const [dev, w, h] of [['ipad', 820, 1180], ['ipad-sideways', 1180, 820], ['android-tablet', 800, 1280], ['android-small', 360, 780]]) {
      await setup(w, h, 'light', true);
      for (const p of ['home', 'listings', 'festive', 'models', 'simulate']) { await go(p); await shot(`t-${dev}-${p}`, {maxHeight: 3600}); }
      await go('listings'); await click('#ap-open'); await shot(`t-${dev}-add-sheet`, {viewport: true}); await click('#ap-close');
    }
    await send('Emulation.setTouchEmulationEnabled', {enabled: false});

    // ---- a wide monitor
    await setup(1920, 1080, 'light');
    for (const [p, n] of [['home', '34'], ['festive', '42'], ['listings', '35'], ['simulate', '36'], ['optimize', '37'], ['analyst', '38'], ['models', '39']]) { await go(p); await shot(`${n}-${p}-wide`, {maxHeight: 3200}); }

    // ---- desktop, dark
    await setup(1360, 900, 'dark');
    for (const [p, n] of [['home', '19'], ['festive', '44'], ['simulate', '20'], ['optimize', '21'], ['analyst', '22'], ['data', '23']]) { await go(p); await shot(`${n}-${p}-dark`, {maxHeight: 3000}); }
    await go('pipeline'); await shot('54-pipeline-dark', {maxHeight: 3000});
    await click('#bk-btn'); await shot('55-basket-dark', {viewport: true}); await run(`const b = document.querySelector('#basket .bk-body'); if (!b || b.scrollWidth > b.clientWidth + 1) throw new Error('the basket runs past its edge: ' + (b && b.scrollWidth) + ' > ' + (b && b.clientWidth));`); await click('#bk-close');

    // ---- phone
    await setup(390, 844, 'light', true);
    for (const [p, n] of [['home', '24'], ['festive', '43'], ['listings', '25'], ['simulate', '26'], ['optimize', '27'], ['analyst', '28'], ['models', '29'], ['data', '30'], ['plan', '31'], ['pipeline', '32']]) { await go(p); await shot(`${n}-${p}-phone`, {maxHeight: 4200}); }
    await go('home'); await click('#fab'); await shot('33-floating-analyst-phone', {viewport: true});
    await click('#dock-close'); await click('#bk-btn'); await shot('56-basket-phone', {viewport: true}); await run(`const b = document.querySelector('#basket .bk-body'); if (!b || b.scrollWidth > b.clientWidth + 1) throw new Error('the basket runs past its edge: ' + (b && b.scrollWidth) + ' > ' + (b && b.clientWidth));`); await click('#bk-close');
    await click('#pal-btn'); await shot('57-palette-phone', {viewport: true});
    await run(`document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); await new Promise(r => setTimeout(r, 150));
      if (!document.getElementById('pal').hidden) throw new Error('Escape did not close the palette');`);

    console.log(JSON.stringify({browser: path.basename(exe), analyst: live, offline: sw, screenshots: report.length, folder: OUT, errors: errors.length, sideways_scroll: sideways.length}));
    for (const e of [...new Set(errors)]) console.log('ERROR', e);
    for (const s of sideways) console.log('SIDEWAYS', s);
    ws.close();
    done(errors.length || sideways.length ? 1 : 0);
  } catch (e) {
    console.log('FAILED', e && e.message ? e.message : e);
    done(1);
  }
}
main();
