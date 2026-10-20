"""
agent.py — deliverable 13, the provenance-labelled AI analyst. Two engines, one contract.

    offline (default)   deterministic: refusal policy -> REAL snapshot query when the question asks for one ->
                        BM25 retrieval -> extractive claims (the best-matching sentences, each with its label)
    claude              claude-opus-5 runs a manual tool loop over the same four tools (src/analyst/tools.py) and
                        returns a JSON answer constrained by a schema (output_config.format). Needs Anthropic API
                        credentials; without them the offline engine answers and says so.

Both engines return the same answer object and both go through guard.verify(): every claim gets a label, a source
file and a date; a SYNTHETIC source forces a SYNTHETIC label; every number must appear in the evidence the answer
retrieved. Any SYNTHETIC claim adds the SYNTHETIC banner, unprompted.
"""
import json
import re

from src import provenance
from src.analyst import guard
from src.analyst.tools import (PLATFORM_NAMES, REAL_DATE, get_model_metrics, kb, list_models, promo_frontier,
                               query_real_snapshot, real_rows, restock_capacity, run_tool, search_knowledge,
                               simulate_price_move, tool_schemas, explain_listing, price_headroom)

MODEL = 'claude-opus-5'
MAX_TURNS = 10

ANSWER_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['refused', 'refusal_reason', 'answer_summary', 'claims', 'caveats'],
    'properties': {
        'refused': {'type': 'boolean'},
        'refusal_reason': {'type': ['string', 'null']},
        'answer_summary': {'type': 'string'},
        'claims': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'required': ['text', 'provenance', 'source_file', 'source_detail'],
            'properties': {'text': {'type': 'string'},
                           'provenance': {'type': 'string', 'enum': ['REAL', 'SYNTHETIC', 'METHOD', 'EXTERNAL']},
                           'source_file': {'type': 'string'},
                           'source_detail': {'type': 'string'}}}},
        'caveats': {'type': 'array', 'items': {'type': 'string'}},
    },
}


# =========================================================================== shared
def _finish(question, mode, summary, claims, evidence, caveats=(), refused=False, refusal_reason=None, note=None):
    ev_text = '\n'.join(json.dumps(e, default=str) for e in evidence)
    claims = guard.verify(claims, ev_text, kb()) if claims else []
    has_syn = any(c['provenance'] == 'SYNTHETIC' for c in claims)
    has_ext = any(c['provenance'] == 'EXTERNAL' for c in claims)
    # a REAL claim that rests on the store label is marked on the claim itself and announced once (src/provenance.py)
    store_level = provenance.unverified() and any(provenance.is_store_level_claim(c) for c in claims)
    for c in claims:
        if provenance.unverified() and provenance.is_store_level_claim(c):
            c['store_label'] = 'UNVERIFIED'
    return {'question': question, 'mode': mode, 'refused': refused, 'refusal_reason': refusal_reason,
            'answer_summary': summary, 'claims': claims, 'caveats': list(dict.fromkeys(caveats)),
            'banner': guard.SYNTHETIC_BANNER if has_syn else None,
            'external_banner': guard.EXTERNAL_BANNER if has_ext else None,
            'store_label_banner': provenance.BANNER if store_level else None, 'note': note,
            'all_claims_verified': all(c['verified'] for c in claims)}


def _refused(question, mode, ref):
    return _finish(question, mode, f"I can't answer this from the project's data ({ref['topic']}).", [], [],
                   caveats=[ref['reason'], 'The data is supply-side only: prices, stock, ETA, offers. No customers, '
                            'orders, quantities or revenue (CLAUDE.md s.4).'],
                   refused=True, refusal_reason=ref['reason'])


# =========================================================================== offline engine
_MODEL_WORDS = ('model', 'forecast', 'classifier', 'recover', 'simulat', 'accura', 'predict', 'optimi', 'survival',
                'planted', 'generator', 'baseline')
_METRICS = [('out of stock', 'oos_rate'), ('out-of-stock', 'oos_rate'), ('stock-out', 'oos_rate'), ('oos', 'oos_rate'),
            ('availability', 'oos_rate'), ('discount', 'mean_discount_pct'), ('eta', 'median_eta_min'),
            ('delivery time', 'median_eta_min'), ('price', 'median_price'), ('how many listings', 'listings'),
            ('number of listings', 'listings'), ('how many products', 'listings'), ('listings', 'listings')]
_GROUPS = [('subcategor', 'subcategory'), ('categor', 'category'), ('brand', 'brand'), ('store', 'store_id'),
           ('area', 'area'), ('zone', 'area')]


def parse_real_query(question: str):
    q = question.lower()
    real_signal = any(w in q for w in ('real', 'snapshot', '2026-07-10', 'july', 'observed'))
    if not real_signal or any(w in q for w in _MODEL_WORDS):
        return None
    metric = next((m for w, m in _METRICS if re.search(r'\b' + re.escape(w), q)), None)
    if metric is None:
        return None
    grouped = re.search(r'\b(by|per|each|which|across|every)\b', q)
    group_by = next((g for w, g in _GROUPS if w in q), 'none') if grouped else 'none'
    cats = sorted(real_rows().category.unique())
    def _hit(c):
        head = c.split(',')[0].split('&')[0].strip().lower()
        return re.search(r'\b' + re.escape(c.lower()) + r'\b', q) or re.search(r'\b' + re.escape(head) + r'\b', q)
    cat = next((c for c in cats if _hit(c)), None)
    if cat and group_by == 'category':
        group_by = 'none'
    return {'metric': metric, 'group_by': group_by, 'category': cat, 'top_n': 10}


_PHRASE = {'oos_rate': 'the share of listings out of stock', 'median_price': 'the median selling price (Rs)',
           'mean_discount_pct': 'the mean discount (%)', 'median_eta_min': 'the median promised ETA (minutes)',
           'listings': 'the number of listings'}


