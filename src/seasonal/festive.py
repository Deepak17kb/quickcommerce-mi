"""
festive.py — the festive stock planner: when each festival falls, what is traditionally bought for it, and which of
those products Blinkit listed on the day it was observed.

    python -m src.seasonal.festive            # -> outputs/festive/festive_planner.json
    python -m src.seasonal.festive --probe    # print every group's matches, to review the keyword rules

Three parts, three provenances, kept apart in the output:

    calendar    EXTERNAL where cited: festival dates for Oct 2026 - Oct 2027 from public panchang and holiday calendars,
                checked 2026-10-14, each with its source URLs. METHOD everywhere else: computed by src/seasonal/almanac.py
                (the lunisolar calendar for Bhubaneswar, sankrantis, nth-Sunday days, the tabular Islamic calendar) for
                this year and the next HORIZON_YEARS, so the planner never runs out. The computed dates reproduce all 19
                cited ones, day and span (tests/test_festive.py). Eid depends on the moon sighting and stays approximate.
    groups      METHOD. Which product types are traditionally bought for which festival (diyas and candles for
                Diwali, rakhis for Raksha Bandhan ...), as keyword rules over product names. A rule of the planner,
                not a measurement.
    listings    REAL. The 2026-07-10 Blinkit snapshot rows each rule matches: how many listings, how many out of
                stock that day, observed prices (web-researched prices excluded, src/load.py).

What it does NOT do: say how much more anything sells, when, or by how much. The data has no orders, so no demand,
seasonality or uplift can be estimated from it (CLAUDE.md s.4). The planner says WHEN a product is in season, from the
calendar, and leaves HOW MUCH to stock to the operator. Nothing here is written into outputs/models: it is a reference
page, not a model, and the analyst does not index it.
"""
import argparse
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'outputs' / 'festive' / 'festive_planner.json'
CHECKED = '2026-10-14'
SNAPSHOT_DATE = '2026-07-10'

