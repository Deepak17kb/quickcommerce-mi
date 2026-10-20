"""
readme_assets.py — the README's screenshots, cut from the pictures the browser check takes.

    python scripts/serve_site.py --no-open              (in another terminal)
    node scripts/site_browser_check.js                  # -> outputs/site/screens/*.png
    python scripts/readme_assets.py                     # -> docs/assets/*.png

Each README picture is the top of one screenshot (or a band of it), scaled to a fixed width and saved optimised, so
the pictures stay in step with the site: re-run these three after a change to site/.
"""
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCREENS = ROOT / 'outputs' / 'site' / 'screens'
OUT = ROOT / 'docs' / 'assets'

# README name: (screenshot, top, height in screenshot pixels or None for all of it, width to save)
SHOTS = {
    'home.png': ('01-home-light.png', 0, 900, 1280),
    'home-dark.png': ('19-home-dark.png', 0, 900, 1280),
    'products.png': ('03-products-another-light.png', 1760, 1080, 1280),
    'simulate.png': ('04-simulate-move-light.png', 0, 1000, 1280),
    'analyst.png': ('12-analyst-light.png', 0, 1000, 1280),
    'models.png': ('13-models-light.png', 0, 1150, 1280),
    'pipeline.png': ('16-pipeline-light.png', 0, 1250, 1280),
    'festive.png': ('40-festive-light.png', 0, 1000, 1280),
    'basket.png': ('51-basket-light.png', 0, None, 1280),
    'palette.png': ('52-palette-light.png', 0, None, 1280),
    'phone.png': ('24-home-phone.png', 0, 1688, 390),
    'phone-basket.png': ('56-basket-phone.png', 0, None, 390),
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    missing = [s for s, *_ in SHOTS.values() if not (SCREENS / s).exists()]
    if missing:
        print('missing screenshots (run node scripts/site_browser_check.js first):', ', '.join(missing))
        return 1
    for name, (src, top, height, width) in SHOTS.items():
        im = Image.open(SCREENS / src).convert('RGB')
        bottom = im.height if height is None else min(im.height, top + height)
        im = im.crop((0, top, im.width, bottom))
        if im.width != width:
            im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        im.save(OUT / name, optimize=True)
        print(f'{name:<18} {im.width}x{im.height}  {(OUT / name).stat().st_size / 1024:.0f} KB  <- {src}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
