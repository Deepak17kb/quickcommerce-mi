"""
verify_raw_integrity.py — fail loudly if data/raw/ has changed.

    python scripts/verify_raw_integrity.py        (or: make verify-raw)

Computes sha256 for every data/raw/*.parquet and compares the first 16 hex chars
against the frozen baseline below. Exits 1 on any mismatch, missing file or
unexpected extra file; exits 0 only if all four match.

BASELINE
  These are the parquet hashes AFTER the v15.1 calibrated regeneration (2026-09-17,
  src/pipeline/build_v15_dynamics.py; see data/raw/GENERATOR_LOG.md). v15.x rewrote the SYNTHETIC
  rows of all four files; the 21,949 REAL rows are cell-for-cell identical to the v2 state.
  data/ml/ was rebuilt from this state on 2026-09-17 (python -m src.pipeline.build_features).

  History (first 16 hex chars):
    shipped (quickcommerce-mi.zip)  Blinkit 78fecff38345e3e2  Instamart 4b9189c2d7302286
                                    FlipkartMinutes ce6d6274263d700d  BigBasket fb440c7a4d19a8d2
    after patch v1                  Blinkit 1f3258cac3b25c37  Instamart 42433edfe5aaffde
                                    FlipkartMinutes 3b693b724ed785d2  BigBasket dcb4f7ba0c826bbd
    after patch v2                  Blinkit 4e04dffcac84b821  (others as v1)
                                    archived in data/archive/v14_pre_regen/
    after v15.0 regeneration        Blinkit 44f9441b8b53da0b  Instamart fb33e5f7a7cec520
                                    FlipkartMinutes a788a956ddcb83ed  BigBasket 83de89b8f53b1d6a
                                    archived in data/archive/v15_0_pre_calibration/
    after v15.1 calibration (current) Blinkit d9d87056baace107  Instamart 65f0b5d368a30150
                                    FlipkartMinutes 5e8ee620ec72ed09  BigBasket 68d8d15cc5ea1d0a

  The hashes in docs/README_ML_v2.md (cec0bf04…, 59e39c95…, bb3b3510…, 27ddf91b…)
  are for the earlier *_RAW.csv.gz files, not these parquet files, and are kept there
  for history only.

  If raw is ever changed deliberately, update EXPECTED here in the same commit and
  record why in data/raw/PATCH_LOG.md.
"""
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
PREFIX = 16

EXPECTED = {
    'Blinkit_RAW.parquet':         'd9d87056baace107',
    'Instamart_RAW.parquet':       '65f0b5d368a30150',
    'FlipkartMinutes_RAW.parquet': '5e8ee620ec72ed09',
    'BigBasket_RAW.parquet':       '68d8d15cc5ea1d0a',
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    failures = 0
    found = {p.name for p in RAW.glob('*.parquet')}

    for name, want in EXPECTED.items():
        path = RAW / name
        if not path.exists():
            print(f"  FAIL  {name:<30} missing")
            failures += 1
            continue
        got = sha256(path)[:PREFIX]
        ok = got == want
        failures += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<30} {got}"
              + ('' if ok else f"  (expected {want})"))

    for extra in sorted(found - EXPECTED.keys()):
        print(f"  FAIL  {extra:<30} unexpected file in data/raw/")
        failures += 1

    print(f"\nraw integrity: {'OK' if not failures else f'{failures} FAILURE(S)'}")
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