# --------------------------------------------------------------------------- product groups (METHOD)
# include / exclude are regexes on the lower-cased product name; cats, when given, limits the categories searched.
# words are what a typed question is matched against ("handmade diya" -> diyas_candles).
GROUPS = {
    'diyas_candles': {
        'label': 'Diyas & candles', 'icon': 'flame',
        'include': r'\bdiyas?\b|\bdiye\b|\bcandles?\b|\btea ?lights?\b',
        'exclude': r'candle ?nut|wax strip',
        'cats': ['Other / General Merchandise', 'Home & Cleaning', 'Fruits & Vegetables'],
        'words': ['diya', 'diyas', 'diye', 'deepak', 'candle', 'candles', 'tealight', 'tea light', 'lamp', 'lamps', 'dia'],
    },
    'puja': {
        'label': 'Puja essentials', 'icon': 'bell',
        'include': r'\bpoo?ja\b|agarbatti|incense|\bdhoop|camphor|\bkapoor\b|\bkarpur|ghee batti|cotton wicks?|\bkumkum\b|'
                   r'\broli\b|sindoor|havan|samagri|\bkalash\b|\bjanoi\b|\bpanch ?phal\b|puja thali|pooja thali|shami patra',
        'exclude': r'mosquito|repell|air freshener|car freshener|floor cleaner|diffuser|\bpods?\b|perfume|\bedp\b|\bedt\b|soap|'
                   r'intimate|cleansing gel',
        'cats': None,
        'words': ['puja', 'pooja', 'agarbatti', 'incense', 'dhoop', 'camphor', 'kapoor', 'kumkum', 'roli', 'sindoor', 'chandan',
                  'havan', 'samagri', 'kalash', 'thali', 'wick', 'batti', 'prasad', 'offering', 'aarti'],
    },
    'flowers': {
        'label': 'Flowers & garlands', 'icon': 'flower',
        'include': r'garland|marigold|\bgenda\b|lotus flower|poo?ja flower|\bphula\b|\btuls[ie]\b|\bmala\b|\bflowers?\b',
        'exclude': r'artificial|cauliflower|sunflower|flower (tea|honey|vase|pot)|elderflower|flower shaped|safflower|\bjam\b|'
                   r'infusion|\btea\b|\bbags\b|seeds?|planter|planting|fertili[sz]er|hooks?|basil|crochet|dried|doll|roll on|'
                   r'poppers|bedsheet|cotton|\bvines?\b|\bivy\b',
        'cats': ['Fruits & Vegetables', 'Other / General Merchandise'],
        'words': ['flower', 'flowers', 'garland', 'marigold', 'genda', 'phool', 'lotus', 'mala', 'tulsi', 'rose', 'roses'],
    },
    'decor': {
        'label': 'Decor & party', 'icon': 'spark',
        'include': r'string lights?|led (string|strip|lights?)|fairy lights?|decorative lights?|\btoran\b|\bjhalar\b|'
                   r'bandhanwar|rangoli|\blanterns?\b|\bakash ?kandil\b|\bdiwali\b|\burli\b|artificial (?:flowers?|garlands?|marigold)|'
                   r'flower shower|\bpoppers\b',
        'exclude': r'torch|bulb holder|emergency|mosquito|racquet|candle',
        'cats': ['Other / General Merchandise', 'Home & Cleaning', 'Electronics & Electricals'],
        'words': ['lights', 'string lights', 'fairy', 'decor', 'decoration', 'toran', 'rangoli', 'lantern', 'jhalar', 'bandhanwar'],
    },
    'sweets': {
        'label': 'Sweets & mithai', 'icon': 'gift',
        'include': r'soan ?papdi|\bmithai\b|kaju katli|gulab jamun|rasgull?a|\bladd?oo?s?\b|\bbarfi\b|\bpeda\b|\bpetha\b|'
                   r'gujiya|rasmalai|mysore pak|\bmalpua\b|\bjalebi\b|\bbundi\b|\bboondi\b|\bchhena\b|\brasabali\b',
        'exclude': r'boondi raita|raita|namkeen',
        'cats': ['Sweets & Chocolates', 'Instant & Ready to Eat', 'Snacks & Munchies', 'Dairy, Bread & Eggs'],
        'words': ['sweet', 'sweets', 'mithai', 'laddu', 'ladoo', 'barfi', 'katli', 'soan papdi', 'peda', 'gujiya', 'rasgulla',
                  'jamun', 'jalebi', 'halwa', 'chhena'],
    },
    'dry_fruits': {
        'label': 'Dry fruits', 'icon': 'nut',
        'include': r'\bcashews?\b|\bkaju\b|\balmonds?\b|\bbadam\b|\bpista(chio)?s?\b|\braisins?\b|\bkishmish\b|\bwalnuts?\b|'
                   r'\bakhrot\b|\bkhajur\b|dry ?fruits?|\banjeer\b|\bdried figs?\b|\bapricots? dried\b|\bdried apricots?\b',
        'exclude': r'beverage|milk|drink|\boil\b|butter|chocolate|biscuit|cookie|cream|\bbars?\b|shake|soap|face|scrub|lotion|'
                   r'shampoo|cereal|muesli|granola|ice|kulfi|cake|lassi|curd|yog(h)?urt|paste|flour|atta|katli|cookies|'
                   r'spread|protein|powder|bhujia|mixture|namkeen|coated|masala|shrikhand|thandai|corn ?flakes|falooda|ladd?u|'
                   r'barfi|burfi|chikki|patisa|gajak|\broll\b|mysore|sattu|trail mix|peri|bbq|smokey|flavou?red|gift|potli',
        'cats': ['Fruits & Vegetables', 'Staples & Grains', 'Other / General Merchandise'],
        'words': ['dry fruit', 'dry fruits', 'dryfruit', 'cashew', 'kaju', 'almond', 'badam', 'pista', 'raisin', 'kishmish',
                  'walnut', 'akhrot', 'khajur', 'anjeer', 'fig'],
    },
    'gift_packs': {
        'label': 'Gift packs & hampers', 'icon': 'gift',
        'include': r'gift ?(pack|box|hamper|set|tin)|\bhampers?\b|\bcelebrations\b',
        'exclude': r'gift card|gift wrap',
        'cats': None,
        'words': ['gift', 'gifts', 'hamper', 'hampers', 'gift pack', 'gift box', 'celebrations'],
    },
    'cakes': {
        'label': 'Cakes & plum cakes', 'icon': 'cake',
        'include': r'plum cake|fruit cake|\bcakes?\b',
        'exclude': r'rice cakes?|cake (mix|flour|decor|topper|gel|tin|pan|stand)|pancake|cupcake liner|rusk',
        'cats': ['Bakery & Biscuits', 'Sweets & Chocolates', 'Dairy, Bread & Eggs'],
        'words': ['cake', 'cakes', 'plum cake', 'fruit cake', 'pastry', 'brownie'],
    },
    'til_jaggery': {
        'label': 'Til, jaggery & chikki', 'icon': 'nut',
        'include': r'\btil\b|sesame seeds?|\bgajak\b|\bchikki\b|jaggery|\bgur\b|\bgud\b|\brewdi\b|\brevdi\b',
        'exclude': r'\boil\b|biscuit|cookie|\batta\b|cracker|rusk|protein|energy bar|kaju katli',
        'cats': None,
        'words': ['til', 'sesame', 'gajak', 'chikki', 'jaggery', 'gur', 'gud', 'rewdi', 'revdi', 'pitha'],
    },
    'sewai': {
        'label': 'Sewai & dessert mixes', 'icon': 'bowl',
        'include': r'\bsewai\b|\bsevai\b|\bseviyan\b|vermicelli|kheer mix|payasam|phirni',
        'exclude': r'sprinkles|upma',
        'cats': None,
        'words': ['sewai', 'sevai', 'seviyan', 'vermicelli', 'kheer', 'payasam', 'phirni', 'sheer khurma'],
    },
    'holi_colours': {
        'label': 'Holi colours', 'icon': 'drop',
        'include': r'\bgulal\b|holi colou?rs?|herbal colou?rs?|\bpichkari\b',
        'exclude': r'food colou?r',
        'cats': None,
        'words': ['gulal', 'holi colours', 'holi colors', 'colours', 'pichkari', 'abir'],
    },
    'rakhi': {
        'label': 'Rakhis & rakhi gift packs', 'icon': 'gift',
        'include': r'\brakhi\b',
        'exclude': None,
        'cats': None,
        'words': ['rakhi', 'rakhee', 'raksha'],
    },
    'modak': {
        'label': 'Modak makings', 'icon': 'bowl',
        'include': r'\bmodak\b',
        'exclude': r'lipstick|matte|kit',
        'cats': ['Staples & Grains', 'Sweets & Chocolates', 'Instant & Ready to Eat'],
        'words': ['modak', 'modaks'],
    },
    'fasting': {
        'label': 'Fasting foods', 'icon': 'bowl',
        'include': r'sabudana|\bsago\b|\bkuttu\b|singhara|rajgira|\bmakhana\b|\bsamak\b|\bvrat\b|fox ?nuts?|sendha',
        'exclude': r'chocolate|cookie|biscuit|tikki|chikki|\bbar\b|sprinklers|iodi[sz]ed|flavou?red|cream & onion|tomato|'
                   r'pudina|masala|peri|salt & pepper|cheese|tangy',
        'cats': None,
        'words': ['sabudana', 'sago', 'kuttu', 'singhara', 'rajgira', 'makhana', 'samak', 'vrat', 'fasting', 'foxnut',
                  'sendha'],
    },
    # ---- added 2026-10-23 for special days (Valentine's, Mother's and Father's Day ...). Each rule was read against the
    # observed names before it went in; the lookalikes it caught are in its exclude (milkshakes, fabric conditioner).
    'chocolates': {
        'label': 'Chocolates & chocolate gifts', 'icon': 'gift',
        'include': r'\bchocolates?\b|\bdairy milk\b|\bkit ?kat\b|\bferrero\b|\bsilk\b|\bbournville\b|\bpralines?\b|\btruffles?\b|'
                   r'\bfive star\b|\btoblerone\b|\blindt\b|\bcelebrations\b',
        'exclude': r'compound|sprinkles|chips|drink|beverage|\bmix\b|syrup|spread|wafers?\b|cookie|biscuit|granola|aphrodisiac|'
                   r'protein|supplement|milkshake|cake|muffin|donut|brownie|waffle|coffee|powder|toffee',
        'cats': ['Chocolates', 'Sweets & Chocolates'],
        'words': ['chocolate', 'chocolates', 'dairy milk', 'kitkat', 'ferrero', 'truffle', 'truffles', 'pralines', 'toblerone'],
    },
    'perfumes': {
        'label': 'Perfumes & gift sets', 'icon': 'spray',
        'include': r'\bperfumes?\b|\bbody mists?\b|eau de|\bedp\b|\bedt\b|\bbody spray\b',
        'exclude': r'soap|body ?wash|dog|\bpet\b|\bcar\b|room|candle|cockroach|urinal|bathing|aphrodisiac|fabric|conditioner',
        'cats': ['Personal Care'],
        'words': ['perfume', 'perfumes', 'body mist', 'fragrance', 'scent', 'deo', 'deodorant', 'body spray'],
    },
    'grooming': {
        'label': "Men's grooming", 'icon': 'user',
        'include': r'\bshav(e|ing)\b|\brazors?\b|after ?shave|\bbeard\b|\btrimmers?\b|\bmen\b.*\b(face wash|perfume|deo|cream)\b|'
                   r'\bfor men\b|\bgillette\b|\bbombay shaving\b|\bbeardo\b|\bnivea men\b',
        'exclude': r'women|ladies|\bher\b|baby|kids|\bpet\b',
        'cats': ['Personal Care'],
        'words': ['razor', 'shaving', 'shave', 'beard', 'trimmer', 'grooming', 'aftershave', 'face wash for men'],
    },
    'party': {
        'label': 'Soft drinks & party snacks', 'icon': 'cup',
        'include': r'\bsoft drinks?\b|\bcoca[- ]cola\b|\bpepsi\b|\bsprite\b|\bfanta\b|\bthums up\b|\bmirinda\b|\b7 ?up\b|'
                   r'\bmountain dew\b|\bpopcorn\b|\bnachos\b|\bpotato chips\b',
        'exclude': r'baking|choco ?chips|protein|energy|chicken|combo|electrolyte|kernels|chocolate|wafers?',
        'cats': None,
        'words': ['soft drink', 'cola', 'pepsi', 'coke', 'sprite', 'popcorn', 'nachos', 'chips', 'party snacks'],
    },
    'balloons': {
        'label': 'Balloons & party props', 'icon': 'spark',
        'include': r'\bballoons?\b|party poppers?|birthday (banner|decoration|caps)|decoration kit|foil curtain|\bconfetti\b',
        'exclude': r'pump|bubble gum|dart|magnet',
        'cats': None,
        'words': ['balloon', 'balloons', 'party props', 'decoration kit', 'birthday banner', 'confetti', 'party poppers'],
    },
    # products made for one occasion, found by the occasion's own name in the product name
    'made_for_teachers_day': {
        'label': "Made for Teachers' Day", 'icon': 'flower', 'include': r"teacher'?s'? day|best teacher", 'exclude': None,
        'cats': None, 'words': ["teachers day", "teacher's day", 'for teacher'],
    },
    'made_for_valentines': {
        'label': "Made for Valentine's Day", 'icon': 'gift', 'include': r'valentine|\bi love you\b|\blove you\b',
        'exclude': r'plant|\bpot\b', 'cats': None, 'words': ['valentine', 'valentines', 'i love you'],
    },
    'made_for_christmas': {
        'label': 'Made for Christmas', 'icon': 'spark', 'include': r'christmas|\bxmas\b|\bsanta\b', 'exclude': None,
        'cats': None, 'words': ['christmas tree', 'wreath', 'santa'],
    },
    'made_for_womens_day': {
        'label': "Made for Women's Day", 'icon': 'flower', 'include': r"women'?s day", 'exclude': None,
        'cats': None, 'words': ["womens day", "women's day"],
    },
    'made_for_eid': {
        'label': 'Made for Eid and Ramzan', 'icon': 'nut', 'include': r'\beid\b|ramadan|ramzan', 'exclude': None,
        'cats': None, 'words': ['ramzan', 'ramadan', 'iftar'],
    },
}

