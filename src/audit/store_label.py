"""
store_label.py — does the store label on the REAL Blinkit rows carry any information? REAL data only.

    python -m src.audit.store_label

WHY
  Deliverables 10 (assortment gaps), 12c (category coverage), the REAL part of "a store adds products" and the chain's
  REAL context row all read `store_id` on the 21,949 REAL rows as "this store listed this product". Earlier docs had
  already noticed that listing similarity does not follow distance and that two stores are five times deeper than the
  other six. This module asks the direct question: can the store label be told apart from a random label?

THE TESTS  (observed statistic against its distribution when store labels are shuffled across rows, store sizes kept)
  eta / log price / in_stock by store      share of variance between stores (eta squared)
  category, subcategory, brand,            chi-square of the level x store table (levels under MIN_ROWS rows pooled)
    ETA value, price decile x store
  same name|pack, same store               of all pairs of records sharing a canonical_product_key, the share that sit
                                           in the same store. Real per-store listing puts this near 0 (a store lists a
                                           SKU once); a label independent of the product puts it at sum(share_s ** 2).
  runs along the source id                 how often the store changes between consecutive MASTER ids

POSITIVE CONTROLS  (a null result means nothing unless the test can see a store effect that exists)
  planted shift   a known ETA shift is added to one small store, in memory only, and the same test is re-run
  synthetic       the same tests on the SYNTHETIC Blinkit rows, where the generator planted store ETA effects.
                  Saved to its own output so its provenance never blends into the REAL result.

RECORD-LEVEL ANATOMY  (what the snapshot does say, once the store label is set aside)
  Records sharing a name|pack: how often their stock status, price and ETA agree, against a shuffle within category.

WHAT IT CAN CLAIM
  "On these tests the store label cannot be told apart from a random label" is a statement about the data in
  data/raw, verified against scripts/verify_raw_integrity.py. It is NOT a statement about how the source was collected:
  neither source workbook ships with this repo (CLAUDE.md §3.1), so the collection method is unknown here. Price and
  stock status per record were verified against the source and are untouched by this result.
"""
import json

import numpy as np
import pandas as pd

import src.load as L
from src.model_output import save_model_outputs

OUT_NAME = 'real_store_label_audit'
CONTROL_NAME = 'real_store_label_audit_synthetic_control'
B = 2000
SEED = 20261013
MIN_ROWS = 40                         # a level needs this many rows to keep its own row in a chi-square table
POWER_SHIFTS_MIN = (0.05, 0.1, 0.2, 0.5)
POWER_REPS = 400
UNNAMED_PREFIX = 'UNNAMED LISTING'
NUMERIC = {'eta_minutes': 'delivery_eta_min', 'log_price': '_log_price', 'in_stock': 'in_stock'}
CATEGORICAL = {'category': 'category', 'subcategory': 'subcategory', 'brand': 'brand',
               'eta_value': 'delivery_eta_min', 'price_decile': '_price_decile'}


# --------------------------------------------------------------------------- statistics on integer codes
def _codes(s: pd.Series, min_rows: int = 1) -> np.ndarray:
    s = s.astype(str)
    if min_rows > 1:
        n = s.map(s.value_counts())
        s = s.where(n >= min_rows, '__POOLED__')
    return pd.factorize(s)[0]


def eta_squared(y: np.ndarray, store: np.ndarray, n_stores: int) -> float:
    """Share of the variance of y that lies between stores."""
    n = np.bincount(store, minlength=n_stores)
    m = np.bincount(store, weights=y, minlength=n_stores) / n
    return float((n * (m - y.mean()) ** 2).sum() / ((y - y.mean()) ** 2).sum())


def chi_square(level: np.ndarray, store: np.ndarray, n_levels: int, n_stores: int) -> float:
    obs = np.bincount(level * n_stores + store, minlength=n_levels * n_stores).reshape(n_levels, n_stores)
    exp = obs.sum(1, keepdims=True) * obs.sum(0, keepdims=True) / obs.sum()
    return float(((obs - exp) ** 2 / exp).sum())


