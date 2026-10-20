"""
tools.py — the analyst's tools. The offline engine and the Claude tool loop call exactly the same functions, so both
modes see the same evidence and the verifier can check any answer against it.

    search_knowledge      BM25 over docs + model metrics (kb.py), each hit labelled REAL / SYNTHETIC / METHOD
    get_model_metrics     one saved model's metrics (a key or all), with its manifest claim scope and date
    query_real_snapshot   live aggregates over the 21,949 REAL Blinkit rows of 2026-07-10 — the only market facts
    list_models           every saved model with its provenance, date and claim scope
  experiments (SYNTHETIC, under the fitted dynamics; positioning and availability only, never demand):
    simulate_price_move   a platform cuts or raises a category's prices: cheapest-of-4 share before / after, 90% band
    price_headroom        how far Blinkit can raise a category before losing 1 pp of cheapest-of-4 share, and what
                          withdrawing a promo does to stock-outs
    promo_frontier        price position vs availability when a cut is delivered as a promo vs a list-price cut
    restock_capacity      what restock capacity buys, and how close the priority index is to a clairvoyant benchmark
    outage_impact         a platform's listings go out of stock: cheapest-available share lost, who picks it up
    store_adds            a store adds its REAL assortment gaps: REAL mix shift, SYNTHETIC position and restock dilution
    restock_objective     restock by stock-outs saved vs by lost cheapest-available wins: the trade-off frontier
    explain_listing       one product x store through the seven chain stages: observe -> applicability -> prediction
                          record -> price grid -> simulation (baseline check first) -> optimization -> explanation
"""
import json
from functools import lru_cache

import numpy as np
import pandas as pd

import src.load as L
from src.analyst.kb import KB
from src.model_output import MODELS_DIR

REAL_DATE = '2026-07-10'
REAL_METRICS = ('listings', 'oos_rate', 'median_price', 'mean_discount_pct', 'median_eta_min')
REAL_GROUPS = ('none', 'category', 'subcategory', 'brand', 'store_id', 'area')


@lru_cache(maxsize=1)
def kb() -> KB:
    return KB()


@lru_cache(maxsize=1)
def real_rows() -> pd.DataFrame:
    r = L.real_only(L.load_raw())
    assert r.data_status.eq('REAL').all()
    return r


def search_knowledge(query: str, k: int = 6) -> dict:
    hits = kb().search(query, k=max(1, min(int(k or 6), 10)))
    return {'query': query, 'results': [
        {'id': p.pid, 'source_file': p.source_file, 'section': p.section, 'provenance': p.provenance, 'date': p.date,
         'historical_doc': p.historical, 'score': round(s, 2), 'text': p.text[:1800]} for s, p in hits]}


def list_models() -> dict:
    return {'models': [{'model': n, 'provenance': i['provenance'], 'date': i['date'], 'target': i['target'],
                        'claim_scope': i['claim_scope'], 'metrics_file': i['metrics_file']}
                       for n, i in kb().catalog.items()]}


def get_model_metrics(model: str, key: str | None = None) -> dict:
    cat = kb().catalog
    if model not in cat:
        return {'error': f"unknown model {model!r}; known: {sorted(cat)}"}
    met = json.loads((MODELS_DIR / model / 'metrics.json').read_text(encoding='utf-8'))
    if key:
        if key not in met:
            return {'error': f"metrics of {model} have no key {key!r}; keys: {sorted(met)}"}
        met = {key: met[key]}
    txt = json.dumps(met, default=str)
    if len(txt) > 12000:
        txt = txt[:12000] + ' …(truncated; ask for one key)'
    info = cat[model]
    return {'model': model, 'provenance': info['provenance'], 'claim_scope': info['claim_scope'], 'date': info['date'],
            'source_file': info['metrics_file'], 'metrics_json': txt, 'available_keys': sorted(
                json.loads((MODELS_DIR / model / 'metrics.json').read_text(encoding='utf-8')))}