# --------------------------------------------------------------------------- the calendar (EXTERNAL, checked CHECKED)
_DIWALI_SRC = ['https://www.kissht.com/blog/diwali-2026-date-and-lakshmi-puja-timing',
               'https://www.azafashions.com/blog/diwali-2026-dates-your-5-day-festive-outfit-calendar/']
_2027_SRC = ['https://www.calendarlabs.com/holidays/hindu/2027', 'https://calendarific.com/holidays/2027/IN',
             'https://www.drikpanchang.com/calendars/hindu/hinducalendar.html?year=2027']
FESTIVALS = [
    {'key': 'durga_puja', 'name': 'Durga Puja', 'start': '2026-10-17', 'end': '2026-10-21', 'day': '2026-10-19',
     'local': True, 'groups': ['puja', 'flowers', 'sweets', 'gift_packs', 'decor'],
     'note': 'Shashthi to Dashami on the Bengal and Odia calendar; the central holiday list puts Ashtami a day earlier.',
     'sources': ['https://www.bangladatetoday.com/blog/durga-puja-2026-dates-and-schedule',
                 'https://hindutone.com/festivals/durga-puja-2026-dates-kolkata-mahalaya-to-sindoor-khela/']},
    {'key': 'dussehra_2026', 'name': 'Dussehra', 'start': '2026-10-20', 'end': '2026-10-20', 'day': '2026-10-20',
     'groups': ['puja', 'flowers', 'sweets'],
     'note': 'One source gives 21 October.',
     'sources': ['https://www.businesstoday.in/india/story/navratri-2026-full-calendar-durga-ashtami-maha-navami-dussehra-dates-check-here-560833-2026-10-11',
                 'https://www.outlookindia.com/astrology/astro-picks/navratri-and-durga-puja-2026-know-the-dates-rituals-and-significance']},
    {'key': 'karwa_chauth', 'name': 'Karwa Chauth', 'start': '2026-10-29', 'end': '2026-10-29', 'day': '2026-10-29',
     'groups': ['puja', 'dry_fruits', 'sweets', 'flowers'],
     'note': 'Most sources give 29 October; one gives 28 October.',
     'sources': ['https://hindutone.com/festivals/karwa-chauth-2026-date-moonrise-vidhi/',
                 'https://www.azafashions.com/blog/karwa-chauth-2026-date-moonrise-time-what-to-wear/']},
    {'key': 'diwali_2026', 'name': 'Diwali', 'start': '2026-11-06', 'end': '2026-11-11', 'day': '2026-11-08',
     'groups': ['diyas_candles', 'puja', 'flowers', 'decor', 'sweets', 'dry_fruits', 'gift_packs'],
     'note': 'Dhanteras 6 Nov, Lakshmi Puja 8 Nov, Bhai Dooj 11 Nov. Govardhan Puja and Bhai Dooj move by a day between sources.',
     'sources': _DIWALI_SRC + ['https://dekhopanchang.com/en/festivals/govardhan-puja']},
    {'key': 'chhath', 'name': 'Chhath Puja', 'start': '2026-11-13', 'end': '2026-11-16', 'day': '2026-11-15',
     'groups': ['puja', 'flowers', 'til_jaggery'],
     'note': 'Sandhya Arghya on 15 November; one source starts the four days a day later.',
     'sources': ['https://www.smartpuja.com/blog/chhath-puja-2026-date-arghya-timings-vidhi/',
                 'https://shubhpanchang.com/festivals/chhath-puja']},
    {'key': 'kartika_purnima', 'name': 'Kartika Purnima · Boita Bandana', 'start': '2026-11-24', 'end': '2026-11-24',
     'day': '2026-11-24', 'local': True, 'groups': ['diyas_candles', 'flowers', 'puja'],
     'note': 'Dev Deepawali the same day. Bali Jatra in Cuttack starts on it and runs for several days.',
     'sources': ['https://hindutone.com/festivals/kartika-purnima-2026-tripurari-purnima-dev-deepawali-date-significance-varanasi/',
                 'https://hindutone.com/festivals/boita-bandana-bali-jatra-2026-odisha/']},
    {'key': 'christmas', 'name': 'Christmas', 'start': '2026-12-24', 'end': '2026-12-25', 'day': '2026-12-25',
     'groups': ['cakes', 'made_for_christmas', 'gift_packs', 'chocolates', 'decor', 'diyas_candles'], 'note': 'Fixed date.', 'sources': []},
    {'key': 'new_year', 'name': "New Year's Eve", 'start': '2026-12-31', 'end': '2026-12-31', 'day': '2026-12-31',
     'groups': ['party', 'cakes', 'balloons', 'decor', 'gift_packs'], 'note': 'Fixed date.', 'sources': []},
    {'key': 'sankranti', 'name': 'Makar Sankranti', 'start': '2027-01-15', 'end': '2027-01-15', 'day': '2027-01-15',
     'groups': ['til_jaggery', 'sweets', 'puja'], 'note': 'Pongal the same day.',
     'sources': ['https://hindupad.com/hindu-festivals-2027/', 'https://www.calendarlabs.com/holidays/hindu/2027']},
    {'key': 'valentines', 'name': "Valentine's Day", 'start': '2027-02-14', 'end': '2027-02-14', 'day': '2027-02-14',
     'groups': ['made_for_valentines', 'chocolates', 'flowers', 'perfumes', 'gift_packs', 'cakes'], 'note': 'Fixed date.', 'sources': []},
    {'key': 'eid_ul_fitr', 'name': 'Eid ul-Fitr', 'start': '2027-03-09', 'end': '2027-03-10', 'day': '2027-03-10',
     'groups': ['sewai', 'dry_fruits', 'made_for_eid', 'sweets', 'gift_packs'],
     'note': 'Set by the moon sighting: 9 or 10 March, confirmed the evening before.',
     'sources': ['https://calendarific.com/holidays/2027/IN', 'https://www.officeholidays.com/holidays/india/delhi/eid-al-fitr']},
    {'key': 'holi', 'name': 'Holi', 'start': '2027-03-21', 'end': '2027-03-22', 'day': '2027-03-22',
     'groups': ['holi_colours', 'sweets', 'gift_packs'], 'note': 'Holika Dahan 21 March, Holi 22 March.',
     'sources': _2027_SRC},
    {'key': 'rath_yatra', 'name': 'Rath Yatra', 'start': '2027-07-05', 'end': '2027-07-05', 'day': '2027-07-05',
     'local': True, 'groups': ['puja', 'flowers', 'sweets'],
     'note': 'Puri. Panchang sites agree; the temple administration confirms it nearer the day.',
     'sources': ['https://dekhopanchang.com/en/festivals/jagannath-rath-yatra/2027', 'https://shubhpanchang.com/festivals/rath-yatra']},
    {'key': 'raksha_bandhan', 'name': 'Raksha Bandhan', 'start': '2027-08-17', 'end': '2027-08-17', 'day': '2027-08-17',
     'groups': ['rakhi', 'gift_packs', 'chocolates', 'sweets', 'dry_fruits'], 'note': 'One panchang gives 16 August, the full-moon day.',
     'sources': _2027_SRC},
    {'key': 'janmashtami', 'name': 'Janmashtami', 'start': '2027-08-25', 'end': '2027-08-25', 'day': '2027-08-25',
     'groups': ['puja', 'sweets', 'flowers', 'fasting'], 'note': 'Smarta observance on 24 August in one panchang.',
     'sources': _2027_SRC},
    {'key': 'ganesh_chaturthi', 'name': 'Ganesh Chaturthi', 'start': '2027-09-04', 'end': '2027-09-04', 'day': '2027-09-04',
     'groups': ['modak', 'puja', 'flowers', 'sweets'], 'note': 'One panchang gives 3 September.',
     'sources': _2027_SRC},
    {'key': 'navratri_2027', 'name': 'Navratri', 'start': '2027-09-30', 'end': '2027-10-08', 'day': '2027-10-04',
     'groups': ['fasting', 'puja', 'flowers'], 'note': 'Start date differs between sources.',
     'sources': ['https://www.drikpanchang.com/calendars/hindu/hinducalendar.html?year=2027']},
    {'key': 'dussehra_2027', 'name': 'Dussehra', 'start': '2027-10-09', 'end': '2027-10-09', 'day': '2027-10-09',
     'groups': ['puja', 'flowers', 'sweets'], 'note': '',
     'sources': ['https://dekhopanchang.com/en/festivals/dussehra/2027']},
    {'key': 'diwali_2027', 'name': 'Diwali', 'start': '2027-10-27', 'end': '2027-10-31', 'day': '2027-10-29',
     'groups': ['diyas_candles', 'puja', 'flowers', 'decor', 'sweets', 'dry_fruits', 'gift_packs'],
     'note': 'About 29 October; one panchang places Lakshmi Puja on 28 October. The five days are approximate.',
     'sources': ['https://calendarific.com/holidays/2027/IN', 'https://www.drikpanchang.com/telugu/calendar/telugu-calendar.html?year=2027']},
]


