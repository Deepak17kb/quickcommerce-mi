"""
build_run_page.py — one page that shows the last end-to-end run: every step, whether it worked, how long it took, what
it rewrote (with each output's REAL / SYNTHETIC scope from its manifest), the tail of its console output, and the tests.

    python scripts/run_all.py && python scripts/build_run_page.py     # -> outputs/showcase/run_log.html
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / 'outputs' / 'run_log' / 'run_all.json'
MODELS = ROOT / 'outputs' / 'models'
OUT = ROOT / 'outputs' / 'showcase' / 'run_log.html'

GROUPS = {'data': 'Data layer', 'matching': 'Model 1 · product matcher', 'audit': 'Audits of the REAL snapshot',
          'models': 'Models 2–10', 'simulate': 'Simulate & optimise', 'planner': 'Planning the real panel',
          'chain': 'Product × store chain', 'analyst': 'AI analyst', 'pages': 'Showcase pages'}


def scope(name: str) -> str:
    p = MODELS / name / 'manifest.json'
    if not p.exists():
        return ''
    s = json.loads(p.read_text(encoding='utf-8')).get('claim_scope', '')
    return 'REAL' if s.startswith('REAL') else 'SYNTHETIC' if s.startswith('SYNTHETIC') else ''


def planned() -> list:
    import importlib.util
    spec = importlib.util.spec_from_file_location('run_all', ROOT / 'scripts' / 'run_all.py')
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod.STEPS


def payload() -> dict:
    run = json.loads(LOG.read_text(encoding='utf-8'))
    for s in run['steps']:
        s['outputs'] = [{'name': n, 'scope': scope(n)} for n in s.pop('outputs_rewritten')]
    ran = {s['step'] for s in run['steps']}
    run['not_run'] = [{'group': g, 'step': n, 'what': w, 'command': 'python ' + ' '.join(
        a if ' ' not in a else f'"{a}"' for a in args)} for g, n, w, args in planned() if n not in ran]
    run['groups'] = GROUPS
    return run


PAGE = r'''<title>Quickcommerce Run Log</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@100..125,500..800&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
:root {
  color-scheme: light;
  --page: #eef2f0; --surface: #f7f9f8; --ink: #0f1512; --ink-2: #48514c; --muted: #6f7873;
  --grid: #dde4e0; --rule: rgba(15,21,18,.12); --blue: #2a78d6;
  --ok: #1f7a4d; --ok-bg: rgba(31,122,77,.12); --bad: #c2410c; --bad-bg: rgba(194,65,12,.12);
  --real: #2a78d6; --syn: #8a5a00; --bar: #9fb0a7; --code: #e6ebe8;
  --display: "Archivo", "Arial Narrow", Arial, sans-serif;
  --sans: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0c0f0d; --surface: #141816; --ink: #edf2ee; --ink-2: #b8c1bc; --muted: #8d9690;
    --grid: #232a26; --rule: rgba(237,242,238,.12); --blue: #3987e5;
    --ok: #4cc38a; --ok-bg: rgba(76,195,138,.14); --bad: #f08a5d; --bad-bg: rgba(240,138,93,.14);
    --real: #6aa8f0; --syn: #e0b04a; --bar: #4a5a52; --code: #0a0d0b;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0c0f0d; --surface: #141816; --ink: #edf2ee; --ink-2: #b8c1bc; --muted: #8d9690;
  --grid: #232a26; --rule: rgba(237,242,238,.12); --blue: #3987e5;
  --ok: #4cc38a; --ok-bg: rgba(76,195,138,.14); --bad: #f08a5d; --bad-bg: rgba(240,138,93,.14);
  --real: #6aa8f0; --syn: #e0b04a; --bar: #4a5a52; --code: #0a0d0b;
}
* { box-sizing: border-box; }
body { background: var(--page); color: var(--ink); font: 15px/1.55 var(--sans); margin: 0; }
.wrap { max-width: 1040px; margin: 0 auto; padding-inline: 20px; padding-block: 28px 64px; }
h1 { font-family: var(--display); font-variation-settings: "wdth" 125; font-weight: 800; font-size: clamp(30px, 5.4vw, 44px);
     line-height: 1; letter-spacing: -.02em; margin: 0 0 8px; text-wrap: balance; }
.sub { color: var(--ink-2); margin: 0 0 18px; max-width: 72ch; }
.sub code { font: 13px var(--mono); }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 1px; background: var(--rule);
         border: 1px solid var(--rule); margin-bottom: 26px; }
.stats div { background: var(--surface); padding: 12px 14px; }
.stats .v { font: 600 24px/1.1 var(--sans); display: block; font-variant-numeric: tabular-nums; }
.stats .v.ok { color: var(--ok); } .stats .v.bad { color: var(--bad); }
.stats .l { font-size: 12.5px; color: var(--muted); display: block; margin-top: 4px; }
h2 { font: 600 13px var(--mono); letter-spacing: .07em; text-transform: uppercase; color: var(--muted);
     margin: 28px 0 8px; display: flex; gap: 10px; align-items: baseline; }
h2 span { font-weight: 500; letter-spacing: 0; text-transform: none; }
.steps { border-top: 1px solid var(--rule); }
.step { border-bottom: 1px solid var(--rule); }
.step > summary { list-style: none; cursor: pointer; display: grid; align-items: center; gap: 4px 14px; padding: 10px 4px;
                  grid-template-columns: 52px minmax(0, 1.1fr) minmax(0, 1.6fr) 150px; }
.step > summary::-webkit-details-marker { display: none; }
.step > summary:hover { background: var(--surface); }
.step > summary:focus-visible { outline: 2px solid var(--blue); outline-offset: -2px; }
.pill { font: 600 11px/1 var(--mono); letter-spacing: .05em; padding: 5px 0; border-radius: 3px; text-align: center; }
.pill.ok { color: var(--ok); background: var(--ok-bg); } .pill.bad { color: var(--bad); background: var(--bad-bg); }
.pill.wait { color: var(--muted); border: 1px dashed var(--muted); font-size: 9.5px; letter-spacing: 0; }
.name { font: 500 13.5px var(--mono); overflow-wrap: anywhere; }
.what { color: var(--ink-2); font-size: 14px; }
.chips { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 3px; }
.chip { font: 500 11px var(--mono); padding: 1px 6px; border-radius: 3px; border: 1px solid var(--rule); color: var(--ink-2); }
.chip.REAL { border-color: var(--real); color: var(--real); } .chip.SYNTHETIC { border-color: var(--syn); color: var(--syn); }
.time { display: grid; grid-template-columns: 1fr 58px; gap: 8px; align-items: center; }
.time i { display: block; height: 6px; background: var(--grid); border-radius: 3px; overflow: hidden; }
.time i b { display: block; height: 100%; background: var(--bar); }
.time span { font: 500 12.5px var(--mono); text-align: right; font-variant-numeric: tabular-nums; }
.body { padding: 2px 4px 14px 66px; }
.cmd { font: 12.5px var(--mono); color: var(--ink-2); margin: 0 0 8px; overflow-wrap: anywhere; }
.cmd b { color: var(--ink); font-weight: 500; }
pre { margin: 0; background: var(--code); border: 1px solid var(--rule); border-radius: 4px; padding: 10px 12px; font: 12px/1.5 var(--mono);
      color: var(--ink); overflow-x: auto; max-height: 360px; }
.tests { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 8px; }
.tf { background: var(--surface); border: 1px solid var(--rule); border-radius: 4px; padding: 10px 12px; }
.tf b { font: 500 13px var(--mono); display: block; overflow-wrap: anywhere; }
.tf span { font-size: 13px; color: var(--ink-2); font-variant-numeric: tabular-nums; }
.tf .f { color: var(--bad); font-weight: 600; }
.tf ul { margin: 6px 0 0; padding-left: 18px; font: 12px var(--mono); color: var(--bad); }
.note { color: var(--muted); font-size: 13.5px; margin-top: 28px; max-width: 78ch; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 13px; color: var(--ink-2); margin: -8px 0 8px; }
@media (max-width: 720px) {
  .step > summary { grid-template-columns: 46px minmax(0, 1fr); }
  .step > summary .what { grid-column: 2; }
  .step > summary .time { grid-column: 2; }
  .body { padding-left: 4px; }
}
</style>

<div class="wrap">
  <h1>Quickcommerce Run Log</h1>
  <p class="sub" id="sub"></p>
  <div class="stats" id="stats"></div>
  <div class="legend">
    <span><span class="chip REAL">REAL</span> output built only from the real Blinkit snapshot</span>
    <span><span class="chip SYNTHETIC">SYNTHETIC</span> uses generated rows: shows the pipeline works, not a market fact</span>
  </div>
  <div id="groups"></div>
  <h2>Tests <span id="testsum"></span></h2>
  <div class="tests" id="tests"></div>
  <p class="note">Not run, on purpose: the synthetic data generator and the raw-data patches (the raw files are frozen and
  checked by the first step), and the interactive labelling tools, which need a person. Click any step to see its command
  and the last lines it printed.</p>
</div>

<script>
const RUN = __DATA__;
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const fmt = s => s >= 60 ? `${Math.floor(s / 60)}m ${String(Math.round(s % 60)).padStart(2, '0')}s` : `${s.toFixed(1)}s`;
const NOTRUN = RUN.not_run || [];
const steps = RUN.steps, ok = steps.filter(s => s.ok).length, total = steps.reduce((a, s) => a + s.seconds, 0);
const maxT = Math.max(...steps.map(s => s.seconds), 1);
const cases = RUN.tests ? RUN.tests.cases : [];
const tPass = cases.filter(c => c.state === 'passed').length, tFail = cases.filter(c => c.state === 'failed').length;
const when = new Date(RUN.started_utc);
const REUSED = steps.filter(s => s.resumed_from_earlier_run).length, BLOCKED = steps.filter(s => s.blocked_by).length;

document.getElementById('sub').innerHTML =
  `Every command in the project run for real, in dependency order, on ${esc(when.toLocaleString([], {dateStyle: 'medium', timeStyle: 'short'}))}
   with Python ${esc(RUN.python)}.${NOTRUN.length ? ` <b>Incomplete:</b> ${NOTRUN.length} planned step${NOTRUN.length === 1 ? ' is' : 's are'} not in this log (marked NOT RUN below).` : ''}${BLOCKED ? ` ${BLOCKED} step${BLOCKED === 1 ? ' was' : 's were'} blocked because a step ${BLOCKED === 1 ? 'it needs' : 'they need'} failed, so nothing stale looks current.` : ''}${REUSED ? ` ${REUSED} step${REUSED === 1 ? ' was' : 's were'} recorded OK in an earlier pass and reused (<code>--resume</code>), ${steps.length - REUSED} ran in this one; every step shown ran once, for real.` : ''} Rebuild with <code>python scripts/run_all.py</code>, then <code>python scripts/build_run_page.py</code>.`;

const raw = steps.find(s => s.step === 'verify_raw_integrity');
const outs = new Set(steps.flatMap(s => s.outputs.map(o => o.name)));
const stat = (v, l, cls = '') => `<div><span class="v ${cls}">${v}</span><span class="l">${l}</span></div>`;
document.getElementById('stats').innerHTML =
  stat(`${ok}/${steps.length + NOTRUN.length}`, NOTRUN.length ? `steps finished OK · ${NOTRUN.length} not run yet` : 'steps finished without error',
       ok === steps.length && !NOTRUN.length ? 'ok' : 'bad') +
  stat(RUN.tests ? `${tPass}/${cases.length}` : 'Not run', RUN.tests ? 'tests passed' : 'test suite (runs after the last step)', RUN.tests && !tFail ? 'ok' : '') +
  stat(raw && raw.ok ? 'Unchanged' : 'CHANGED', 'raw data vs frozen hashes', raw && raw.ok ? 'ok' : 'bad') +
  stat(outs.size, 'model outputs rewritten') +
  stat(fmt(total), 'total run time');

const byGroup = {};
steps.forEach(s => (byGroup[s.group] ||= []).push(s));
NOTRUN.forEach(s => (byGroup[s.group] ||= []).push({...s, notrun: true, ok: false, seconds: 0, outputs: [], tail: []}));
document.getElementById('groups').innerHTML = Object.entries(RUN.groups).filter(([g]) => byGroup[g]).map(([g, label]) => {
  const list = byGroup[g], gOk = list.filter(s => s.ok).length, gT = list.reduce((a, s) => a + s.seconds, 0);
  const row = s => s.notrun ? `
    <details class="step">
      <summary>
        <span class="pill wait">NOT RUN</span>
        <span class="name">${esc(s.step)}</span>
        <span class="what">${esc(s.what)}</span>
        <span class="time"><i></i><span>—</span></span>
      </summary>
      <div class="body"><p class="cmd"><b>${esc(s.command)}</b> · not run in this log. Run <b>python scripts/run_all.py --resume</b> to finish it.</p></div>
    </details>` : null;
  return `<h2>${esc(label)} <span>${gOk}/${list.length} OK · ${fmt(gT)}</span></h2><div class="steps">` + list.map(s => row(s) || `
    <details class="step"${s.ok ? '' : ' open'}>
      <summary>
        <span class="pill ${s.ok ? 'ok' : s.blocked_by ? 'wait' : 'bad'}">${s.ok ? 'OK' : s.blocked_by ? 'BLOCKED' : s.timed_out ? 'TIMEOUT' : 'FAIL'}</span>
        <span class="name">${esc(s.step)}</span>
        <span class="what">${esc(s.what)}${s.outputs.length ? `<span class="chips">${s.outputs.map(o =>
          `<span class="chip ${o.scope}">${esc(o.name)}</span>`).join('')}</span>` : ''}</span>
        <span class="time"><i><b style="width:${(100 * s.seconds / maxT).toFixed(1)}%"></b></i><span>${fmt(s.seconds)}</span></span>
      </summary>
      <div class="body">
        <p class="cmd"><b>${esc(s.command)}</b> · ${s.blocked_by ? `blocked: needs ${esc(s.blocked_by.join(', '))}` : `exit code ${s.exit_code} · ${s.output_lines} lines printed`}${s.resumed_from_earlier_run ? ' · earlier pass' : ''}</p>
        <pre>${esc(s.tail.join('\n')) || '(no output)'}</pre>
      </div>
    </details>`).join('') + '</div>';
}).join('');

const files = {};
cases.forEach(c => { const f = (files[c.file] ||= {p: 0, f: 0, s: 0, failed: []});
  if (c.state === 'passed') f.p++; else if (c.state === 'skipped') f.s++; else { f.f++; f.failed.push(c.name); } });
document.getElementById('testsum').textContent = RUN.tests
  ? `${tPass} passed · ${tFail} failed · ${cases.length - tPass - tFail} skipped · ${fmt(RUN.tests.seconds)}` : 'not run';
document.getElementById('tests').innerHTML = Object.entries(files).map(([f, v]) => `
  <div class="tf"><b>${esc(f)}.py</b><span>${v.p} passed${v.f ? ` · <span class="f">${v.f} failed</span>` : ''}${v.s ? ` · ${v.s} skipped` : ''}</span>
  ${v.failed.length ? `<ul>${v.failed.map(n => `<li>${esc(n)}</li>`).join('')}</ul>` : ''}</div>`).join('');
</script>
'''


def main():
    data = json.dumps(payload(), ensure_ascii=False).replace('</', '<\\/')
    OUT.write_text(PAGE.replace('__DATA__', data), encoding='utf-8')
    print(f'wrote {OUT.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