def query_real_snapshot(metric: str, group_by: str = 'none', category: str | None = None, top_n: int = 15) -> dict:
    if metric not in REAL_METRICS:
        return {'error': f'metric must be one of {REAL_METRICS}'}
    if group_by not in REAL_GROUPS:
        return {'error': f'group_by must be one of {REAL_GROUPS}'}
    r = real_rows()
    if category:
        m = r.category.str.lower() == category.lower()
        if not m.any():
            return {'error': f'no REAL rows with category {category!r}; categories: {sorted(r.category.unique())}'}
        r = r[m]
    val = {'listings': ('observation_key', 'size'), 'oos_rate': ('in_stock', lambda s: 1 - s.mean()),
           'median_price': ('selling_price', 'median'), 'mean_discount_pct': ('discount_percent', 'mean'),
           'median_eta_min': ('delivery_eta_min', 'median')}[metric]
    if group_by == 'none':
        col, fn = val
        v = r[col].agg(fn) if not callable(fn) else fn(r[col])
        table = [{'group': 'all', metric: round(float(v), 4), 'listings': int(len(r))}]
    else:
        g = r.groupby(group_by)
        t = g.agg(value=val, listings=('observation_key', 'size')).reset_index()
        t = t[t.listings >= 20].sort_values('value', ascending=False).head(max(1, min(int(top_n or 15), 50)))
        table = [{'group': str(x[group_by]), metric: round(float(x.value), 4), 'listings': int(x.listings)}
                 for _, x in t.iterrows()]
    caveats = ['REAL: one observed Blinkit snapshot, 2026-07-10; no other platform and no history is real.']
    if metric == 'oos_rate':
        caveats.append('A single snapshot gives stock-out PREVALENCE; it cannot separate how fast items sell out '
                       'from how slowly they restock (never "category X sells out faster").')
    if metric == 'mean_discount_pct':
        caveats.append('Absent MRP was set equal to selling price (discount 0) on some REAL rows; see mrp_source.')
    if group_by != 'none':
        caveats.append('Groups with fewer than 20 listings are left out.')
    if group_by in ('store_id', 'area'):
        caveats.append('The store label on the REAL rows cannot be told apart from a random label (ten permutation '
                       'tests, docs/STORE_LABEL_AUDIT_v1.md): differences between stores or areas here are not '
                       'evidence about real stores.')
    return {'provenance': 'REAL', 'date': REAL_DATE, 'source': 'data/raw (data_status == REAL) via src.load',
            'metric': metric, 'group_by': group_by, 'category_filter': category, 'rows': table, 'caveats': caveats}


PLATFORM_NAMES = ['Blinkit', 'Swiggy Instamart', 'Flipkart Minutes', 'BigBasket']
EXPERIMENT_NOTE = ('SYNTHETIC experiment under the fitted, generated dynamics: positioning and availability only. '
                   'Not a market forecast and never demand or revenue.')


def _grid_groups():
    from src.simulate.grid import load_grid
    return load_grid()['groups']


