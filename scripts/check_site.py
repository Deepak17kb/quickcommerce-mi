"""
check_site.py — exercise the built website without a browser.

    python scripts/check_site.py          # exit 1 if any page or control throws

Runs scripts/site_smoke.js under node: the site's own two scripts, on its own embedded data, against a stand-in DOM.
Every page is visited, every control is pressed with real values and with junk, and the analyst answers six questions.
It proves the code runs; it cannot see the layout. Without node it reports that and exits 0.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'outputs' / 'site' / 'index.html'


def run() -> tuple[int, str]:
    if not SITE.exists():
        return 1, 'site not built: python scripts/build_site.py'
    node = shutil.which('node')
    if not node:
        return 0, 'node not found: the site was built, but its scripts were not exercised'
    p = subprocess.run([node, str(ROOT / 'scripts' / 'site_smoke.js'), str(SITE)], capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return p.returncode, (p.stdout.strip() + ('\n' + p.stderr.strip() if p.stderr.strip() else ''))


if __name__ == '__main__':
    code, out = run()
    print(out)
    sys.exit(code)
