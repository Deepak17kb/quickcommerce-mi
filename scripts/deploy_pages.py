"""
deploy_pages.py — publish the website on GitHub Pages: https://deepak17kb.github.io/quickcommerce-mi/

    python scripts/build_site.py                      # builds outputs/site and stages site_dist/ (stage() below)
    python scripts/deploy_pages.py                    # stage site_dist/ again, commit it, push: the Pages workflow deploys it
    python scripts/deploy_pages.py --no-push          # stage and commit only
    python scripts/deploy_pages.py --check site_dist  # what the Pages workflow runs before it deploys; exit 1 if not ready

HOW THE LIVE SITE UPDATES ITSELF. site_dist/ is tracked in git. Every site build (build_site.py, and so the last phase
of run_all.py) writes it, and .github/workflows/pages.yml deploys it whenever a push to main changes it. Publishing is
a commit and a push, which this script does; nothing is uploaded by hand.

WHAT GOES IN site_dist/: the one-file site (every number inlined), its service worker, icons and web manifest, the
README's badge files (badges/*.json, read by shields.io), a 404 page that sends a lost visitor home, and .nojekyll.
stage() refuses anything off that list, and never deletes a file it did not write.

THE LIVE SITE'S ANALYST. GitHub Pages serves files only. The page answers with the analyst engine built into it,
scored at build time on the project's own question sets, and asks the project's Python analyst instead whenever
site/config.json names a public one that answers (render.yaml deploys it). A product a visitor adds stays in their
own browser; Export and Import on the Products page move it between browsers and devices.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'outputs' / 'site'
DIST = ROOT / 'site_dist'
FILES = ['index.html', 'sw.js', 'manifest.webmanifest', 'icon-192.png', 'icon-512.png', 'apple-touch-icon.png']
WRITTEN = set(FILES) | {'404.html', '.nojekyll', 'badges'}
BLOCKS = ['meta', 'models', 'optimize', 'pipeline', 'whatif', 'explorer', 'reality', 'analyst', 'festive', 'photos', 'analystEval']
SOURCES = [ROOT / 'site' / f for f in ('index.html', 'app.css', 'app.js', 'analyst.js', 'sw.js', 'config.json')] + \
          [ROOT / 'scripts' / 'build_site.py']

NOT_FOUND = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ShelfPulse · not found</title>
<meta name="theme-color" content="#111216"><link rel="icon" href="{base}icon-192.png">
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#111216;color:#f4f5f7;font:16px/1.5 system-ui,sans-serif;padding:24px}}
a{{display:inline-block;margin-top:14px;background:#c9f24a;color:#1b2500;font-weight:800;text-decoration:none;padding:12px 18px;border-radius:12px}}
b{{font-size:28px;letter-spacing:-.02em}}</style></head>
<body><div><b>Nothing at this address.</b><p>ShelfPulse lives on one page. Its sections are behind the # in the address.</p>
<a href="{base}">Open ShelfPulse</a></div><script>setTimeout(function () {{ location.replace('{base}' + (location.hash || '')); }}, 2500);</script></body></html>
"""


def git(*args, cwd=ROOT, check=True) -> str:
    p = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if check and p.returncode != 0:
        raise SystemExit(f'git {" ".join(args)} failed:\n{p.stderr.strip()}')
    return p.stdout.strip()


def owner_repo(remote_url: str) -> tuple[str, str] | None:
    m = re.search(r'github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$', remote_url or '')
    return (m.group(1), m.group(2)) if m else None


def site_url() -> tuple[str, str]:
    """(live URL, base path) from the origin remote: a project site lives under /<repo>/, a user site at /."""
    o = owner_repo(git('remote', 'get-url', 'origin', check=False))
    if not o:
        return '', '/'
    owner, repo = o
    base = '/' if repo.lower() == f'{owner.lower()}.github.io' else f'/{repo}/'
    return f'https://{owner.lower()}.github.io{base}', base


def problems(folder: Path) -> list:
    """What is wrong with a staged folder; [] when it can be deployed."""
    out = []
    if not folder.is_dir():
        return [f'{folder} does not exist']
    for f in FILES + ['404.html', '.nojekyll']:
        if not (folder / f).is_file():
            out.append(f'{f} is missing')
    extra = sorted(p.name for p in folder.iterdir() if p.name not in WRITTEN)
    if extra:
        out.append(f'unexpected files: {extra}')
    page = folder / 'index.html'
    if page.is_file():
        html = page.read_text(encoding='utf-8')
        missing = [b for b in BLOCKS if f'id="d-{b}"' not in html]
        if missing:
            out.append(f'index.html is missing data blocks {missing}')
        if html.count('<script>') < 2 or 'QCAnalyst' not in html:
            out.append('index.html has no analyst engine')
    for b in sorted((folder / 'badges').glob('*.json')) if (folder / 'badges').is_dir() else []:
        try:
            doc = json.loads(b.read_text(encoding='utf-8'))
            if doc.get('schemaVersion') != 1 or not doc.get('label') or not doc.get('message'):
                out.append(f'badges/{b.name} is not a shields.io endpoint document')
        except ValueError:
            out.append(f'badges/{b.name} is not JSON')
    return out


