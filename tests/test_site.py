"""The website: its sources, its built file, the in-browser analyst's refusals, its wording rule, its smoke test and
the localhost server."""
import http.client
import importlib.util
import json
import re
import shutil
import subprocess
import threading

import pytest

from conftest import ROOT

SITE = ROOT / 'outputs' / 'site'
PAGES = ['home', 'data', 'models', 'simulate', 'optimize', 'analyst', 'listings', 'festive', 'plan', 'pipeline']
FONTS = 'https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500..800&family=Manrope:wght@400..800&display=swap'


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sources_exist_and_name_every_page():
    for f in ('index.html', 'app.css', 'app.js', 'analyst.js'):
        assert (ROOT / 'site' / f).exists(), f
    app = (ROOT / 'site' / 'app.js').read_text(encoding='utf-8')
    nav = app.split('const NAV = ')[1].split('];')[0]
    for p in PAGES:
        assert f"['{p}'," in nav and f'PAGES.{p} = ' in app, p
    # a design token must be defined for light, for system-dark and for forced dark
    css = (ROOT / 'site' / 'app.css').read_text(encoding='utf-8')
    assert css.count('--bg:') == 3 and ':root:not([data-theme="light"])' in css and ':root[data-theme="dark"]' in css


def _built(name='index.html'):
    f = SITE / name
    if not f.exists():
        pytest.skip('site not built: python scripts/build_site.py')
    return f.read_text(encoding='utf-8')


def test_built_site_is_self_contained_and_complete():
    html = _built()
    assert html.startswith('<!doctype html>') and '__DATA__' not in html and '/*__' not in html
    blocks = dict(re.findall(r'<script type="application/json" id="d-(\w+)">(.*?)</script>', html, flags=re.S))
    assert set(blocks) == {'meta', 'models', 'optimize', 'pipeline', 'whatif', 'explorer', 'reality', 'analyst', 'analystEval', 'festive', 'photos'}
    data = {k: json.loads(v) for k, v in blocks.items()}                     # every block is valid JSON
    assert data['meta']['rows'] == 610_789 and len(data['models']) == 10
    assert sum(m['real'] for m in data['meta']['mix']) == 21_949              # only Blinkit has real rows
    assert [m['real'] > 0 for m in data['meta']['mix']] == [True, False, False, False]
    assert data['meta']['storeLabel']['status'] == 'UNVERIFIED'
    # the only outside resource is the font stylesheet; no script is loaded from anywhere
    assert not re.search(r'<script[^>]+src=', html)
    head, body = html.split('</head><body>', 1)
    assert set(re.findall(r'https?://[^"\')\s]+', head)) <= {'https://fonts.googleapis.com', 'https://fonts.gstatic.com', FONTS}
    assert body.lstrip().startswith('<div class="ticker"')                    # nothing of the body leaked into the head
    assert 'claude.use' not in html                                          # it does not depend on an artifact host


def test_site_keeps_the_two_tags_while_dropping_the_two_words():
    """The owner asked for the label words off the pages (2026-10-14). The distinction itself must stay: every model
    card is tagged, and the tags are drawn from the provenance the build recorded."""
    html = _built()
    blocks = dict(re.findall(r'<script type="application/json" id="d-(\w+)">(.*?)</script>', html, flags=re.S))
    models = json.loads(blocks['models'])
    assert {m['data'] for m in models} == {'REAL', 'SYNTHETIC'} and sum(m['data'] == 'REAL' for m in models) == 3
    app = (ROOT / 'site' / 'app.js').read_text(encoding='utf-8')
    assert "if (p === 'REAL') return ''" in app and "SYNTHETIC: ['is-lab', 'flask', 'Lab']" in app   # observed: no tag
    assert 'Seen 10 Jul' not in app                                   # the observed tag is gone (owner, 2026-10-24)
    assert '/* plain:start */' in app and '/* plain:end */' in app
    meta = json.loads(blocks['meta'])
    shown = meta['suggested']
    assert len(shown) >= 6 and not any(re.search(r'\b(real|synthetic)\b', q, flags=re.I) for q in shown)
    answers = json.loads(blocks['analyst'])['answers']
    assert all(meta['ask'].get(q, q) in answers for q in shown)               # each one has the analyst's saved answer


