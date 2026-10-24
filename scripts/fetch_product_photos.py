"""
fetch_product_photos.py — real product photos for the website, from Open Food Facts, matched strictly or not at all.

    python scripts/fetch_product_photos.py            # -> data/reference/PRODUCT_PHOTOS.json (tracked, reviewed)
    python scripts/fetch_product_photos.py --review   # print every candidate with why it was taken or refused

WHY THIS SOURCE. The owner asked for real product images "from Google or Blinkit". Photos on Google Images and on
Blinkit belong to the brands and to Blinkit, Blinkit's terms forbid scraping, and this project's own rule is no
scraping (CLAUDE.md s.2). Open Food Facts (openfoodfacts.org) is an open database of packaged foods whose product
photos are published under CC BY-SA 3.0 for anyone to reuse with credit. So that is the source, and every photo is
credited on the page that shows it. Nothing is downloaded: the site links the photo where Open Food Facts hosts it.

MATCHING. A wrong photo is worse than a drawing, so a photo is used only when
    brand     the Open Food Facts brand appears at the start of our product name,
    theirs    every word of its product name (brand and pack words aside) is in ours, at least two,
    ours      at least half of our own words are in its name, so a short name ("Kitkat Chocolate") cannot stand in for
              a long one ("KitKat Cele-Break Assorted Rakhi Chocolate Gift Pack"), and
    form      a gift pack, hamper or assortment only takes a photo that is one too,
and among those the candidate with the same pack size wins. The first run (2026-10-24) at a looser rule (75% of their
words, no reverse check) put a plain Dairy Milk bar on a Silk Heart Blush gift pack; the rule above refuses it. The caption always says what the photo shows ("Frooti
Mango Drink, 600 ml"), so a photo of another pack size of the same product is never passed off as ours.

Products searched: the followed listings, and the observed listings the festive planner shows. Food only: Open Food
Facts holds food; personal-care and household items keep their drawn picture. Search is polite (one request every
two seconds) and the result is a reviewed file, so a build never touches the network.
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'reference' / 'PRODUCT_PHOTOS.json'
API = 'https://search.openfoodfacts.org/search?'
UA = 'Qcom/1.0 (portfolio project; https://github.com/Deepak17kb/quickcommerce-mi)'
NON_FOOD = {'Personal Care', 'Home & Cleaning', 'Baby Care', 'Pet Supplies', 'Electronics & Stationery', 'Fashion & Lifestyle',
            'Kitchen & Dining', 'Other / General Merchandise', 'Health & Wellness'}
GENERIC = {'the', 'and', 'with', 'of', 'in', 'for', 'a', 'pack', 'combo', 'new', 'premium', 'classic', 'original', 'flavour',
           'flavor', 'flavoured', 'flavored', 'g', 'gm', 'kg', 'ml', 'l', 'ltr', 'litre', 'pcs', 'x', 'pouch', 'box', 'jar',
           'bottle', 'can', 'tin', 'bag', 'free', 'by'}
GIFT = {'gift', 'hamper', 'assorted', 'minis', 'celebrations'}


def words(text: str) -> list:
    t = re.sub(r"[*'’`]", '', str(text or '').lower())
    return [w for w in re.findall(r'[a-z0-9]+', t) if w not in GENERIC and not re.fullmatch(r'\d+(\.\d+)?', w)]


def qty(text: str):
    """A pack size in grams or millilitres, if one can be read: '600 ml' -> 600, '2 Ltr' -> 2000, '1Kg' -> 1000."""
    m = re.search(r'(\d+(?:\.\d+)?)\s*(kg|g|gm|gms|ml|l|ltr|litre|liter)\b', str(text or '').lower())
    if not m:
        return None
    v, u = float(m.group(1)), m.group(2)
    return v * 1000 if u in ('kg', 'l', 'ltr', 'litre', 'liter') else v


def judge(ours: dict, hit: dict) -> dict:
    """Is this Open Food Facts product ours? The reasons are kept for review."""
    name = ours['name']
    brands = hit.get('brands') or []
    brands = brands if isinstance(brands, list) else [b.strip() for b in str(brands).split(',')]
    lead = ' '.join(words(name)[:4])
    brand_ok = any(words(b) and ' '.join(words(b)) in lead for b in brands if b)
    brand_words = {w for b in brands if b for w in words(b)}
    theirs = set(words(hit.get('product_name'))) - brand_words
    mine = set(words(name)) - brand_words
    shared = sorted(theirs & mine)
    score = len(shared) / len(theirs) if theirs else 0.0
    cover = len(shared) / len(mine) if mine else 0.0
    form_ok = not (GIFT & mine) or bool(GIFT & theirs)
    q1, q2 = qty(ours.get('pack')) or qty(name), qty(hit.get('quantity'))
    ok = bool(brand_ok and score == 1.0 and cover >= 0.5 and len(shared) >= 2 and form_ok and hit.get('image_front_small_url'))
    return {'ok': ok, 'brand_ok': brand_ok, 'name_score': round(score, 2), 'cover': round(cover, 2), 'form_ok': form_ok,
            'shared': shared, 'same_pack': q1 is not None and q2 is not None and abs(q1 - q2) < 1e-6}


def search(q: str) -> list:
    url = API + urllib.parse.urlencode({'q': q, 'page_size': 8,
                                        'fields': 'code,product_name,brands,quantity,image_front_small_url,image_front_url'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=30) as r:
                return json.loads(r.read().decode('utf-8')).get('hits', [])
        except Exception:
            time.sleep(4 * (attempt + 1))
    return []


def candidates() -> list:
    """The products the site draws a picture for: followed listings and the festive planner's examples."""
    seen, out = set(), []
    def add(name, pack, cat):
        k = (name, pack)
        if name and k not in seen and cat not in NON_FOOD:
            seen.add(k)
            out.append({'name': name, 'pack': pack, 'category': cat})
    site = ROOT / 'outputs' / 'site' / 'index.html'
    if site.exists():
        html = site.read_text(encoding='utf-8')
        m = re.search(r'id="d-explorer">(.*?)</script>', html, re.S)
        for c in json.loads(m.group(1))['chains'] if m else []:
            add(c['name'], c.get('pack'), c.get('category'))
    fest = ROOT / 'outputs' / 'festive' / 'festive_planner.json'
    if fest.exists():
        for g in json.loads(fest.read_text(encoding='utf-8'))['groups'].values():
            for e in g['examples']:
                add(e['name'], e.get('pack'), e.get('category'))
    return out


