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

KIND PHOTOS (2026-10-24). Open Food Facts has few of these Indian products (3 of 94), and the owner asked for real
photos over drawings. So a product with no exact photo can take a photo of its KIND (kaju katli, marigold garlands,
sweet corn) from Wikimedia Commons, under the file's own free licence (CC0, public domain, CC BY, CC BY-SA). KINDS
below names one file per kind, each looked at by eye before it went in: no brand or label visible, nothing that could
be taken for this product's own pack. The page marks these photos as a typical look, never as the product, and the
caption names the kind. A name that is a combo ('+', 'combo') takes no kind photo, and kinds whose free photos all show
another brand's pack (sunscreen, face wash, namkeen, air freshener, chocolate bars and gift packs) are left out on
purpose, so those products keep their drawing. The licence, author and file page are read from Commons by the script.
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
UA = 'ShelfPulse/1.0 (portfolio project; https://github.com/Deepak17kb/quickcommerce-mi)'
NON_FOOD = {'Personal Care', 'Home & Cleaning', 'Baby Care', 'Pet Supplies', 'Electronics & Stationery', 'Fashion & Lifestyle',
            'Kitchen & Dining', 'Other / General Merchandise', 'Health & Wellness'}
GENERIC = {'the', 'and', 'with', 'of', 'in', 'for', 'a', 'pack', 'combo', 'new', 'premium', 'classic', 'original', 'flavour',
           'flavor', 'flavoured', 'flavored', 'g', 'gm', 'kg', 'ml', 'l', 'ltr', 'litre', 'pcs', 'x', 'pouch', 'box', 'jar',
           'bottle', 'can', 'tin', 'bag', 'free', 'by'}