# what a typed question may call each festival (the key without its year)
ALIASES = {
    'durga_puja': ['durga puja', 'durga', 'pujo'], 'dussehra': ['dussehra', 'dasara', 'vijayadashami'],
    'karwa_chauth': ['karwa chauth', 'karva chauth', 'karwa'],
    'diwali': ['diwali', 'deepavali', 'dhanteras', 'bhai dooj', 'lakshmi puja'], 'chhath': ['chhath'],
    'kartika_purnima': ['kartika purnima', 'kartik purnima', 'boita bandana', 'dev deepawali', 'bali jatra'],
    'christmas': ['christmas', 'xmas'], 'new_year': ['new year'], 'sankranti': ['sankranti', 'pongal'],
    'valentines': ['valentine'], 'eid_ul_fitr': ['eid', 'ramzan', 'ramadan'], 'holi': ['holi'],
    'rath_yatra': ['rath yatra', 'ratha yatra', 'rath'], 'raksha_bandhan': ['raksha bandhan', 'rakhi'],
    'janmashtami': ['janmashtami'], 'ganesh_chaturthi': ['ganesh chaturthi', 'ganesh', 'ganpati', 'vinayaka'],
    'navratri': ['navratri', 'navaratri'],
    'ugadi': ['ugadi', 'gudi padwa'], 'ram_navami': ['ram navami', 'rama navami'],
    'maha_shivratri': ['shivratri', 'maha shivratri', 'shivaratri'], 'raja_parba': ['raja parba', 'raja', 'raja sankranti'],
    'eid_ul_adha': ['bakrid', 'eid ul adha', 'eid al adha', 'bakri eid'], 'womens_day': ["women's day", 'womens day'],
    'odisha_day': ['odisha day', 'utkala dibasa'], 'mothers_day': ["mother's day", 'mothers day'],
    'fathers_day': ["father's day", 'fathers day'], 'friendship_day': ['friendship day'],
    'teachers_day': ["teachers' day", "teacher's day", 'teachers day'], 'childrens_day': ["children's day", 'childrens day'],
}