def _fmt(metric, v):
    return f'{100 * v:.2f}%' if metric == 'oos_rate' else (f'{v:,.0f}' if metric == 'listings' else f'{v:g}')


def claims_from_real(res):
    m = res['metric']
    scope = f" in {res['category_filter']}" if res['category_filter'] else ''
    src = {'source_file': 'data/raw (REAL rows)', 'provenance': 'REAL', 'date': REAL_DATE}
    if res['group_by'] == 'none':
        row = res['rows'][0]
        return [{**src, 'source_detail': f"query_real_snapshot({m})",
                 'text': (f"On the REAL Blinkit snapshot of {REAL_DATE}, {_PHRASE[m]}{scope} is "
                          f"{_fmt(m, row[m])} across {row['listings']:,} listings.")}]
    rows = res['rows'][:6]
    parts = '; '.join(f"{r['group']} {_fmt(m, r[m])} ({r['listings']:,} listings)" for r in rows)
    return [{**src, 'source_detail': f"query_real_snapshot({m}, by {res['group_by']})",
             'text': f"REAL snapshot {REAL_DATE}, {_PHRASE[m]}{scope} by {res['group_by']}, highest first: {parts}."}]


def _best_sentences(text, qtok, n=2, limit=420):
    from src.analyst.kb import tokenize
    parts = [p.strip(' -*|') for p in re.split(r'(?<=[.!?])\s+|\n+', text) if len(p.strip()) > 25]
    idf = kb().idf
    score = [sum(idf.get(t, 0) for t in set(tokenize(p)) & qtok) for p in parts]
    top = sorted(range(len(parts)), key=lambda i: -score[i])[:n]
    # a short sentence usually leans on the one before it ("There is no real Blinkit history."): bring that one along
    picked = []
    for i in top:
        if len(parts[i]) < 60 and i > 0 and (i - 1) not in top and (i - 1) not in picked:
            picked.append(i - 1)
        picked.append(i)
    out = ' '.join(parts[i] for i in picked)
    return out if len(out) <= limit else out[:limit].rsplit(' ', 1)[0] + ' …'


_KEY_TERMS = ('mae', 'skill', 'verdict', 'auc', 'recall', 'precision', 'coverage', 'estimate', 'planted', 'beats',
              'log_loss', 'corrected', 'reduction', 'capture', 'k_hat', 'change_pp', 'min_cut', 'ari', 'rand')


def _leaves(obj, prefix=''):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaves(v, f'{prefix}.{k}' if prefix else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:12]):
            yield from _leaves(v, f'{prefix}[{i}]')
    else:
        yield prefix, obj


def _fmt_leaf(v):
    """Plain notation only: the verifier matches numbers as written, and 1.308e+04 would never match 13081.7."""
    if isinstance(v, float):
        if abs(v) >= 1000:
            return f'{v:,.1f}'
        if abs(v) >= 1:
            return f'{v:.4g}' if 'e' not in f'{v:.4g}' else f'{v:.2f}'
        return f'{v:.4f}'.rstrip('0').rstrip('.') if v != 0 else '0'
    s = str(v)
    return s if len(s) <= 90 else s[:90] + ' …'


def metric_claim(model, key, qtok, n=7):
    """Readable claim from one metrics.json key: the leaves most related to the question, as path = value."""
    from src.analyst.kb import tokenize
    res = get_model_metrics(model, key)
    if 'error' in res:
        return None, res
    obj = json.loads(res['metrics_json'].split(' …(truncated')[0]) if not res['metrics_json'].endswith(
        'ask for one key)') else {}
    leaves = [(p, v) for p, v in _leaves(obj) if v is not None]
    idf = kb().idf

    def score(pv):
        toks = set(tokenize(pv[0].replace('_', ' ').replace('.', ' ')))
        return sum(idf.get(t, 0) for t in toks & qtok) + 2 * any(t in pv[0].lower() for t in _KEY_TERMS)
    top = sorted(leaves, key=lambda pv: -score(pv))[:n]
    top = [pv for pv in leaves if pv in top]                          # keep the file's own order
    text = f"{model} · " + '; '.join(f'{p} = {_fmt_leaf(v)}' for p, v in top)
    return text, res


def _url(text):
    m = re.search(r'https?://[^\s)]+', text)
    return m.group(0).rstrip('.,') if m else ''


def _external_fact(h, limit=480):
    """An EXTERNAL passage's fact paragraph(s): the heading and the text before its 'Source:' block (URL goes to
    source_detail, not the claim text)."""
    body = h['text'].split('Source:')[0]
    body = ' '.join(body.split())
    if len(body) > limit:
        cut = body[:limit].rsplit('. ', 1)[0]
        body = cut + '.' if cut else body[:limit]
    return f"{h['section']}: {body}"


