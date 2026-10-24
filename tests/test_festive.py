"""The festive stock planner: a dated, sourced calendar; product groups as keyword rules; snapshot rows only; and no
claim about how much anything sells."""
import json
import re
from datetime import date

import pytest

from conftest import ROOT
from src.seasonal import festive as F


def test_calendar_is_dated_sourced_and_in_order():
    keys = [f['key'] for f in F.FESTIVALS]
    assert len(keys) == len(set(keys))
    for f in F.FESTIVALS:
        s, d, e = (date.fromisoformat(f[k]) for k in ('start', 'day', 'end'))
        assert s <= d <= e and (e - s).days <= 10, f['key']
        assert f['groups'] and all(g in F.GROUPS for g in f['groups']), f['key']
        assert F.aliases(f), f['key']                                      # a typed question can name it
        # a lunar date carries its sources; only fixed-date days may have none
        assert f['sources'] or f['note'] == 'Fixed date.', f['key']
        assert all(u.startswith('https://') for u in f['sources']), f['key']
    starts = [f['start'] for f in F.FESTIVALS]
    assert starts == sorted(starts)
    assert {'diwali_2026', 'raksha_bandhan', 'holi', 'christmas'} <= set(keys)
    diwali = next(f for f in F.FESTIVALS if f['key'] == 'diwali_2026')
    assert diwali['day'] == '2026-11-08' and 'diyas_candles' in diwali['groups']


def test_group_rules_compile_and_their_lookup_words_are_unambiguous():
    for k, g in F.GROUPS.items():
        inc, exc = F._compile(g)
        assert inc.pattern and (exc is None or exc.pattern), k
        assert g['words'] and g['label'], k
    # words that would send an ordinary question to a festival group were taken out on purpose
    every = {w for g in F.GROUPS.values() for w in g['words']}
    assert not {'deep', 'fast', 'dates', 'light', 'color', 'colour'} & every


def test_rules_match_what_they_name_and_not_lookalikes():
    import pandas as pd
    rows = pd.DataFrame({'product_name': [
        'Brass Akhand Diya (Golden) by Sehaz Artworks', 'Sensodyne Deep Clean Sensitive Toothpaste',
        'Chandan Mint Saunf Mouth Freshener', 'AuraCam Gold Standard Camphor Pod Air Freshener (Oudh)',
        'Phool Incense Sticks / Agarbatti (Mango & Pineapple)', 'Fresh Garland - Orange Marigold',
        'Organic India Tulsi Ginger Organic Herbal Infusion Bags', 'Happilo Rakhi Dry Fruit Potli',
        'Mr. Right Rechargeable Anti Mosquito Racquet with LED Light', 'Whole Farm Premium Cashew (Kaju)',
        "Kellogg's Almonds & Honey Corn Flakes", 'Britannia Toastea Cake Rusk', 'Awsum Handcrafted Premium Plum Cake (Eggless)'],
        'category': ['Other / General Merchandise', 'Personal Care', 'Sweets & Chocolates', 'Home & Cleaning',
                     'Other / General Merchandise', 'Fruits & Vegetables', 'Beverages', 'Fruits & Vegetables',
                     'Other / General Merchandise', 'Fruits & Vegetables', 'Breakfast & Instant Food', 'Bakery & Biscuits',
                     'Bakery & Biscuits']})

    def names(k):
        return set(F.match(rows, k).product_name)
    assert names('diyas_candles') == {'Brass Akhand Diya (Golden) by Sehaz Artworks'}
    assert names('puja') == {'Phool Incense Sticks / Agarbatti (Mango & Pineapple)'}      # not the candy brand, not air freshener
    assert names('flowers') == {'Fresh Garland - Orange Marigold'}                          # not tulsi tea
    assert names('rakhi') == {'Happilo Rakhi Dry Fruit Potli'}
    assert names('decor') == set()                                                         # not a mosquito racquet
    assert names('dry_fruits') == {'Whole Farm Premium Cashew (Kaju)'}                     # not corn flakes
    assert names('cakes') == {'Awsum Handcrafted Premium Plum Cake (Eggless)'}             # not a rusk


def _built():
    f = ROOT / 'outputs' / 'festive' / 'festive_planner.json'
    if not f.exists():
        pytest.skip('planner not built: python -m src.seasonal.festive')
    return json.loads(f.read_text(encoding='utf-8'))


def test_built_planner_reads_the_snapshot_only_and_claims_no_demand():
    d = _built()
    assert d['snapshot_date'] == '2026-07-10' and d['snapshot_rows'] == 21_949
    assert d['provenance'] == {'calendar': 'EXTERNAL where cited, METHOD where computed', 'groups': 'METHOD', 'listings': 'REAL'}
    keys = {f['key'] for f in d['festivals']}
    assert {f['key'] for f in F.FESTIVALS} <= keys and len(keys) == len(d['festivals']) and set(d['groups']) == set(F.GROUPS)
    for k, g in d['groups'].items():
        assert 0 <= g['products'] <= g['listings'] <= d['snapshot_rows'], k
        assert (g['out_of_stock_share'] is None) == (g['listings'] == 0), k
        assert len(g['examples']) <= 8
    assert d['groups']['diyas_candles']['listings'] > 0 and d['groups']['holi_colours']['listings'] == 0
    # nothing in the file is a sales, demand or uplift figure
    text = json.dumps(d).lower()
    for word in ('units_sold', 'demand_', 'uplift', 'revenue', 'gmv', 'orders_', 'sales_'):
        assert word not in text, word
    assert 'no orders' in d['claim_limit']