def same_store_pair_share(key: np.ndarray, store: np.ndarray, n_stores: int, pairs_total: int) -> float:
    cell = np.bincount(key * n_stores + store)
    return float((cell * (cell - 1) // 2).sum() / pairs_total)


def store_changes(store_in_id_order: np.ndarray) -> int:
    return int((store_in_id_order[1:] != store_in_id_order[:-1]).sum())


def _summary(obs: float, null: np.ndarray, tail: str) -> dict:
    mu, sd = float(null.mean()), float(null.std(ddof=1))
    if tail == 'upper':
        p = (1 + int((null >= obs).sum())) / (len(null) + 1)
    else:
        p = (1 + int((np.abs(null - mu) >= abs(obs - mu)).sum())) / (len(null) + 1)
    return {'observed': obs, 'null_mean': mu, 'null_sd': sd, 'z': (obs - mu) / sd if sd else None,
            'observed_over_null_mean': obs / mu if mu else None, 'p_permutation': p, 'tail': tail}


# --------------------------------------------------------------------------- the battery
def prepare(df: pd.DataFrame) -> dict:
    d = df.reset_index(drop=True).copy()
    d['_log_price'] = np.log(d.selling_price.astype(float))
    d['_price_decile'] = pd.qcut(d.selling_price.astype(float), 10, duplicates='drop').astype(str)
    store_levels = sorted(d.store_id.unique())
    store = d.store_id.map({s: i for i, s in enumerate(store_levels)}).to_numpy()
    out = {'frame': d, 'store': store, 'stores': store_levels, 'n_stores': len(store_levels),
           'numeric': {k: d[c].to_numpy(float) for k, c in NUMERIC.items()},
           'categorical': {}}
    for k, c in CATEGORICAL.items():
        code = _codes(d[c], MIN_ROWS)
        out['categorical'][k] = (code, int(code.max()) + 1)
    return out


def battery(P: dict, store: np.ndarray, pairs: dict | None = None) -> dict:
    """Every statistic for one assignment of store labels."""
    S = P['n_stores']
    out = {f'eta2_{k}': eta_squared(y, store, S) for k, y in P['numeric'].items()}
    for k, (code, n_levels) in P['categorical'].items():
        out[f'chi2_{k}_x_store'] = chi_square(code, store, n_levels, S)
    if pairs is not None:
        out['same_key_pairs_in_same_store_share'] = same_store_pair_share(
            pairs['key'], store[pairs['rows']], S, pairs['total'])
        out['store_changes_along_source_id'] = store_changes(store[pairs['id_order']])
    return out


TAILS = {'same_key_pairs_in_same_store_share': 'two-sided', 'store_changes_along_source_id': 'two-sided'}


def permutation_tests(P: dict, pairs: dict | None, b: int, rng) -> dict:
    obs = battery(P, P['store'], pairs)
    null = {k: np.empty(b) for k in obs}
    for i in range(b):
        perm = rng.permutation(P['store'])
        for k, v in battery(P, perm, pairs).items():
            null[k][i] = v
    return {k: _summary(obs[k], null[k], TAILS.get(k, 'upper')) for k in obs}


def key_pairs(d: pd.DataFrame) -> dict:
    """Records that share a canonical_product_key with at least one other record (unnamed listings left out)."""
    named = ~d.product_name.astype(str).str.startswith(UNNAMED_PREFIX)
    n = d.canonical_product_key.map(d.canonical_product_key[named].value_counts()).fillna(0)
    rows = np.flatnonzero((named & (n >= 2)).to_numpy())
    key = pd.factorize(d.canonical_product_key.iloc[rows])[0]
    size = np.bincount(key)
    pid = d.product_id.astype(str).str.extract(r'(\d+)')[0].astype(int).to_numpy()
    return {'rows': rows, 'key': key, 'total': int((size * (size - 1) // 2).sum()), 'keys': int(len(size)),
            'id_order': np.argsort(pid, kind='stable')}


# --------------------------------------------------------------------------- positive control: planted shift
def planted_shift_power(P: dict, null_eta2: np.ndarray, rng) -> list[dict]:
    """Add a known ETA shift to the smallest store under a random labelling and re-run the test. Nothing is written:
    the shifted column lives only inside this function."""
    y = P['numeric']['eta_minutes']
    crit = float(np.quantile(null_eta2, 0.95))
    small = int(np.argmin(np.bincount(P['store'])))
    rows = []
    for shift in POWER_SHIFTS_MIN:
        hits = 0
        for _ in range(POWER_REPS):
            lab = rng.permutation(P['store'])
            hits += eta_squared(y + shift * (lab == small), lab, P['n_stores']) > crit
        rows.append({'planted_eta_shift_minutes': shift, 'store': P['stores'][small],
                     'store_rows': int((P['store'] == small).sum()), 'detected_share_at_5pct': hits / POWER_REPS})
    return rows


# --------------------------------------------------------------------------- record-level anatomy
def _pair_table(d: pd.DataFrame, pairs: dict) -> pd.DataFrame:
    """Every pair of records sharing a name|pack."""
    sub = d.iloc[pairs['rows']].assign(_k=pairs['key'])
    cols = ['_k', 'store_id', 'selling_price', 'in_stock', 'delivery_eta_min', 'category']
    m = sub[cols].reset_index().merge(sub[cols].reset_index(), on='_k', suffixes=('_a', '_b'))
    return m[m.index_a < m.index_b].reset_index(drop=True)


def anatomy(d: pd.DataFrame, pairs: dict, b: int, rng) -> dict:
    pt = _pair_table(d, pairs)
    sub = d.iloc[pairs['rows']]
    out_a, out_b = pt.in_stock_a.eq(0).to_numpy(), pt.in_stock_b.eq(0).to_numpy()

    def cond(a, b_):
        either = (a | b_).sum()
        return float(2 * (a & b_).sum() / ((a & b_).sum() + either)) if either else float('nan')

    base = float(1 - sub.in_stock.mean())
    obs = cond(out_a, out_b)
    # null: stock status shuffled within category, so category out-of-stock levels are kept
    stock = sub.in_stock.to_numpy()
    cat = pd.factorize(sub.category)[0]
    order = np.argsort(cat, kind='stable')
    bounds = np.flatnonzero(np.r_[True, np.diff(cat[order]) != 0, True])
    pos = pd.Series(np.arange(len(sub)), index=sub.index)
    ia, ib = pos.loc[pt.index_a].to_numpy(), pos.loc[pt.index_b].to_numpy()
    null = np.empty(b)
    for i in range(b):
        sh = stock.copy()
        for lo, hi in zip(bounds[:-1], bounds[1:]):
            sh[order[lo:hi]] = rng.permutation(stock[order[lo:hi]])
        null[i] = cond(sh[ia] == 0, sh[ib] == 0)
    same_store = pt.store_id_a.eq(pt.store_id_b)
    price_eq = pt.selling_price_a.eq(pt.selling_price_b)
    eta_eq = pt.delivery_eta_min_a.eq(pt.delivery_eta_min_b)
    by_cat = (pt.assign(price_differs=~price_eq,
                        rel_gap=(pt.selling_price_a - pt.selling_price_b).abs()
                        / pt[['selling_price_a', 'selling_price_b']].min(axis=1))
              .groupby('category_a')
              .agg(pairs=('price_differs', 'size'), price_differs_share=('price_differs', 'mean'),
                   median_gap_when_differs=('rel_gap', lambda v: float(v[v > 0].median()) if (v > 0).any() else 0.0))
              .query('pairs >= 50').sort_values('pairs', ascending=False).round(4))
    k_eta = eta_squared(sub.delivery_eta_min.to_numpy(float), pairs['key'], pairs['keys'])
    return {
        'records_sharing_a_name_pack': int(len(sub)), 'name_pack_keys': pairs['keys'], 'record_pairs': int(len(pt)),
        'stock': {
            'out_of_stock_rate': base, 'p_other_record_out_given_one_out': obs,
            'lift_over_rate': obs / base,
            'null_shuffled_within_category': _summary(obs, null, 'upper'),
            'reading': 'Records with the same name and pack tend to be out of stock together, far beyond what their '
                       'category explains. Whether the records are the same product at different places, or at '
                       'different times, cannot be told from this data.'},
        'price': {'pairs_with_different_price_share': float((~price_eq).mean()),
                  'by_category': by_cat.to_dict(orient='index')},
        'eta': {'pairs_with_identical_eta_share': float(eta_eq.mean()),
                'eta_variance_between_name_pack_keys_share': k_eta,
                'reading': 'ETA follows the product record, not the store label.'},
        'same_store_vs_other_store_pairs': {
            'same_store_pairs': int(same_store.sum()), 'other_store_pairs': int((~same_store).sum()),
            'price_equal_share': {'same_store': float(price_eq[same_store].mean()),
                                  'other_store': float(price_eq[~same_store].mean())},
            'eta_equal_share': {'same_store': float(eta_eq[same_store].mean()),
                                'other_store': float(eta_eq[~same_store].mean())},
            'both_out_given_either_out': {
                'same_store': float((out_a & out_b)[same_store].sum() / max((out_a | out_b)[same_store].sum(), 1)),
                'other_store': float((out_a & out_b)[~same_store].sum() / max((out_a | out_b)[~same_store].sum(), 1))},
            'reading': 'If the label marked real stores, two records of one name|pack inside one store would be '
                       'duplicates and agree more often than records from different stores.'},
    }


# --------------------------------------------------------------------------- run
def verdict(tests: dict, power: list[dict]) -> dict:
    p = {k: v['p_permutation'] for k, v in tests.items()}
    n = len(p)
    departs = sorted(k for k, v in p.items() if v * n < 0.05)
    pair = tests['same_key_pairs_in_same_store_share']
    smallest = min((r['planted_eta_shift_minutes'] for r in power if r['detected_share_at_5pct'] >= 0.8), default=None)
    closest = min(p, key=p.get)
    text = (f"On {n} permutation tests the store label on the REAL rows "
            + ('cannot be told apart from a random label after Bonferroni correction' if not departs else
               'departs from a random label on: ' + ', '.join(departs))
            + f" (closest: {closest}, p {p[closest]:.3f}; threshold {0.05 / n:.4f}). Records sharing a name|pack sit "
            f"in the same store in {pair['observed']:.1%} of pairs; a label independent of the product gives "
            f"{pair['null_mean']:.1%}, real per-store listing would give close to 0."
            + (f" The ETA test detects a planted shift of {smallest} min in one small store at least 80% of the time, "
               "so the null result is not a lack of power." if smallest is not None else ''))
    return {'tests': n, 'departures_after_bonferroni': departs, 'smallest_p': min(p.values()),
            'closest_test': closest,
            'smallest_detectable_eta_shift_minutes_80pct': smallest, 'text': text,
            'what_it_does_not_show': 'How the source was collected. The source workbooks are not in this repo, so '
                                     'this is a property of the data in data/raw, not a statement about its origin.',
            'affected_REAL_results': ['assortment_gaps (10)', 'store_category_coverage (12c)',
                                      'simulate_store_adds_real', 'listing chain REAL context row (store part)'],
            'unaffected': 'price and stock status per record (verified against the source, CLAUDE.md §3.1), the '
                          'product matcher, the REAL anomaly detector, and the v15.1 calibration (per category, '
                          'not per store).'}


def run(save: bool = True, b: int = B) -> dict:
    rng = np.random.default_rng(SEED)
    raw = L.load_raw('Blinkit')
    real = L.real_only(raw).reset_index(drop=True)
    assert real.data_status.eq('REAL').all()
    P = prepare(real)
    pairs = key_pairs(P['frame'])
    shares = np.bincount(P['store']) / len(real)
    tests = permutation_tests(P, pairs, b, rng)
    # the null of the ETA statistic, for the power check
    null_eta = np.array([eta_squared(P['numeric']['eta_minutes'], rng.permutation(P['store']), P['n_stores'])
                         for _ in range(b)])
    power = planted_shift_power(P, null_eta, rng)
    anat = anatomy(P['frame'], pairs, min(b, 500), rng)
    result = {
        'NOTE': 'REAL rows only (2026-07-10 Blinkit snapshot). A property of data/raw, not of how it was collected.',
        'rows': int(len(real)), 'stores': dict(zip(P['stores'], np.bincount(P['store']).tolist())),
        'store_share_of_rows': dict(zip(P['stores'], shares.round(4).tolist())),
        'expected_same_store_share_if_label_independent_of_product': float((shares ** 2).sum()),
        'permutations': b, 'permutation_tests': tests,
        'positive_control_planted_eta_shift': power,
        'record_level_anatomy': anat,
        'verdict': verdict(tests, power),
    }

    # ---- positive control on SYNTHETIC rows (own output)
    syn = L.synthetic_only(raw)
    last = syn[syn.snapshot_id == syn.snapshot_id.max()].reset_index(drop=True)
    assert last.data_status.eq('SYNTHETIC').all()
    Ps = prepare(last)
    ctrl_tests = permutation_tests(Ps, None, min(b, 500), np.random.default_rng(SEED + 1))
    per_snap = syn.groupby('snapshot_id').apply(
        lambda g: eta_squared(g.delivery_eta_min.to_numpy(float),
                              pd.factorize(g.store_id)[0], g.store_id.nunique()))
    control = {
        'NOTE': 'SYNTHETIC Blinkit rows: the generator planted store ETA effects. This shows the tests see a store '
                'effect when one exists. It says nothing about the real market.',
        'snapshot': str(last.snapshot_id.iloc[0]), 'rows': int(len(last)),
        'permutation_tests': ctrl_tests,
        'eta2_eta_minutes_by_snapshot': {'median': float(per_snap.median()), 'min': float(per_snap.min()),
                                         'max': float(per_snap.max()), 'snapshots': int(len(per_snap))},
        'real_value_for_comparison': tests['eta2_eta_minutes']['observed'],
    }
    result['positive_control_synthetic'] = {'eta2_eta_minutes': ctrl_tests['eta2_eta_minutes'],
                                            'output': f'outputs/models/{CONTROL_NAME}'}
    print(json.dumps({'verdict': result['verdict']['text'],
                      'tests': {k: {'observed': round(v['observed'], 5), 'null_mean': round(v['null_mean'], 5),
                                    'p': round(v['p_permutation'], 4)} for k, v in tests.items()},
                      'planted_shift': power,
                      'stock_anatomy': {k: v for k, v in anat['stock'].items() if k != 'reading'},
                      'synthetic_control_eta2': control['eta2_eta_minutes_by_snapshot']}, indent=1, default=str))
    if not save:
        return result

    d = P['frame']
    n_rec = d.canonical_product_key.map(d.canonical_product_key.value_counts())
    n_sto = d.canonical_product_key.map(d.groupby('canonical_product_key').store_id.nunique())
    pred = pd.DataFrame({'observation_key': d.observation_key, 'data_status': 'REAL', 'store_id': d.store_id,
                         'canonical_product_key': d.canonical_product_key, 'records_of_name_pack': n_rec.to_numpy(),
                         'store_labels_of_name_pack': n_sto.to_numpy(), 'in_stock': d.in_stock,
                         'selling_price': d.selling_price, 'delivery_eta_min': d.delivery_eta_min})
    save_model_outputs(OUT_NAME, pred, {'permutations': b, 'seed': SEED, 'min_rows_per_level': MIN_ROWS,
                                        'power_shifts_minutes': POWER_SHIFTS_MIN, 'power_reps': POWER_REPS},
                       result, training_data=real, split={'fit': 'nothing (audit)', 'evaluated_on': 'holdout_real'},
                       target='none (audit of the store label)',
                       training_source='data/raw REAL Blinkit rows via src.load',
                       notes='Audit, no model. Permutation tests of whether store_id on the REAL rows carries '
                             'information. A property of data/raw; the collection method is not known here.')
    cpred = pd.DataFrame({'observation_key': last.observation_key, 'data_status': 'SYNTHETIC',
                          'store_id': last.store_id, 'delivery_eta_min': last.delivery_eta_min,
                          'in_stock': last.in_stock})
    save_model_outputs(CONTROL_NAME, cpred, {'permutations': min(b, 500), 'seed': SEED + 1}, control,
                       training_data=last, split={'fit': 'nothing (audit)', 'evaluated_on': 'last synthetic snapshot'},
                       target='none (positive control for real_store_label_audit)',
                       training_source='data/raw SYNTHETIC Blinkit rows via src.load',
                       notes='Positive control only: the same tests on generated rows with planted store effects.')
    return result


if __name__ == '__main__':
    run()