def claims_from_hits(question, hits, max_claims, allowed=('REAL', 'SYNTHETIC', 'METHOD', 'EXTERNAL')):
    """Claims from search hits. Returns (claims, extra_evidence, caveats)."""
    from src.analyst.kb import expand, tokenize
    qtok = set(expand(tokenize(question)))
    qplain = set(tokenize(question))
    claims, seen, extra, caveats = [], set(), [], []
    results = [h for h in hits['results'] if h['provenance'] in allowed]
    # an EXTERNAL fact must share at least two distinct words with the question: one shared name ("Blinkit") is not
    # enough to make a news fact relevant to a question about the project's own data
    results = [h for h in results if h['provenance'] != 'EXTERNAL'
               or len(set(tokenize(h['section'] + ' ' + h['text'])) & qplain) >= 2]

    def heading_boost(h):
        # an EXTERNAL section heading states its fact: a heading that matches the question should lead
        if h['provenance'] != 'EXTERNAL':
            return 1.0
        head = set(tokenize(h['section']))
        shared = len(head & qplain)
        # one shared name ("Blinkit") is not a matching headline; two or more shared words are
        return 1.0 + (shared / max(len(qplain), 1)) if shared >= 2 else 1.0
    results = sorted(results, key=lambda h: -h['score'] * heading_boost(h))
    # and it must be among the strongest matches (within 10% of the best): news context joins an answer about the
    # project only when it is what the question is most about, not because it shares a name or a common word
    if results:
        best = results[0]['score'] * heading_boost(results[0])
        results = [h for h in results if h['provenance'] != 'EXTERNAL' or h['score'] * heading_boost(h) >= 0.9 * best]
    # the model the question is about: most of the metric-hit score
    by_model = {}
    for h in results:
        if h['source_file'].startswith('outputs/models/'):
            m = h['source_file'].split('/')[2]
            by_model[m] = by_model.get(m, 0) + h['score']
    total = sum(h['score'] for h in results) or 1
    lead = max(by_model, key=by_model.get) if by_model else None
    top_is_external = bool(results) and results[0]['provenance'] == 'EXTERNAL'
    if lead and by_model[lead] >= 0.3 * total and not top_is_external:
        full = get_model_metrics(lead)
        extra.append(full)
        met = json.loads(full['metrics_json']) if not full['metrics_json'].endswith('ask for one key)') else {}
        for k in ('verdict', 'headline', 'transferable_method_finding'):
            if isinstance(met.get(k), str):
                claims.append({'text': f"{lead} · {met[k]}", 'provenance': full['provenance'],
                               'source_file': full['source_file'], 'source_detail': k, 'date': full['date']})
                seen.add((full['source_file'], k))
                break
        if isinstance(met.get('claim_limit'), str):
            caveats.append(f"{lead}: {met['claim_limit']}")
    for h in results:
        if len(claims) >= max_claims:
            break
        key = (h['source_file'], h['section'])
        if key in seen:
            continue
        seen.add(key)
        if h['source_file'].startswith('outputs/models/'):
            model = h['source_file'].split('/')[2]
            text, res = metric_claim(model, h['section'], qtok)
            if text is None:
                continue
            extra.append(res)
        elif h['provenance'] == 'EXTERNAL':
            text = _external_fact(h)
        else:
            # a long section is indexed in windows; merge every retrieved window of it so an answer split across two
            # windows is not lost to whichever window happened to rank first
            sib = sorted((x for x in results if x['source_file'] == h['source_file'] and x['section'] == h['section']),
                         key=lambda x: int(x['id'].rsplit('#', 1)[1]) if x['id'].rsplit('#', 1)[-1].isdigit() else 0)
            text = _best_sentences('\n\n'.join(x['text'] for x in sib), qtok, n=3)
            # an informative heading often IS the answer ("The 2,923 duplicates are NOT duplicates")
            if len(h['section'].split()) >= 3 and not h['section'].lower().startswith(('deliverable', 'what this')):
                text = f"{h['section']}: {text}"
        detail = h['section'] + (' (historical doc)' if h['historical_doc'] else '')
        if h['provenance'] == 'EXTERNAL':
            detail += f" · {_url(h['text'])}"                            # every EXTERNAL claim carries its URL
        claims.append({'text': text, 'provenance': h['provenance'], 'source_file': h['source_file'],
                       'source_detail': detail, 'date': h['date']})
    return claims, extra, caveats


# --------------------------------------------------------------------------- experiments (offline routing)
_PLATFORM_WORDS = [('instamart', 'Swiggy Instamart'), ('swiggy', 'Swiggy Instamart'), ('flipkart', 'Flipkart Minutes'),
                   ('bigbasket', 'BigBasket'), ('big basket', 'BigBasket'), ('blinkit', 'Blinkit')]
_CUT = re.compile(r'\b(cut|cuts|cutting|drop|drops|lower|lowers|lowering|reduce|reduces|reducing|discount|discounts)\b'
                  r'[^0-9]{0,60}?(\d+(?:\.\d+)?)\s*(%|percent|per cent)')
_RAISE = re.compile(r'\b(raise|raises|raising|increase|increases|increasing|hike|hikes|hiking|put up|puts up|lift|lifts)'
                    r'\b[^0-9]{0,60}?(\d+(?:\.\d+)?)\s*(%|percent|per cent)')
_HEADROOM = re.compile(r'\bheadroom\b|how (much|far) (can|could) \w+( \w+)? (raise|increase|put up)|'
                       r'(raise|increase|hike)\w* .{0,40}\bwithout (losing|giving up|hurting)')
_STATIC = re.compile(r"\b(static|frozen|don'?t react|do not react|no (competitor )?(reaction|response)|nobody reacts|"
                     r"without (a |the )?(competitor )?(reaction|response))\b")


def _experiment_category(q):
    """The grid category a question names. Matched on stemmed words too, so "snack" finds Snacks & Munchies (an exact
    regex on "snacks" missed the singular and sent a held-out promo question to plain retrieval)."""
    from src.analyst.kb import tokenize
    from src.simulate.grid import load_grid
    qt = set(tokenize(q))
    for g in load_grid()['groups']:
        if g == 'All':
            continue
        head = g.split(',')[0].split('&')[0].strip().lower()
        ht = set(tokenize(head))
        if (re.search(r'\b' + re.escape(g.lower()) + r'\b', q) or re.search(r'\b' + re.escape(head) + r'\b', q)
                or (ht and ht <= qt)):
            return g
    return None