def test_planner_is_not_a_model_output_the_analyst_indexes():
    assert not (ROOT / 'outputs' / 'models' / 'festive_planner').exists()
    src = (ROOT / 'src' / 'seasonal' / 'festive.py').read_text(encoding='utf-8')
    assert 'save_model_outputs' not in src and re.search(r"OUT = ROOT / 'outputs' / 'festive'", src)


# --------------------------------------------------------------------------- the computed calendar (src/seasonal/almanac.py)
def test_the_almanac_reproduces_every_cited_date_and_span():
    """Computed dates are trusted only because they give back all 19 cited ones: the day, and the first and last day."""
    from src.seasonal import almanac as A
    rows = A.check()
    assert len(rows) == len(F.FESTIVALS) == 19
    assert [r[0] for r in rows if r[3] != 0] == []                 # the day
    assert [r[0] for r in rows if r[4] != r[5]] == []              # the span (Dhanteras to Bhai Dooj, Shashthi to Dashami)


def test_the_almanac_follows_the_rules_of_the_special_days():
    from src.seasonal import almanac as A
    for y in (2027, 2030, 2033):
        fd = A.compute('fathers_day', y)[0][1]
        md = A.compute('mothers_day', y)[0][1]
        assert fd.month == 6 and fd.weekday() == 6 and 15 <= fd.day <= 21              # third Sunday of June
        assert md.month == 5 and md.weekday() == 6 and 8 <= md.day <= 14               # second Sunday of May
        assert A.compute('christmas', y)[0][1] == date(y, 12, 25)
        s = A.compute('sankranti', y)[0][1]
        assert s.month == 1 and 13 <= s.day <= 16
        d = A.compute('diwali', y)[0][1]
        assert date(y, 10, 15) <= d <= date(y, 11, 16)                                 # Diwali moves, within these weeks
        r = A.compute('raksha_bandhan', y)[0][1]
        assert date(y, 7, 25) <= r <= date(y, 8, 31)
    months = A.lunar_months(2026)                                  # 2026 has an adhika Jyeshtha (17 May - 15 Jun)
    assert any(m['adhika'] and m['name'] == 'Jyeshtha' for m in months)


def test_the_built_calendar_runs_years_ahead_without_doubling_a_cited_festival():
    d = _built()
    assert d['almanac_check'] == {'festivals': 19, 'same_day': 19, 'same_span': 19}
    assert d['horizon'][1] >= f'{date.today().year + 6}-12-01'           # years ahead, not one
    comp = [f for f in d['festivals'] if f['provenance'] == 'METHOD']
    assert comp and all(not f['sources'] and f['note'] and f['rule'] for f in comp)
    for f in d['festivals']:
        assert f['start'] <= f['day'] <= f['end'] and all(k in d['groups'] for k in f['groups']), f['key']
    base = lambda f: re.sub(r'(_20\d\d)(_\d\d)?$', '', f['key'])
    days = {}
    for f in d['festivals']:
        for other in days.get(base(f), []):
            assert abs((date.fromisoformat(f['day']) - other).days) > 3, f['key']    # no festival listed twice
        days.setdefault(base(f), []).append(date.fromisoformat(f['day']))
    names = {f['name'] for f in comp}
    assert {"Father's Day", "Mother's Day", 'Raksha Bandhan', 'Diwali', "Teachers' Day"} <= names
    assert all(f['approximate'] for f in comp if base(f).startswith('eid'))


def test_special_day_rules_match_gifts_and_not_lookalikes():
    import pandas as pd
    rows = pd.DataFrame({'product_name': [
        'Cadbury Dairy Milk Silk Heart Blush Valentine Chocolate Gift Pack', 'Amul Dark Chocolate Milkshake',
        'Bella Vita Organic Men\'s Luxury Perfume Gift Set', 'Comfort Perfume Deluxe Elixir Fabric Conditioner',
        'Gillette Mach3 Men\'s Razor Cartridge', 'Coca-Cola Cherry Flavoured Soft Drink', 'Puramate Dark Compound Choco Chips',
        'Metallic Balloons (Golden) Party Propz', "Party Propz Teacher's Day Fridge Magnet (4\" x 3\", Multicolour)",
        "IGP - Red Teacher's Day Rose Single Flower Bouquet"],
        'category': ['Chocolates', 'Dairy, Bread & Eggs', 'Personal Care', 'Home & Cleaning', 'Personal Care', 'Beverages',
                     'Sweets & Chocolates', 'Other / General Merchandise', 'Other / General Merchandise', 'Fruits & Vegetables']})

    def names(k):
        return set(F.match(rows, k).product_name)
    assert names('chocolates') == {'Cadbury Dairy Milk Silk Heart Blush Valentine Chocolate Gift Pack'}   # not a milkshake
    assert names('perfumes') == {"Bella Vita Organic Men's Luxury Perfume Gift Set"}                     # not fabric conditioner
    assert names('grooming') == {"Gillette Mach3 Men's Razor Cartridge", "Bella Vita Organic Men's Luxury Perfume Gift Set"}
    assert names('party') == {'Coca-Cola Cherry Flavoured Soft Drink'}                                   # not baking choco chips
    assert names('balloons') == {'Metallic Balloons (Golden) Party Propz'}                               # not a fridge magnet
    assert 'Cadbury Dairy Milk Silk Heart Blush Valentine Chocolate Gift Pack' in names('made_for_valentines')
    assert "IGP - Red Teacher's Day Rose Single Flower Bouquet" in names('made_for_teachers_day')
