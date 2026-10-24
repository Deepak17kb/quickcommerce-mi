"""Publishing: the released outputs come back only as checked, and only under data/ml/ and outputs/; site_dist/ is a
complete, deployable site and nothing else; the README's badges are shields.io documents read off the run itself."""
import hashlib
import importlib.util
import json
import re
import zipfile

import pytest

from conftest import ROOT


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope='module')
def F():
    return _script('fetch_outputs')


@pytest.mark.parametrize('name, ok', [
    ('outputs/models/price_forecast_lgbm/metrics.json', True), ('data/ml/Blinkit_ML_price.parquet', True),
    ('outputs/site/index.html', True), ('/etc/passwd', False), ('../outside.txt', False),
    ('outputs/../../escape.txt', False), ('data/raw/Blinkit_RAW.parquet', False), ('data/user_added/products.json', False),
    ('C:/Windows/x', False), ('outputs\\models\\x.json', False), ('src/load.py', False), ('outputs/', False)])
def test_fetch_accepts_only_plain_paths_under_the_two_folders(F, name, ok):
    assert F.safe_name(name) is ok


def _zip(path, entries, link=None):
    with zipfile.ZipFile(path, 'w') as z:
        for name, data in entries.items():
            z.writestr(name, data)
        if link:
            info = zipfile.ZipInfo(link)
            info.external_attr = (0o120777 << 16)
            z.writestr(info, 'target')
    return path


def test_fetch_refuses_an_archive_with_anything_unsafe_in_it(F, tmp_path, monkeypatch):
    monkeypatch.setattr(F, 'ROOT', tmp_path)
    for bad in ({'outputs/ok.json': '{}', '../evil.txt': 'x'}, {'src/load.py': 'x'}):
        with pytest.raises(SystemExit):
            F.extract(_zip(tmp_path / 'bad.zip', bad), force=False)
    with pytest.raises(SystemExit):
        F.extract(_zip(tmp_path / 'link.zip', {'outputs/ok.json': '{}'}, link='outputs/link'), force=False)
    assert not (tmp_path / 'outputs').exists() and not (tmp_path / 'evil.txt').exists()   # nothing written before the check


def test_fetch_keeps_what_is_there_unless_forced(F, tmp_path, monkeypatch):
    monkeypatch.setattr(F, 'ROOT', tmp_path)
    z = _zip(tmp_path / 'ok.zip', {'outputs/a.json': 'new', 'data/ml/b.parquet': 'new'})
    (tmp_path / 'outputs').mkdir()
    (tmp_path / 'outputs' / 'a.json').write_text('mine')
    assert F.extract(z, force=False) == {'written': 1, 'kept': 1}
    assert (tmp_path / 'outputs' / 'a.json').read_text() == 'mine'
    assert F.extract(z, force=True) == {'written': 2, 'kept': 0}
    assert (tmp_path / 'outputs' / 'a.json').read_text() == 'new'


def test_fetch_refuses_a_download_whose_hash_differs(F, tmp_path, monkeypatch):
    z = _zip(tmp_path / 'r.zip', {'outputs/a.json': '{}'})
    manifest = tmp_path / 'OUTPUTS_RELEASE.json'
    manifest.write_text(json.dumps({'tag': 't', 'asset': 'r.zip', 'url': 'https://example.invalid/r.zip', 'bytes': 1,
                                    'sha256': '0' * 64, 'files': 1,
                                    'run': {'started_utc': 's', 'steps_ok': 1, 'steps': 1, 'tests_passed': 1, 'tests': 1}}))
    monkeypatch.setattr(F, 'MANIFEST', manifest)
    monkeypatch.setattr(F, 'ROOT', tmp_path)
    monkeypatch.setattr('sys.argv', ['fetch_outputs.py', '--zip', str(z)])
    with pytest.raises(SystemExit, match='does not match'):
        F.main()
    assert not (tmp_path / 'outputs').exists()
    m = json.loads(manifest.read_text())
    m['sha256'] = hashlib.sha256(z.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(m))
    assert F.main() == 0 and (tmp_path / 'outputs' / 'a.json').exists()