def simulate_price_move(mover: str, cut_pct: int, category: str | None = None, competitors_react: bool = True,
                        direction: str = 'cut') -> dict:
    """cut_pct is the SIZE of the move (1-10); direction says which way ('cut' or 'raise')."""
    from src.simulate.grid import load_grid, lookup
    if mover not in PLATFORM_NAMES:
        return {'error': f'mover must be one of {PLATFORM_NAMES}'}
    group = category or 'All'
    if group not in load_grid()['groups']:
        return {'error': f"category must be one of {load_grid()['groups']}"}
    if direction not in ('cut', 'raise'):
        return {'error': "direction must be 'cut' or 'raise'"}
    cells = {v: lookup(mover, cut_pct, group, v, direction) for v in ('static', 'strategic')}
    if not all(cells.values()):
        return {'error': 'grid cell missing; run python -m src.simulate.grid'}
    view = 'strategic' if competitors_react else 'static'
    c, other = cells[view], cells['static' if competitors_react else 'strategic']
    return {'provenance': 'SYNTHETIC', 'source_file': 'outputs/models/simulate_grid/grid.json',
            'note': EXPERIMENT_NOTE, 'mover': mover, 'direction': direction, 'cut_pct': c['cut_pct'],
            'move_pct': c.get('move_pct', -c['cut_pct']), 'category': group, 'skus': c['skus'],
            'view': view, 'cheapest_share_before': c['base'], 'cheapest_share_after': c['share'],
            'change_pp_p05_median_p95': c['change_pp'],
            'other_view': {'view': other['view'], 'mover_change_pp_median': other['change_pp'][mover][1]},
            'cut_was_rounded_to_whole_percent_1_to_10': c['cut_pct'] != cut_pct,
            'band': '90% band: 5th to 95th percentile over paired simulations', 'horizon_snapshots': 12}


def price_headroom(category: str) -> dict:
    path = MODELS_DIR / 'optimize_price_headroom' / 'metrics.json'
    if not path.exists():
        return {'error': 'run python -m src.optimize.price_headroom'}
    m = json.loads(path.read_text(encoding='utf-8'))
    rows = {r['category']: r for r in m['by_category']}
    rows['All'] = m['panel']
    if category not in rows:
        return {'error': f'category must be one of {sorted(rows)}'}
    return {'provenance': 'SYNTHETIC', 'source_file': 'outputs/models/optimize_price_headroom/metrics.json',
            'note': EXPERIMENT_NOTE + ' Headroom means a raise costs little cheapest-of-4 share, never that it earns more.',
            'loss_budgets_pp': m['loss_budgets_pp'], 'raises_pct_range': [1, 10], 'horizon_snapshots': m['horizon'],
            **rows[category]}


def promo_frontier(category: str) -> dict:
    path = MODELS_DIR / 'optimize_promo_frontier' / 'metrics.json'
    if not path.exists():
        return {'error': 'run python -m src.optimize.promo_frontier'}
    m = json.loads(path.read_text(encoding='utf-8'))
    row = next((r for r in m['by_category'] if r['category'].lower() == (category or '').lower()), None)
    if row is None:
        return {'error': f"category must be one of {[r['category'] for r in m['by_category']]}"}
    return {'provenance': 'SYNTHETIC', 'source_file': 'outputs/models/optimize_promo_frontier/metrics.json',
            'note': EXPERIMENT_NOTE + ' The promo-to-stock-out link is a planted generator assumption.',
            'oos_budget_pp': m['oos_budget_pp'], **row}


def restock_capacity() -> dict:
    path = MODELS_DIR / 'optimize_restock_lab' / 'metrics.json'
    if not path.exists():
        return {'error': 'run python -m src.optimize.restock_lab'}
    m = json.loads(path.read_text(encoding='utf-8'))
    keep = ('reduction_pct_by_capacity', 'index_share_of_oracle_by_capacity', 'oracle_gap_pp_by_capacity',
            'topup_contribution_pp_by_capacity', 'marginal_saved_per_extra_action_priority')
    return {'provenance': 'SYNTHETIC', 'source_file': 'outputs/models/optimize_restock_lab/metrics.json',
            'note': EXPERIMENT_NOTE + ' The oracle knows true outage lengths no operator has.', **{k: m[k] for k in keep}}


def _chain_files():
    d = MODELS_DIR / 'listing_chain' / 'chains'
    return sorted(d.glob('*.json')) if d.exists() else []


def _match_score(text, name):
    """How much of the QUERY the product name covers ("sugar" fully matches "Whole Farm Grocery Sugar (5 kg)"); name
    coverage only breaks ties. Scoring by name coverage alone once sent "sugar" to a sugar-free lassi."""
    from src.analyst.kb import tokenize
    a, b = set(tokenize(text)), set(tokenize(name))
    return len(a & b) / max(len(a), 1) + 0.01 * len(a & b) / max(len(b), 1)