def test_wording_filter_rewords_labels_and_leaves_numbers_and_the_brand():
    if not shutil.which('node'):
        pytest.skip('node not installed')
    app = (ROOT / 'site' / 'app.js').read_text(encoding='utf-8')
    fn = app.split('/* plain:start */')[1].split('/* plain:end */')[0]
    cases = [
        'REAL snapshot 2026-07-10, the share of listings out of stock is 12.34% across 21,949 listings.',
        'SYNTHETIC: with restock effort fixed at 14 actions the exposure changes by -1.25%.',
        'It shows what the pipeline recovers, not how the real market behaves.',
        'real_store_label_audit_synthetic_control · rows = 588840',
        'highest first: Real 4.20% (31 listings); Tropicana 3.10% (58 listings)',
    ]
    js = fn + '; console.log(JSON.stringify(' + json.dumps(cases) + '.map(plain)));'
    p = subprocess.run(['node', '-e', js], capture_output=True, text=True, encoding='utf-8')
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    for before, after in zip(cases, out):
        assert re.findall(r'\d[\d,.]*', before) == re.findall(r'\d[\d,.]*', after), after   # no digit is touched
    assert not any(re.search(r'(?<![A-Za-z0-9])(real|REAL|synthetic|SYNTHETIC)(?![A-Za-z0-9])', o) or re.search('snapshot', o, flags=re.I) for o in out), out
    assert out[0].startswith('Observed check') and out[1].startswith('Lab:') and 'actual market' in out[2]
    assert out[3].startswith('observed_store_label_audit_lab_control')
    assert 'Real 4.20%' in out[4]                                            # a juice brand, not a label


def test_in_browser_analyst_refuses_what_it_must():
    f = SITE / 'analyst_eval.json'
    if not f.exists():
        pytest.skip('in-browser analyst not evaluated (needs node at build time)')
    s = json.loads(f.read_text(encoding='utf-8'))['summary']
    for name in ('tuning', 'holdout'):
        assert s[name]['refused_when_it_must'] == s[name]['must_refuse'] and s[name]['false_refusals'] == 0, s[name]
        assert s[name]['passed'] >= 0.9 * s[name]['questions'], s[name]       # cache off: the engine itself, not a lookup


def test_refusal_rules_match_the_python_guard():
    """The page's refusal list is a hand port of guard.REFUSALS: same count, same topics, same order."""
    from src.analyst import guard
    js = (ROOT / 'site' / 'analyst.js').read_text(encoding='utf-8')
    block = js.split('const REFUSALS = [')[1].split('];')[0]
    topics = [t for _, t, _ in guard.REFUSALS]
    found = [t for t in topics if f"'{t}'" in block]
    assert found == topics, set(topics) - set(found)
    assert [block.index(f"'{t}'") for t in topics] == sorted(block.index(f"'{t}'") for t in topics)
    assert guard.SYNTHETIC_BANNER in js and 'latent-pressure' in js


def test_site_smoke_runs_every_page_and_control():
    _built()
    if not shutil.which('node'):
        pytest.skip('node not installed')
    code, out = _script('check_site').run()
    assert code == 0, out[-1500:]
    summary = json.loads(out.splitlines()[0])
    assert summary['failures'] == 0 and summary['analyst_answers'] == 6 and all(v > 0 for v in summary['pages'].values())
    # the wording rule was checked on real output: every saved answer and the engine's own, as the page draws them
    assert summary['answers_drawn'] >= 100 and summary['characters_checked_for_label_words'] > 1_000_000


def test_node_syntax_of_site_sources():
    if not shutil.which('node'):
        pytest.skip('node not installed')
    for f in ('site/app.js', 'site/analyst.js', 'scripts/site_smoke.js'):
        p = subprocess.run(['node', '--check', str(ROOT / f)], capture_output=True, text=True)
        assert p.returncode == 0, p.stderr


# --------------------------------------------------------------------------- the localhost server
@pytest.fixture(scope='module')
def server():
    _built()
    mod = _script('serve_site')
    srv = mod.make_server(0)                                                 # any free port
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield mod, srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def _call(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=120)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, r.getheader('Content-Type') or '', data


def test_server_binds_the_loopback_only(server):
    mod, _ = server
    srv = mod.make_server(0)
    try:
        assert srv.server_address[0] == '127.0.0.1'
        assert srv.twin is None or srv.twin.server_address[0] == '::1'
    finally:
        srv.server_close()


