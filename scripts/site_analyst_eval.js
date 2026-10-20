/*
 * site_analyst_eval.js — score the in-browser analyst (site/analyst.js) on the project's own question sets.
 *
 *     node scripts/site_analyst_eval.js site/analyst.js <input.json> <output.json>     (build_site.py runs this)
 *
 * The grading is src/analyst/evaluate.py :: grade, line for line. The answer cache is switched OFF, so a pass means
 * the engine in the page reached the answer itself, not that it looked up what the Python analyst said.
 */
const fs = require('fs');
const path = require('path');

const [, , enginePath, inputPath, outputPath] = process.argv;
const QC = require(path.resolve(enginePath));
const data = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
const whatif = data.whatif || null;
const engine = QC.create(data, {whatif: whatif ? () => whatif : null});

function grade(item, a) {
  const res = {q: item.q, set: item.set};
  const labels = a.claims.map(c => c.provenance);
  const cited = a.claims.map(c => c.source_file + ' ' + (c.source_detail || '')).join(' ').toLowerCase();
  const text = [a.answer_summary].concat(a.claims.map(c => c.text)).join(' ');
  if (item.refuse) {
    res.pass_refusal = !!a.refused;
    res.passed = res.pass_refusal;
    return res;
  }
  res.pass_refusal = !a.refused;
  let ok = res.pass_refusal;
  if (item.must_label) {
    res.pass_label = labels.includes(item.must_label) && (item.must_label !== 'SYNTHETIC' || !!a.banner);
    ok = ok && res.pass_label;
  }
  if (item.forbid_only) {
    res.pass_not_only_forbidden = labels.length > 0 && !labels.every(l => l === item.forbid_only);
    ok = ok && res.pass_not_only_forbidden;
  }
  if (item.sources) {
    res.pass_source = item.sources.some(s => cited.includes(s.toLowerCase()));
    ok = ok && res.pass_source;
  }
  if (item.must_mention) {
    res.pass_mention = item.must_mention.every(m => text.toLowerCase().includes(m.toLowerCase()));
    ok = ok && res.pass_mention;
  }
  if (item.labels_all) {
    res.pass_labels_all = item.labels_all.every(l => labels.includes(l));
    ok = ok && res.pass_labels_all;
  }
  if (item.stage_order) {
    const order = a.claims.filter(c => c.stage).map(c => parseInt(c.stage.split('_')[0], 10));
    const sorted = order.slice().sort((x, y) => x - y);
    res.pass_stage_order = order.every((v, i) => v === sorted[i]) && [1, 2, 3, 4, 5, 6].every(s => order.includes(s));
    ok = ok && res.pass_stage_order;
  }
  if (item.want) {
    res.pass_value = item.want.some(w => text.includes(w));
    ok = ok && res.pass_value;
  }
  res.all_claims_verified = a.all_claims_verified;
  ok = ok && a.all_claims_verified;
  res.passed = !!ok;
  return res;
}

const rows = data.evalq.map(item => grade(item, engine.answer(item.q, {cache: false})));
const summary = {};
for (const set of ['tuning', 'holdout']) {
  const r = rows.filter(x => x.set === set);
  const must = data.evalq.filter(x => x.set === set && x.refuse).map(x => x.q);
  const refusedRight = r.filter(x => must.includes(x.q) && x.pass_refusal).length;
  const falseRefusals = r.filter(x => !must.includes(x.q) && !x.pass_refusal).length;
  summary[set] = {questions: r.length, passed: r.filter(x => x.passed).length, must_refuse: must.length, refused_when_it_must: refusedRight,
    false_refusals: falseRefusals};
}
const out = {note: 'In-browser engine, answer cache off. Graded with the rules of src/analyst/evaluate.py.', summary,
  failures: rows.filter(x => !x.passed)};
fs.writeFileSync(outputPath, JSON.stringify(out, null, 1));
console.log(JSON.stringify(summary));
for (const f of out.failures) console.log('FAIL', JSON.stringify(f));