def _compact_rung(r):
    def view(v):
        return {'mean_cheapest_share': round(v['mean_cheapest_share'], 4), 'band_90': [round(x, 4) for x in v['band_90']]}
    return {'kind': r['kind'], 'price': r['price'], 'cut_rs': r['cut_rs'], 'cut_pct': r['cut_pct'],
            'strategic': view(r['strategic']), 'static': view(r['static']),
            'promo': {k: r['promo'][k] for k in ('depth_after', 'extra_p_oos_within_12_pp', 'eta_added_min')}}


def explain_listing(product: str | None = None, store: str | None = None) -> dict:
    """One listing through the seven chain stages: the saved chain for the best-matching product x store (the first
    gallery listing when nothing is named), or a live run when the listing has no saved chain yet (slower).
    Returns stages 1-6 as evidence. Stage 7, the stored explanation, is left out so the verifier checks claims against
    the numbers they were built from, not against themselves."""
    import re
    from src.chain.listing import STAGES, chain_file, find_listing, run_chain
    store_digits = re.search(r'(\d{3})', store or '')
    best, best_score = None, 0.0
    for f in _chain_files():
        rec = json.loads(f.read_text(encoding='utf-8'))
        lst = rec['1_observe']['listing']
        if store_digits and not lst['store_id'].endswith(store_digits.group(1)):
            continue
        sc = _match_score(product or '', lst['product_name']) if product else 0.01
        if sc > best_score:
            best, best_score = (f, rec), sc
    if best is None or (product and best_score < 0.99):              # not every query word found: search all listings
        lst = find_listing(product, store)
        if lst is None:
            return {'error': 'no listing matches: the chain needs a Blinkit product sold on all four platforms with a '
                             'REAL row in the same store'}
        rec = run_chain(lst, verbose=False)
        f = chain_file(rec['1_observe']['listing'])
    else:
        f, rec = best
    out = {k: rec[k] for k in ('claim_scope', 'stages', *STAGES[:6], 'assumptions', 'built')}
    sim = dict(out['5_simulation'])
    sim['ladder'] = [_compact_rung(r) for r in sim['ladder']]
    sim['status_quo'] = {k: sim['status_quo'][k] for k in ('mean_cheapest_share', 'band_90', 'p_cheapest_next')}
    out['5_simulation'] = sim
    out['source_file'] = f'outputs/models/listing_chain/chains/{f.name}'
    return out


def _metrics_of(name):
    p = MODELS_DIR / name / 'metrics.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None


def outage_impact(platform: str = 'Blinkit', category: str | None = None) -> dict:
    """A platform loses its common-panel listings now: cheapest-available-of-4 share lost, who picks it up, what
    restoring stock sooner is worth, and the data check for substitution. SYNTHETIC."""
    m = _metrics_of('simulate_unavailable')
    if m is None:
        return {'error': 'run python -m src.simulate.unavailable'}
    if platform not in PLATFORM_NAMES:
        return {'error': f'platform must be one of {PLATFORM_NAMES}'}
    out = {'provenance': 'SYNTHETIC', 'source_file': 'outputs/models/simulate_unavailable/metrics.json',
           'note': EXPERIMENT_NOTE + ' Cheapest-available = in stock and cheapest of the four.',
           'platform': platform, 'horizon_snapshots': m['horizon'], 'band': 90,
           'cheapest_available_now': m['cheapest_available_now'],
           'outage_change_pp_p05_median_p95': m['who_inherits'][platform],
           'substitution_check': {k: m['substitution_check'][k] for k in
                                  ('odds_ratio', 'odds_ratio_ci95_cluster_by_product', 'p_value_cluster_by_product',
                                   'verdict', 'meaning')}}
    if platform == 'Blinkit':
        out['blinkit_by_outage_length_pp'] = m['blinkit_outage_by_length_pp']
        if category:
            row = m['blinkit_outage_by_category'].get(category)
            if row is None:
                return {'error': f"category must be one of {sorted(m['blinkit_outage_by_category'])}"}
            out['category'] = category
            out['category_result'] = row
    return out


