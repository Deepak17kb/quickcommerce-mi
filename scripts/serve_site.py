"""
serve_site.py — the website on localhost, with the project's own analyst behind it.

    python scripts/serve_site.py                # http://localhost:8000, opens the browser
    python scripts/serve_site.py --port 8080    # another port (the next free one is used if it is taken)
    python scripts/serve_site.py --no-open      # do not open a browser
    python scripts/serve_site.py --rebuild      # rebuild outputs/site/index.html first
    python scripts/serve_site.py --lan          # also on phones and tablets on the same Wi-Fi, behind a six-digit code
    python scripts/serve_site.py --public       # a read-only public server on $PORT (render.yaml); see PUBLIC below

    GET    /                          the built site (outputs/site/index.html), gzip when asked, revalidated by ETag
    GET    /sw.js                     the service worker: the page keeps working offline once it has loaded
    GET    /api/health                {"ok": true, "ready": ...}
    GET    /api/metrics               uptime, requests by route and status, analyst latency and cache hits, rate limits
    POST   /api/ask                   {"q": "..."}  ->  the offline analyst's answer object (src/analyst/agent.py)
    POST   /api/unlock                {"code": "123456"}: a device on the Wi-Fi (--lan) gets in for the session
    GET    /api/products              the products people added on the site (src/user_products.py)
    POST   /api/products              add one: {"name", "brand", "pack", "category", "prices", "in_stock", "eta", "image"}
    GET    /api/products/<id>/image   its photo
    PUT    /api/products/<id>         change its details (a new photo replaces the old one)
    DELETE /api/products/<id>         take it off the list

By default the server listens on the loopback only: it is for the machine it runs on, not for a network. With --lan it
also answers phones and tablets on the same Wi-Fi, each of which must first enter the code printed at start-up. The only thing a request
writes is the list of added products, in data/user_added/, which nothing else in the project reads. No request starts a
long job: a question about a listing that has no saved chain is answered "no saved chain", not by running the chain
live (minutes). The page also works without the server (open the file from disk); it then answers with the engine
embedded in it and keeps added products in the browser.

The site is rebuilt first when it is missing or older than its sources (site/*, scripts/build_site.py).

Hardening (2026-10-20). Every response carries a content security policy (scripts and connections to this server
only; fonts from Google Fonts), no framing, no referrer, and a permissions policy that allows the camera here only.
The page and its files are sent gzip-compressed to a browser that accepts it (2.7 MB -> about a fifth) with an ETag,
so a reload costs a 304. In Wi-Fi mode, asking and adding products are rate-limited per device (a token bucket: a
burst, then a steady rate; 429 with Retry-After past it); the person at this computer is not limited. The analyst is deterministic for a question, so its answers are kept in a
small LRU cache; /api/metrics reports hits, latency percentiles and refusals. An unexpected error in a handler is
answered with a 500 JSON body instead of a dropped connection.
"""
import argparse
import errno
import gzip
import hashlib
import hmac
import importlib.util
import json
import os
from collections import OrderedDict, deque
import re
import secrets
import socket
import sys
import threading
import time
import webbrowser
from http.cookies import SimpleCookie
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import user_products as UP  # noqa: E402  (the products people add: data/user_added, never the project's data)

SITE = ROOT / 'outputs' / 'site' / 'index.html'
SOURCES = [ROOT / 'site' / f for f in ('index.html', 'app.css', 'app.js', 'analyst.js', 'sw.js', 'config.json')] + [ROOT / 'scripts' / 'build_site.py']
MAX_QUESTION = 500                 # characters
MAX_BODY = 8192                    # bytes of a question's POST body
MAX_PRODUCT_BODY = 5 * 1024 * 1024 # bytes of a new product, its photo included (base64 of at most 3 MB)
DRAIN_CAP = 32 * 1024 * 1024       # an oversized body up to this size is read and dropped before the 413 is sent
PRODUCTS_STORE = None              # None: data/user_added (src/user_products.py); the tests point it at a temp folder
PRODUCT_IMAGE = re.compile(r'/api/products/([0-9a-f]{12})/image')
PRODUCT_ID = re.compile(r'/api/products/([0-9a-f]{12})')
LOCAL_HOSTS = ('localhost', '127.0.0.1', '[::1]')
NO_CHAIN = ('No saved chain matches that listing. The site holds the gallery listings only: pick one on the Products '
            'page, or run python -m src.chain.listing for another.')
FAVICON = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect width="24" height="24" rx="6" fill="#c9f24a"/>'
           b'<path d="M13 3 6 13h5l-1 8 8-11h-5z" fill="#1b2500"/></svg>')

