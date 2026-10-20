"""
deploy_pages.py — publish the built website to GitHub Pages, from the gh-pages branch of this repository.

    python scripts/build_site.py              # first, whenever the site or its outputs changed
    python scripts/deploy_pages.py            # -> https://<owner>.github.io/<repo>/
    python scripts/deploy_pages.py --dry-run  # stage the files and list them; push nothing

WHAT GOES UP: outputs/site/index.html (the one-file site, every number inlined), its service worker, icons and web
manifest, a 404 page that sends a lost visitor to the home page, and .nojekyll. Nothing else from the repository: the
gh-pages branch is an orphan whose only history is deploys, so the data and code stay on main.

THE LIVE SITE HAS NO PYTHON SERVER BEHIND IT. It runs as the page does when opened from disk: the analyst answers with
the engine built into the page (scored at build time on the project's own question sets, 42/42 and 25/25 on
2026-10-14), the simulations and optimizer read the grids run in advance, and a product a visitor adds stays in that
visitor's browser. `python scripts/serve_site.py` is still the way to get the project's own Python analyst live.

Before pushing, the staged page is checked: it must be the complete built site (all data blocks, both scripts), and
the stage must hold no file outside the list above.

First deploy only: Pages is switched on for the gh-pages branch with the GitHub CLI (`gh`), if it is installed and
signed in; otherwise the script prints the one setting to change by hand.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'outputs' / 'site'
FILES = ['index.html', 'sw.js', 'manifest.webmanifest', 'icon-192.png', 'icon-512.png', 'apple-touch-icon.png']
BLOCKS = ['meta', 'models', 'optimize', 'pipeline', 'whatif', 'explorer', 'reality', 'analyst', 'festive', 'analystEval']

NOT_FOUND = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Qcom · not found</title>
<meta name="theme-color" content="#111216"><link rel="icon" href="{base}icon-192.png">
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#111216;color:#f4f5f7;font:16px/1.5 system-ui,sans-serif;padding:24px}}
a{{display:inline-block;margin-top:14px;background:#c9f24a;color:#1b2500;font-weight:800;text-decoration:none;padding:12px 18px;border-radius:12px}}
b{{font-size:28px;letter-spacing:-.02em}}</style></head>
<body><div><b>Nothing at this address.</b><p>Qcom lives on one page. Its sections are behind the # in the address.</p>
<a href="{base}">Open Qcom</a></div><script>setTimeout(function () {{ location.replace('{base}' + (location.hash || '')); }}, 2500);</script></body></html>
"""


def git(*args, cwd=ROOT, check=True) -> str:
    p = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if check and p.returncode != 0:
        raise SystemExit(f'git {" ".join(args)} failed:\n{p.stderr.strip()}')
    return p.stdout.strip()


def owner_repo(remote_url: str) -> tuple[str, str]:
    m = re.search(r'github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$', remote_url)
    if not m:
        raise SystemExit(f'the remote is not a GitHub repository: {remote_url}')
    return m.group(1), m.group(2)


def check_site(html: str):
    """The page must be the complete built site: every data block and both inline scripts."""
    missing = [b for b in BLOCKS if f'id="d-{b}"' not in html]
    if missing:
        raise SystemExit(f'outputs/site/index.html is missing data blocks {missing}: rebuild it with python scripts/build_site.py')
    if html.count('<script>') < 2 or 'QCAnalyst' not in html:
        raise SystemExit('outputs/site/index.html has no analyst engine: rebuild it with python scripts/build_site.py')


def stage(dest: Path, base: str):
    for f in FILES:
        src = SITE / f
        if not src.exists():
            raise SystemExit(f'{src.relative_to(ROOT)} is missing: rebuild with python scripts/build_site.py')
        shutil.copyfile(src, dest / f)
    check_site((dest / 'index.html').read_text(encoding='utf-8'))
    (dest / '404.html').write_text(NOT_FOUND.format(base=base), encoding='utf-8', newline='\n')
    (dest / '.nojekyll').write_text('', encoding='utf-8')
    extra = sorted(p.name for p in dest.iterdir() if p.name not in set(FILES) | {'404.html', '.nojekyll', '.git'})
    if extra:
        raise SystemExit(f'unexpected files staged: {extra}')


def enable_pages(owner: str, repo: str) -> str:
    if not shutil.which('gh'):
        return 'gh not found: in the repository settings, set Pages to deploy from the gh-pages branch, folder /'
    body = json.dumps({'source': {'branch': 'gh-pages', 'path': '/'}})
    p = subprocess.run(['gh', 'api', '-X', 'POST', f'repos/{owner}/{repo}/pages', '--input', '-'], input=body,
                       capture_output=True, text=True, encoding='utf-8')
    if p.returncode == 0:
        return 'Pages switched on for the gh-pages branch'
    if 'already' in (p.stdout + p.stderr).lower() or '409' in p.stderr:
        return 'Pages was already on'
    return f'could not switch Pages on ({p.stderr.strip()[:200]}): set it to the gh-pages branch in the repository settings'


def main():
    ap = argparse.ArgumentParser(description='Publish outputs/site to GitHub Pages (gh-pages branch).')
    ap.add_argument('--dry-run', action='store_true', help='stage and list the files; push nothing')
    ap.add_argument('--remote', default='origin')
    a = ap.parse_args()

    url = git('remote', 'get-url', a.remote)
    owner, repo = owner_repo(url)
    user_site = repo.lower() == f'{owner.lower()}.github.io'
    base = '/' if user_site else f'/{repo}/'
    live = f'https://{owner.lower()}.github.io{base}'
    sha = git('rev-parse', '--short', 'HEAD', check=False) or 'unknown'
    dirty = bool(git('status', '--porcelain', check=False))
    name, email = git('config', 'user.name', check=False), git('config', 'user.email', check=False)

    with tempfile.TemporaryDirectory(prefix='qcom-pages-') as tmp:
        dest = Path(tmp)
        stage(dest, base)
        size = sum(p.stat().st_size for p in dest.iterdir() if p.is_file())
        print(f'staged {len(list(dest.iterdir()))} files, {size / 1024:.0f} KB, for {live}')
        for p in sorted(dest.iterdir()):
            print(f'  {p.name:<24} {p.stat().st_size / 1024:>8.1f} KB')
        if a.dry_run:
            print('dry run: nothing pushed')
            return 0
        built = datetime.fromtimestamp((SITE / 'index.html').stat().st_mtime, timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        msg = f'Deploy Qcom: site built {built} from {sha}{" (with uncommitted changes)" if dirty else ""}'
        ident = (['-c', f'user.name={name}'] if name else []) + (['-c', f'user.email={email}'] if email else [])
        git('init', '-q', '-b', 'gh-pages', cwd=dest)
        git('add', '-A', cwd=dest)
        git(*ident, 'commit', '-q', '-m', msg, cwd=dest)
        git('push', '-q', '--force', url, 'gh-pages', cwd=dest)
    print(f'pushed gh-pages: {msg}')
    print(enable_pages(owner, repo))
    print(f'live (GitHub takes a minute or two to publish): {live}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
