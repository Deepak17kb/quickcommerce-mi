"""
review.py — the human labelling terminal for the priority batch. YOU label; this only records.

    python -m src.matching.review                  # label the priority batch (297 pairs)
    python -m src.matching.review --limit 40       # a short session
    python -m src.matching.review --queue          # label MATCH_REVIEW_QUEUE.csv instead
    python -m src.matching.review --status         # how far the batch is from tier 1

Keys:  s = same product   d = different   u = unsure (leave blank)   b = back one
       n = add a note     q = save and quit

WHY THIS EXISTS
  Tier 1 of model 1 — real name variation — is NOT MEASURABLE until a person labels >= 30 same and
  >= 30 different pairs (docs/MATCHER_v1.md, CLAUDE.md section 8). No rule and no model may produce
  those labels: the batch keys are reserved evaluation keys, so a guessed label silently becomes the
  yardstick the model is then scored against. This script writes only what you type.

  Pairs are served round-robin across strata (L_likely_same / M_ambiguous / N_hard_contrast) so that
  both label classes accumulate together and tier 1 unlocks as early as possible.

Every write goes straight to the CSV, so quitting or crashing never loses a decision. An existing
label is never silently overwritten — pass --relabel to revisit pairs you already decided.
"""
import argparse

import pandas as pd

import src.load as L
from src.matching import labels as LB

KEYS = {'s': '1', 'd': '0', 'u': ''}
NEEDED_PER_CLASS = 30


def _load(path):
    df = pd.read_csv(path, dtype=str).fillna('')
    for col in ('label', 'reviewer_note'):
        if col not in df.columns:
            df[col] = ''
    return df


def status(df: pd.DataFrame) -> dict:
    lab = df.label.str.strip()
    pos, neg = int((lab == '1').sum()), int((lab == '0').sum())
    return {'rows': len(df), 'same_1': pos, 'different_0': neg,
            'unlabelled': int((lab == '').sum()),
            'tier1_unlocked': pos >= NEEDED_PER_CLASS and neg >= NEEDED_PER_CLASS,
            'still_needed': {'same': max(0, NEEDED_PER_CLASS - pos),
                             'different': max(0, NEEDED_PER_CLASS - neg)}}


def _order(df: pd.DataFrame, relabel: bool) -> list[int]:
    """Round-robin across strata so both classes accumulate together."""
    todo = df.index if relabel else df.index[df.label.str.strip() == '']
    if 'stratum' not in df.columns:
        return list(todo)
    buckets = [list(g) for _, g in df.loc[todo].groupby('stratum', sort=True).groups.items()]
    out = []
    for i in range(max((len(b) for b in buckets), default=0)):
        out += [b[i] for b in buckets if i < len(b)]
    return out


def _show(row, n, total, st):
    def field(a, b, name):
        mark = '  ' if str(a) == str(b) else '->'
        return f"  {name:<10} {mark} A: {a}\n  {'':<10}    B: {b}"

    print('\n' + '=' * 78)
    print(f"[{n}/{total}]  stratum: {row.get('stratum', '?')}   "
          f"labelled so far: {st['same_1']} same / {st['different_0']} different "
          f"(need {st['still_needed']['same']} more same, {st['still_needed']['different']} more different)")
    if row.get('selection_reason'):
        print(f"  why chosen: {row['selection_reason']}")
    print('-' * 78)
    print(field(row.get('name_a', ''), row.get('name_b', ''), 'name'))
    print(field(row.get('pack_a', ''), row.get('pack_b', ''), 'pack'))
    print(field(row.get('brand_a', ''), row.get('brand_b', ''), 'brand'))
    print(field(row.get('category_a', ''), row.get('category_b', ''), 'category'))
    sims = [f"{k}={float(row[k]):.3f}" for k in ('jw_full', 'ngram_cos_full', 'ngram_cos_base',
                                                 'tokjac_full') if str(row.get(k, '')).strip()]
    if sims:
        print('  similarity   ' + '  '.join(sims))
    if str(row.get('label', '')).strip():
        print(f"  CURRENT LABEL: {row['label']}  {row.get('reviewer_note', '')}")
    print('-' * 78)
    print('  s = same   d = different   u = unsure   n = note   b = back   q = save and quit')


def run(path, limit, relabel):
    df = _load(path)
    order = _order(df, relabel)
    if not order:
        print(f"nothing to label in {path.name} — every pair already has a label.")
        return status(df)
    if limit:
        order = order[:limit]

    print(f"{path.name}: {len(order)} pairs this session. Decisions are saved as you go.")
    pos = 0
    while 0 <= pos < len(order):
        idx = order[pos]
        st = status(df)
        _show(df.loc[idx], pos + 1, len(order), st)
        try:
            key = input('  > ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            print('\n  stopping — everything decided so far is saved.')
            break
        if key == 'q':
            break
        if key == 'b':
            pos = max(0, pos - 1)
            continue
        if key == 'n':
            df.loc[idx, 'reviewer_note'] = input('  note: ').strip()
            df.to_csv(path, index=False)
            continue
        if key not in KEYS:
            print('  ? use s / d / u / n / b / q')
            continue
        df.loc[idx, 'label'] = KEYS[key]
        df.to_csv(path, index=False)
        pos += 1

    st = status(df)
    print(f"\nsaved {path}")
    print(f"  {st['same_1']} same / {st['different_0']} different / {st['unlabelled']} unlabelled")
    if st['tier1_unlocked']:
        print("  TIER 1 IS UNLOCKED — rerun: python -m src.matching.train")
    else:
        need = st['still_needed']
        print(f"  tier 1 still needs {need['same']} more 'same' and {need['different']} more "
              f"'different' labels before python -m src.matching.train can measure it.")
    return st


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument('--queue', action='store_true', help='label MATCH_REVIEW_QUEUE.csv instead')
    ap.add_argument('--limit', type=int, default=0, help='stop after N pairs')
    ap.add_argument('--relabel', action='store_true', help='revisit pairs that already have a label')
    ap.add_argument('--status', action='store_true', help='print progress and exit')
    a = ap.parse_args()

    path = LB.QUEUE_PATH if a.queue else LB.PRIORITY_PATH
    if a.status:
        import json
        print(json.dumps(status(_load(path)), indent=1))
        return
    run(path, a.limit, a.relabel)


if __name__ == '__main__':
    main()
