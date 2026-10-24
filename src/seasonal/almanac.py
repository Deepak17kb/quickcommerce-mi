"""
almanac.py — festival dates for any year, computed: the Hindu lunisolar calendar for Bhubaneswar, the sidereal solar
months, the tabular Islamic calendar, fixed dates and "nth weekday" days (Mother's Day, Father's Day ...).

    python -m src.seasonal.almanac 2028          # every festival of 2028, with how each date was decided
    python -m src.seasonal.almanac --check       # the computed dates against the cited 2026-27 calendar (festive.py)

WHY. The festive planner's calendar was a table of cited dates for Oct 2026 - Oct 2027 and stopped there. The owner
asked for it to keep up by itself ("whenever the next festive season or special day comes, plan for it"). Lunar
festivals cannot be listed by rule of thumb (Diwali moves by up to three weeks), so this computes them the way a
panchang does, from the positions of the sun and the moon:

    sun     apparent ecliptic longitude, Meeus (Astronomical Algorithms) ch. 25, about 0.01 deg
    moon    ecliptic longitude from the 31 largest periodic terms of Meeus Table 47.A, about 0.005 deg
    tithi   the moon's elongation from the sun in 12-degree steps (1-15 bright half, 16-30 dark half; 15 = Purnima,
            30 = Amavasya); a 0.01 deg error moves a tithi boundary by about a minute
    month   amanta (new moon to new moon), named after the sidereal sign the sun is in at the opening new moon
            (Lahiri ayanamsa); two new moons in one sign make the first month adhika (leap), as in every panchang
    day     a festival's tithi is looked for at the moment tradition uses: sunrise for most, dusk (pradosh) for
            Diwali, Dhanteras and Holika Dahan, midday for Ganesh Chaturthi, afternoon for Dussehra, midnight for
            Janmashtami and Maha Shivratri, moonrise for Karwa Chauth. Sunrise and sunset are Bhubaneswar's.

HOW IT IS CHECKED. `check()` computes every festival of the cited 2026-27 calendar in festive.py and compares dates;
tests/test_festive.py requires them to agree, allowing one day only where the cited calendar itself notes that
panchangs disagree. Computed dates are a METHOD result, labelled as such on the site; Eid depends on the sighting of
the moon and is marked approximate (the tabular calendar can be a day off either way).
"""
import argparse
import math
from datetime import date, datetime, timedelta, timezone

LAT, LON = 20.2961, 85.8245                    # Bhubaneswar
IST = timezone(timedelta(hours=5, minutes=30))
DELTA_T = 70.0 / 86400                         # TT - UT in days, about 70 s in the 2020s-30s

MONTHS = ['Chaitra', 'Vaishakha', 'Jyeshtha', 'Ashadha', 'Shravana', 'Bhadrapada', 'Ashvin', 'Kartika',
          'Margashirsha', 'Pausha', 'Magha', 'Phalguna']
RAD = math.pi / 180


