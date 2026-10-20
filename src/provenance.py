"""
provenance.py — one place that says which REAL results depend on the store label, and what that label's status is.

WHY THIS EXISTS
  docs/STORE_LABEL_AUDIT_v1.md found that `store_id` on the 21,949 REAL rows cannot be told apart from a random label,
  and the source workbook does not say how a product row was tied to a store (docs/audit/AUDIT_2026-10-13.md, section
  1). A caveat that lives only in a doc is not a safeguard: the analyst, the pages and the manifests would go on
  presenting store-level results as plain REAL. Everything that shows such a result reads its status from here.

    python -m src.provenance            # print the status and stamp it into the manifests of the outputs listed below

STATUS VALUES
  UNVERIFIED            the audit ran and found no store information in the label
  DEPARTS_FROM_RANDOM   the audit ran and at least one test departs after correction (look before trusting it)
  NOT_AUDITED           the audit has not been run

This module imports nothing from the rest of src, so src.model_output can use it without a cycle.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / 'outputs' / 'models'
AUDIT_NAME = 'real_store_label_audit'

# REAL outputs and docs whose result reads store_id on a REAL row as "this store listed this product"
STORE_LEVEL_REAL_OUTPUTS = ('assortment_gaps', 'store_category_coverage', 'simulate_store_adds_real')
STORE_LEVEL_DOCS = ('docs/ASSORTMENT_GAPS_v1.md', 'docs/COVERAGE_12C.md')

BANNER = ('STORE LABEL UNVERIFIED: part of this answer groups the REAL rows by store. On ten permutation tests that '
          'label cannot be told apart from a random one, and the source file does not record how a product was tied to '
          'a store (docs/STORE_LABEL_AUDIT_v1.md). Read it as a property of the file, not as a fact about real stores.')
SHORT = ('store label unverified: cannot be told apart from a random label, and the source does not record how '
         'products were tied to stores')


def store_label_status() -> dict:
    p = MODELS_DIR / AUDIT_NAME / 'metrics.json'
    if not p.exists():
        return {'status': 'NOT_AUDITED', 'basis': f'outputs/models/{AUDIT_NAME} has not been built',
                'doc': 'docs/STORE_LABEL_AUDIT_v1.md'}
    m = json.loads(p.read_text(encoding='utf-8'))
    man = json.loads((p.parent / 'manifest.json').read_text(encoding='utf-8'))
    departs = m['verdict']['departures_after_bonferroni']
    pair = m['permutation_tests']['same_key_pairs_in_same_store_share']
    return {'status': 'DEPARTS_FROM_RANDOM' if departs else 'UNVERIFIED',
            'basis': f"{m['verdict']['tests']} permutation tests, {len(departs)} depart after Bonferroni correction; "
                     f"records of one name|pack share a store in {pair['observed']:.1%} of pairs against "
                     f"{pair['null_mean']:.1%} for a label independent of the product",
            'audit_date': man.get('date'), 'doc': 'docs/STORE_LABEL_AUDIT_v1.md',
            'source_check': 'the source workbook attaches a store to every product row but records no method for it; '
                            'its provenance fields describe store locations (docs/audit/AUDIT_2026-10-13.md)'}


def unverified() -> bool:
    """True unless the audit ran and found store information. Not audited counts as unverified."""
    return store_label_status()['status'] != 'DEPARTS_FROM_RANDOM'


def is_store_level_claim(claim: dict) -> bool:
    """Does an analyst claim rest on the REAL store label? Registered outputs and docs, a REAL query grouped by store
    or area, and the REAL context row of a listing chain (same product AND same store)."""
    if claim.get('provenance') != 'REAL':
        return False
    src = str(claim.get('source_file', '')).replace('\\', '/')
    detail = str(claim.get('source_detail', ''))
    if any(src.startswith(f'outputs/models/{name}/') for name in STORE_LEVEL_REAL_OUTPUTS) or src in STORE_LEVEL_DOCS:
        return True
    if 'by store_id' in detail or 'by area' in detail:
        return True
    return claim.get('stage') == '1_observe'


def stamp_manifests() -> list[str]:
    """Write the current status into the manifest of every registered output that exists. Results are not touched."""
    status = store_label_status()
    done = []
    for name in STORE_LEVEL_REAL_OUTPUTS:
        p = MODELS_DIR / name / 'manifest.json'
        if not p.exists():
            continue
        man = json.loads(p.read_text(encoding='utf-8'))
        man['store_label'] = {**status, 'stamped_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                              'note': 'metadata only: this output reads store_id on REAL rows as "this store listed '
                                      'this product". Its results were not changed.'}
        p.write_text(json.dumps(man, indent=2), encoding='utf-8')
        done.append(name)
    return done


if __name__ == '__main__':
    print(json.dumps(store_label_status(), indent=1))
    print('stamped:', stamp_manifests())