def parse_experiment(question: str):
    """(tool, args) when the question asks for a what-if the simulator or optimiser can run, else None."""
    q = question.lower()
    # one listing, end to end: "explain this listing", "why is <product> risky at BBSR-003"
    store_m = re.search(r'\b(?:blk-)?bbsr-?(\d{3})\b|\bstore\s*(\d{3})\b', q)
    if re.search(r'\bexplain\b.*\b(listing|product)\b|\bthis listing\b', q) or (
            store_m and re.search(r'\b(why|risky|risk|explain|what should|recommend)\b', q)):
        store = next((g for g in (store_m.groups() if store_m else ()) if g), None)
        product = re.sub(r'\b(explain|this|the|listing|product|why|is|risky|risk|at|in|store|what|should|blinkit|'
                         r'do|about|recommend|for|price|bbsr|blk)\b|[-?.,0-9]', ' ', q)
        product = ' '.join(product.split()) or None
        return 'explain_listing', {'product': product, 'store': store}
    if _HEADROOM.search(q):
        return 'price_headroom', {'category': _experiment_category(q) or 'All'}
    mover = next((name for w, name in _PLATFORM_WORDS if w in q), None)
    r = _RAISE.search(q)
    if r and mover:
        return 'simulate_price_move', {'mover': mover, 'cut_pct': float(r.group(2)), 'direction': 'raise',
                                       'category': _experiment_category(q), 'competitors_react': not _STATIC.search(q)}
    m = _CUT.search(q)
    # "smallest / minimum cut needed to ..." is an optimisation question (deliverable 12a), not a what-if
    asks_for_cut = re.search(r'\b(smallest|minimum|least|how (deep|big|large))\b.{0,40}\bcut', q)
    if m and mover and not asks_for_cut and not re.search(r'\b(promo|promotion)\b.*\b(stock|availability)\b', q):
        return 'simulate_price_move', {'mover': mover, 'cut_pct': float(m.group(2)), 'direction': 'cut',
                                       'category': _experiment_category(q), 'competitors_react': not _STATIC.search(q)}
    if re.search(r'\bsubstitut', q) or (
            re.search(r'\b(goes|go|went|is|are|were|become|becomes|ran|runs?)\s+(out of stock|unavailable)\b|\boutage\b|'
                      r'\bunavailab', q)
            and not re.search(r'\b(real|snapshot)\b', q)):
        plat = next((name for w, name in _PLATFORM_WORDS if w in q), 'Blinkit')
        return 'outage_impact', {'platform': plat, 'category': _experiment_category(q) if plat == 'Blinkit' else None}
    if re.search(r'\b(add|adds|adding|added)\b', q) and re.search(r'\b(gap|gaps|products?|missing|assortment)\b', q) \
            and not re.search(r'\bcapacity\b', q):
        sm = re.search(r'bbsr-?(\d{3})|store\s*(\d{3})', q)
        store = next((g for g in (sm.groups() if sm else ()) if g), None)
        nm = re.search(r'\b(10|25|50)\b', q)
        return 'store_adds', {'store': store, 'n': int(nm.group(1)) if nm else 50}
    if re.search(r'\b(promo|promotion|promotions|discount)', q) and re.search(r'\b(stock|availability|available)', q):
        cat = _experiment_category(q)
        if cat:
            return 'promo_frontier', {'category': cat}
    if re.search(r'\bcapacity\b', q) and re.search(r'restock|stock-out|out of stock|expedite', q):
        return 'restock_capacity', {}
    if re.search(r'\b(oracle|clairvoyant|optimal|optimality)\b', q) and 'restock' in q:
        return 'restock_capacity', {}
    if 'restock' in q and re.search(r'\b(win|wins|cheapest|objective|weight|weighted|weighting|pareto|trade-?off|'
                                    r'position|positions)\b', q):
        return 'restock_objective', {}
    return None


def claims_from_listing(r):
    """Stage 7 of the chain: the same stage-ordered explanation the chain stores, rebuilt from stages 1-6."""
    if r.get('error'):
        return []
    from src.chain.listing import explain
    return explain(r, r['source_file'])

def _pct(v):
    return f'{100 * v:.1f}%'


def claims_from_store_adds(res):
    """Two provenances in one answer: the REAL assortment part and the SYNTHETIC position / operations parts."""
    R, S, n = res['real'], res['synthetic'], res['n']
    real = {'provenance': 'REAL', 'source_file': R['source_file'], 'date': R['date']}
    syn = {'provenance': 'SYNTHETIC', 'source_file': S['source_file']}
    if 'store_id' not in res:
        return [{**real, 'source_detail': 'all stores, top 50 gaps',
                 'text': (f"REAL ({R['date']} snapshot): if each Blinkit store added its top 50 assortment gaps, "
                          f"{R['stores_moving_closer_to_peer_mix_at_50']} of {R['stores']} stores would move closer to "
                          f"their peers' category mix; the median distance goes from "
                          f"{R['median_tv_distance_before_at_50']:.4f} to {R['median_tv_distance_after_at_50']:.4f}. The "
                          f"gaps are product-level recommendations, not a category rebalancing.")},
                {**syn, 'source_detail': 'all stores, top 50 gaps, operations',
                 'text': (f"SYNTHETIC: with today's restock effort held fixed, the existing listings' out-of-stock exposure "
                          f"changes by a median {S['median_existing_oos_change_pct_fixed_capacity']:+.2f}% across stores; "
                          f"with restock capacity scaled to the larger assortment, by "
                          f"{S['median_existing_oos_change_pct_scaled_capacity']:+.2f}%. Blinkit is cheapest-of-4 on the "
                          f"added products in {100 * S['median_blinkit_share_additions']:.1f}% of snapshots against "
                          f"{100 * S['median_blinkit_share_current']:.1f}% on current ones (medians).")}]
    closer = R['tv_distance_to_peer_mix_after'] < R['tv_distance_to_peer_mix_before']
    P, O = S['position'], S['operations']
    out = [{**real, 'source_detail': f"{res['store_id']}, top {n} gaps",
            'text': (f"REAL ({R['date']} snapshot): {res['store_id']} lists {R['products_now']:,} products. Adding its "
                     f"top {n} assortment gaps ({R['added']} new) moves its category mix "
                     f"{'closer to' if closer else 'further from'} its peers' median (distance "
                     f"{R['tv_distance_to_peer_mix_before']:.4f} to {R['tv_distance_to_peer_mix_after']:.4f}); "
                     f"{100 * R['share_of_additions_in_under_represented_categories']:.1f}% of the additions are in "
                     f"categories where it is under-represented. A gap means the product was not seen in the store's "
                     f"listing; it may still be stocked.")}]
    if P.get('blinkit_cheapest_of_4_share_additions') is not None:
        out.append({**syn, 'source_detail': 'price position of the additions',
                    'text': (f"SYNTHETIC: {P['additions_in_four_platform_panel']} of the additions are in the "
                             f"four-platform panel; Blinkit is cheapest-of-4 on them in "
                             f"{100 * P['blinkit_cheapest_of_4_share_additions']:.1f}% of snapshots, against "
                             f"{100 * P['blinkit_cheapest_of_4_share_current']:.1f}% on the store's current panel "
                             f"products" + (" (too few products to read much into)" if
                                            P['additions_in_four_platform_panel'] < 10 else "") + ".")})
    out.append({**syn, 'source_detail': 'restock dilution',
                'text': (f"SYNTHETIC: with restock effort fixed at {O['restock_actions_per_snapshot']} actions per "
                         f"snapshot, the {O['existing_listings']} existing generated listings' out-of-stock exposure "
                         f"changes by {O['existing_oos_change_pct_fixed_capacity']:+.2f}% (90% band "
                         f"{O['dilution_band_90_pct'][0]:+.2f} to {O['dilution_band_90_pct'][1]:+.2f}); with "
                         f"{O['scaled_actions']} actions (capacity scaled to the larger assortment), by "
                         f"{O['existing_oos_change_pct_scaled_capacity']:+.2f}%.")})
    return out