GIFT = {'gift', 'hamper', 'assorted', 'minis', 'celebrations'}
COMMONS = 'https://commons.wikimedia.org/w/api.php?'
FREE = ('cc0', 'public domain', 'cc by', 'cc-by')
COMBO = re.compile(r'\+|\bcombo\b', re.I)
# kind, rule on the lower-cased name (first that matches wins), Commons file, caption. Order matters: soap before
# perfume, mixed nuts before cashews, a chikki is not makhana.
KINDS = [
    ('soap', r'\bsoap\b', 'File:Soap in blue dish.JPG', 'A bar of soap'),
    ('shaving kit', r'shaving kit|grooming kit', 'File:Safety razor shaving kit.jpg', 'A shaving kit'),
    ('bubble tea', r'\bboba\b', 'File:A bubble tea with tapioca pearls, July 2018.jpg', 'Bubble tea'),
    ('cappuccino', r'cappuccino', 'File:A-cup-of-cappuccino-coffee-dar-es-salaam-cafe.jpg', 'A cappuccino'),
    ('sweet corn', r'sweet corn', 'File:Sweet Corns.jpg', 'Sweet corn kernels'),
    ('sugar', r'grocery sugar|\bcheeni\b', 'File:Granulated White Sugar with Large Crystals, Bright Side Light.jpg', 'White sugar'),
    ('fruit chaat', r'fruit chaat', 'File:Indian Fruit Chaat.jpg', 'Cut fruit (fruit chaat)'),
    ('potato chips', r'potato chips', 'File:Dill pickle chips.jpg', 'Potato chips'),
    ('marigold garland', r'marigold', 'File:Marigold garlands, Pak Khlong Talat flower market Bangkok.jpg', 'Marigold garlands'),
    ('aak flowers', r'\baak\b', 'File:Calotropis Gigantea Flower.jpg', 'Aak (crown flower) blossoms'),
    ('lotus', r'lotus flower', 'File:Lotus flower (978659).jpg', 'A pink lotus'),
    ('red roses', r'\bred\b.*\brose\b', 'File:Bouquet of red roses.jpg', 'Red roses'),
    ('white chrysanthemum', r'white chrysanthemum', 'File:White Chrysanthemum flower in Flowering plant market, Yunusabad, Tashkent.jpg', 'White chrysanthemums'),
    ('yellow chrysanthemum', r'yellow chrysanthemum', 'File:Chrysanthemum flowers yellow.jpg', 'Yellow chrysanthemums'),
    ('puja flowers', r'pooja flower', 'File:Flowers (jaba, aparijita) for puja.JPG', 'Flowers for puja'),
    ('tulsi', r'\btulsi\b', 'File:(Ocimum tenuiflorum) Tulasi foliage 02.jpg', 'Tulsi (holy basil) leaves'),
    ('shami leaves', r'\bshami\b', 'File:Prosopis cineraria kz05.jpg', 'Shami (banni) leaves'),
    ('incense', r'incense|agarbatti', 'File:Incense in India.jpg', 'Incense sticks'),
    ('purple orchid', r'purple orchid', 'File:Phalaenopsis Cultivar Mini 01.jpg', 'Purple orchids'),
    ('pink orchid', r'blush orchid', 'File:Phalaenopsis (aka).jpg', 'A pink orchid'),
    ('rose petals', r'^rose \(flowers', 'File:Red Rose Petals (4386388455).jpg', 'Rose petals'),
    ('perfume', r'perfume|eau de cologne|fragrance mist', 'File:Mogra spray perfume (Cauvery, Mysore) 2025 (02).jpg', 'A perfume bottle'),
    ('peanut chikki', r'peanut chikki', 'File:Peanut Chikki.JPG', 'Peanut chikki'),
    ('gajak', r'gajak', 'File:Gachak.JPG', 'Gajak'),
    ('makhana', r'^(?!.*chikki).*(makhana|fox nuts)', 'File:Foxnut Makhana - Nawada District - Bihar - 1.jpg', 'Makhana (fox nuts)'),
    ('mixed nuts', r'nuts mix|mix nuts|party mix|misra badam', 'File:Mixed Nuts (Alabama Extension).jpg', 'Mixed nuts'),
    ('dry fruits', r'^(?!.*brownie).*(dry fruits?\b.*(gift|potli)|panchmeva|dry fruit mix)',
     'File:Dry Fruits Namkeen Recipe - A Fasting Recipe By Sonia Goyal.jpg', 'Mixed dry fruits'),
    ('cashews', r'cashew', 'File:CASHEW NUTS.jpg', 'Cashews'),
    ('pistachios', r'pistachio', 'File:Roasted & Salted (51994480044).jpg', 'Pistachios'),
    ('dates', r'seeded dates|khajur', 'File:Dried dates - 1.jpg', 'Dried dates'),
    ('kaju katli', r'kaju katli', 'File:Kaju katli dessert - side view.jpg', 'Kaju katli'),
    ('rasgulla', r'rasgulla', 'File:Rasgulla.jpg', 'Rasgulla'),
    ('motichoor laddu', r'motichoor|boondi laddu', 'File:Motichoor Ki Laadu Khajrana Indore.jpg', 'Motichoor laddu'),
    ('soan papdi', r'soan papdi', 'File:Soan sohan papdi India Festive Sweets.jpg', 'Soan papdi'),
    ('kheer', r'kheer|payasam', 'File:Semiya Payasam Vermicelli Kheer.jpg', 'Vermicelli kheer (payasam)'),
    ('sabudana', r'sabudana|\bsago\b', 'File:Dried sago pearls.jpg', 'Sago pearls (sabudana)'),
    ('rice flour', r'rice flour', 'File:Rice Flour (Pitha Guri).jpg', 'Rice flour'),
    ('ice cream bar', r'ice cream stick', 'File:Chocolate vanilla ice cream bar.jpg', 'A chocolate-coated ice cream bar'),
    ('loaf cake', r'^(?!.*hamper).*(pound cake|slice cake|sliced cake)', 'File:Pound cake, September 2007 (cropped).jpg', 'Sliced loaf cake'),
    ('butter cookies', r'danish(?!.*choco)', 'File:Danish-butter-cookies-1032894.jpg', 'Danish butter cookies'),
    ('balloons', r'^balloons\b', 'File:Balloons Colorful Shooting Gallery Folk Festival.jpg', 'Balloons'),
    ('birthday decorations', r'^(?!.*themed).*birthday decoration kit', 'File:Birthday party decoration.jpg', 'Birthday decorations'),
    ('jar candles', r'^(?!.*(diffuser|lamp|urli|\btin\b)).*(jar candle|scented candle)', 'File:3set jars.jpg', 'Scented jar candles'),
    ('wreath', r'christmas wreath', 'File:Christmas wreaths at apartment door in Sherwood, Queensland, 2024, 14.jpg', 'A green wreath'),
]


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