def stage(dest: Path = DIST, base: str | None = None) -> str:
    """Write the publishable site into `dest` (site_dist/ by default) from outputs/site. Returns its relative path."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    foreign = sorted(p.name for p in dest.iterdir() if p.name not in WRITTEN | {'.git'})
    if foreign:
        raise SystemExit(f'{dest} holds files this script did not write ({foreign}): move them, then stage again')
    for name in WRITTEN:
        p = dest / name
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    for f in FILES:
        src = SITE / f
        if not src.exists():
            raise SystemExit(f'{src.relative_to(ROOT)} is missing: build the site with python scripts/build_site.py')
        shutil.copyfile(src, dest / f)
    if (SITE / 'badges').is_dir():
        shutil.copytree(SITE / 'badges', dest / 'badges')
    base = site_url()[1] if base is None else base
    (dest / '404.html').write_text(NOT_FOUND.format(base=base), encoding='utf-8', newline='\n')
    (dest / '.nojekyll').write_text('', encoding='utf-8')
    bad = problems(dest)
    if bad:
        raise SystemExit('the staged site is not ready: ' + '; '.join(bad))
    try:
        return str(dest.relative_to(ROOT))
    except ValueError:
        return str(dest)


def stale() -> list:
    page = SITE / 'index.html'
    if not page.exists():
        return ['outputs/site/index.html']
    return [str(s.relative_to(ROOT)) for s in SOURCES if s.exists() and s.stat().st_mtime > page.stat().st_mtime]


def pages_on_actions(owner: str, repo: str) -> str:
    """Pages must deploy from GitHub Actions (the pages workflow), not from a branch. Switch it once if needed."""
    if not shutil.which('gh'):
        return 'gh not found: in the repository settings, set Pages > Source to GitHub Actions'
    p = subprocess.run(['gh', 'api', f'repos/{owner}/{repo}/pages', '--jq', '.build_type'], capture_output=True, text=True)
    if p.returncode == 0 and p.stdout.strip() == 'workflow':
        return 'Pages deploys from GitHub Actions'
    verb = 'PUT' if p.returncode == 0 else 'POST'
    q = subprocess.run(['gh', 'api', '-X', verb, f'repos/{owner}/{repo}/pages', '-f', 'build_type=workflow'],
                       capture_output=True, text=True)
    return 'Pages switched to deploy from GitHub Actions' if q.returncode == 0 else \
        f'could not switch Pages to GitHub Actions ({q.stderr.strip()[:160]}): do it in the repository settings'


def publish(push: bool = True, force: bool = False) -> int:
    old = stale()
    if old and not force:
        print('the built site is older than its sources (' + ', '.join(old) + '): run python scripts/build_site.py first, '
              'or pass --force to publish it as it is')
        return 1
    print('staged', stage())
    git('add', '--all', '--', 'site_dist')
    if not git('diff', '--cached', '--name-only', '--', 'site_dist'):
        print('site_dist is unchanged since the last commit: nothing new to publish')
        return 0
    built = datetime.fromtimestamp((SITE / 'index.html').stat().st_mtime, timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    git('commit', '-q', '-m', f'Publish the site built {built}', '--', 'site_dist')
    print('committed:', git('log', '-1', '--format=%h %s'))
    if not push:
        print('not pushed (--no-push): git push publishes it')
        return 0
    git('push', '-q')
    url, _ = site_url()
    o = owner_repo(git('remote', 'get-url', 'origin', check=False))
    if o:
        print(pages_on_actions(*o))
    print(f'pushed: the Pages workflow deploys it in a minute or two ({url}); watch it with gh run watch')
    return 0


def main():
    ap = argparse.ArgumentParser(description='Publish the built site on GitHub Pages through site_dist/.')
    ap.add_argument('--check', metavar='DIR', help='check a staged folder and exit (the Pages workflow runs this)')
    ap.add_argument('--no-push', action='store_true', help='stage and commit, do not push')
    ap.add_argument('--force', action='store_true', help='publish even if the built site is older than its sources')
    a = ap.parse_args()
    if a.check:
        bad = problems(Path(a.check))
        for b in bad:
            print('NOT READY', b)
        if not bad:
            print(f'{a.check}: ready to deploy')
        return 1 if bad else 0
    return publish(push=not a.no_push, force=a.force)


if __name__ == '__main__':
    sys.exit(main())