def claims_from_experiment(tool, res):
    if tool == 'store_adds':
        return claims_from_store_adds(res)
    src = {'provenance': 'SYNTHETIC', 'source_file': res['source_file']}
    if tool == 'outage_impact':
        pl = res['platform']
        ch = res['outage_change_pp_p05_median_p95']
        lo, med, hi = ch[pl]['change_pp']
        gains = {q: v['change_pp'][1] for q, v in ch.items() if q != pl}
        top = max(gains, key=gains.get)
        out = [{**src, 'source_detail': f'outage_impact({pl})',
                'text': (f"If {pl} lost every listing of the four-platform panel now (outage lengths drawn from the fitted "
                         f"restock model), its cheapest-available-of-4 share over the next {res['horizon_snapshots']} "
                         f"snapshots would change by {med:+.2f} pp (90% band {lo:+.2f} to {hi:+.2f}), from "
                         f"{100 * res['cheapest_available_now'][pl]:.1f}% now. {top} picks up the most "
                         f"({gains[top]:+.2f} pp).")}]
        if res.get('category_result'):
            c = res['category_result']
            inh = max(c['inherits'], key=c['inherits'].get)
            out.append({**src, 'source_detail': f"category {res['category']}",
                        'text': (f"In {res['category']} ({c['skus']} SKUs), a Blinkit outage changes its cheapest-"
                                 f"available share by {c['blinkit_change_pp']:+.2f} pp (from "
                                 f"{c['blinkit_share_now_pp']:.1f}%); {inh} gains the most ({c['inherits'][inh]:+.2f} pp).")})
        if res.get('blinkit_by_outage_length_pp'):
            L_ = res['blinkit_by_outage_length_pp']
            out.append({**src, 'source_detail': 'Blinkit outage by length',
                        'text': (f"By outage length (snapshots out after now): restored before the next snapshot "
                                 f"{L_['0']:+.2f} pp (it returns with a fresh in-stock clock), 1 {L_['1']:+.2f}, "
                                 f"2 {L_['2']:+.2f}, 4 {L_['4']:+.2f}, 8 {L_['8']:+.2f} pp; the drawn length gives "
                                 f"{L_['drawn_from_restock_model']:+.2f} pp.")})
        sc = res['substitution_check']
        out.append({**src, 'source_detail': 'substitution check on the SYNTHETIC panel',
                    'text': (f"Data check: competitor listings do not run out faster while Blinkit is out (odds ratio "
                             f"{sc['odds_ratio']:.3f}, 95% CI {sc['odds_ratio_ci95_cluster_by_product'][0]:.3f} to "
                             f"{sc['odds_ratio_ci95_cluster_by_product'][1]:.3f}, clustered by product): "
                             f"{sc['verdict']}. Real substitution cannot be measured here, since the data has no orders "
                             f"or shoppers.")})
        return out
    if tool == 'restock_objective':
        r = res
        pol = r['policies']
        plain, full, orc = pol['index_alpha_1'], pol['index_alpha_0'], pol['oracle_win_weighted']
        fr = '; '.join(f"alpha {f['alpha']:g}: {f['J1_reduction_pct']:.1f}% / {f['J2_reduction_pct']:.1f}%"
                       for f in r['frontier_alpha'])
        best = max((f for f in r['frontier_alpha'] if f['alpha'] not in r.get('dominated_alphas', [])),
                   key=lambda f: f['J1_reduction_pct'] + f['J2_reduction_pct'])
        pv = r['paired_vs_plain_index'].get(f"{best['alpha']:g}")
        out = [{**src, 'source_detail': 'restock_objective: plain index',
                'text': (f"Restocking by expected out-of-stock snapshots saved (deliverable 12b's index) cuts stock-out "
                         f"exposure {plain['J1_reduction_pct']:.1f}% and cheapest-available wins lost to stock-outs "
                         f"{plain['J2_reduction_pct']:.1f}% (capacity {100 * r['capacity_share']:g}% of each store per "
                         f"snapshot, {r['horizon']} snapshots).")},
               {**src, 'source_detail': 'frontier over alpha (exposure cut / lost-wins cut)',
                'text': f"Weighting each listing by its chance of being the cheapest traces a trade-off: {fr}."}]
        if pv and best['alpha'] != 1:
            out.append({**src, 'source_detail': f"alpha {best['alpha']:g} vs the plain index, paired",
                        'text': (f"At alpha {best['alpha']:g}, against the plain index: the lost-wins reduction improves by "
                                 f"{pv['J2_gain_pp']:.1f} pp on average ("
                                 + (f"90% CI of the mean {pv['J2_gain_mean_ci90'][0]:.1f} to "
                                    f"{pv['J2_gain_mean_ci90'][1]:.1f}; " if 'J2_gain_mean_ci90' in pv else '')
                                 + f"single 12-snapshot windows range "
                                 f"{pv['J2_gain_band_90'][0]:.1f} to {pv['J2_gain_band_90'][1]:.1f}), for "
                                 f"{pv['J1_cost_pp']:.1f} pp less exposure reduction. The clairvoyant benchmark reaches "
                                 f"{orc['J2_reduction_pct']:.1f}% on lost wins.")})
        return out

    if tool == 'explain_listing':
        return claims_from_listing(res)
    if tool == 'simulate_price_move':
        mv, cat = res['mover'], res['category']
        where = 'across the common panel' if cat == 'All' else f'in {cat} ({res["skus"]} SKUs)'
        lo, med, hi = res['change_pp_p05_median_p95'][mv]
        view = 'with the fitted competitor response' if res['view'] == 'strategic' else 'with competitors frozen'
        other = res['other_view']
        raising = res.get('direction') == 'raise'
        verb = 'raises' if raising else 'cuts'
        c1 = {**src, 'source_detail': f'simulate_price_move({mv}, {verb} {res["cut_pct"]}%, {cat}, {res["view"]})',
              'text': (f'If {mv} {verb} prices {res["cut_pct"]}% {where}, {view}, its cheapest-of-4 share moves from '
                       f'{_pct(res["cheapest_share_before"][mv])} to {_pct(res["cheapest_share_after"][mv])}: '
                       f'{med:+.1f} pp (90% band {lo:+.1f} to {hi:+.1f}) over the next 12 snapshots.')}
        others = '; '.join(f'{p} {_pct(res["cheapest_share_before"][p])} to {_pct(res["cheapest_share_after"][p])}'
                           for p in PLATFORM_NAMES if p != mv)
        c2 = {**src, 'source_detail': 'the other platforms in the same run', 'text': f'The others: {others}.'}
        gap = abs(other['mover_change_pp_median'] - med)
        if gap < 0.5:
            verdict = ("Nobody responds to this platform's move in the fitted dynamics (only Blinkit is followed), so "
                       'both views agree.')
        elif raising:
            verdict = ('Followers follow Blinkit up, so ignoring the response overstates the loss.'
                       if other['view'] == 'static' else 'The fitted response gives part of the loss back.')
        else:
            verdict = ('Ignoring the response overstates the gain.' if other['view'] == 'static'
                       else 'The fitted response takes part of the gain back.')
        c3 = {**src, 'source_detail': f'same scenario, {other["view"]} view',
              'text': (f'The {other["view"]} view of the same {"raise" if raising else "cut"} gives '
                       f'{other["mover_change_pp_median"]:+.1f} pp. {verdict}')}
        return [c1, c2, c3]
    if tool == 'price_headroom':
        r = res
        where = 'across the common panel' if r['category'] == 'All' else f'in {r["category"]}'

        def hr(d):
            return ', '.join(f'{b.replace("pp", " pp")}: {"none" if x == 0 else f"up to {x}%"}' for b, x in d.items())
        c1 = {**src, 'source_detail': f'price_headroom({r["category"]})',
              'text': (f'{where[0].upper() + where[1:]}, Blinkit is cheapest-of-4 on {_pct(r["cheapest_share_now"])} of '
                       f'SKUs now, and even a 1% raise costs {r["loss_pp_at_1pct_strategic"]:+.1f} pp of that share with '
                       f'competitors responding. Largest raise within a loss budget, competitors responding: '
                       f'{hr(r["headroom_pct_strategic"])}; if they did not: {hr(r["headroom_pct_static"])}.')}
        lg = r.get('loss_over_gain_at_5pct')
        c2 = {**src, 'source_detail': 'raise vs cut of the same size',
              'text': (f'A 5% raise costs {r["loss_pp_at_5pct_strategic"]:+.1f} pp with the response '
                       f'({r["loss_pp_at_5pct_static"]:+.1f} pp without); a 5% cut gains '
                       f'{r["gain_pp_cut_5pct_strategic"]:+.1f} pp'
                       + (f', so the loss is {lg:.2f} times the gain.' if lg is not None else '.'))}
        c3 = {**src, 'source_detail': 'raise taken by withdrawing promos',
              'text': (f'Taken by withdrawing promos ({r["blinkit_listings_on_promo"]} of {r["blinkit_listings"]} '
                       f'Blinkit listings have one), a 5% raise changes the stock-out rate by '
                       f'{r["withdraw_oos_change_pp_at_5pct"]:+.2f} pp and ETA by '
                       f'{r["withdraw_eta_change_min_at_5pct"]:+.2f} min; as a list-price raise, neither.')}
        return [c1, c2, c3]
    if tool == 'promo_frontier':
        r = res
        return [{**src, 'source_detail': f'promo_frontier({r["category"]})',
                 'text': (f'In {r["category"]} ({r["blinkit_listings"]} Blinkit listings), a 10% Blinkit price cut adds '
                          f'{r["share_gain_at_10pct_pp"]:.1f} pp of cheapest-of-4 share. Delivered as a promo it also adds '
                          f'{r["oos_added_at_10pct_pp"]:.2f} pp of stock-outs and {r["eta_added_at_10pct_min"]:.2f} min '
                          f'of delivery time; as a list-price cut, neither.')},
                {**src, 'source_detail': 'availability budget',
                 'text': (f'The largest promo that keeps added stock-outs within {r["oos_budget_pp"]:g} pp is '
                          f'{r["largest_promo_within_budget_pct"]}%. Cost: {r["oos_pp_per_share_pp_at_10pct"]:.3f} pp of '
                          f'stock-outs per pp of share at a 10% cut.')}]
    if tool == 'restock_capacity':
        red = res['reduction_pct_by_capacity']
        share = res['index_share_of_oracle_by_capacity']
        topup = res['topup_contribution_pp_by_capacity']
        caps = sorted(red, key=float)
        curve = '; '.join(f'{float(c):g}%: {red[c]["priority_index"]:.1f}%' for c in caps)
        one = next(c for c in caps if abs(float(c) - 1.0) < 1e-9)
        return [{**src, 'source_detail': 'restock_capacity: priority index by capacity',
                 'text': f'Out-of-stock exposure cut by the priority index at each capacity (share of listings per store per snapshot): {curve}.'},
                {**src, 'source_detail': 'restock_capacity: oracle and top-ups at 1% capacity',
                 'text': (f'At 1% capacity the index reaches {100 * share[one]:.1f}% of a clairvoyant benchmark that knows '
                          f'every outage\'s true length; pre-emptive top-ups contribute {topup[one]:.1f} pp of its reduction.')}]
    return []