def main():
    ap = argparse.ArgumentParser(description='Match products to openly licensed Open Food Facts photos.')
    ap.add_argument('--review', action='store_true', help='print every candidate and the reason it was taken or refused')
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')   # product names carry Devanagari, Odia, emoji
    prods = candidates()[: a.limit or None]
    photos = {}
    for i, p in enumerate(prods, 1):
        hits = search(re.sub(r'\*+', '', p['name']))
        judged = [(judge(p, h), h) for h in hits]
        good = [(j, h) for j, h in judged if j['ok']]
        good.sort(key=lambda jh: (not jh[0]['same_pack'], -jh[0]['cover']))
        if good:
            j, h = good[0]
            photos[f"{p['name']}|{p.get('pack') or ''}"] = {
                'name': p['name'], 'pack': p.get('pack'), 'image': h['image_front_small_url'], 'image_large': h.get('image_front_url'),
                'shows': ', '.join(x for x in (h.get('product_name'), h.get('quantity')) if x),
                'source': f"https://world.openfoodfacts.org/product/{h['code']}", 'code': h['code'],
                'license': 'CC BY-SA 3.0', 'credit': 'Open Food Facts contributors', 'same_pack': j['same_pack'],
                'match': {'brand': j['brand_ok'], 'name_score': j['name_score'], 'cover': j['cover'], 'shared_words': j['shared']}}
        if a.review:
            print(f"[{i:03d}] {'PHOTO' if good else '  -  '} {p['name']} {p.get('pack') or ''}")
            for j, h in judged[:3]:
                print(f"        {'ok ' if j['ok'] else 'no '} brand={j['brand_ok']!s:<5} score={j['name_score']:<4} cover={j['cover']:<4}"
                      f" form={j['form_ok']!s:<5} same_pack={j['same_pack']!s:<5}"
                      f" {h.get('brands')} | {h.get('product_name')} | {h.get('quantity')}")
        time.sleep(2)                                     # polite: about 30 requests a minute at most
    doc = {'checked': date.today().isoformat(), 'source': 'Open Food Facts (openfoodfacts.org), search.openfoodfacts.org',
           'license': 'CC BY-SA 3.0: reuse with credit', 'searched': len(prods), 'matched': len(photos),
           'rule': 'brand at the start of our name; every word of their name in ours (at least two); at least half of ours in '
                   'theirs; a gift pack only matches a gift pack; same pack preferred',
           'photos': photos}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    print(f'{len(photos)} of {len(prods)} products matched a photo -> {OUT.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