_lock = threading.Lock()           # the analyst's caches are plain module state: one question at a time
_state = {'ready': False, 'error': None}

# ----------------------------------------------------------------------------- headers every response carries
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob: https://images.openfoodfacts.org https://upload.wikimedia.org; media-src 'self' blob: mediastream:; "
       "connect-src 'self'; worker-src 'self'; manifest-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
       "form-action 'self'; object-src 'none'")
SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
    'Cross-Origin-Opener-Policy': 'same-origin', 'Content-Security-Policy': CSP,
    'Permissions-Policy': 'camera=(self), microphone=(), geolocation=(), payment=(), usb=()',
}
COMPRESSIBLE = ('text/', 'application/json', 'application/manifest+json', 'image/svg+xml')


class RateLimiter:
    """A token bucket per device: `burst` requests at once, then `per_minute` a minute. allow() -> (ok, retry_after_s)."""

    def __init__(self, burst: int, per_minute: float):
        self.burst, self.rate = float(burst), per_minute / 60.0
        self._b = {}
        self._mu = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> tuple[bool, int]:
        now = time.monotonic() if now is None else now
        with self._mu:
            tokens, last = self._b.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens >= 1:
                self._b[key] = (tokens - 1, now)
                return True, 0
            self._b[key] = (tokens, now)
            if len(self._b) > 4096:                     # forget the devices that have been quiet longest
                for k in list(self._b)[:1024]:
                    self._b.pop(k, None)
            return False, max(1, int((1 - tokens) / self.rate + 0.999))


# Devices on the Wi-Fi (--lan) are limited. The person at this computer is not: the Host check already stops another
# site from driving their browser here, so a limit would only get in the way of the owner. Tests switch it on.
LIMITS = {'ask': RateLimiter(burst=20, per_minute=30), 'write': RateLimiter(burst=10, per_minute=12)}
LIMIT_LOOPBACK = False
ANSWER_CACHE = 256                                         # questions whose answers are kept (the analyst is deterministic)
_answers = OrderedDict()
_files = {}                                                # path -> (mtime, size, body, gzip body, etag)


class Metrics:
    """What /api/metrics reports. Counters only: no question text and no device address is kept."""

    def __init__(self):
        self.started = time.time()
        self.routes, self.status = {}, {}
        self.ask_ms = deque(maxlen=500)
        self.cache_hits = self.cache_misses = self.limited = 0
        self._mu = threading.Lock()

    def hit(self, route: str, code: int):
        with self._mu:
            self.routes[route] = self.routes.get(route, 0) + 1
            self.status[str(code)] = self.status.get(str(code), 0) + 1

    def snapshot(self) -> dict:
        with self._mu:
            ms = sorted(self.ask_ms)
            pick = lambda q: round(ms[min(len(ms) - 1, int(q * len(ms)))], 1) if ms else None
            return {'uptime_s': round(time.time() - self.started), 'requests': dict(self.routes), 'status': dict(self.status),
                    'ask': {'answered': len(ms), 'p50_ms': pick(0.5), 'p95_ms': pick(0.95), 'max_ms': round(ms[-1], 1) if ms else None,
                            'cache_hits': self.cache_hits, 'cache_misses': self.cache_misses, 'cached_answers': len(_answers)},
                    'rate_limited': self.limited, 'limits': {k: {'burst': int(v.burst), 'per_minute': round(v.rate * 60)}
                                                             for k, v in LIMITS.items()}}


METRICS = Metrics()


def file_entry(path: Path):
    """(body, gzip body, etag) for a file, recomputed only when it changes on disk."""
    st = path.stat()
    hit = _files.get(path)
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2:]
    body = path.read_bytes()
    entry = (body, gzip.compress(body, 6), '"' + hashlib.sha256(body).hexdigest()[:32] + '"')
    _files[path] = (st.st_mtime, st.st_size) + entry
    return entry

# ----------------------------------------------------------------------------- phones and tablets on the same Wi-Fi
# Off unless the server is started with --lan. Then a device that is not this computer sees a page asking for a six-digit
# code shown on this computer; the right code sets a cookie for the session. Five wrong codes from one device in ten
# minutes and it waits. Every start makes a new code, so an old one stops working.
LAN = None                         # {'code', 'token', 'hosts', 'urls'} in Wi-Fi mode