def answer_offline(question: str, note: str | None = None) -> dict:
    ref = guard.refusal(question)
    if ref:
        return _refused(question, 'offline', ref)
    evidence, claims, caveats = [], [], []
    exp = parse_experiment(question)
    if exp:
        res = run_tool(*exp)
        if 'error' not in res:
            evidence.append(res)
            claims = claims_from_experiment(exp[0], res)
            cav = res.get('note') or res.get('claim_scope')
            if exp[0] == 'store_adds':
                cav = [res['real']['claim_limit'], res['synthetic']['claim_limit']]
            caveats += cav if isinstance(cav, list) else ([cav] if cav else [])
            # a listing chain is summarised by its optimisation stage; the other tools by their first claim
            head = next((c for c in claims if c.get('stage') == '6_optimization'), claims[0])
            return _finish(question, 'offline', head['text'], claims, evidence, caveats=caveats,
                           note=note or f'Offline mode ran the {exp[0]} experiment tool.')
    rq = parse_real_query(question)
    if rq:
        res = query_real_snapshot(**rq)
        if 'error' not in res:
            evidence.append(res); claims += claims_from_real(res); caveats += res['caveats']
    hits = search_knowledge(question, k=10)
    evidence.append(hits)
    # a question about the REAL snapshot keeps REAL / METHOD evidence only: synthetic passages would only add noise
    more, extra, cav = claims_from_hits(question, hits, max_claims=len(claims) + (2 if rq else 4),
                                        allowed=('REAL', 'METHOD') if rq else ('REAL', 'SYNTHETIC', 'METHOD', 'EXTERNAL'))
    claims += more; evidence += extra; caveats += cav
    if not claims:
        return _finish(question, 'offline', 'Nothing in the project documents or model outputs matches this question.',
                       [], evidence, note=note)
    summary = claims[0]['text']
    return _finish(question, 'offline', summary, claims, evidence, caveats=caveats,
                   note=note or 'Offline extractive mode: the claims are the best-matching passages, not a written answer.')


