"""Hashes of the data a model was trained against. Baseline lives in scripts/verify_raw_integrity.py."""
import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW, ML = ROOT / 'data' / 'raw', ROOT / 'data' / 'ml'
PREFIX = 16


def sha256_prefix(path: Path, n: int = PREFIX) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()[:n]


def raw_hashes() -> dict[str, str]:
    return {p.name: sha256_prefix(p) for p in sorted(RAW.glob('*.parquet'))}


def ml_hashes() -> dict[str, str]:
    return {p.name: sha256_prefix(p) for p in sorted(ML.glob('*.parquet'))}


def raw_baseline() -> dict[str, str]:
    """EXPECTED from scripts/verify_raw_integrity.py (single source of truth)."""
    spec = importlib.util.spec_from_file_location('_verify_raw', ROOT / 'scripts' / 'verify_raw_integrity.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return dict(mod.EXPECTED)