def test_server_serves_the_site_and_its_health(server):
    _, port = server
    status, ctype, body = _call(port, 'GET', '/')
    assert status == 200 and ctype.startswith('text/html') and body.startswith(b'<!doctype html>')
    assert body == (SITE / 'index.html').read_bytes()
    status, ctype, body = _call(port, 'GET', '/api/health')
    assert status == 200 and json.loads(body)['ok'] is True
    assert _call(port, 'GET', '/../CLAUDE.md')[0] == 404 and _call(port, 'GET', '/site/app.js')[0] == 404   # one file only


def test_server_turns_away_what_is_not_a_local_json_question(server):
    _, port = server
    J = {'Content-Type': 'application/json'}
    assert _call(port, 'GET', '/', headers={'Host': 'example.com'})[0] == 403          # another site, via the browser
    assert _call(port, 'POST', '/api/ask', body='q=hi', headers={'Content-Type': 'application/x-www-form-urlencoded'})[0] == 415
    assert _call(port, 'POST', '/api/ask', body='not json', headers=J)[0] == 400
    assert _call(port, 'POST', '/api/ask', body=json.dumps({'q': '  '}), headers=J)[0] == 400
    assert _call(port, 'POST', '/api/ask', body=json.dumps({'q': 'x' * 9000}), headers=J)[0] == 413
    assert _call(port, 'POST', '/nope', body='{}', headers=J)[0] == 404


def test_server_answers_with_the_project_analyst(server):
    _, port = server
    J = {'Content-Type': 'application/json'}

    def ask(q):
        status, _, body = _call(port, 'POST', '/api/ask', body=json.dumps({'q': q}), headers=J)
        assert status == 200, body[:300]
        return json.loads(body)
    a = ask('What is Blinkit revenue?')
    assert a['refused'] is True and a['claims'] == []
    a = ask('What happens if Blinkit cuts prices by 3 percent?')
    assert not a['refused'] and a['all_claims_verified'] and {c['provenance'] for c in a['claims']} == {'SYNTHETIC'}
    assert a['banner']                                                       # the page turns this into its Lab note
    a = ask('Out-of-stock rate by category on the snapshot')
    assert a['claims'][0]['provenance'] == 'REAL' and a['all_claims_verified']


def test_server_never_runs_a_chain_live(server):
    mod, port = server
    assert mod.needs_live_chain('Explain the zzzz qqqq listing') is True
    assert mod.needs_live_chain('Explain this listing') is False
    assert mod.needs_live_chain('What is Blinkit revenue?') is False
    status, _, body = _call(port, 'POST', '/api/ask', body=json.dumps({'q': 'Explain the zzzz qqqq listing'}),
                            headers={'Content-Type': 'application/json'})
    a = json.loads(body)
    assert status == 200 and a['answer_summary'] == mod.NO_CHAIN and a['claims'] == [] and not a['refused']


PNG_1PX = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='


def test_server_adds_lists_serves_and_removes_a_product(server, tmp_path):
    """A product a person adds is checked, kept in its own folder with its photo, tagged USER, and can be removed."""
    import base64
    mod, port = server
    old, mod.PRODUCTS_STORE = mod.PRODUCTS_STORE, tmp_path
    J = {'Content-Type': 'application/json'}
    try:
        body = {'name': 'Handmade clay diya (set of 12)', 'pack': '12 pcs', 'category': 'Other / General Merchandise',
                'prices': {'Blinkit': 149, 'BigBasket': '139.5'}, 'in_stock': True, 'eta': 12,
                'image': 'data:image/png;base64,' + PNG_1PX}
        status, _, raw = _call(port, 'POST', '/api/products', body=json.dumps(body), headers=J)
        assert status == 201, raw
        p = json.loads(raw)
        assert p['provenance'] == 'USER' and p['prices'] == {'Blinkit': 149.0, 'BigBasket': 139.5}
        assert p['image'] == f"api/products/{p['id']}/image" and p['eta'] == 12
        listed = json.loads(_call(port, 'GET', '/api/products')[2])['products']
        assert [x['id'] for x in listed] == [p['id']]
        status, ctype, img = _call(port, 'GET', f"/api/products/{p['id']}/image")
        assert status == 200 and ctype == 'image/png' and img == base64.b64decode(PNG_1PX)
        # turned away: no name, a negative price, a file that is not the image it claims, an impossible delivery time
        for bad in ({'name': ''}, {'name': 'x', 'prices': {'Blinkit': -5}}, {'name': 'x', 'eta': 999},
                    {'name': 'x', 'image': 'data:image/png;base64,' + base64.b64encode(b'not a png at all').decode()}):
            assert _call(port, 'POST', '/api/products', body=json.dumps(bad), headers=J)[0] == 400, bad
        assert _call(port, 'POST', '/api/products', body='{"name": "x"}', headers={'Content-Type': 'text/plain'})[0] == 415
        assert _call(port, 'DELETE', '/api/products/../../CLAUDE.md')[0] == 404
        assert _call(port, 'DELETE', f"/api/products/{p['id']}")[0] == 200
        assert _call(port, 'DELETE', f"/api/products/{p['id']}")[0] == 404
        assert json.loads(_call(port, 'GET', '/api/products')[2])['products'] == []
        assert not list((tmp_path / 'images').glob('*'))
    finally:
        mod.PRODUCTS_STORE = old


