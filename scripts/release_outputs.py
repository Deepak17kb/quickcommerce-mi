"""
release_outputs.py — publish what a full run produced as a GitHub Release, so a clone can use it without the
three-hour pipeline.

    python scripts/release_outputs.py              # pack, upload as release outputs-<date>, update data/OUTPUTS_RELEASE.json
    python scripts/release_outputs.py --pack-only  # write the zip under outputs/release/ and stop

PACKED: the ML layer (data/ml/*.parquet) and outputs/ (models, analyst, audit, festive planner, run log, showcase
pages, the built site), as left by the last run recorded in outputs/run_log/run_all.json. Left out: the browser
check's screenshots (outputs/site/screens; the README's pictures are in docs/assets) and outputs/release itself.
NEVER packed: data/user_added (products a person added on their own machine, with photos from their camera).

The manifest data/OUTPUTS_RELEASE.json (tracked in git) names the release, the file, its sha256 and size, and the
commit and run it came from. scripts/fetch_outputs.py downloads exactly that file and refuses it if the hash differs;
CI does the same before it runs the full test suite.

A release is refused unless the run it packs finished with every step and every test passing.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'data' / 'OUTPUTS_RELEASE.json'
RUN = ROOT / 'outputs' / 'run_log' / 'run_all.json'
OUT = ROOT / 'outputs' / 'release'
SKIP = ('outputs/site/screens/', 'outputs/release/')


def members() -> list:
    files = sorted((ROOT / 'data' / 'ml').glob('*.parquet'))
    files += sorted(p for p in (ROOT / 'outputs').rglob('*') if p.is_file())
    out = []
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith(SKIP) or rel == 'outputs/.gitkeep' or 'user_added' in rel:
            continue
        out.append((p, rel))
    return out


def run_summary() -> dict:
    run = json.loads(RUN.read_text(encoding='utf-8'))
    cases = (run.get('tests') or {}).get('cases', [])
    return {'started_utc': run.get('started_utc'), 'finished_utc': run.get('finished_utc'), 'resumed': run.get('resumed'),
            'steps': len(run['steps']), 'steps_ok': sum(s['ok'] for s in run['steps']),
            'tests': len(cases), 'tests_passed': sum(c['state'] == 'passed' for c in cases)}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def pack(stamp: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    zpath = OUT / f'shelfpulse-outputs-{stamp}.zip'
    files = members()
    with zipfile.ZipFile(zpath, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p, rel in files:
            z.write(p, rel)
    print(f'packed {len(files)} files, {sum(p.stat().st_size for p, _ in files) / 1e6:.1f} MB -> '
          f'{zpath.relative_to(ROOT)} ({zpath.stat().st_size / 1e6:.1f} MB)')
    return zpath


def gh(*args) -> str:
    p = subprocess.run(['gh', *args], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    if p.returncode != 0:
        raise SystemExit(f'gh {" ".join(args[:2])} failed: {p.stderr.strip()}')
    return p.stdout.strip()


def main():
    ap = argparse.ArgumentParser(description='Publish the ML layer and outputs/ as a GitHub Release.')
    ap.add_argument('--pack-only', action='store_true')
    ap.add_argument('--allow-incomplete', action='store_true', help='release even if the run had a failing step or test')
    a = ap.parse_args()
    run = run_summary()
    complete = run['steps'] and run['steps_ok'] == run['steps'] and run['tests'] and run['tests_passed'] == run['tests']
    if not complete and not a.allow_incomplete:
        sys.exit(f'the last run is not complete ({run["steps_ok"]}/{run["steps"]} steps, {run["tests_passed"]}/{run["tests"]} '
                 'tests): finish it first, or pass --allow-incomplete')
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    zpath = pack(today)
    digest, size = sha256(zpath), zpath.stat().st_size
    if a.pack_only:
        print('sha256', digest)
        return 0
    if not shutil.which('gh'):
        sys.exit('the GitHub CLI (gh) is needed to publish; the zip is ready at ' + str(zpath.relative_to(ROOT)))
    repo = gh('repo', 'view', '--json', 'nameWithOwner', '--jq', '.nameWithOwner')
    tags = set(gh('release', 'list', '--limit', '100', '--json', 'tagName', '--jq', '.[].tagName').split())
    tag, n = f'outputs-{today}', 2
    while tag in tags:
        tag, n = f'outputs-{today}-{n}', n + 1
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    notes = (f"Everything a full run of the pipeline produced, so a clone can open the site, ask the analyst and run the "
             f"whole test suite without the three-hour run.\n\n"
             f"- Run: started {run['started_utc']}, finished {run['finished_utc']}; {run['steps_ok']}/{run['steps']} steps OK, "
             f"{run['tests_passed']}/{run['tests']} tests passed\n"
             f"- Built from commit `{commit[:12]}`\n- `{zpath.name}`: {size / 1e6:.1f} MB, sha256 `{digest}`\n\n"
             f"Use it: `python scripts/fetch_outputs.py` (checks the sha256, writes data/ml/ and outputs/).\n\n"
             f"Inside: the ML feature layer (data/ml) and outputs/ (models, analyst, audits, run log, built site). "
             f"Observed and simulated results keep their tags in every file; see the README.")
    # gh reads "file#label": the project lives under "Project #1 ML", so pass the path relative to ROOT (gh runs there)
    # and name the label, or gh cuts the path at the '#' and finds no file
    asset = f'{zpath.relative_to(ROOT).as_posix()}#{zpath.name}'
    gh('release', 'create', tag, asset, '--title', f'Run outputs, {today}', '--notes', notes, '--target', 'main')
    doc = {'tag': tag, 'asset': zpath.name, 'url': f'https://github.com/{repo}/releases/download/{tag}/{zpath.name}',
           'sha256': digest, 'bytes': size, 'files': len(members()), 'commit': commit,
           'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'run': run}
    MANIFEST.write_text(json.dumps(doc, indent=1) + '\n', encoding='utf-8', newline='\n')
    print(f'released {tag}: {doc["url"]}\nwrote {MANIFEST.relative_to(ROOT)}: commit it so fetch_outputs.py and CI use this release')
    return 0


if __name__ == '__main__':
    sys.exit(main())