# How each festival the almanac computes appears in the planner: its name, what to stock, whether it is big in Odisha.
# Festivals of the cited calendar keep their own entry (FESTIVALS); these fill every other year.
HORIZON_YEARS = 8
INFO = {
    'ugadi': {'name': 'Ugadi · Gudi Padwa', 'groups': ['sweets', 'puja', 'flowers', 'dry_fruits']},
    'ram_navami': {'name': 'Ram Navami', 'groups': ['puja', 'flowers', 'sweets', 'fasting']},
    'rath_yatra': {'name': 'Rath Yatra', 'groups': ['puja', 'flowers', 'sweets'], 'local': True},
    'raksha_bandhan': {'name': 'Raksha Bandhan', 'groups': ['rakhi', 'gift_packs', 'chocolates', 'sweets', 'dry_fruits']},
    'janmashtami': {'name': 'Janmashtami', 'groups': ['puja', 'sweets', 'flowers', 'fasting']},
    'ganesh_chaturthi': {'name': 'Ganesh Chaturthi', 'groups': ['modak', 'puja', 'flowers', 'sweets']},
    'navratri': {'name': 'Navratri', 'groups': ['fasting', 'puja', 'flowers']},
    'durga_puja': {'name': 'Durga Puja', 'groups': ['puja', 'flowers', 'sweets', 'gift_packs', 'decor'], 'local': True},
    'dussehra': {'name': 'Dussehra', 'groups': ['puja', 'flowers', 'sweets']},
    'karwa_chauth': {'name': 'Karwa Chauth', 'groups': ['puja', 'dry_fruits', 'sweets', 'flowers']},
    'diwali': {'name': 'Diwali', 'groups': ['diyas_candles', 'puja', 'flowers', 'decor', 'sweets', 'dry_fruits', 'gift_packs']},
    'chhath': {'name': 'Chhath Puja', 'groups': ['puja', 'flowers', 'til_jaggery']},
    'kartika_purnima': {'name': 'Kartika Purnima · Boita Bandana', 'groups': ['diyas_candles', 'flowers', 'puja'], 'local': True},
    'maha_shivratri': {'name': 'Maha Shivratri', 'groups': ['puja', 'flowers', 'fasting']},
    'holi': {'name': 'Holi', 'groups': ['holi_colours', 'sweets', 'gift_packs', 'party']},
    'sankranti': {'name': 'Makar Sankranti', 'groups': ['til_jaggery', 'sweets', 'puja']},
    'raja_parba': {'name': 'Raja Parba', 'groups': ['sweets', 'flowers', 'gift_packs'], 'local': True},
    'eid_ul_fitr': {'name': 'Eid ul-Fitr', 'groups': ['sewai', 'dry_fruits', 'made_for_eid', 'sweets', 'gift_packs']},
    'eid_ul_adha': {'name': 'Eid ul-Adha (Bakrid)', 'groups': ['dry_fruits', 'sweets', 'gift_packs']},
    'new_year': {'name': "New Year's Eve", 'groups': ['party', 'cakes', 'balloons', 'decor', 'gift_packs']},
    'valentines': {'name': "Valentine's Day", 'groups': ['made_for_valentines', 'chocolates', 'flowers', 'perfumes', 'gift_packs', 'cakes']},
    'womens_day': {'name': "Women's Day", 'groups': ['made_for_womens_day', 'flowers', 'chocolates', 'perfumes', 'gift_packs']},
    'odisha_day': {'name': 'Odisha Day · Utkala Dibasa', 'groups': ['sweets'], 'local': True},
    'mothers_day': {'name': "Mother's Day", 'groups': ['flowers', 'chocolates', 'perfumes', 'cakes', 'gift_packs']},
    'fathers_day': {'name': "Father's Day", 'groups': ['grooming', 'perfumes', 'chocolates', 'cakes', 'gift_packs']},
    'friendship_day': {'name': 'Friendship Day', 'groups': ['chocolates', 'gift_packs', 'party', 'balloons']},
    'teachers_day': {'name': "Teachers' Day", 'groups': ['made_for_teachers_day', 'flowers', 'chocolates', 'gift_packs']},
    'childrens_day': {'name': "Children's Day", 'groups': ['chocolates', 'party', 'balloons', 'cakes']},
    'christmas': {'name': 'Christmas', 'groups': ['cakes', 'made_for_christmas', 'gift_packs', 'chocolates', 'decor', 'diyas_candles']},
}