def store_adds(store: str | None = None, n: int = 50) -> dict:
    """A Blinkit store adds its top-n REAL assortment gaps: REAL category-mix shift; SYNTHETIC price position and restock
    dilution. Two outputs, two provenances."""
    r, s = _metrics_of('simulate_store_adds_real'), _metrics_of('simulate_store_adds')
    if r is None or s is None:
        return {'error': 'run python -m src.simulate.store_adds'}
    n = min(r['adds'], key=lambda x: abs(x - int(n or 50)))
    if not store:
        return {'n': n, 'real': {'provenance': 'REAL', 'source_file': 'outputs/models/simulate_store_adds_real/metrics.json',
                                 'date': REAL_DATE, 'claim_limit': r['claim_limit'],
                                 'stores_moving_closer_to_peer_mix_at_50': r['stores_moving_closer_to_peer_mix_at_50'],
                                 'median_tv_distance_before_at_50': r['median_tv_distance_before_at_50'],
                                 'median_tv_distance_after_at_50': r['median_tv_distance_after_at_50'],
                                 'stores': len({x['store_id'] for x in r['by_store']})},
                'synthetic': {'provenance': 'SYNTHETIC', 'source_file': 'outputs/models/simulate_store_adds/metrics.json',
                              'claim_limit': s['claim_limit'], **s['summary_at_50']}}
    import re
    m = re.search(r'(\d{3})', store)
    sid = f'BLK-BBSR-{m.group(1)}' if m else store
    a = next((x for x in r['by_store'] if x['store_id'] == sid and x['n'] == n), None)
    b = next((x for x in s['by_store'] if x['store_id'] == sid and x['n'] == n), None)
    if a is None or b is None:
        return {'error': f"store must be one of {sorted({x['store_id'] for x in r['by_store']})}"}
    return {'n': n, 'store_id': sid,
            'real': {'provenance': 'REAL', 'source_file': 'outputs/models/simulate_store_adds_real/metrics.json',
                     'date': REAL_DATE, 'claim_limit': r['claim_limit'], **a},
            'synthetic': {'provenance': 'SYNTHETIC', 'source_file': 'outputs/models/simulate_store_adds/metrics.json',
                          'claim_limit': s['claim_limit'], 'horizon_snapshots': s['horizon'],
                          'position': b['position'], 'operations': b['operations']}}


def restock_objective() -> dict:
    """Restock ranking by expected stock-outs saved vs by lost cheapest-available wins: the alpha frontier. SYNTHETIC."""
    m = _metrics_of('optimize_restock_objective')
    if m is None:
        return {'error': 'run python -m src.optimize.restock_objective'}
    keep = ('frontier_alpha', 'paired_vs_plain_index', 'dominated_alphas', 'win_weighted_share_of_oracle_J2',
            'lost_wins_with_no_action', 'capacity_share', 'horizon', 'n_sims', 'weights')
    pol = {p['policy']: {k: p[k] for k in ('J1_reduction_pct', 'J2_reduction_pct', 'J3_store_eta_minutes')}
           for p in m['policies']}
    return {'provenance': 'SYNTHETIC', 'source_file': 'outputs/models/optimize_restock_objective/metrics.json',
            'note': EXPERIMENT_NOTE + ' A lost win is a lost cheapest-available position, never a lost sale.',
            'policies': pol, **{k: m[k] for k in keep if k in m}}