# ----------------------------------------------------------------------------- public, read-only mode (a host on the internet)
# Off unless started with --public (render.yaml does). Then the server answers any Host on $PORT, nothing writes
# (products a visitor adds stay in their own browser), every device is rate-limited by the address the host's proxy
# forwards, and pages on the allowed origins (the GitHub Pages site) may ask it questions across origins: CORS for
# /api/health and /api/ask only. It serves the site it was given (scripts/fetch_outputs.py) and never rebuilds it.
PUBLIC = None                      # {'origins': set of allowed origins} in public mode
DEFAULT_ORIGINS = ('https://deepak17kb.github.io',)
CORS_PATHS = ('/api/health', '/api/ask')
READ_ONLY = 'This server is read-only: products you add stay in your own browser.'
LOCK_AFTER, LOCK_WINDOW = 5, 600   # wrong codes from one device before it must wait, and the window in seconds
COOKIE = 'qcom_key'
_fails = {}                        # device address -> times of its recent wrong codes
STATIC = {'/manifest.webmanifest': ('manifest.webmanifest', 'application/manifest+json'), '/icon-192.png': ('icon-192.png', 'image/png'),
          '/icon-512.png': ('icon-512.png', 'image/png'), '/apple-touch-icon.png': ('apple-touch-icon.png', 'image/png'),
          '/sw.js': ('sw.js', 'text/javascript; charset=utf-8')}


def host_of(header) -> str:
    """The host part of a Host header: 'localhost:8000' -> 'localhost', '[::1]:8000' -> '[::1]'."""
    h = (header or '').strip().lower()
    if h.startswith('['):
        return h.split(']')[0] + ']'
    return h.rsplit(':', 1)[0] if h.count(':') == 1 else h


def is_loopback(ip) -> bool:
    return ip in ('::1', '::ffff:127.0.0.1') or str(ip).startswith('127.')


def gate(ip, host_header, cookie_header, lan) -> str:
    """'ok', 'host' (a Host this server does not answer to: refused), or 'locked' (a device on the Wi-Fi that has not
    entered the code yet)."""
    host = host_of(host_header)
    if is_loopback(ip):
        return 'ok' if host in LOCAL_HOSTS or (lan and host in lan['hosts']) else 'host'
    if not lan or host not in lan['hosts']:
        return 'host'
    c = SimpleCookie()
    try:
        c.load(cookie_header or '')
    except Exception:
        return 'locked'
    sent = c[COOKIE].value if COOKIE in c else ''
    return 'ok' if sent and hmac.compare_digest(sent, lan['token']) else 'locked'


def check_code(ip, code, lan, now=None) -> str:
    """'ok', 'wrong' or 'wait' (too many wrong codes from this device lately)."""
    now = time.time() if now is None else now
    recent = [t for t in _fails.get(ip, []) if now - t < LOCK_WINDOW]
    if len(recent) >= LOCK_AFTER:
        _fails[ip] = recent
        return 'wait'
    if isinstance(code, str) and hmac.compare_digest(code.strip().encode(), lan['code'].encode()):
        _fails.pop(ip, None)
        return 'ok'
    _fails[ip] = recent + [now]
    return 'wrong'


def lan_addresses() -> list:
    """This computer's addresses on the local network (no packet is sent: a UDP socket is only pointed somewhere)."""
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith('127.') and not ip.startswith('169.254.'))


def lan_setup(port, ips=None) -> dict:
    ips = lan_addresses() if ips is None else ips
    name = socket.gethostname().lower()
    return {'code': f'{secrets.randbelow(10 ** 6):06d}', 'token': secrets.token_urlsafe(32),
            'hosts': set(LOCAL_HOSTS) | set(ips) | {name, name + '.local'}, 'urls': [f'http://{ip}:{port}/' for ip in ips]}