def test_added_products_live_apart_from_the_project_data():
    from src import user_products as UP
    assert UP.STORE == ROOT / 'data' / 'user_added'
    for f in ROOT.glob('src/**/*.py'):                       # nothing in the pipeline, the models or the analyst reads them
        if f.name != 'user_products.py':
            assert 'user_added' not in f.read_text(encoding='utf-8') and 'user_products' not in f.read_text(encoding='utf-8'), f


def test_server_edits_a_product_and_keeps_its_photo_unless_told(server, tmp_path):
    import base64
    mod, port = server
    old, mod.PRODUCTS_STORE = mod.PRODUCTS_STORE, tmp_path
    J = {'Content-Type': 'application/json'}
    try:
        body = {'name': 'Rakhi gift box', 'prices': {'Blinkit': 299}, 'image': 'data:image/png;base64,' + PNG_1PX}
        p = json.loads(_call(port, 'POST', '/api/products', body=json.dumps(body), headers=J)[2])
        # new details, no photo sent: the photo stays
        status, _, raw = _call(port, 'PUT', f"/api/products/{p['id']}", body=json.dumps({'name': 'Rakhi gift box, 6 pcs', 'prices': {'Blinkit': 279, 'BigBasket': 269}}), headers=J)
        q = json.loads(raw)
        assert status == 200 and q['id'] == p['id'] and q['name'] == 'Rakhi gift box, 6 pcs' and q['prices'] == {'Blinkit': 279.0, 'BigBasket': 269.0}
        assert q['image'] and q['added'] == p['added'] and q['provenance'] == 'USER' and 'updated' in q
        assert _call(port, 'GET', f"/api/products/{p['id']}/image")[2] == base64.b64decode(PNG_1PX)
        # told to drop it: it goes, file and all
        q = json.loads(_call(port, 'PUT', f"/api/products/{p['id']}", body=json.dumps({'name': 'Rakhi gift box', 'remove_image': True}), headers=J)[2])
        assert q['image'] is None and not list((tmp_path / 'images').glob('*'))
        # a bad edit is refused and changes nothing; an unknown product is a 404
        assert _call(port, 'PUT', f"/api/products/{p['id']}", body=json.dumps({'name': ''}), headers=J)[0] == 400
        assert json.loads(_call(port, 'GET', '/api/products')[2])['products'][0]['name'] == 'Rakhi gift box'
        assert _call(port, 'PUT', '/api/products/0123456789ab', body=json.dumps({'name': 'x'}), headers=J)[0] == 404
    finally:
        mod.PRODUCTS_STORE = old


# --------------------------------------------------------------------------- phones, tablets and every browser
def test_site_scripts_parse_on_older_safari():
    """Safari before 16.4 (older iPhones and iPads) rejects a whole script over a single lookbehind in a regex."""
    for f in ('app.js', 'analyst.js'):
        js = (ROOT / 'site' / f).read_text(encoding='utf-8')
        assert '(?<=' not in js and '(?<!' not in js, f