def test_the_release_never_packs_personal_or_throwaway_files():
    R = _script('release_outputs')
    names = [rel for _, rel in R.members()]
    assert not any(n.startswith(('outputs/site/screens/', 'outputs/release/')) or 'user_added' in n for n in names)
    assert all(n.startswith(('data/ml/', 'outputs/')) for n in names)
    F = _script('fetch_outputs')
    assert all(F.safe_name(n) for n in names)                     # what is packed can be fetched back


def test_site_dist_is_a_complete_deployable_site():
    D = _script('deploy_pages')
    if not (ROOT / 'site_dist' / 'index.html').exists():
        pytest.skip('site_dist not staged yet: python scripts/build_site.py')
    if D.stale():                                  # run_all's tests run before its site rebuild
        pytest.skip('the built site is older than its sources: python scripts/build_site.py')
    assert D.problems(ROOT / 'site_dist') == []
    for b in ('tests', 'pipeline', 'contracts'):
        doc = json.loads((ROOT / 'site_dist' / 'badges' / f'{b}.json').read_text(encoding='utf-8'))
        assert doc['schemaVersion'] == 1 and doc['label'] and doc['message']


def test_staging_writes_only_its_own_files_and_flags_anything_else(tmp_path):
    D = _script('deploy_pages')
    if not (D.SITE / 'index.html').exists() or D.stale():
        pytest.skip('site not built, or older than its sources: python scripts/build_site.py')
    dest = tmp_path / 'dist'
    D.stage(dest, base='/repo/')
    assert D.problems(dest) == [] and '/repo/' in (dest / '404.html').read_text(encoding='utf-8')
    (dest / 'notes.txt').write_text('mine')
    assert any('unexpected' in p for p in D.problems(dest))
    with pytest.raises(SystemExit):                               # never deletes a file it did not write
        D.stage(dest, base='/repo/')
    assert (dest / 'notes.txt').read_text() == 'mine'
    (dest / 'notes.txt').unlink()
    (dest / 'index.html').write_text('<html>not the site</html>', encoding='utf-8')
    assert any('data blocks' in p for p in D.problems(dest))


def test_badges_read_the_run_and_turn_red_when_something_fails():
    B = _script('build_site')
    meta = {'run': {'ok': 42, 'steps': 42, 'passed': 250, 'tests': 251}, 'contracts': {'passed': 21, 'total': 21},
            'ledger': {'claims': 37, 'stale': 0}}
    b = B.badges(meta)
    assert b['pipeline']['message'] == '42 steps OK' and b['contracts']['message'] == '21 hold'
    assert b['tests']['message'] == '250 of 251 passing' and b['tests']['color'] == 'd63a3f'
    assert all(d['schemaVersion'] == 1 for d in b.values())


def test_the_remote_analyst_must_be_https(monkeypatch):
    B = _script('build_site')
    monkeypatch.setenv('QCOM_API', 'http://insecure.example/')
    with pytest.raises(ValueError):
        B.remote_api()
    monkeypatch.setenv('QCOM_API', 'https://qcom-analyst.onrender.com/')
    assert B.remote_api() == 'https://qcom-analyst.onrender.com/'
    monkeypatch.setenv('QCOM_API', '')
    assert B.remote_api() == ''
    monkeypatch.setenv("QCOM_API", "http://127.0.0.1:8100/")                # this machine, while trying it out
    assert B.remote_api() == "http://127.0.0.1:8100/"


# The product-photo matcher, on the cases its first run met (2026-10-24): a wrong photo is worse than a drawing.
IMG = {'image_front_small_url': 'https://images.openfoodfacts.org/x.jpg'}