def computed_festivals(first_year: int, years: int) -> list:
    """Festival entries computed by the almanac for `years` years from `first_year`, in the cited calendar's shape,
    with provenance METHOD and the rule that decided each date. A festival the cited calendar already has (same
    festival, within three days) is left to the cited entry."""
    from src.seasonal import almanac as A
    cited = [(re.sub(r'_20\d\d$', '', f['key']), date.fromisoformat(f['day'])) for f in FESTIVALS]
    out = []
    for y in range(first_year, first_year + years):
        months = A.lunar_months(y)
        for key, info in INFO.items():
            for start, day, end, how in A.compute(key, y, months):
                if any(k == key and abs((d - day).days) <= 3 for k, d in cited):
                    continue
                kind = A.RULES[key]['kind']
                if kind == 'weekday':
                    note = f"{['First', 'Second', 'Third', 'Fourth'][A.RULES[key]['n'] - 1]} Sunday of {day.strftime('%B')}."
                else:
                    note = {'tithi': f'Computed for Bhubaneswar from the lunar calendar ({how}). Panchangs can differ by a day.',
                            'sankranti': 'Computed: the day the sun enters its sidereal sign (Lahiri).',
                            'islamic': 'Approximate: set by the sighting of the moon, which can move it by a day either way.',
                            'fixed': 'Fixed date.'}[kind]
                out.append({'key': f'{key}_{day.year}' if day.year == y else f'{key}_{y}', 'name': info['name'],
                            'start': start.isoformat(), 'end': end.isoformat(), 'day': day.isoformat(),
                            'local': bool(info.get('local')), 'groups': list(info['groups']), 'note': note, 'sources': [],
                            'provenance': 'METHOD', 'rule': how, 'approximate': kind == 'islamic'})
    keys = [f['key'] for f in out]
    for i, f in enumerate(out):                         # an Islamic festival can fall twice in one Gregorian year
        if keys.count(f['key']) > 1:
            f['key'] = f"{f['key']}_{f['day'][5:7]}"
    return out


