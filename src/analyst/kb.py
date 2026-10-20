"""
kb.py — the analyst's knowledge base: every project doc and every saved model output, each labelled by provenance.

Two kinds of passage, both searchable with BM25:
  doc      a section of CLAUDE.md, README.md or docs/*.md (split on headings, long sections windowed)
  metric   one top-level key of a model's metrics.json, with the model's manifest claim_scope and date

PROVENANCE LABELS (the analyst's whole point)
  REAL       from the 21,949 REAL Blinkit rows of 2026-07-10, or a REAL-ONLY model
  SYNTHETIC  from generated rows, or a SYNTHETIC-DERIVED model: describes the generator / pipeline, never the market
  METHOD     how the project works (rules, conventions, definitions), no market statement
  EXTERNAL   a cited public web source (docs/external/*.md): company, market and competitor facts, each with its URL,
             publisher and dates. Not the project's data and never checked against it.
  A doc that declares "(REAL)", "(SYNTHETIC)" or "(EXTERNAL)" in its title labels every section. Other docs are labelled per
  section, conservatively: any mention of synthetic data makes the section SYNTHETIC.
"""
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import src.load as L
from src.model_output import MODELS_DIR

ROOT = L.ROOT
DOC_FILES = ['CLAUDE.md', 'README.md']
HISTORICAL = {'README_PIPELINE.md', 'README_ML_v2.md', 'README_FINAL_v11_mrp_fill.md',
              'README_FINAL_v12_catalog_and_duplicates.md', 'README_FINAL_v13_canonical_key_review.md'}
# A design study names every quantity in the project without owning any of them, so on plain BM25 it outranks the
# model that does. It is down-weighted unless the question is about collecting data.
PLANNING_FILES = {'COLLECTION_PLANNER_v1.md'}
PLANNING_MODELS = {'collection_planner'}
PLANNING_WORDS = ('collect', 'collection', 'collecting', 'panel', 'watchlist', 'pilot', 'logger', 'logging', 'enough',
                  'days', 'design')
WINDOW = 1400
STOP = set('a an the of to in on for and or is are was were be by with at as it its this that from which what who how '
           'do does did can could would should will not no yes if then than there their they them we you i me my our '
           'your about into over under per vs'.split())
ALIASES = {'cheapest': 'cheapest regression cheapest-of-4', 'stockout': 'stockout stock-out oos',
           'oos': 'oos stock-out', 'eta': 'eta delivery', 'restock': 'restock spell', 'elasticity': 'elasticity demand',
           'leader': 'leader follower response', 'follow': 'follower response leader beta',
           'forecast': 'forecast mae baseline', 'anomaly': 'anomaly unusual defect', 'gap': 'gap assortment',
           'coverage': 'coverage store geography', 'matcher': 'matcher match pairs', 'survival': 'survival hazard weibull',
           'long': 'long duration spell', 'last': 'last duration spell'}


@dataclass
class Passage:
    pid: str
    kind: str                     # 'doc' | 'metric'
    source_file: str
    section: str
    text: str
    provenance: str               # REAL | SYNTHETIC | METHOD
    date: str
    historical: bool = False
    planning: bool = False
    model: str | None = None
    tokens: Counter = field(default_factory=Counter)


def stem(t: str) -> str:
    """A light suffix stripper, enough that recover / recovered / recovery and last / lasts meet."""
    if len(t) <= 4 or t[0].isdigit():
        return t
    for suf, rep in (('ies', 'y'), ('sses', 'ss'), ('ery', 'er'), ('ing', ''), ('ed', ''), ('ly', ''), ('es', 'e'),
                     ('s', '')):
        if t.endswith(suf) and not (suf == 's' and t.endswith('ss')):
            return t[:len(t) - len(suf)] + rep
    return t


def tokenize(text: str) -> list[str]:
    toks = re.findall(r'[a-z0-9]+(?:\.[0-9]+)?', text.lower())
    return [stem(t) for t in toks if t not in STOP and len(t) > 1]


def expand(tokens: list[str]) -> list[str]:
    out = list(tokens)
    for t in tokens:
        if t in ALIASES:
            out += tokenize(ALIASES[t])
    return out


def _doc_scope(first_lines: str) -> str | None:
    head = first_lines[:300]
    if '(SYNTHETIC)' in head:
        return 'SYNTHETIC'
    if '(REAL)' in head:
        return 'REAL'
    if '(EXTERNAL)' in head:
        return 'EXTERNAL'
    return None


def _section_label(text: str) -> str:
    low = text.lower()
    if 'synthetic' in low or 'generated' in low or 'generator' in low:
        return 'SYNTHETIC'
    if 'real' in low and ('2026-07-10' in low or 'real blinkit' in low or 'data_status == \'real\'' in low
                          or 'real rows' in low or 'real snapshot' in low):
        return 'REAL'
    return 'METHOD'


def _doc_date(text: str, path: Path) -> str:
    m = re.search(r'(?:Built|built|last checked|checked|Last checked)\s+(20\d\d-\d\d-\d\d)', text)
    if m:
        return m.group(1)
    from datetime import datetime
    return datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()