UNLOCK_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#111216">
<title>ShelfPulse · enter the code</title><style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;min-height:100dvh;display:grid;place-items:center;padding:24px;background:#111216;color:#f4f5f7;
font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}.card{width:min(380px,100%);background:#1b1d23;border-radius:22px;padding:28px;
box-shadow:0 30px 80px rgba(0,0,0,.45)}.logo{width:46px;height:46px;border-radius:14px;background:#c9f24a;display:grid;place-items:center;margin-bottom:14px}
h1{font-size:26px;margin:0 0 6px;letter-spacing:-.02em}p{color:#b9bcc6;margin:0 0 18px}input{width:100%;font:700 30px/1 ui-monospace,Menlo,Consolas,monospace;
letter-spacing:.32em;text-align:center;padding:14px;border-radius:14px;border:1.5px solid #3a3d47;background:#0d0e12;color:#fff}input:focus{outline:none;border-color:#c9f24a}
button{margin-top:14px;width:100%;padding:15px;border:0;border-radius:14px;background:#c9f24a;color:#1b2500;font:800 17px system-ui,sans-serif;cursor:pointer}
#m{min-height:1.5em;color:#ff8a8f;font-size:14px;margin-top:12px}</style></head><body>
<form class="card" id="f" autocomplete="off"><div class="logo"><svg width="24" height="24" viewBox="0 0 24 24"><path d="M13 2 4 14h7l-1 8 9-12h-7z" fill="#1b2500"/></svg></div>
<h1>ShelfPulse</h1><p>Enter the six-digit code shown on the computer running ShelfPulse.</p>
<input id="c" inputmode="numeric" pattern="[0-9]*" maxlength="6" autocomplete="one-time-code" placeholder="000000" aria-label="Six-digit code" autofocus>
<button type="submit">Open ShelfPulse</button><div id="m" role="status"></div></form>
<script>document.getElementById('f').addEventListener('submit', function (e) { e.preventDefault(); var m = document.getElementById('m'); m.textContent = '';
fetch('api/unlock', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({code: document.getElementById('c').value})})
.then(function (r) { if (r.ok) { location.reload(); return null; } return r.json().then(function (j) { m.textContent = j.error || 'That code did not work.'; }); })
.catch(function () { m.textContent = 'Could not reach ShelfPulse. Is it still running on the computer?'; }); });</script></body></html>"""


def needs_live_chain(question: str) -> bool:
    """True when answering would run a listing chain live: the question names a listing no saved chain covers.
    Mirrors the choice in src.analyst.tools.explain_listing."""
    from src.analyst import agent, tools
    exp = agent.parse_experiment(question)
    if not exp or exp[0] != 'explain_listing':
        return False
    product, store = exp[1].get('product'), exp[1].get('store')
    digits = re.search(r'(\d{3})', store or '')
    best = 0.0
    for f in tools._chain_files():
        lst = json.loads(f.read_text(encoding='utf-8'))['1_observe']['listing']
        if digits and not lst['store_id'].endswith(digits.group(1)):
            continue
        best = max(best, tools._match_score(product or '', lst['product_name']) if product else 0.01)
    return best == 0.0 or bool(product and best < 0.99)


def ask(question: str) -> dict:
    """The offline analyst's answer to one question, as the page draws it. The same question (after whitespace is
    normalised) is answered from the LRU cache: the analyst reads saved outputs only, so its answer cannot change while
    the server runs. The returned dict is shared with the cache: read it, do not change it."""
    from src.analyst import agent, guard
    q = ' '.join(str(question).split())[:MAX_QUESTION]
    with _lock:
        if q in _answers:
            _answers.move_to_end(q)
            METRICS.cache_hits += 1
            return _answers[q]
        METRICS.cache_misses += 1
        if not guard.refusal(q) and needs_live_chain(q):
            a = agent._finish(q, 'offline', NO_CHAIN, [], [])
        else:
            a = agent.answer(q)
        _answers[q] = a
        while len(_answers) > ANSWER_CACHE:
            _answers.popitem(last=False)
        return a


def warm():
    """Load the knowledge base and the snapshot rows once, so the first question from the page is quick."""
    try:
        ask('How accurate is the next-price forecast?')
        ask('Out-of-stock rate by category on the real snapshot')
        _state['ready'] = True
    except Exception as e:                                 # the page falls back to its own engine; say why
        _state['error'] = f'{type(e).__name__}: {e}'
        print('analyst did not start:', _state['error'], file=sys.stderr)


class Handler(BaseHTTPRequestHandler):
    server_version = 'qcmi-site/1'
    protocol_version = 'HTTP/1.1'  # keep the connection: every response below carries its length
    timeout = 60                   # seconds an idle connection is kept

    def log_message(self, fmt, *args):
        if getattr(self.server, 'verbose', False):
            sys.stderr.write('%s  %s\n' % (datetime.now().strftime('%H:%M:%S'), fmt % args))

    def log_request(self, code='-', size='-'):
        """One line per request in --verbose mode, with the time it took: method, path, status, bytes, milliseconds."""
        if getattr(self.server, 'verbose', False):
            ms = (time.perf_counter() - getattr(self, '_t0', time.perf_counter())) * 1000
            self.log_message('%s %s %s %s %.1fms', self.command, self.path.split('?', 1)[0], code, size, ms)

    def _route(self) -> str:
        """The route a request counts under in /api/metrics: ids are folded so the table stays small."""
        p = self.path.split('?', 1)[0]
        p = PRODUCT_ID.sub('/api/products/<id>', p) if p.startswith('/api/products/') else p
        return f'{self.command} {p if p in ("/", "/index.html", "/sw.js") or p.startswith("/api/") or p in STATIC else "<other>"}'

    def _send(self, code: int, body: bytes, ctype: str, headers=None, cache: str = 'no-store'):
        self.send_response(code)
        if code != 304:                                  # a 304 describes the copy the browser has: no type, no length
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', cache)
        for k, v in {**SECURITY_HEADERS, **self._cors(), **(headers or {})}.items():
            self.send_header(k, v)
        self.end_headers()
        METRICS.hit(self._route(), code)
        if self.command != 'HEAD' and code != 304:
            self.wfile.write(body)

    def _json(self, code: int, obj, headers=None):
        self._send(code, json.dumps(obj, default=str, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8',
                   headers)

    def _file(self, path: Path, ctype: str, cache: str):
        """A file from outputs/site: 304 when the browser's copy is current, gzip when the browser takes it."""
        body, gz, etag = file_entry(path)
        if etag in [t.strip() for t in (self.headers.get('If-None-Match') or '').split(',')]:
            return self._send(304, b'', ctype, {'ETag': etag}, cache)
        extra = {'ETag': etag, 'Vary': 'Accept-Encoding'}
        if ctype.startswith(COMPRESSIBLE) and 'gzip' in (self.headers.get('Accept-Encoding') or '').lower() and len(gz) < len(body):
            return self._send(200, gz, ctype, {**extra, 'Content-Encoding': 'gzip'}, cache)
        return self._send(200, body, ctype, extra, cache)

    def _client(self) -> str:
        """The device a request comes from. Behind a host's proxy (public mode) that is the last address the proxy
        appended to X-Forwarded-For; earlier entries come from the client and could be anything."""
        if PUBLIC:
            fwd = [a.strip() for a in (self.headers.get('X-Forwarded-For') or '').split(',') if a.strip()]
            if fwd:
                return fwd[-1]
        return self.client_address[0]

    def _cors(self) -> dict:
        """Public mode: a page on an allowed origin may read /api/health and /api/ask. Nothing else is shared."""
        origin = self.headers.get('Origin') if getattr(self, 'headers', None) else None
        if not PUBLIC or not origin or origin not in PUBLIC['origins'] or self.path.split('?', 1)[0] not in CORS_PATHS:
            return {}
        return {'Access-Control-Allow-Origin': origin, 'Vary': 'Origin'}

    def _read_only(self):
        self.close_connection = True
        self._drain()
        return self._json(403, {'error': READ_ONLY})

    def _limited(self, bucket: str) -> bool:
        """True (and a 429 sent) when this device has used up its requests of this kind for now."""
        if not PUBLIC and is_loopback(self.client_address[0]) and not LIMIT_LOOPBACK:
            return False
        ok, wait = LIMITS[bucket].allow(self._client())
        if ok:
            return False
        METRICS.limited += 1
        self.close_connection = True
        self._drain()
        self._json(429, {'error': f'Too many requests from this device. Try again in {wait} s.'}, {'Retry-After': str(wait)})
        return True

    def _drain(self):
        """Read and drop a request body (up to a cap) before an early answer: closing on an unread body resets the
        connection on Windows, and the sender then never sees the answer."""
        try:
            left = min(max(int(self.headers.get('Content-Length') or 0), 0), DRAIN_CAP)
        except ValueError:
            left = 0
        while left > 0:
            chunk = self.rfile.read(min(left, 65536))
            if not chunk:
                break
            left -= len(chunk)

    def handle_one_request(self):
        self._t0 = time.perf_counter()
        super().handle_one_request()

    def _guarded(self, fn):
        """Run a handler; an unexpected error becomes a 500 JSON answer instead of a dropped connection."""
        try:
            return fn()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True
        except Exception as e:                                       # noqa: BLE001  (the page falls back to its own engine)
            self.close_connection = True
            try:
                self._json(500, {'error': f'{type(e).__name__}: {e}'})
            except Exception:
                pass

    def _gate(self) -> str:
        """A page on another site must not reach this server through the visitor's browser (the Host check), and in
        Wi-Fi mode a device that is not this computer must have entered the code (the cookie check). In public mode
        there is nothing private to protect: any Host is answered, and nothing writes."""
        if PUBLIC:
            return 'ok'
        return gate(self.client_address[0], self.headers.get('Host'), self.headers.get('Cookie'), LAN)

    def _refuse(self, state: str):
        self.close_connection = True
        if self.command in ('POST', 'PUT'):
            self._drain()
        if state == 'host':
            return self._json(403, {'error': 'this server answers on localhost only'})
        return self._json(403, {'error': 'enter the code shown on the computer running ShelfPulse first'})

    def do_GET(self):
        return self._guarded(self._get)

    def _get(self):
        path = self.path.split('?', 1)[0]
        state = self._gate()
        if state == 'host':
            return self._refuse(state)
        if path in STATIC:                                   # the icons and the manifest a phone needs to add ShelfPulse to its home screen
            f = SITE.parent / STATIC[path][0]
            if not f.exists():
                return self._json(404, {'error': 'not found'})
            return self._file(f, STATIC[path][1], 'no-cache' if path == '/sw.js' else 'public, max-age=86400')
        if path == '/favicon.ico':
            return self._send(200, FAVICON, 'image/svg+xml', cache='public, max-age=86400')
        if state == 'locked':
            if path in ('/', '/index.html'):
                return self._send(200, UNLOCK_PAGE.encode('utf-8'), 'text/html; charset=utf-8')
            return self._refuse(state)
        if path in ('/', '/index.html'):
            if not SITE.exists():
                return self._send(503, b'site not built: python scripts/build_site.py', 'text/plain; charset=utf-8')
            return self._file(SITE, 'text/html; charset=utf-8', 'no-cache')     # always revalidated: a rebuild shows at once
        if path == '/api/health':
            built = datetime.fromtimestamp(SITE.stat().st_mtime).isoformat(timespec='seconds') if SITE.exists() else None
            lan = {'urls': LAN['urls'], 'code': LAN['code']} if LAN and is_loopback(self.client_address[0]) else None
            return self._json(200, {'ok': True, 'ready': _state['ready'], 'error': _state['error'], 'analyst': 'offline',
                                    'site_built': built, 'lan': lan, 'writes': not PUBLIC,
                                    'mode': 'public' if PUBLIC else 'wifi' if LAN else 'local'})
        if path == '/api/metrics':
            return self._json(200, METRICS.snapshot())
        if path == '/api/products':
            if PUBLIC:                                        # nothing is kept on a public server: the page keeps its own
                return self._json(200, {'products': []})
            return self._json(200, {'products': [UP.public(p) for p in UP.load(PRODUCTS_STORE)]})
        m = PRODUCT_IMAGE.fullmatch(path)
        if m and not PUBLIC:
            img = UP.image(m.group(1), PRODUCTS_STORE)
            return self._send(200, img[0], img[1]) if img else self._json(404, {'error': 'no such photo'})
        return self._json(404, {'error': 'not found'})

    do_HEAD = do_GET

    def _body(self, limit: int, hint: str):
        """The JSON body of a POST, or None after an error response. Until the body is read, the connection must not be
        reused: whatever is left of it would be taken for the next request."""
        self.close_connection = True
        if 'application/json' not in (self.headers.get('Content-Type') or '').lower():
            self._json(415, {'error': f'send JSON: {hint}'})
            return None
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > limit:
            self._drain()                                # read what was sent first, or the sender never sees the 413
            self._json(413, {'error': f'the body must be 1 to {limit} bytes'})
            return None
        body = self.rfile.read(n)
        self.close_connection = False
        try:
            return json.loads(body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            self._json(400, {'error': f'send JSON: {hint}'})
            return None

    def _unlock(self):
        if not LAN:
            self.close_connection = True
            self._drain()
            return self._json(404, {'error': 'not found'})
        payload = self._body(256, '{"code": "123456"}')
        if payload is None:
            return None
        result = check_code(self.client_address[0], payload.get('code') if isinstance(payload, dict) else None, LAN)
        if result == 'ok':
            cookie = f'{COOKIE}={LAN["token"]}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400'
            return self._send(200, b'{"ok": true}', 'application/json; charset=utf-8', {'Set-Cookie': cookie})
        if result == 'wait':
            return self._json(429, {'error': f'Too many wrong codes from this device. Try again in {LOCK_WINDOW // 60} minutes.'})
        return self._json(403, {'error': 'That code did not work. Check the code shown on the computer.'})

    def do_POST(self):
        return self._guarded(self._post)

    def _post(self):
        path = self.path.split('?', 1)[0]
        state = self._gate()
        if state == 'host':
            return self._refuse(state)
        if PUBLIC and path in ('/api/products', '/api/unlock'):
            return self._read_only()
        if path == '/api/unlock':
            return self._unlock()
        if state == 'locked':
            return self._refuse(state)
        if path in ('/api/products', '/api/ask') and self._limited('write' if path == '/api/products' else 'ask'):
            return None
        if path == '/api/products':
            payload = self._body(MAX_PRODUCT_BODY, '{"name": "...", "prices": {...}, "image": "data:image/jpeg;base64,..."}')
            if payload is None:
                return None
            try:
                return self._json(201, UP.public(UP.add(payload, PRODUCTS_STORE)))
            except UP.Invalid as e:
                return self._json(400, {'error': str(e)})
        if path != '/api/ask':
            self.close_connection = True
            self._drain()
            return self._json(404, {'error': 'not found'})
        payload = self._body(MAX_BODY, '{"q": "your question"}')
        if payload is None:
            return None
        q = payload.get('q') if isinstance(payload, dict) else None
        if not isinstance(q, str) or not q.strip():
            return self._json(400, {'error': 'the question is empty'})
        t0 = time.perf_counter()
        try:
            a = ask(q)
        except Exception as e:                             # the page then answers with its own engine
            return self._json(500, {'error': f'{type(e).__name__}: {e}'})
        METRICS.ask_ms.append((time.perf_counter() - t0) * 1000)
        return self._json(200, a)

    def do_PUT(self):
        return self._guarded(self._put)

    def _put(self):
        path = self.path.split('?', 1)[0]
        state = self._gate()
        if state != 'ok':
            return self._refuse(state)
        if PUBLIC:
            return self._read_only()
        m = PRODUCT_ID.fullmatch(path)
        if not m:
            self.close_connection = True
            self._drain()
            return self._json(404, {'error': 'not found'})
        if self._limited('write'):
            return None
        payload = self._body(MAX_PRODUCT_BODY, '{"name": "...", "prices": {...}}')
        if payload is None:
            return None
        try:
            rec = UP.update(m.group(1), payload, PRODUCTS_STORE)
        except UP.Invalid as e:
            return self._json(400, {'error': str(e)})
        return self._json(200, UP.public(rec)) if rec else self._json(404, {'error': 'no such product'})

    def do_DELETE(self):
        return self._guarded(self._delete)

    def _delete(self):
        path = self.path.split('?', 1)[0]
        state = self._gate()
        if state != 'ok':
            return self._refuse(state)
        if PUBLIC:
            return self._read_only()
        m = PRODUCT_ID.fullmatch(path)
        if not m:
            return self._json(404, {'error': 'not found'})
        return self._json(200, {'ok': True}) if UP.remove(m.group(1), PRODUCTS_STORE) else self._json(404, {'error': 'no such product'})


    def do_OPTIONS(self):
        return self._guarded(self._options)

    def _options(self):
        """The browser's preflight before a cross-origin question (a JSON POST). Public mode, allowed origins and the
        two shared routes only; anything else gets no CORS headers, so the browser refuses it."""
        self.close_connection = True
        self._drain()
        cors = self._cors()
        if not cors:
            return self._json(403, {'error': 'cross-origin requests are not accepted here'})
        return self._send(204, b'', 'text/plain', {'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                                                   'Access-Control-Allow-Headers': 'Content-Type',
                                                   'Access-Control-Max-Age': '86400'})


class Server(ThreadingHTTPServer):
    allow_reuse_address = False    # on Windows, reuse would let two servers share a port instead of failing
    daemon_threads = True
    verbose = False
    twin = None                    # the same server on the IPv6 loopback, when the machine has one

    def serve_forever(self, poll_interval=0.5):
        if self.twin is not None:
            threading.Thread(target=self.twin.serve_forever, daemon=True).start()
        super().serve_forever(poll_interval)

    def shutdown(self):
        if self.twin is not None:
            self.twin.shutdown()
        super().shutdown()

    def server_close(self):
        if self.twin is not None:
            self.twin.server_close()
        super().server_close()


class Server6(Server):
    address_family = socket.AF_INET6


def make_server(port: int = 8000, tries: int = 20, lan: bool = False, host: str | None = None) -> Server:
    """A server on the loopback at `port`, or at the next free port after it. port=0 lets the system choose.
    It listens on 127.0.0.1 and, where there is one, on ::1 as well: Windows resolves "localhost" to ::1 first, and
    without a listener there every request waits about two seconds before falling back to 127.0.0.1.
    lan=True listens on every IPv4 address of this computer instead, so phones and tablets on the same Wi-Fi can reach
    it; they still need the code (see gate). host= binds exactly that address and port (public mode: the host assigns
    the port, so there is no next one to try)."""
    if host is not None:
        return Server((host, port), Handler)
    last = None
    for p in ([0] if port == 0 else range(port, port + tries)):
        try:
            srv = Server(('0.0.0.0' if lan else '127.0.0.1', p), Handler)
        except OSError as e:
            last = e
            continue
        try:
            srv.twin = Server6(('::1', srv.server_address[1]), Handler)
        except OSError as e:
            if e.errno == errno.EADDRINUSE and port != 0:   # something else answers "localhost" on this port
                srv.server_close()
                last = e
                continue
            srv.twin = None                                # no IPv6 loopback here: 127.0.0.1 alone
        return srv
    raise OSError(f'no free port from {port} to {port + tries - 1}: {last}')


def stale() -> bool:
    return not SITE.exists() or any(s.exists() and s.stat().st_mtime > SITE.stat().st_mtime for s in SOURCES)


def build():
    spec = importlib.util.spec_from_file_location('build_site', ROOT / 'scripts' / 'build_site.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main()


def main():
    ap = argparse.ArgumentParser(description='Serve the project website on localhost.')
    ap.add_argument('--port', type=int, default=8000)
    ap.add_argument('--no-open', action='store_true', help='do not open a browser')
    ap.add_argument('--rebuild', action='store_true', help='rebuild the site before serving it')
    ap.add_argument('--verbose', action='store_true', help='log every request')
    ap.add_argument('--lan', action='store_true',
                    help='also open ShelfPulse to phones and tablets on the same Wi-Fi, behind a six-digit code shown here')
    ap.add_argument('--public', action='store_true',
                    help='run as a read-only public server (a host such as Render): $PORT, any Host, CORS for the live site')
    ap.add_argument('--host', default=None, help='public mode: the address to bind (default 0.0.0.0)')
    ap.add_argument('--allow-origin', action='append', default=None,
                    help='public mode: a site whose pages may ask questions (repeatable; default $QCOM_ALLOW_ORIGIN or '
                         + ', '.join(DEFAULT_ORIGINS) + ')')
    args = ap.parse_args()
    if args.public:
        return main_public(args)

    if args.rebuild or stale():
        print('building the site ...' if not SITE.exists() else 'rebuilding the site (its sources changed) ...')
        try:
            build()
        except Exception as e:
            if not SITE.exists():
                print(f'the site could not be built: {type(e).__name__}: {e}\nrun the pipeline first: python scripts/run_all.py')
                sys.exit(1)
            print(f'rebuild failed ({type(e).__name__}: {e}); serving the last built site')

    global LAN
    srv = make_server(args.port, lan=args.lan)
    srv.verbose = args.verbose
    port = srv.server_address[1]
    url = f'http://localhost:{port}/'
    if port != args.port:
        print(f'port {args.port} is in use; using {port}', flush=True)
    print(f'ShelfPulse is running at {url}   (Ctrl+C to stop)', flush=True)
    if args.lan:
        LAN = lan_setup(port)
        if LAN['urls']:
            print('\nOn a phone or tablet on the same Wi-Fi, open:', flush=True)
            for u in LAN['urls']:
                print(f'    {u}', flush=True)
            print(f'and enter the code  {LAN["code"]}', flush=True)
            print('If nothing loads there, allow Python through the firewall for private networks when Windows asks.\n', flush=True)
        else:
            print('No Wi-Fi or network address found: only this computer can open ShelfPulse.', flush=True)
    threading.Thread(target=warm, daemon=True).start()
    if not args.no_open:
        threading.Timer(0.8, webbrowser.open, [url]).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\nstopped')
    finally:
        srv.server_close()


def main_public(args):
    """Read-only on the internet. The site and outputs come from the release (python scripts/fetch_outputs.py)."""
    global PUBLIC
    if args.lan:
        sys.exit('--public and --lan do not go together')
    if not SITE.exists():
        sys.exit('no built site at outputs/site/index.html: run python scripts/fetch_outputs.py first')
    env = [o.strip() for o in os.environ.get('QCOM_ALLOW_ORIGIN', '').split(',') if o.strip()]
    origins = {o.rstrip('/') for o in (args.allow_origin or env or DEFAULT_ORIGINS)}
    PUBLIC = {'origins': origins}
    port = int(os.environ.get('PORT') or args.port)
    srv = make_server(port, host=args.host or '0.0.0.0')
    srv.verbose = True if args.verbose or os.environ.get('QCOM_VERBOSE') else False
    print(f'ShelfPulse public and read-only on {srv.server_address[0]}:{srv.server_address[1]}; '
          f'pages that may ask it questions: {", ".join(sorted(origins))}', flush=True)
    threading.Thread(target=warm, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\nstopped')
    finally:
        srv.server_close()


if __name__ == '__main__':
    main()
