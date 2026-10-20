"""
import_labels.py — bring labels from the Product Match Review page into the priority batch. Writes only what a person
decided on that page.

    python -m src.matching.import_labels <labels>              # a folder of exported docs, or one JSON file
    python -m src.matching.import_labels <labels> --dry-run    # validate and report, write nothing
    python -m src.matching.import_labels <labels> --relabel    # also replace labels already in the CSV

WHERE THE LABELS COME FROM
  The page (scripts/build_review_page.py, published as an artifact) saves each decision as labels/r<row>:
      {row, pair_id, label: same | different | unsure, note, at, by_owner}
  Claude exports them with the artifact data tool (one JSON file per document), or the page's fallback "Copy all labels
  as text" gives one JSON object {r001: {...}, ...}. Either form is accepted.

WHAT IT CHECKS BEFORE WRITING ANYTHING
  - the row exists in data/reference/MATCH_REVIEW_PRIORITY.csv and the pair text stored with the label matches that
    row's pair_id (a regenerated batch would otherwise receive labels meant for other pairs)
  - the label is same / different / unsure
  - the decision was made by the page's owner (by_owner true); a decision by another editor needs --allow-editors,
    and one whose author the page could not confirm (by_owner null) is imported with that fact written into the note
  - an existing label in the CSV is never replaced unless --relabel; a disagreement is reported either way

WHAT IT WRITES
  label 1 (same) / 0 (different) / '' (unsure: kept as a note, never counted) and reviewer_note, exactly as the terminal
  reviewer (src/matching/review.py) does, so the trainer counts them as human_reviewed. Then:
      python -m src.matching.train
"""
import argparse
import json
from pathlib import Path

import pandas as pd

import src.load as L

PRIORITY = L.REF / 'MATCH_REVIEW_PRIORITY.csv'
CODE = {'same': '1', 'different': '0', 'unsure': ''}
NEEDED_PER_CLASS = 30


def read_labels(src: Path) -> dict:
    """{r001: body} from a folder of exported JSON documents or from one JSON object."""
    out = {}
    if src.is_dir():
        for f in sorted(src.rglob('*.json')):
            doc = json.loads(f.read_text(encoding='utf-8'))
            body = doc.get('data', doc) if isinstance(doc, dict) else None     # tolerate a {data: ...} wrapper
            if isinstance(body, dict):
                out[f.stem] = body
    else:
        obj = json.loads(src.read_text(encoding='utf-8'))
        out = {k: v for k, v in obj.items() if isinstance(v, dict)}
    return out


def plan(labels: dict, batch: pd.DataFrame, relabel: bool, allow_editors: bool) -> tuple[list, list]:
    by_row = batch.set_index(batch.batch_row.astype(int))
    writes, problems = [], []
    for key, b in sorted(labels.items()):
        row = b.get('row')
        try:
            row = int(row)
        except (TypeError, ValueError):
            problems.append(f'{key}: no valid row number')
            continue
        if row not in by_row.index:
            problems.append(f'{key}: row {row} is not in the batch')
            continue
        csv_row = by_row.loc[row]
        if b.get('pair_id') and b['pair_id'] != csv_row.pair_id:
            problems.append(f'{key}: pair text does not match row {row} of the CSV (was the batch regenerated?)')
            continue
        lab = b.get('label')
        if lab not in CODE:
            problems.append(f'{key}: label {lab!r} is not same / different / unsure')
            continue
        owner = b.get('by_owner')
        if owner is False and not allow_editors:
            problems.append(f'{key}: decided by an editor who is not the owner (pass --allow-editors to accept)')
            continue
        old = str(csv_row.label).strip()
        new = CODE[lab]
        if old and old != new and not relabel:
            problems.append(f'{key}: CSV already says {old}, the page says {new or "unsure"} (pass --relabel to replace)')
            continue
        note = (b.get('note') or '').strip()
        stamp = f"[review page {str(b.get('at', ''))[:10]}{'' if owner is True else ', author not confirmed as owner'}]"
        writes.append({'row': row, 'label': new, 'note': f'{note} {stamp}'.strip(), 'was': old})
    return writes, problems


def status(batch: pd.DataFrame) -> dict:
    lab = batch.label.astype(str).str.strip()
    s, d = int((lab == '1').sum()), int((lab == '0').sum())
    return {'same': s, 'different': d, 'unlabelled_or_unsure': int(len(batch) - s - d),
            'tier1_unlocked': s >= NEEDED_PER_CLASS and d >= NEEDED_PER_CLASS}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument('labels', type=Path)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--relabel', action='store_true')
    ap.add_argument('--allow-editors', action='store_true')
    a = ap.parse_args(argv)
    batch = pd.read_csv(PRIORITY, dtype=str).fillna('')
    labels = read_labels(a.labels)
    writes, problems = plan(labels, batch, a.relabel, a.allow_editors)
    print(f'{len(labels)} decisions read, {len(writes)} to write, {len(problems)} held back')
    for p in problems:
        print('  held back:', p)
    if not a.dry_run and writes:
        idx = {int(r): i for i, r in batch.batch_row.items()}
        for w in writes:
            i = idx[w['row']]
            batch.at[i, 'label'] = w['label']
            batch.at[i, 'reviewer_note'] = w['note']
        batch.to_csv(PRIORITY, index=False)
        print(f'wrote {PRIORITY.relative_to(L.ROOT)}')
    st = status(batch)
    print(json.dumps(st))
    if st['tier1_unlocked'] and not a.dry_run:
        print('tier 1 can be measured: python -m src.matching.train')
    return st, writes, problems


if __name__ == '__main__':
    main()