@pytest.mark.parametrize('ours, hit, ok', [
    ('Frooti Mango Drink - 2 Ltr', {'brands': ['Parle Agro', 'Frooti'], 'product_name': 'FROOTI Mango Drink'}, True),
    ('Bingo Hot & Spicy Korean Style Potato Chips', {'brands': ['Bingo!'], 'product_name': 'Bingo! Hot and spicy Korean style'}, True),
    ('Bingo Original Hot & Spicy Korean Style Potato Chips', {'brands': ['Bingo!'], 'product_name': 'Bingo! Hot and spicy Korean style'}, True),
    ('Cadbury Dairy Milk Silk Heart Blush Valentine Chocolate Gift Pack', {'brands': ['Cadbury'], 'product_name': 'Cadbury dairy milk silk bubbly'}, False),
    ('Cadbury Dairy Milk Silk Heart Blush Valentine Chocolate Gift Pack', {'brands': ['Cadbury'], 'product_name': 'Cadbury dairy milk chocolate dairy milk'}, False),
    ('Nestle KitKat Cele-Break Assorted Rakhi Chocolate Gift Pack', {'brands': ['Nestlé'], 'product_name': 'Nestle Kitkat Chocolate'}, False),
    ('Amul Mithai Mate Condensed Milk', {'brands': None, 'product_name': 'Mithai mate - Amul'}, False),
    ('Aak Flower Garland', {'brands': ['Garland'], 'product_name': 'Minced Garlic'}, False)])
def test_photo_matcher_takes_the_product_or_nothing(ours, hit, ok):
    P = _script('fetch_product_photos')
    assert P.judge({'name': ours, 'pack': None}, {**IMG, **hit})['ok'] is ok


@pytest.mark.parametrize('name, kind', [
    ('Kaju Katli by Lal', 'kaju katli'),
    ('Fresh Garland - Orange Marigold', 'marigold garland'),
    ('Bella Vita Perfume Bathing Soap for Men', 'soap'),                       # a soap, though its name says perfume
    ("MOM Dry Roasted Cashews, Almonds & Pista Nuts Mix", 'mixed nuts'),       # a mix, though its name says cashews
    ('MOM Makhana Chikki Bar', None),                                          # a chikki, not makhana; and not peanut
    ('Open Secret Brownie, Dry Fruits & Biscuits Gift Pack', None),            # mostly brownie
    ('Sapphire Original Danish Chocochip Biscuits Gift Pack', None),           # chocolate chips: not plain butter cookies
    ('Aroma Tin Scented Candle (Multicolor) by IRIS', None),                   # a tin, not a jar
    ('Avengers Themed Birthday Decoration Kit SpecialYou', None),
    ("IGP - Pink Teacher's Day 5 Stem Jumilia Rose Mini Bouquet", None),       # the photo is of red roses
    ('Amul Velvett Milk Chocolate Bar', None),                                 # every free photo showed another brand
    ('Cadbury Celebrations Assorted Chocolate Gift Pack', None),
    ('Derm Ease Sunscreen Spray (SPF 70 PA+++)', None),
    ('GO DESI Milk Peda with 66% Khoa by GO DESi + GO DESi Bombay Bhel with Chutney Combo', None)])
def test_kind_photos_go_only_where_the_kind_is_plain(name, kind):
    P = _script('fetch_product_photos')
    k = P.kind_of(name)
    assert (k[0] if k else None) == kind


def test_every_kind_photo_is_a_commons_file_with_a_caption():
    P = _script('fetch_product_photos')
    assert len({k[0] for k in P.KINDS}) == len(P.KINDS)
    for kind, rule, file, shows in P.KINDS:
        assert file.startswith('File:') and shows and re.compile(rule)


def test_saved_kind_photos_are_free_licensed_and_hosted_on_commons():
    f = ROOT / 'data' / 'reference' / 'PRODUCT_PHOTOS.json'
    photos = json.loads(f.read_text(encoding='utf-8'))['photos'].values()
    kinds = [p for p in photos if p.get('kind')]
    assert kinds
    for p in kinds:
        assert p['image'].startswith('https://upload.wikimedia.org/') and p['source'].startswith('https://commons.wikimedia.org/')
        assert p['license'].lower().startswith(('cc0', 'public domain', 'cc by')) and p['credit']


def test_photo_matcher_wants_a_photo_to_link():
    P = _script('fetch_product_photos')
    assert not P.judge({'name': 'Frooti Mango Drink'}, {'brands': ['Frooti'], 'product_name': 'Frooti Mango Drink'})['ok']