def aliases(f):
    return ALIASES[re.sub(r'(_20\d\d)(_\d\d)?$', '', f['key'])]


def _compile(g):
    nc = lambda rx: re.sub(r'\((?!\?)', '(?:', rx)            # no capturing groups: pandas warns on them
    inc = re.compile(nc(g['include']), re.I)
    exc = re.compile(nc(g['exclude']), re.I) if g.get('exclude') else None
    return inc, exc


def match(real, key):
    """The snapshot rows a group's rule matches."""
    g = GROUPS[key]
    inc, exc = _compile(g)
    d = real if not g.get('cats') else real[real.category.isin(g['cats'])]
    names = d.product_name.fillna('')
    hit = names.str.contains(inc)
    if exc is not None:
        hit &= ~names.str.contains(exc)
    return d[hit]


def group_summary(real, key, observed_price_ids, n_examples=8):
    import numpy as np
    rows = match(real, key)
    if rows.empty:
        return {'key': key, 'listings': 0, 'products': 0, 'out_of_stock_share': None, 'median_price': None, 'examples': []}
    priced = rows[rows.observation_key.isin(observed_price_ids)]
    prod = (rows.assign(observed=rows.observation_key.isin(observed_price_ids))
            .groupby(['product_name', 'pack_size'], dropna=False)
            .agg(listings=('observation_key', 'size'), in_stock=('in_stock', 'mean'), category=('category', 'first'))
            .reset_index())
    prices = priced.groupby(['product_name', 'pack_size'], dropna=False).selling_price.median()
    prod['price'] = [prices.get((n, p)) for n, p in zip(prod.product_name, prod.pack_size)]
    prod = prod.sort_values(['listings', 'product_name'], ascending=[False, True])
    ex = [{'name': str(r.product_name), 'pack': None if r.pack_size != r.pack_size else str(r.pack_size),
           'category': str(r.category), 'price': None if r.price is None or r.price != r.price else float(r.price),
           'in_stock': bool(r.in_stock >= 0.5)} for r in prod.head(n_examples).itertuples()]
    return {'key': key, 'listings': int(len(rows)), 'products': int(len(prod)),
            'out_of_stock_share': round(float(1 - rows.in_stock.mean()), 4),
            'median_price': None if priced.empty else float(np.median(priced.selling_price)),
            'examples': ex}


