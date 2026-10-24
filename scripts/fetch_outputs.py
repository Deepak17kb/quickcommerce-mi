"""
fetch_outputs.py — put the released run outputs into this clone, so the website, the analyst and the full test suite
work without running the pipeline (about three hours on a laptop).

    python scripts/fetch_outputs.py            # data/ml/ and outputs/ from the release named in data/OUTPUTS_RELEASE.json
    python scripts/fetch_outputs.py --force    # also replace files that are already here
    python scripts/fetch_outputs.py --zip FILE # use a zip already downloaded (still checked against the manifest)

Checks, in order: the download's sha256 must equal the manifest's; every member must be a plain file under data/ml/
or outputs/ (no absolute path, no '..', no link, nothing else); a file that is already here is kept unless --force.
Standard library only, so it runs before anything is installed.
"""
import argparse
import hashlib
import json
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'data' / 'OUTPUTS_RELEASE.json'
ALLOWED = ('data/ml/', 'outputs/')


def safe_name(name: str) -> bool:
    """A member may be written only if it is a relative path under data/ml/ or outputs/ with no '..' in it."""
    p = PurePosixPath(name)
    return (not name.startswith('/') and '\\' not in name and ':' not in name and '..' not in p.parts
            and name.startswith(ALLOWED) and not name.endswith('/'))


def is_link(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, size: int):
    with urllib.request.urlopen(url, timeout=60) as r, open(dest, 'wb') as f:
        got, step = 0, max(size // 10, 1)
        for chunk in iter(lambda: r.read(1 << 20), b''):
            f.write(chunk)
            if (got + len(chunk)) // step > got // step:
                print(f'  {min(100, round(100 * (got + len(chunk)) / max(size, 1)))}%', flush=True)
            got += len(chunk)


def extract(zpath: Path, force: bool) -> dict:
    counts = {'written': 0, 'kept': 0}
    with zipfile.ZipFile(zpath) as z:
        bad = [i.filename for i in z.infolist() if not i.is_dir() and (not safe_name(i.filename) or is_link(i))]
        if bad:
            raise SystemExit(f'refused: the archive holds entries outside data/ml/ and outputs/ or links: {bad[:5]}')
        for info in z.infolist():
            if info.is_dir():
                continue
            target = ROOT / info.filename
            if target.exists() and not force:
                counts['kept'] += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, 'wb') as out:
                for chunk in iter(lambda: src.read(1 << 20), b''):
                    out.write(chunk)
            counts['written'] += 1
    return counts


def main():
    ap = argparse.ArgumentParser(description='Download the released run outputs (data/ml, outputs/) into this clone.')
    ap.add_argument('--force', action='store_true', help='replace files that are already here')
    ap.add_argument('--zip', help='a zip already downloaded')
    a = ap.parse_args()
    if not MANIFEST.exists():
        sys.exit(f'{MANIFEST.relative_to(ROOT)} is missing: no release has been published yet')
    m = json.loads(MANIFEST.read_text(encoding='utf-8'))
    print(f"release {m['tag']}: {m['files']} files from the run of {m['run']['started_utc']} "
          f"({m['run']['steps_ok']}/{m['run']['steps']} steps, {m['run']['tests_passed']}/{m['run']['tests']} tests)")
    with tempfile.TemporaryDirectory(prefix='qcom-outputs-') as tmp:
        zpath = Path(a.zip) if a.zip else Path(tmp) / m['asset']
        if not a.zip:
            print(f"downloading {m['bytes'] / 1e6:.0f} MB from {m['url']}")
            download(m['url'], zpath, m['bytes'])
        digest = sha256(zpath)
        if digest != m['sha256']:
            sys.exit(f"refused: sha256 {digest} does not match the manifest's {m['sha256']}")
        counts = extract(zpath, a.force)
    print(f"done: {counts['written']} files written, {counts['kept']} already here and kept"
          + (' (pass --force to replace them)' if counts['kept'] else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
