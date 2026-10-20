"""
user_products.py — products a person adds on the website (a photo and the details), kept apart from the project's data.

They live in data/user_added/: products.json and images/. Nothing in the pipeline, the models or the analyst reads
them. A product added here is the person's own entry, tagged USER: it is not an observation of any platform and is never
mixed with the observed or the simulated rows. data/raw is never touched.

Every field is checked on the way in: text lengths, prices between Rs 0.01 and Rs 1,00,000, a delivery time of 1-240
minutes, and a photo that must really be the JPEG, PNG or WebP it claims to be, at most 3 MB.
"""
import base64
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'data' / 'user_added'
PLATFORMS = ('Blinkit', 'Swiggy Instamart', 'Flipkart Minutes', 'BigBasket')
MAX_IMAGE = 3 * 1024 * 1024
MAX_PRODUCTS = 500
ID = re.compile(r'[0-9a-f]{12}')
IMAGE_TYPES = {'image/jpeg': ('jpg', b'\xff\xd8\xff'), 'image/png': ('png', b'\x89PNG\r\n\x1a\n'), 'image/webp': ('webp', None)}
CONTENT_TYPE = {'jpg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp'}
_lock = threading.Lock()


class Invalid(ValueError):
    """A product that cannot be saved; the message says why, in words a person can act on."""


def _text(v, n, field, required=False):
    s = ' '.join(str(v if v is not None else '').split())
    if required and not s:
        raise Invalid(f'{field} is required')
    if len(s) > n:
        raise Invalid(f'{field} is longer than {n} characters')
    return s or None


def _num(v, lo, hi, field):
    if v is None or v == '':
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise Invalid(f'{field} is not a number') from None
    if x != x or not lo <= x <= hi:
        raise Invalid(f'{field} must be between {lo:g} and {hi:g}')
    return round(x, 2)


def _image(data_url):
    if not data_url:
        return None
    m = re.fullmatch(r'data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=\s]+)', str(data_url))
    if not m:
        raise Invalid('the photo must be a JPEG, PNG or WebP image')
    try:
        raw = base64.b64decode(re.sub(r'\s+', '', m.group(2)), validate=True)
    except ValueError:
        raise Invalid('the photo could not be read') from None
    if len(raw) > MAX_IMAGE:
        raise Invalid('the photo is larger than 3 MB')
    ext, magic = IMAGE_TYPES[m.group(1)]
    ok = raw.startswith(magic) if magic else (raw[:4] == b'RIFF' and raw[8:12] == b'WEBP')
    if not ok:
        raise Invalid('the file is not the image it says it is')
    return ext, raw


def clean(payload) -> dict:
    """The fields of a new product, checked; raises Invalid."""
    if not isinstance(payload, dict):
        raise Invalid('send the product as a JSON object')
    prices = payload.get('prices') or {}
    if not isinstance(prices, dict):
        raise Invalid('prices must be an object of platform -> price')
    out = {}
    for p in PLATFORMS:
        x = _num(prices.get(p), 0.01, 100000, f'the {p} price')
        if x is not None:
            out[p] = x
    stock = payload.get('in_stock', True)
    in_stock = stock if isinstance(stock, bool) else str(stock).strip().lower() not in ('false', '0', 'no', 'out')
    return {'name': _text(payload.get('name'), 120, 'the name', required=True), 'brand': _text(payload.get('brand'), 60, 'the brand'),
            'pack': _text(payload.get('pack'), 40, 'the pack size'), 'category': _text(payload.get('category'), 60, 'the category'),
            'prices': out, 'in_stock': bool(in_stock), 'eta': _num(payload.get('eta'), 1, 240, 'the delivery time'),
            'notes': _text(payload.get('notes'), 300, 'the notes')}


def _file(store):
    return Path(store) / 'products.json'


def load(store=None) -> list:
    f = _file(store or STORE)
    if not f.exists():
        return []
    try:
        d = json.loads(f.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    return [p for p in d if isinstance(p, dict) and ID.fullmatch(str(p.get('id', '')))] if isinstance(d, list) else []


def _save(store, items):
    store = Path(store)
    store.mkdir(parents=True, exist_ok=True)
    tmp = store / 'products.json.tmp'
    tmp.write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding='utf-8', newline='\n')
    os.replace(tmp, _file(store))                               # never a half-written list


def add(payload, store=None) -> dict:
    store = Path(store or STORE)
    rec = clean(payload)
    img = _image(payload.get('image'))
    with _lock:
        items = load(store)
        if len(items) >= MAX_PRODUCTS:
            raise Invalid(f'the list holds {MAX_PRODUCTS} products at most')
        pid = uuid.uuid4().hex[:12]
        rec = {'id': pid, **rec, 'image': None, 'added': datetime.now(timezone.utc).isoformat(timespec='seconds'),
               'provenance': 'USER'}
        if img:
            ext, raw = img
            (store / 'images').mkdir(parents=True, exist_ok=True)
            (store / 'images' / f'{pid}.{ext}').write_bytes(raw)
            rec['image'] = f'{pid}.{ext}'
        items.append(rec)
        _save(store, items)
    return rec


def update(pid, payload, store=None):
    """Change a product's details. The photo is replaced only when a new one is sent, and dropped only on
    "remove_image": true. Returns the record, or None when there is no such product."""
    if not ID.fullmatch(str(pid)):
        return None
    store = Path(store or STORE)
    rec = clean(payload)
    img = _image(payload.get('image'))
    with _lock:
        items = load(store)
        i = next((k for k, p in enumerate(items) if p['id'] == pid), None)
        if i is None:
            return None
        old = items[i]
        new = {**old, **rec, 'id': pid, 'added': old.get('added'), 'provenance': 'USER',
               'updated': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        drop = img is not None or payload.get('remove_image') is True
        if drop and old.get('image'):
            f = store / 'images' / Path(old['image']).name
            if f.exists():
                f.unlink()
            new['image'] = None
        if img:
            ext, raw = img
            (store / 'images').mkdir(parents=True, exist_ok=True)
            (store / 'images' / f'{pid}.{ext}').write_bytes(raw)
            new['image'] = f'{pid}.{ext}'
        items[i] = new
        _save(store, items)
    return new


def remove(pid, store=None) -> bool:
    """Take one product, and its photo, off the list. False when there is no such product."""
    if not ID.fullmatch(str(pid)):
        return False
    store = Path(store or STORE)
    with _lock:
        items = load(store)
        gone = next((p for p in items if p['id'] == pid), None)
        if gone is None:
            return False
        if gone.get('image'):
            f = store / 'images' / Path(gone['image']).name
            if f.exists():
                f.unlink()
        _save(store, [p for p in items if p['id'] != pid])
    return True


def image(pid, store=None):
    """(bytes, content type) of a product's photo, or None."""
    if not ID.fullmatch(str(pid)):
        return None
    store = Path(store or STORE)
    p = next((x for x in load(store) if x['id'] == pid), None)
    if not p or not p.get('image'):
        return None
    f = store / 'images' / Path(p['image']).name
    ext = f.suffix.lstrip('.')
    if not f.exists() or ext not in CONTENT_TYPE:
        return None
    return f.read_bytes(), CONTENT_TYPE[ext]


def public(p) -> dict:
    """A product as the page receives it: the photo as a URL on this server."""
    return {**p, 'image': f"api/products/{p['id']}/image" if p.get('image') else None}