def test_built_site_has_what_phones_and_tablets_need():
    html = _built()
    head = html.split('</head>', 1)[0]
    assert 'width=device-width,initial-scale=1,viewport-fit=cover' in head
    for tag in ('name="format-detection" content="telephone=no"', 'rel="manifest" href="manifest.webmanifest"',
                'rel="apple-touch-icon" href="apple-touch-icon.png"', 'name="apple-mobile-web-app-capable"'):
        assert tag in head, tag
    from PIL import Image
    for name, size in (('icon-192.png', 192), ('icon-512.png', 512), ('apple-touch-icon.png', 180)):
        with Image.open(SITE / name) as im:
            assert im.size == (size, size), name
    m = json.loads((SITE / 'manifest.webmanifest').read_text(encoding='utf-8'))
    assert m['short_name'] == 'Qcom' and m['display'] == 'standalone' and {i['sizes'] for i in m['icons']} == {'192x192', '512x512'}
    css = (ROOT / 'site' / 'app.css').read_text(encoding='utf-8')
    for rule in ('-webkit-backdrop-filter', '100dvh', 'env(safe-area-inset-left', '@media (pointer: coarse)', '@media (hover: none)',
                 '@supports not (color: color-mix('):
        assert rule in css, rule


def test_lan_gate_decides_who_gets_in(server):
    mod, _ = server
    lan = mod.lan_setup(8000, ips=['192.168.1.5'])
    assert len(lan['code']) == 6 and lan['code'].isdigit() and len(lan['token']) >= 32
    g = mod.gate
    assert g('127.0.0.1', 'localhost:8000', '', None) == 'ok'
    assert g('::1', '[::1]:8000', '', None) == 'ok'
    assert g('127.0.0.1', 'evil.example:8000', '', None) == 'host'            # another site, through the browser
    assert g('192.168.1.9', '192.168.1.5:8000', '', None) == 'host'           # no Wi-Fi mode: no other device
    assert g('192.168.1.9', '192.168.1.5:8000', '', lan) == 'locked'          # Wi-Fi mode, no code yet
    assert g('192.168.1.9', '192.168.1.5:8000', f"qcom_key={lan['token']}", lan) == 'ok'
    assert g('192.168.1.9', '192.168.1.5:8000', 'qcom_key=guess', lan) == 'locked'
    assert g('192.168.1.9', 'rebound.example:8000', f"qcom_key={lan['token']}", lan) == 'host'
    assert g('127.0.0.1', '192.168.1.5:8000', '', lan) == 'ok'                 # this computer, by its Wi-Fi address


def test_lan_code_locks_a_device_out_after_five_wrong_guesses(server):
    mod, _ = server
    lan = mod.lan_setup(8000, ips=['192.168.1.5'])
    wrong = '000000' if lan['code'] != '000000' else '111111'
    mod._fails.clear()
    t = 1_000_000.0
    assert [mod.check_code('10.0.0.7', wrong, lan, t + i) for i in range(5)] == ['wrong'] * 5
    assert mod.check_code('10.0.0.7', lan['code'], lan, t + 6) == 'wait'            # even the right code waits
    assert mod.check_code('10.0.0.8', lan['code'], lan, t + 6) == 'ok'              # another device is not affected
    assert mod.check_code('10.0.0.7', lan['code'], lan, t + 6 + mod.LOCK_WINDOW) == 'ok'
    mod._fails.clear()


def test_unlock_route_only_exists_in_wifi_mode(server):
    mod, port = server
    J = {'Content-Type': 'application/json'}
    assert mod.LAN is None and _call(port, 'POST', '/api/unlock', body='{"code": "123456"}', headers=J)[0] == 404
    assert json.loads(_call(port, 'GET', '/api/health')[2])['lan'] is None
    old, mod.LAN = mod.LAN, mod.lan_setup(port, ips=['192.168.1.5'])
    try:
        health = json.loads(_call(port, 'GET', '/api/health')[2])                     # this computer is shown the code
        assert health['lan']['code'] == mod.LAN['code'] and health['lan']['urls'] == [f'http://192.168.1.5:{port}/']
        c = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
        c.request('POST', '/api/unlock', body=json.dumps({'code': mod.LAN['code']}), headers=J)
        r = c.getresponse()
        cookie = r.getheader('Set-Cookie') or ''
        r.read(); c.close()
        assert r.status == 200 and cookie.startswith(f"qcom_key={mod.LAN['token']}") and 'HttpOnly' in cookie and 'SameSite=Strict' in cookie
        for path in ('/manifest.webmanifest', '/icon-192.png', '/apple-touch-icon.png'):
            assert _call(port, 'GET', path)[0] == 200, path
    finally:
        mod.LAN = old
        mod._fails.clear()


# --------------------------------------------------------------------------- hardening (2026-10-20)
def _full(port, method, path, body=None, headers=None):
    """Like _call, with the response headers too."""
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=120)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, data