# --------------------------------------------------------------------------- time
def jd_from_dt(dt: datetime) -> float:
    """Julian day (UT) of an aware datetime."""
    u = dt.astimezone(timezone.utc)
    return 2440587.5 + (u - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds() / 86400


def dt_from_jd(jd: float) -> datetime:
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(days=jd - 2440587.5)


def local_jd(d: date, hour: float) -> float:
    """Julian day of a local (IST) clock time on a civil date."""
    return jd_from_dt(datetime(d.year, d.month, d.day, tzinfo=IST)) + hour / 24


def local_date(jd: float) -> date:
    return dt_from_jd(jd).astimezone(IST).date()


# --------------------------------------------------------------------------- the sun and the moon
def sun_longitude(jd: float) -> float:
    """Apparent geocentric ecliptic longitude of the sun, degrees (Meeus ch. 25)."""
    t = (jd + DELTA_T - 2451545.0) / 36525
    l0 = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    m = (357.52911 + 35999.05029 * t - 0.0001537 * t * t) * RAD
    c = ((1.914602 - 0.004817 * t - 0.000014 * t * t) * math.sin(m) + (0.019993 - 0.000101 * t) * math.sin(2 * m)
         + 0.000289 * math.sin(3 * m))
    omega = (125.04 - 1934.136 * t) * RAD
    return (l0 + c - 0.00569 - 0.00478 * math.sin(omega)) % 360


# Meeus Table 47.A, longitude terms: (D, M, M', F, coefficient in 1e-6 degrees); terms with M are scaled by E^|M|
_MOON = [
    (0, 0, 1, 0, 6288774), (2, 0, -1, 0, 1274027), (2, 0, 0, 0, 658314), (0, 0, 2, 0, 213618),
    (0, 1, 0, 0, -185116), (0, 0, 0, 2, -114332), (2, 0, -2, 0, 58793), (2, -1, -1, 0, 57066),
    (2, 0, 1, 0, 53322), (2, -1, 0, 0, 45758), (0, 1, -1, 0, -40923), (1, 0, 0, 0, -34720),
    (0, 1, 1, 0, -30383), (2, 0, 0, -2, 15327), (0, 0, 1, 2, -12528), (0, 0, 1, -2, 10980),
    (4, 0, -1, 0, 10675), (0, 0, 3, 0, 10034), (4, 0, -2, 0, 8548), (2, 1, -1, 0, -7888),
    (2, 1, 0, 0, -6766), (1, 0, -1, 0, -5163), (1, 1, 0, 0, 4987), (2, -1, 1, 0, 4036),
    (2, 0, 2, 0, 3994), (4, 0, 0, 0, 3861), (2, 0, -3, 0, 3665), (0, 1, -2, 0, -2689),
    (2, 0, -1, 2, -2602), (2, -1, -2, 0, 2390), (1, 0, 1, 0, -2348),
]


def moon_longitude(jd: float) -> float:
    """Apparent geocentric ecliptic longitude of the moon, degrees (Meeus ch. 47, 31 terms + additive terms)."""
    t = (jd + DELTA_T - 2451545.0) / 36525
    lp = 218.3164477 + 481267.88123421 * t - 0.0015786 * t * t
    d = (297.8501921 + 445267.1114034 * t - 0.0018819 * t * t) * RAD
    m = (357.5291092 + 35999.0502909 * t - 0.0001536 * t * t) * RAD
    mp = (134.9633964 + 477198.8675055 * t + 0.0087414 * t * t) * RAD
    f = (93.2720950 + 483202.0175233 * t - 0.0036539 * t * t) * RAD
    e = 1 - 0.002516 * t - 0.0000074 * t * t
    s = 0.0
    for cd, cm, cmp, cf, coef in _MOON:
        s += coef * (e ** abs(cm)) * math.sin(cd * d + cm * m + cmp * mp + cf * f)
    a1 = (119.75 + 131.849 * t) * RAD
    a2 = (53.09 + 479264.290 * t) * RAD
    s += 3958 * math.sin(a1) + 1962 * math.sin(lp * RAD - f) + 318 * math.sin(a2)
    omega = (125.04452 - 1934.136261 * t) * RAD
    nutation = -0.004778 * math.sin(omega)                 # the main term; the sun's longitude carries the same
    return (lp + s / 1e6 + nutation) % 360


def ayanamsa(jd: float) -> float:
    """Lahiri ayanamsa, degrees: 23.853 at J2000, moving with precession (about 50.29 arcsec a year)."""
    return 23.85306 + 1.396971 * (jd - 2451545.0) / 36525


def sidereal_sun(jd: float) -> float:
    return (sun_longitude(jd) - ayanamsa(jd)) % 360


def elongation(jd: float) -> float:
    return (moon_longitude(jd) - sun_longitude(jd)) % 360


def tithi(jd: float) -> int:
    """1-30: 1-15 the bright half (15 = Purnima), 16-30 the dark half (30 = Amavasya)."""
    return int(elongation(jd) // 12) + 1


def _root(fn, a: float, b: float, tol: float = 1e-6) -> float:
    """fn crosses zero upward between a and b (fn in (-180, 180])."""
    fa = fn(a)
    for _ in range(60):
        mid = (a + b) / 2
        fm = fn(mid)
        if (fa < 0) == (fm < 0):
            a, fa = mid, fm
        else:
            b = mid
        if b - a < tol:
            break
    return (a + b) / 2


def _signed(x: float) -> float:
    return (x + 180) % 360 - 180


def new_moons(jd0: float, jd1: float) -> list:
    """Every new moon between two Julian days."""
    out, t = [], jd0
    while t < jd1:
        a, b = _signed(elongation(t)), _signed(elongation(t + 1))
        if a < 0 <= b:
            out.append(_root(lambda x: _signed(elongation(x)), t, t + 1))
        t += 1
    return out


def sun_enters(target_deg: float, jd0: float, jd1: float) -> list:
    """Moments the sidereal sun enters `target_deg` (a sankranti when a multiple of 30)."""
    out, t = [], jd0
    fn = lambda x: _signed(sidereal_sun(x) - target_deg)
    while t < jd1:
        if fn(t) < 0 <= fn(t + 1):
            out.append(_root(fn, t, t + 1))
        t += 1
    return out


# --------------------------------------------------------------------------- the day: sunrise, sunset and the rest
def sun_times(d: date) -> tuple:
    """(sunrise, sunset) of a civil date in Bhubaneswar, as Julian days (UT). The sunrise equation with refraction
    and the sun's radius (-0.833 deg), iterated once on the solar position: about a minute."""
    lw = -LON
    jd = local_jd(d, 12.0)
    for _ in range(2):
        n = round(jd - 2451545.0 - 0.0009 - lw / 360)
        jstar = n + 0.0009 + lw / 360
        m = (357.5291 + 0.98560028 * jstar) % 360
        c = 1.9148 * math.sin(m * RAD) + 0.0200 * math.sin(2 * m * RAD) + 0.0003 * math.sin(3 * m * RAD)
        lam = (m + c + 180 + 102.9372) % 360
        transit = 2451545.0 + jstar + 0.0053 * math.sin(m * RAD) - 0.0069 * math.sin(2 * lam * RAD)
        dec = math.asin(math.sin(lam * RAD) * math.sin(23.44 * RAD))
        cosw = ((math.sin(-0.833 * RAD) - math.sin(LAT * RAD) * math.sin(dec)) / (math.cos(LAT * RAD) * math.cos(dec)))
        w = math.acos(max(-1.0, min(1.0, cosw))) / RAD
        jd = transit
    return transit - w / 360, transit + w / 360


def moment(d: date, when: str) -> float:
    """The moment of a civil date at which tradition reads the tithi for an observance."""
    rise, sset = sun_times(d)
    day = sset - rise
    return {'sunrise': rise + 1 / 1440,                     # a minute after sunrise
            'midday': rise + 0.5 * day,                     # madhyahna
            'afternoon': rise + 0.7 * day,                  # aparahna (Dussehra)
            'pradosh': sset + 1.0 / 24,                     # an hour after sunset (Diwali, Dhanteras, Holika Dahan)
            'moonrise': sset + 2.4 / 24,                    # Karwa Chauth's moonrise, about 20:00 in autumn
            'midnight': local_jd(d, 24.0 - 0.25)}[when]     # nishita, a little before midnight


# --------------------------------------------------------------------------- lunar months
def lunar_months(year: int) -> list:
    """The amanta months that start in or near a Gregorian year: [{name, adhika, start, end}] (Julian days, UT)."""
    jd0 = local_jd(date(year - 1, 11, 1), 0)
    jd1 = local_jd(date(year + 1, 3, 1), 0)
    nms = new_moons(jd0, jd1)
    out = []
    for a, b in zip(nms, nms[1:]):
        rashi_a, rashi_b = int(sidereal_sun(a) // 30), int(sidereal_sun(b) // 30)
        out.append({'name': MONTHS[(rashi_a + 1) % 12], 'adhika': rashi_a == rashi_b, 'start': a, 'end': b})
    return out


def find_tithi_day(months: list, month: str, t: int, when: str, near_year: int) -> date | None:
    """The civil date on which tithi `t` of lunar month `month` (not the adhika one) holds at the moment `when`.
    If it holds on two days the first is taken; if on none (the tithi falls between two such moments), the day
    on which it begins."""
    cands = [m for m in months if m['name'] == month and not m['adhika']]
    cands = [m for m in cands if abs(local_date(m['start']).year - near_year) <= 1]
    best = None
    for m in cands:
        d, last = local_date(m['start']) - timedelta(days=1), local_date(m['end']) + timedelta(days=1)
        hits = []
        while d <= last:
            x = moment(d, when)
            if m['start'] <= x < m['end'] and tithi(x) == t:
                hits.append(d)
            d += timedelta(days=1)
        if hits:
            day = hits[0]
        else:                                               # the day the tithi begins
            lo = m['start'] + (t - 1) * (m['end'] - m['start']) / 30 - 2
            day = None
            x = lo
            while x < m['end']:
                if tithi(x) == t:
                    day = local_date(x)
                    break
                x += 1 / 96
        if day and day.year == near_year:
            best = day if best is None else min(best, day)
    return best


# --------------------------------------------------------------------------- the Islamic calendar (tabular, approximate)
def islamic_to_jd(y: int, m: int, d: int) -> float:
    """Julian day of a tabular (arithmetic) Islamic date. The festival itself waits for the moon to be sighted."""
    return d + math.ceil(29.5 * (m - 1)) + (y - 1) * 354 + (3 + 11 * y) // 30 + 1948439.5 - 1


def islamic_dates(year: int, month: int, day: int) -> list:
    out = []
    for hy in range(int((year - 622) * 33 / 32) - 2, int((year - 622) * 33 / 32) + 3):
        g = local_date(islamic_to_jd(hy, month, day) + 0.5)
        if g.year == year:
            out.append(g)
    return out


# --------------------------------------------------------------------------- the festivals
def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


# each rule says how to find a festival's dates in a year. 'span' gives start and end relative to the main day.
RULES = {
    'ugadi':            {'kind': 'tithi', 'month': 'Chaitra', 'tithi': 1, 'when': 'sunrise'},
    'ram_navami':       {'kind': 'tithi', 'month': 'Chaitra', 'tithi': 9, 'when': 'midday'},
    'rath_yatra':       {'kind': 'tithi', 'month': 'Ashadha', 'tithi': 2, 'when': 'sunrise'},
    'raksha_bandhan':   {'kind': 'tithi', 'month': 'Shravana', 'tithi': 15, 'when': 'sunrise'},
    'janmashtami':      {'kind': 'tithi', 'month': 'Shravana', 'tithi': 23, 'when': 'sunrise'},
    'ganesh_chaturthi': {'kind': 'tithi', 'month': 'Bhadrapada', 'tithi': 4, 'when': 'midday'},
    'navratri':         {'kind': 'tithi', 'month': 'Ashvin', 'tithi': 1, 'when': 'sunrise', 'day_offset': 4,
                         'end': ('Ashvin', 10, 'afternoon', -1)},       # nine nights: they end the day before Vijayadashami
    'durga_puja':       {'kind': 'tithi', 'month': 'Ashvin', 'tithi': 8, 'when': 'sunrise',
                         'end': ('Ashvin', 10, 'sunrise'), 'days': 5},  # five days, Shashthi to Dashami, counted back
    'dussehra':         {'kind': 'tithi', 'month': 'Ashvin', 'tithi': 10, 'when': 'afternoon'},
    'karwa_chauth':     {'kind': 'tithi', 'month': 'Ashvin', 'tithi': 19, 'when': 'moonrise'},
    'diwali':           {'kind': 'tithi', 'month': 'Ashvin', 'tithi': 30, 'when': 'pradosh',
                         'start': ('Ashvin', 28, 'pradosh'), 'end': ('Kartika', 2, 'afternoon')},    # Dhanteras to Bhai Dooj
    'chhath':           {'kind': 'tithi', 'month': 'Kartika', 'tithi': 6, 'when': 'sunrise',
                         'start': ('Kartika', 4, 'sunrise'), 'end': ('Kartika', 7, 'sunrise')},     # Nahay Khay to Usha Arghya
    'kartika_purnima':  {'kind': 'tithi', 'month': 'Kartika', 'tithi': 15, 'when': 'sunrise'},
    'maha_shivratri':   {'kind': 'tithi', 'month': 'Magha', 'tithi': 29, 'when': 'midnight'},
    'holi':             {'kind': 'tithi', 'month': 'Phalguna', 'tithi': 15, 'when': 'pradosh', 'span': (0, 1), 'day_offset': 1},
    'sankranti':        {'kind': 'sankranti', 'deg': 270},
    'raja_parba':       {'kind': 'sankranti', 'deg': 60, 'span': (-1, 1)},
    'eid_ul_fitr':      {'kind': 'islamic', 'month': 10, 'day': 1, 'span': (-1, 0)},
    'eid_ul_adha':      {'kind': 'islamic', 'month': 12, 'day': 10, 'span': (-1, 0)},
    'new_year':         {'kind': 'fixed', 'month': 12, 'day': 31},
    'republic_day':     {'kind': 'fixed', 'month': 1, 'day': 26},
    'valentines':       {'kind': 'fixed', 'month': 2, 'day': 14},
    'womens_day':       {'kind': 'fixed', 'month': 3, 'day': 8},
    'odisha_day':       {'kind': 'fixed', 'month': 4, 'day': 1},
    'mothers_day':      {'kind': 'weekday', 'month': 5, 'weekday': 6, 'n': 2},
    'fathers_day':      {'kind': 'weekday', 'month': 6, 'weekday': 6, 'n': 3},
    'friendship_day':   {'kind': 'weekday', 'month': 8, 'weekday': 6, 'n': 1},
    'independence_day': {'kind': 'fixed', 'month': 8, 'day': 15},
    'teachers_day':     {'kind': 'fixed', 'month': 9, 'day': 5},
    'childrens_day':    {'kind': 'fixed', 'month': 11, 'day': 14},
    'christmas':        {'kind': 'fixed', 'month': 12, 'day': 25, 'span': (-1, 0)},
}


def _near(months: list, rule: tuple, d: date, year: int) -> date | None:
    """A span's first or last day, found by its own tithi within three weeks of the main day."""
    for y in (year, year - 1, year + 1):
        x = find_tithi_day(months, rule[0], rule[1], rule[2], y)
        if x and abs((x - d).days) <= 21:
            return x + timedelta(days=rule[3] if len(rule) > 3 else 0)
    return None


def sankranti_day(deg: float, year: int) -> date:
    """The civil date of a sankranti: the day of the transit if it falls before sunset, else the next day."""
    hits = sun_enters(deg, local_jd(date(year, 1, 1), 0) - 1, local_jd(date(year, 12, 31), 24) + 1)
    hits = [h for h in hits if local_date(h).year == year]
    if not hits:
        return None
    h = hits[0]
    d = local_date(h)
    return d if h < sun_times(d)[1] else d + timedelta(days=1)


def compute(key: str, year: int, months: list | None = None) -> list:
    """[(start, day, end, how)] for a festival in a year (two for an Islamic festival that falls twice in a year)."""
    r = RULES[key]
    lo, hi = r.get('span', (0, 0))
    out = []
    if r['kind'] == 'tithi':
        months = months or lunar_months(year)
        d = find_tithi_day(months, r['month'], r['tithi'], r['when'], year)
        if d:
            main = d + timedelta(days=r.get('day_offset', 0))
            half = 'shukla' if r['tithi'] <= 15 else 'krishna'
            start, end = d + timedelta(days=lo), d + timedelta(days=hi)
            if 'start' in r:                            # the first day by its own tithi (Dhanteras, Nahay Khay, Shashthi)
                start = _near(months, r['start'], d, year) or start
            if 'end' in r:                              # the last day by its own tithi (Bhai Dooj, Usha Arghya, Dashami)
                end = _near(months, r['end'], d, year) or end
            if 'days' in r:                             # a run of consecutive days ending on `end` (Durga Puja)
                start = end - timedelta(days=r['days'] - 1)
            out.append((start, main, end,
                        f"{r['month']} {half} tithi {r['tithi'] if r['tithi'] <= 15 else r['tithi'] - 15} at {r['when']}"))
    elif r['kind'] == 'sankranti':
        d = sankranti_day(r['deg'], year)
        if d:
            out.append((d + timedelta(days=lo), d, d + timedelta(days=hi), f"the sun enters sidereal {r['deg']} deg"))
    elif r['kind'] == 'islamic':
        for d in islamic_dates(year, r['month'], r['day']):
            out.append((d + timedelta(days=lo), d, d + timedelta(days=hi), 'tabular Islamic calendar; set by the moon sighting'))
    elif r['kind'] == 'fixed':
        d = date(year, r['month'], r['day'])
        out.append((d + timedelta(days=lo), d, d + timedelta(days=hi), 'fixed date'))
    elif r['kind'] == 'weekday':
        d = nth_weekday(year, r['month'], r['weekday'], r['n'])
        out.append((d, d, d, f"Sunday number {r['n']} of the month"))
    return out


def year_calendar(year: int) -> dict:
    """Every festival in RULES for one year: {key: [(start, day, end, how)]}."""
    months = lunar_months(year)
    return {k: compute(k, year, months) for k in RULES}


def check() -> list:
    """Each festival of the cited calendar (festive.py) beside its computed date: [(key, cited, computed, diff)]."""
    import re
    from src.seasonal.festive import FESTIVALS
    out = []
    for f in FESTIVALS:
        base = re.sub(r'_20\d\d$', '', f['key'])
        if base not in RULES:
            continue
        cited = date.fromisoformat(f['day'])
        got = [c for c in compute(base, cited.year) if abs((c[1] - cited).days) < 60]
        comp = got[0] if got else None
        out.append((f['key'], cited, None if comp is None else comp[1], None if comp is None else (comp[1] - cited).days,
                    (date.fromisoformat(f['start']), date.fromisoformat(f['end'])), None if comp is None else (comp[0], comp[2])))
    return out


def main():
    ap = argparse.ArgumentParser(description='Compute festival dates.')
    ap.add_argument('year', nargs='?', type=int, default=date.today().year)
    ap.add_argument('--check', action='store_true', help='compare with the cited 2026-27 calendar')
    a = ap.parse_args()
    if a.check:
        rows = check()
        for k, cited, comp, diff, cspan, span in rows:
            same_span = span == cspan
            print(f"{k:<18} cited {cited}  computed {comp}  {'same' if diff == 0 else f'{diff:+d} day'}"
                  + ('' if same_span else f"   span cited {cspan[0]}..{cspan[1]} computed {span[0]}..{span[1]}"))
        print(f"{sum(r[3] == 0 for r in rows)} of {len(rows)} the same day; {sum(r[4] == r[5] for r in rows)} the same span")
        return
    cal = year_calendar(a.year)
    for k, hits in sorted(cal.items(), key=lambda kv: kv[1][0][1] if kv[1] else date.max):
        for s, d, e, how in hits:
            print(f'{k:<18} {d}  ({s} to {e})  {how}')


if __name__ == '__main__':
    main()