def build():
    import src.load as L
    raw = L.load_raw('Blinkit')
    real = raw[raw.data_status == 'REAL'].copy()
    dates = sorted(real.snapshot_date.astype(str).unique())
    assert dates == [SNAPSHOT_DATE], dates                   # the snapshot is one day; anything else is a wrong load
    observed = set(L.real_observed_price_only(real).observation_key)
    groups = {k: {**{f: g[f] for f in ('label', 'icon', 'words', 'include')}, **group_summary(real, k, observed)}
              for k, g in GROUPS.items()}
    from src.seasonal import almanac as A
    first = min(date.today().year, int(FESTIVALS[0]['start'][:4]))
    cal = [{**f, 'provenance': 'EXTERNAL'} for f in FESTIVALS] + computed_festivals(first, HORIZON_YEARS + 1)
    for f in cal:
        assert f['start'] <= f['day'] <= f['end'] and all(k in GROUPS for k in f['groups']), f['key']
    agree = A.check()
    return {
        'built': date.today().isoformat(), 'calendar_checked': CHECKED, 'snapshot_date': SNAPSHOT_DATE,
        'provenance': {'calendar': 'EXTERNAL where cited, METHOD where computed', 'groups': 'METHOD', 'listings': 'REAL'},
        'horizon': [min(f['start'] for f in cal), max(f['end'] for f in cal)],
        'almanac_check': {'festivals': len(agree), 'same_day': sum(r[3] == 0 for r in agree),
                          'same_span': sum(r[4] == r[5] for r in agree)},
        'festivals': sorted(({**f, 'aliases': aliases(f)} for f in cal), key=lambda f: (f['start'], f['key'])), 'groups': groups,
        'snapshot_rows': int(len(real)),
        'claim_limit': ('When a product is in season comes from the festival calendar. How much more it sells cannot be '
                        'measured: the data has no orders. Listings and stock status are from the one observed day, '
                        f'{SNAPSHOT_DATE}, not from a festival period.'),
    }


def probe():
    import src.load as L
    raw = L.load_raw('Blinkit')
    real = raw[raw.data_status == 'REAL']
    for k in GROUPS:
        m = match(real, k)
        names = m.product_name.drop_duplicates().tolist()
        print(f'\n== {k}: {len(m)} rows, {len(names)} names')
        for n in names[:60]:
            print('   ', n)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument('--probe', action='store_true', help='print every group\'s matched product names')
    a = ap.parse_args()
    if a.probe:
        return probe()
    out = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding='utf-8', newline='\n')
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out['festivals'])} festivals, "
          + ', '.join(f"{g['label']} {g['listings']}" for g in out['groups'].values()))


if __name__ == '__main__':
    main()