def doc_passages() -> list[Passage]:
    files = ([ROOT / f for f in DOC_FILES] + sorted((ROOT / 'docs').glob('*.md'))
             + sorted((ROOT / 'docs' / 'external').glob('*.md')))
    out = []
    for path in files:
        if not path.exists():
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        rel = str(path.relative_to(ROOT)).replace('\\', '/')
        scope = _doc_scope(text)
        date = _doc_date(text, path)
        parts = re.split(r'(?m)^(#{1,4} .*)$', text)
        heading, buf = path.stem, parts[0]
        sections = [(heading, buf)]
        for i in range(1, len(parts), 2):
            sections.append((parts[i].lstrip('#').strip(), parts[i + 1] if i + 1 < len(parts) else ''))
        n = 0
        for head, body in sections:
            body = body.strip()
            if len(body) < 40:
                continue
            paras, win = re.split(r'\n\s*\n', body), ''
            chunks = []
            for para in paras:
                if len(win) + len(para) > WINDOW and win:
                    chunks.append(win); win = ''
                win += ('\n\n' if win else '') + para
            if win:
                chunks.append(win)
            for ch in chunks:
                n += 1
                out.append(Passage(pid=f'{rel}#{n}', kind='doc', source_file=rel, section=head, text=ch,
                                   provenance=scope or _section_label(head + ' ' + ch), date=date,
                                   historical=path.name in HISTORICAL, planning=path.name in PLANNING_FILES))
    return out


def _compact(obj, limit=1500):
    s = json.dumps(obj, default=str, separators=(', ', ': '))
    return s if len(s) <= limit else s[:limit] + ' …'


def model_catalog() -> dict:
    cat = {}
    for d in sorted(MODELS_DIR.iterdir()):
        man, met = d / 'manifest.json', d / 'metrics.json'
        if not (man.exists() and met.exists()):
            continue
        m = json.loads(man.read_text(encoding='utf-8'))
        scope = m.get('claim_scope', '')
        cat[d.name] = {'provenance': 'REAL' if scope.startswith('REAL-ONLY') else 'SYNTHETIC',
                       'claim_scope': scope, 'date': m.get('date', ''), 'target': m.get('target'),
                       'notes': m.get('notes', ''), 'metrics_file': f'outputs/models/{d.name}/metrics.json',
                       'rows_real': m.get('prediction_row_mix', {}).get('REAL'),
                       'rows_synthetic': m.get('prediction_row_mix', {}).get('SYNTHETIC')}
    return cat


def metric_passages(catalog: dict) -> list[Passage]:
    out = []
    for name, info in catalog.items():
        met = json.loads((MODELS_DIR / name / 'metrics.json').read_text(encoding='utf-8'))
        head = f"model {name.replace('_', ' ')} ({info['provenance']}). {info['notes']}"
        for key, val in met.items():
            text = f"{head}\n{key.replace('_', ' ')}: {_compact(val)}"
            out.append(Passage(pid=f"{name}::{key}", kind='metric', source_file=info['metrics_file'],
                               section=key, text=text, provenance=info['provenance'], date=info['date'], model=name,
                               planning=name in PLANNING_MODELS))
    return out


class KB:
    def __init__(self):
        self.root = ROOT
        self.catalog = model_catalog()
        self.passages = doc_passages() + metric_passages(self.catalog)
        for p in self.passages:
            p.tokens = Counter(tokenize(p.section + ' ' + (p.model or '') + ' ' + p.text))
        self.N = len(self.passages)
        df = Counter()
        for p in self.passages:
            df.update(p.tokens.keys())
        self.idf = {t: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for t, n in df.items()}
        self.avgdl = sum(sum(p.tokens.values()) for p in self.passages) / max(self.N, 1)
        self.by_id = {p.pid: p for p in self.passages}

    def search(self, query: str, k: int = 6, kind: str | None = None, k1=1.5, b=0.75) -> list[tuple[float, Passage]]:
        q = expand(tokenize(query))
        about_collecting = bool(set(tokenize(query)) & set(tokenize(' '.join(PLANNING_WORDS))))
        scores = []
        for p in self.passages:
            if kind and p.kind != kind:
                continue
            dl = sum(p.tokens.values())
            s = 0.0
            for t in q:
                f = p.tokens.get(t, 0)
                if f:
                    s += self.idf.get(t, 0) * f * (k1 + 1) / (f + k1 * (1 - b + b * dl / self.avgdl))
            if p.historical or (p.planning and not about_collecting):
                s *= 0.5
            if s > 0:
                scores.append((s, p))
        scores.sort(key=lambda x: -x[0])
        return scores[:k]

    def provenance_of_file(self, source_file: str) -> str | None:
        """One label when every passage of the file agrees (every model output does), else MIXED."""
        labels = {p.provenance for p in self.passages if p.source_file == source_file}
        if not labels and source_file.startswith('outputs/models/'):
            name = source_file.split('/')[2]    # any file in a model's folder takes the model's provenance
            return self.catalog[name]['provenance'] if name in self.catalog else None
        if not labels:
            return None
        return labels.pop() if len(labels) == 1 else 'MIXED'

    def date_of_file(self, source_file: str) -> str:
        for p in self.passages:
            if p.source_file == source_file:
                return p.date
        if source_file.startswith('outputs/models/') and source_file.split('/')[2] in self.catalog:
            return self.catalog[source_file.split('/')[2]]['date']
        return ''