def test_server_compresses_the_page_and_revalidates_it(server):
    import gzip
    _, port = server
    page = (SITE / 'index.html').read_bytes()
    status, h, body = _full(port, 'GET', '/', headers={'Accept-Encoding': 'gzip, deflate, br'})
    assert status == 200 and h['content-encoding'] == 'gzip' and gzip.decompress(body) == page
    assert len(body) < len(page) / 3 and h['vary'] == 'Accept-Encoding' and h['cache-control'] == 'no-cache'
    etag = h['etag']
    status, h, body = _full(port, 'GET', '/', headers={'If-None-Match': etag})
    assert status == 304 and body == b'' and h['etag'] == etag and 'content-length' not in h
    status, h, body = _full(port, 'GET', '/', headers={'If-None-Match': '"stale"'})
    assert status == 200 and body == page and 'content-encoding' not in h                # no gzip unless asked


def test_every_response_carries_the_security_headers(server):
    mod, port = server
    for method, path in (('GET', '/'), ('GET', '/api/health'), ('GET', '/nope'), ('GET', '/icon-192.png')):
        _, h, _ = _full(port, method, path)
        for k, v in mod.SECURITY_HEADERS.items():
            assert h.get(k.lower()) == v, (path, k)
    csp = mod.SECURITY_HEADERS['Content-Security-Policy']
    assert "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert 'https://fonts.googleapis.com' in csp and 'https://fonts.gstatic.com' in csp           # fonts
    assert 'img-src ' + "'self' data: blob: https://images.openfoodfacts.org https://upload.wikimedia.org;" in csp   # product photos, nothing else
    outside = set(re.findall(r'https://[a-z0-9.-]+', csp))
    assert outside == {'https://fonts.googleapis.com', 'https://fonts.gstatic.com', 'https://images.openfoodfacts.org',
                       'https://upload.wikimedia.org'}
    assert 'unsafe-eval' not in csp


def test_rate_limiter_allows_a_burst_then_a_steady_rate():
    mod = _script('serve_site')
    lim = mod.RateLimiter(burst=3, per_minute=60)                                 # one a second after the burst
    assert [lim.allow('a', 100.0)[0] for _ in range(3)] == [True] * 3
    ok, wait = lim.allow('a', 100.0)
    assert not ok and wait == 1
    assert lim.allow('b', 100.0)[0]                                               # another device has its own bucket
    assert lim.allow('a', 101.01)[0] and not lim.allow('a', 101.02)[0]


def test_server_rate_limits_a_device_and_says_when_to_retry(server):
    mod, port = server
    J = {'Content-Type': 'application/json'}
    old = mod.LIMITS['ask'], mod.LIMIT_LOOPBACK
    mod.LIMITS['ask'], mod.LIMIT_LOOPBACK = mod.RateLimiter(burst=2, per_minute=1), True
    try:
        q = json.dumps({'q': 'What is Blinkit revenue?'})
        assert [_call(port, 'POST', '/api/ask', body=q, headers=J)[0] for _ in range(2)] == [200, 200]
        status, h, body = _full(port, 'POST', '/api/ask', body=q, headers=J)
        assert status == 429 and int(h['retry-after']) >= 1 and 'Try again' in json.loads(body)['error']
    finally:
        mod.LIMITS['ask'], mod.LIMIT_LOOPBACK = old
    assert _call(port, 'POST', '/api/ask', body=q, headers=J)[0] == 200             # the owner's own machine is not limited


def test_server_caches_answers_and_reports_metrics(server):
    mod, port = server
    J = {'Content-Type': 'application/json'}
    q = 'What is the GMV of Swiggy Instamart?'
    first = _call(port, 'POST', '/api/ask', body=json.dumps({'q': q}), headers=J)
    before = json.loads(_call(port, 'GET', '/api/metrics')[2])
    again = _call(port, 'POST', '/api/ask', body=json.dumps({'q': '  ' + q.replace(' ', '   ') + ' '}), headers=J)
    after = json.loads(_call(port, 'GET', '/api/metrics')[2])
    assert first[0] == again[0] == 200 and json.loads(first[2]) == json.loads(again[2])
    assert after['ask']['cache_hits'] == before['ask']['cache_hits'] + 1
    assert after['ask']['answered'] >= 2 and after['ask']['p50_ms'] is not None and after['uptime_s'] >= 0
    assert after['requests'].get('POST /api/ask', 0) >= 2 and after['status'].get('200', 0) > 0
    assert q not in json.dumps(after) and '127.0.0.1' not in json.dumps(after)      # counters only