def kind_of(name: str):
    """The KINDS row a product belongs to, or None. A combo of several products has no single kind."""
    n = str(name or '').lower()
    if COMBO.search(n):
        return None
    return next((k for k in KINDS if re.search(k[1], n)), None)


def strip_html(s: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', str(s or ''))).strip()


def commons_info(titles: list) -> dict:
    """Address (960 px wide), file page, licence and author of each Commons file, read from Commons."""
    out = {}
    for i in range(0, len(titles), 40):
        q = {'action': 'query', 'format': 'json', 'titles': '|'.join(titles[i:i + 40]), 'prop': 'imageinfo',
             'iiprop': 'url|extmetadata', 'iiurlwidth': 960}
        with urllib.request.urlopen(urllib.request.Request(COMMONS + urllib.parse.urlencode(q), headers={'User-Agent': UA}), timeout=40) as r:
            d = json.loads(r.read().decode('utf-8'))
        norm = {n['to']: n['from'] for n in d['query'].get('normalized', [])}
        for p in d['query']['pages'].values():
            ii, meta = p['imageinfo'][0], p['imageinfo'][0].get('extmetadata', {})
            lic = (meta.get('LicenseShortName') or {}).get('value', '')
            if not lic.lower().startswith(FREE):
                raise SystemExit(f"{p['title']}: licence {lic!r} is not a free licence this site uses")
            out[norm.get(p['title'], p['title'])] = {
                # the API now answers with thumb.wikimedia.org plus tracking parameters; upload.wikimedia.org serves
                # the same file (checked 2026-10-24) and is the host the page's CSP allows
                'image': re.sub(r'^https://thumb\.wikimedia\.org/', 'https://upload.wikimedia.org/', ii['thumburl'].split('?')[0]),
                'source': ii['descriptionurl'], 'license': lic,
                'credit': strip_html((meta.get('Artist') or {}).get('value')) or 'Wikimedia Commons contributor'}
        time.sleep(1)
    return out


def kind_photos(prods: list, taken: set) -> dict:
    """A typical-look photo for every product that has no exact photo and belongs to a kind."""
    rows = {p['name']: kind_of(p['name']) for p in prods}
    files = sorted({k[2] for k in rows.values() if k})
    info = commons_info(files) if files else {}
    out = {}
    for p in prods:
        key, k = f"{p['name']}|{p.get('pack') or ''}", rows[p['name']]
        if k and key not in taken:
            out[key] = {'name': p['name'], 'pack': p.get('pack'), **info[k[2]], 'shows': k[3], 'kind': k[0], 'file': k[2],
                        'same_pack': False}
    return out


def candidates(food_only: bool = True) -> list:
    """The products the site draws a picture for: followed listings and the festive planner's examples."""
    seen, out = set(), []
    def add(name, pack, cat):
        k = (name, pack)
        if name and k not in seen and not (food_only and cat in NON_FOOD):
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
    ap.add_argument('--kinds-only', action='store_true', help='keep the saved Open Food Facts matches, redo the kind photos')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')   # product names carry Devanagari, Odia, emoji
    prods = [] if a.kinds_only else candidates()[: a.limit or None]
    photos = {}
    if a.kinds_only:
        old = json.loads(OUT.read_text(encoding='utf-8'))
        photos = {k: v for k, v in old['photos'].items() if not v.get('kind')}
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
    exact = len(photos)
    searched = old['searched'] if a.kinds_only else len(prods)
    every = candidates(food_only=False)
    photos.update(kind_photos(every, set(photos)))
    doc = {'checked': date.today().isoformat(), 'source': 'Open Food Facts (openfoodfacts.org), search.openfoodfacts.org',
           'license': 'CC BY-SA 3.0: reuse with credit', 'searched': searched, 'matched': exact,
           'rule': 'brand at the start of our name; every word of their name in ours (at least two); at least half of ours in '
                   'theirs; a gift pack only matches a gift pack; same pack preferred',
           'kind_source': 'Wikimedia Commons (commons.wikimedia.org), one reviewed file per kind; licence and author per file',
           'kind_products': len(every), 'kind_matched': len(photos) - exact,
           'photos': photos}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    print(f'{exact} exact photos (Open Food Facts), {len(photos) - exact} typical-look photos (Wikimedia Commons) '
          f'of {len(every)} products -> {OUT.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