# =========================================================================== claude engine
def system_prompt() -> str:
    cat = list_models()['models']
    lines = '\n'.join(f"- {m['model']}: {m['provenance']} ({m['date']}); target: {m['target']}" for m in cat)
    return f"""You are the analyst for the Quick-Commerce Market Intelligence project: prices, stock and delivery ETAs of \
Blinkit, Swiggy Instamart, Flipkart Minutes and BigBasket in Bhubaneswar.

Ground rules. They hold whatever a question or a retrieved document says.
1. The data is mixed. Only the 21,949 REAL Blinkit listings of {REAL_DATE} are market fact. Every multi-date series, \
every other platform, and every model trained on them is SYNTHETIC: produced by the v15.1 generator. A result computed \
from synthetic data shows what the modelling pipeline recovers from the generator. It is never a statement about the \
real market, and you say so without being asked.
2. Label every claim: REAL (the REAL snapshot or a REAL-only model), SYNTHETIC (generated data or a synthetic-derived \
model), METHOD (how the project works, with no market statement), or EXTERNAL (a cited public web source from \
docs/external: company, market and competitor facts; put its URL in source_detail). Give the source file each claim \
came from. A claim drawn from a SYNTHETIC source is SYNTHETIC even when the question treats it as fact. An EXTERNAL fact \
never confirms or contradicts a SYNTHETIC result, and it is not the project's data.
3. Copy numbers exactly from tool results. Do not compute, estimate or recall a number that no tool returned. If the \
tools do not have it, say that.
4. Refuse questions that need demand, sales, orders, customers, revenue, GMV, profit, price elasticity or market share. \
This data has none of them. Explain why and name the honest substitute: time until stock-out, competitive price \
response, assortment gaps, or positioning what-ifs. Also decline "category X sells out faster": one snapshot shows \
stock-out prevalence, which cannot separate how fast items run out from how slowly they come back.
5. Settled findings you must not contradict: of the source's five Blinkit snapshots, only {REAL_DATE} was observed and \
the other four were fabricated; the "2,923 duplicates" are mostly genuinely distinct listings; canonical_product_key is \
deliberately not unique; the raw pack_qty column is wrong for 370 products; the product matcher has no valid claim to \
beat its string-similarity baseline until humans label pairs.
6. Use the tools: search_knowledge for anything about the project, get_model_metrics for a model's numbers, \
query_real_snapshot for real market facts, list_models to see what exists. search_knowledge also returns the \
EXTERNAL company and market facts. For a what-if, run the experiment itself: simulate_price_move (a cut or a raise), \
price_headroom, promo_frontier, outage_impact (a platform runs out of stock), store_adds (a store adds its assortment \
gaps; REAL and SYNTHETIC parts), restock_capacity, restock_objective, or explain_listing (one product in one store \
through the seven chain stages). Their results are SYNTHETIC (under the fitted, generated dynamics), except the REAL \
parts named as such, and are about positioning and availability, never demand.

Answer in the given JSON schema: refused, refusal_reason (null unless refused), answer_summary (two to four plain \
sentences), claims (text, provenance, source_file, source_detail), caveats.

Saved models (provenance, date, target):
{lines}
"""