def test_an_unexpected_error_is_answered_not_dropped(server, monkeypatch):
    mod, port = server
    def boom(*a, **k):
        raise RuntimeError('disk on fire')
    monkeypatch.setattr(mod.UP, 'load', boom)
    status, ctype, body = _call(port, 'GET', '/api/products')
    assert status == 500 and ctype.startswith('application/json') and 'disk on fire' in json.loads(body)['error']


# --------------------------------------------------------------------------- public, read-only mode (render.yaml)
LIVE = 'https://deepak17kb.github.io'


def test_public_mode_answers_any_host_writes_nothing_and_shares_two_routes(server):
    mod, port = server
    J = {'Content-Type': 'application/json'}
    old = mod.PUBLIC
    mod.PUBLIC = {'origins': {LIVE}}
    try:
        status, h, body = _full(port, 'GET', '/api/health', headers={'Host': 'qcom.onrender.com', 'Origin': LIVE})
        j = json.loads(body)
        assert status == 200 and j['writes'] is False and j['mode'] == 'public'
        assert h['access-control-allow-origin'] == LIVE and h['vary'] == 'Origin'
        assert _call(port, 'GET', '/', headers={'Host': 'qcom.onrender.com'})[0] == 200          # any Host
        # the browser's preflight, then the question, from the live site
        status, h, _ = _full(port, 'OPTIONS', '/api/ask', headers={'Origin': LIVE, 'Access-Control-Request-Method': 'POST',
                                                                     'Access-Control-Request-Headers': 'content-type'})
        assert status == 204 and h['access-control-allow-origin'] == LIVE and 'POST' in h['access-control-allow-methods']
        status, h, body = _full(port, 'POST', '/api/ask', body=json.dumps({'q': 'What is Blinkit revenue?'}),
                                headers={**J, 'Origin': LIVE})
        assert status == 200 and h['access-control-allow-origin'] == LIVE and json.loads(body)['refused'] is True
        # another site gets no CORS headers, and no other route is shared
        status, h, _ = _full(port, 'OPTIONS', '/api/ask', headers={'Origin': 'https://elsewhere.example'})
        assert status == 403 and 'access-control-allow-origin' not in h
        assert 'access-control-allow-origin' not in _full(port, 'GET', '/api/metrics', headers={'Origin': LIVE})[1]
        assert 'access-control-allow-origin' not in _full(port, 'GET', '/', headers={'Origin': LIVE})[1]
        # nothing writes, and nothing anyone added is listed
        assert _call(port, 'POST', '/api/products', body=json.dumps({'name': 'x'}), headers=J)[0] == 403
        assert _call(port, 'PUT', '/api/products/0123456789ab', body=json.dumps({'name': 'x'}), headers=J)[0] == 403
        assert _call(port, 'DELETE', '/api/products/0123456789ab')[0] == 403
        assert _call(port, 'POST', '/api/unlock', body='{"code": "000000"}', headers=J)[0] == 403
        assert json.loads(_call(port, 'GET', '/api/products')[2]) == {'products': []}
    finally:
        mod.PUBLIC = old
    assert json.loads(_call(port, 'GET', '/api/health')[2])['writes'] is True                  # back to local


def test_public_mode_limits_each_device_behind_the_proxy(server):
    mod, port = server
    J = {'Content-Type': 'application/json'}
    old = mod.PUBLIC, mod.LIMITS['ask']
    mod.PUBLIC, mod.LIMITS['ask'] = {'origins': set()}, mod.RateLimiter(burst=1, per_minute=1)
    try:
        q = json.dumps({'q': 'What is Blinkit revenue?'})
        ask = lambda ip: _call(port, 'POST', '/api/ask', body=q, headers={**J, 'X-Forwarded-For': f'203.0.113.9, {ip}'})[0]
        # the proxy appends the device's address last; an earlier entry is whatever the client sent
        assert [ask('10.0.0.1'), ask('10.0.0.1'), ask('10.0.0.2')] == [200, 429, 200]
    finally:
        mod.PUBLIC, mod.LIMITS['ask'] = old


def test_public_server_binds_exactly_the_address_it_is_given():
    mod = _script('serve_site')
    srv = mod.make_server(0, host='127.0.0.1')
    try:
        assert srv.server_address[0] == '127.0.0.1' and srv.twin is None
    finally:
        srv.server_close()