TOOL_FUNCS = {'search_knowledge': search_knowledge, 'get_model_metrics': get_model_metrics,
              'query_real_snapshot': query_real_snapshot, 'list_models': list_models,
              'simulate_price_move': simulate_price_move, 'promo_frontier': promo_frontier,
              'price_headroom': price_headroom, 'outage_impact': outage_impact, 'store_adds': store_adds,
              'restock_objective': restock_objective,
              'restock_capacity': restock_capacity, 'explain_listing': explain_listing}


def run_tool(name: str, args: dict) -> dict:
    fn = TOOL_FUNCS.get(name)
    if fn is None:
        return {'error': f'unknown tool {name}'}
    try:
        return fn(**(args or {}))
    except TypeError as e:
        return {'error': f'bad arguments for {name}: {e}'}


def tool_schemas() -> list[dict]:
    """Strict JSON schemas for the Claude tool loop, in a fixed order (keeps the prompt-cache prefix stable)."""
    models = sorted(kb().catalog)
    groups = _grid_groups()
    return [
        {'name': 'search_knowledge', 'strict': True,
         'description': ('Search the project documentation and every saved model\'s metrics (BM25). Each hit carries its '
                         'provenance label (REAL / SYNTHETIC / METHOD), source file and date. Use it first for any '
                         'question about how the project works or what a model found.'),
         'input_schema': {'type': 'object', 'additionalProperties': False, 'required': ['query', 'k'],
                          'properties': {'query': {'type': 'string'},
                                         'k': {'type': 'integer', 'enum': [3, 6, 10]}}}},
        {'name': 'get_model_metrics', 'strict': True,
         'description': ('Read one saved model\'s metrics.json (one key, or all keys when key is null), with its manifest '
                         'claim scope and date. Copy numbers from here; never compute or recall them.'),
         'input_schema': {'type': 'object', 'additionalProperties': False, 'required': ['model', 'key'],
                          'properties': {'model': {'type': 'string', 'enum': models},
                                         'key': {'type': ['string', 'null']}}}},
        {'name': 'query_real_snapshot', 'strict': True,
         'description': ('Aggregate the 21,949 REAL Blinkit listings of 2026-07-10 — the only rows that are market fact. '
                         'Returns a table labelled REAL. There is no real data for other platforms or other dates.'),
         'input_schema': {'type': 'object', 'additionalProperties': False,
                          'required': ['metric', 'group_by', 'category', 'top_n'],
                          'properties': {'metric': {'type': 'string', 'enum': list(REAL_METRICS)},
                                         'group_by': {'type': 'string', 'enum': list(REAL_GROUPS)},
                                         'category': {'type': ['string', 'null']},
                                         'top_n': {'type': 'integer', 'enum': [5, 10, 15, 25, 50]}}}},
        {'name': 'list_models', 'strict': True,
         'description': 'List every saved model with its provenance (REAL / SYNTHETIC), date, target and claim scope.',
         'input_schema': {'type': 'object', 'additionalProperties': False, 'required': [], 'properties': {}}},
        {'name': 'simulate_price_move', 'strict': True,
         'description': ('Run a price what-if on the fitted simulator: one platform cuts or raises prices (1-10%) in '
                         'one category or all ("All"). cut_pct is the size of the move and direction says which way. '
                         'Returns cheapest-of-4 share before and after for all four platforms, with a 90% band, with or '
                         'without the fitted competitor response. SYNTHETIC; positioning only, never demand.'),
         'input_schema': {'type': 'object', 'additionalProperties': False,
                          'required': ['mover', 'cut_pct', 'category', 'competitors_react', 'direction'],
                          'properties': {'mover': {'type': 'string', 'enum': PLATFORM_NAMES},
                                         'cut_pct': {'type': 'integer', 'enum': list(range(1, 11))},
                                         'category': {'type': 'string', 'enum': groups},
                                         'competitors_react': {'type': 'boolean'},
                                         'direction': {'type': 'string', 'enum': ['cut', 'raise']}}}},
        {'name': 'price_headroom', 'strict': True,
         'description': ('For one category (or "All"): the largest Blinkit price raise (1-10%) that costs at most 1, 2 '
                         'or 5 pp of cheapest-of-4 share, with and without the fitted competitor response; how the loss from a '
                         'raise compares with the gain from a cut of the same size; and what taking the raise by '
                         'withdrawing a promo does to stock-outs and ETA. SYNTHETIC; never revenue.'),
         'input_schema': {'type': 'object', 'additionalProperties': False, 'required': ['category'],
                          'properties': {'category': {'type': 'string', 'enum': groups}}}},
        {'name': 'promo_frontier', 'strict': True,
         'description': ('For one category: how much cheapest-of-4 share a Blinkit price cut buys, and what it costs in '
                         'stock-outs and delivery minutes when delivered as a promo rather than a list-price cut. SYNTHETIC.'),
         'input_schema': {'type': 'object', 'additionalProperties': False, 'required': ['category'],
                          'properties': {'category': {'type': 'string', 'enum': [g for g in groups if g != 'All']}}}},
        {'name': 'restock_capacity', 'strict': True,
         'description': ('What restock capacity buys (0.25-4% of each store per snapshot) for each policy, and how close '
                         'the priority index gets to a clairvoyant benchmark. SYNTHETIC.'),
         'input_schema': {'type': 'object', 'additionalProperties': False, 'required': [], 'properties': {}}},
        {'name': 'outage_impact', 'strict': True,
         'description': ('A platform loses every listing of the four-platform panel now (outage lengths drawn from the '
                         'fitted restock model): its cheapest-available-of-4 share over 12 snapshots, which platform picks '
                         'it up, for Blinkit the effect by category and by outage length, and the data check for '
                         'substitution. SYNTHETIC; never lost sales.'),
         'input_schema': {'type': 'object', 'additionalProperties': False, 'required': ['platform', 'category'],
                          'properties': {'platform': {'type': 'string', 'enum': PLATFORM_NAMES},
                                         'category': {'type': ['string', 'null']}}}},
        {'name': 'store_adds', 'strict': True,
         'description': ('A Blinkit store adds its top 10, 25 or 50 REAL assortment gaps. Returns the REAL part (category mix '
                         'vs peers) and the SYNTHETIC parts (price position of the additions; restock dilution with fixed '
                         'or scaled capacity) with separate source files. store null gives the summary over all stores.'),
         'input_schema': {'type': 'object', 'additionalProperties': False, 'required': ['store', 'n'],
                          'properties': {'store': {'type': ['string', 'null']},
                                         'n': {'type': 'integer', 'enum': [10, 25, 50]}}}},
        {'name': 'restock_objective', 'strict': True,
         'description': ('Restock priority judged two ways: out-of-stock listing-snapshots (12b) and cheapest-available wins '
                         'lost to stock-outs. Returns the frontier over the weighting alpha, paired differences against '
                         'the plain index, and the clairvoyant benchmark. SYNTHETIC; a lost win is not a lost sale.'),
         'input_schema': {'type': 'object', 'additionalProperties': False, 'required': [], 'properties': {}}},
        {'name': 'explain_listing', 'strict': True,
         'description': ('One product in one store through seven stages: 1 observe (the generated decision snapshot, '
                         'plus the REAL 2026-07-10 row as context only), 2 applicability (which of models 1-10 apply '
                         'and why), 3 prediction record (each applicable model beside what happened), 4 price grid '
                         '(the rupee prices Blinkit can post), 5 simulation (baseline check first, then every rung '
                         'with and without competitor response), 6 optimization (the smallest cut that makes Blinkit '
                         'cheapest-of-4 in half the next 12 snapshots). Explain in the same stage order. Use for '
                         '"explain this listing" or "why is X risky at store Y".'),
         'input_schema': {'type': 'object', 'additionalProperties': False, 'required': ['product', 'store'],
                          'properties': {'product': {'type': ['string', 'null']}, 'store': {'type': ['string', 'null']}}}},
    ]