NO_CREDENTIALS = 'Could not resolve authentication method'   # the SDK's TypeError when nothing is configured


def answer_claude(question: str, client=None) -> dict:
    """The Claude engine. `client` is injectable (the preflight passes one wired to a local mock of the API).
    Without one, the SDK resolves credentials itself, in its own order: ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, then
    an `ant auth login` profile. So there is no environment-variable gate here: that would wrongly skip a machine that
    is logged in with a profile."""
    ref = guard.refusal(question)
    if ref:
        return _refused(question, MODEL, ref)
    try:
        import anthropic
    except ImportError:
        return answer_offline(question, note='The anthropic package is not installed; answered offline.')
    if client is None:
        try:
            client = anthropic.Anthropic()
        except anthropic.AnthropicError as e:
            return answer_offline(question, note=f'Could not create the Anthropic client ({e}); answered offline.')

    system = [{'type': 'text', 'text': system_prompt(), 'cache_control': {'type': 'ephemeral'}}]
    tools = tool_schemas()
    messages = [{'role': 'user', 'content': question}]
    evidence = []
    for _ in range(MAX_TURNS):
        try:
            # server-side refusal fallback ("default" routes by refusal category); the installed SDK does not type
            # the parameter yet, so it goes in extra_body
            resp = client.beta.messages.create(
                model=MODEL, max_tokens=16000, system=system, tools=tools, messages=messages,
                thinking={'type': 'adaptive'},
                output_config={'effort': 'high', 'format': {'type': 'json_schema', 'schema': ANSWER_SCHEMA}},
                betas=['server-side-fallback-2026-07-01'], extra_body={'fallbacks': 'default'})
        except TypeError as e:
            # the SDK raises a plain TypeError, before sending anything, when no credential source exists; any other
            # TypeError is a bug in this code and must surface, not turn into a quiet offline answer
            if NO_CREDENTIALS not in str(e):
                raise
            return answer_offline(question, note='No Anthropic credentials found (API key, auth token or an '
                                                 '`ant auth login` profile); answered offline.')
        except anthropic.AuthenticationError:
            return answer_offline(question, note='Anthropic credentials were rejected; answered offline.')
        except anthropic.RateLimitError:
            return answer_offline(question, note='Rate limited by the Anthropic API; answered offline.')
        except anthropic.APIStatusError as e:
            return answer_offline(question, note=f'Anthropic API error {e.status_code}; answered offline.')
        except anthropic.APIConnectionError:
            return answer_offline(question, note='Could not reach the Anthropic API; answered offline.')

        if resp.stop_reason == 'refusal':
            cat = getattr(resp.stop_details, 'category', None) if resp.stop_details else None
            return _finish(question, MODEL, 'The model declined this request.', [], evidence, refused=True,
                           refusal_reason=f'model refusal (category: {cat})')
        if resp.stop_reason == 'max_tokens':
            return answer_offline(question, note='The Claude answer hit max_tokens; answered offline.')
        if resp.stop_reason in ('tool_use', 'pause_turn'):
            messages.append({'role': 'assistant', 'content': resp.content})
            if resp.stop_reason == 'pause_turn':
                continue
            results = []
            for block in resp.content:
                if block.type == 'tool_use':
                    out = run_tool(block.name, block.input)
                    evidence.append(out)
                    results.append({'type': 'tool_result', 'tool_use_id': block.id,
                                    'content': json.dumps(out, default=str), 'is_error': 'error' in out})
            messages.append({'role': 'user', 'content': results})
            continue
        text = next((b.text for b in resp.content if b.type == 'text'), '')
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return answer_offline(question, note='The Claude answer was not valid JSON; answered offline.')
        if data.get('refused'):
            return _finish(question, MODEL, data.get('answer_summary', ''), [], evidence, caveats=data.get('caveats', []),
                           refused=True, refusal_reason=data.get('refusal_reason'))
        return _finish(question, MODEL, data.get('answer_summary', ''), data.get('claims', []), evidence,
                       caveats=data.get('caveats', []))
    return answer_offline(question, note=f'No final answer after {MAX_TURNS} tool turns; answered offline.')


def answer(question: str, llm: bool = False) -> dict:
    return answer_claude(question) if llm else answer_offline(question)


# =========================================================================== rendering
def render(a: dict) -> str:
    out = [f"Q: {a['question']}", f"[{a['mode']}]"]
    if a.get('note'):
        out.append(f"note: {a['note']}")
    if a['refused']:
        out.append(f"REFUSED: {a['answer_summary']}")
    else:
        out.append(a['answer_summary'])
    if a.get('banner'):
        out.append(f"\n!! {a['banner']}")
    if a.get('external_banner'):
        out.append(f"\n!! {a['external_banner']}")
    if a.get('store_label_banner'):
        out.append(f"\n!! {a['store_label_banner']}")
    for i, c in enumerate(a['claims'], 1):
        mark = 'verified' if c['verified'] else 'UNVERIFIED: ' + '; '.join(c['issues'])
        stage = f"stage {c['stage'].replace('_', ' ')} · " if c.get('stage') else ''
        label = c['provenance'] + (', STORE LABEL UNVERIFIED' if c.get('store_label') else '')
        out.append(f"\n{i}. {stage}[{label}] {c['text']}\n   source: {c['source_file']} · {c['source_detail']} · "
                   f"{c.get('date', '')} · {mark}")
    for cv in a.get('caveats', []):
        out.append(f"\ncaveat: {cv}")
    return '\n'.join(out)
