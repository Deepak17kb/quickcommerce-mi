"""
assortment_gaps.py — deliverable 10, assortment-gap recommender on the REAL Blinkit carry matrix. REAL.

    python -m src.models.assortment_gaps

WHAT THIS MAY AND MAY NOT CLAIM
  Input: which products each of the 8 REAL Blinkit stores listed on 2026-07-10 (21,949 listings). A "gap" is a
  product similar real stores list that this store's listing did NOT show that day. It is not proof the store
  does not stock it: two stores have ~5,600 listed products and six have ~1,300, which says more about how deeply
  each store was collected than about its range. Nothing here is customer preference or sales uplift, and the 22
  SYNTHETIC stores are never used (their assortment was generated).

EVALUATION — hide and recover
  For each store, 20% of its listed products that at least one other store also lists are hidden. Every method
  ranks all products the (masked) store does not list; a hidden product ranked high is a hit.
  recall@K, NDCG@100, averaged over 3 masks. The learned ranker is trained leave-one-store-out: the store being
  scored never contributes training rows.

METHODS
  popularity        how many other stores list the product
  store_knn         other stores' listings weighted by their Jaccard similarity to this store
  mf_svd            rank-3 truncated SVD of the store x product matrix (implicit matrix factorisation)
  affinity          share of the product's brand / subcategory range that this store lists
  hybrid_ranker     LightGBM on all of the above + price position, leave-one-store-out
"""
import json

import lightgbm as lgb
import numpy as np
import pandas as pd

import src.load as L
from src.model_output import save_model_outputs

NAME = 'assortment_gaps'
SEED = 20260923
HIDE = 0.2
N_MASKS = 3
KS = (20, 50, 100, 250)
TOP_N_OUT = 50
RANK = 3


def carry_matrix(r):
    M = r.groupby(['store_id', 'canonical_product_key']).size().unstack(fill_value=0).gt(0).astype(float)
    return M


def product_meta(r, keys):
    g = r.groupby('canonical_product_key')
    meta = g.agg(product_name=('product_name', 'first'), brand=('brand', 'first'), category=('category', 'first'),
                 subcategory=('subcategory', 'first'), price=('selling_price', 'median')).reindex(keys)
    meta['brand'] = meta.brand.fillna('UNKNOWN').astype(str)
    meta['subcategory'] = meta.subcategory.fillna(meta.category).astype(str)
    lp = np.log(meta.price.astype(float))
    meta['price_z_in_sub'] = (lp - lp.groupby(meta.subcategory).transform('median')) / (
        lp.groupby(meta.subcategory).transform('std').replace(0, np.nan))
    return meta


def features(Mm: np.ndarray, meta: pd.DataFrame, s: int) -> pd.DataFrame:
    """Scores for every product for store s, computed on the masked matrix Mm."""
    n_st = Mm.shape[0]
    others = [i for i in range(n_st) if i != s]
    pop = Mm[others].sum(0)
    inter = Mm[others] @ Mm[s]
    union = Mm[others].sum(1) + Mm[s].sum() - inter
    jac = inter / np.maximum(union, 1)
    knn = (jac[:, None] * Mm[others]).sum(0) / max(jac.sum(), 1e-9)
    U, S, Vt = np.linalg.svd(Mm - Mm.mean(0), full_matrices=False)
    mf = (U[s, :RANK] * S[:RANK]) @ Vt[:RANK] + Mm.mean(0)
    carried = Mm[s] > 0
    b = meta.brand.to_numpy(); sc = meta.subcategory.to_numpy(); ca = meta.category.to_numpy()
    def share(key):
        tot = pd.Series(np.ones(len(key))).groupby(key).transform('sum').to_numpy()
        have = pd.Series(carried.astype(float)).groupby(key).transform('sum').to_numpy()
        return (have - carried) / np.maximum(tot - 1, 1)             # leave the product itself out
    return pd.DataFrame({'popularity': pop, 'store_knn': knn, 'mf_svd': mf,
                         'brand_affinity': share(b), 'subcategory_affinity': share(sc), 'category_affinity': share(ca),
                         'brand_size': pd.Series(b).map(pd.Series(b).value_counts()).to_numpy(),
                         'price_z_in_sub': meta.price_z_in_sub.fillna(0).to_numpy(),
                         'store_size': np.full(len(meta), Mm[s].sum()),
                         'carried': carried.astype(int)})


def ndcg_at(rel_sorted, k=100):
    rel = rel_sorted[:k]
    dcg = (rel / np.log2(np.arange(2, len(rel) + 2))).sum()
    ideal = np.sort(rel_sorted)[::-1][:k]
    idcg = (ideal / np.log2(np.arange(2, len(ideal) + 2))).sum()
    return dcg / idcg if idcg > 0 else 0.0


def evaluate(scores, hidden, cand):
    s = np.where(cand, scores, -np.inf)
    order = np.argsort(-s)
    rel = hidden[order].astype(float)
    out = {f'recall@{k}': rel[:k].sum() / max(hidden.sum(), 1) for k in KS}
    out['ndcg@100'] = ndcg_at(rel)
    return out


def main():
    r = L.real_only(L.load_raw())
    assert r.data_status.eq('REAL').all()
    M = carry_matrix(r)
    stores, keys = M.index.tolist(), M.columns.tolist()
    meta = product_meta(r, keys)
    A = M.to_numpy()
    rng = np.random.default_rng(SEED)
    methods = ['popularity', 'store_knn', 'mf_svd', 'brand_affinity', 'hybrid_ranker']
    FEATS = ['popularity', 'store_knn', 'mf_svd', 'brand_affinity', 'subcategory_affinity', 'category_affinity',
             'brand_size', 'price_z_in_sub', 'store_size']
    rows = []
    for mask_i in range(N_MASKS):
        hidden = np.zeros_like(A, bool)
        for s in range(len(stores)):
            elig = np.flatnonzero((A[s] > 0) & (A.sum(0) >= 2))
            hidden[s, rng.choice(elig, int(HIDE * len(elig)), replace=False)] = True
        Am = np.where(hidden, 0.0, A)
        F = {s: features(Am, meta, s) for s in range(len(stores))}
        for s in range(len(stores)):
            cand = F[s].carried.to_numpy() == 0
            # leave-one-store-out ranker
            tr = pd.concat([F[o][F[o].carried == 0].assign(y=hidden[o][F[o].carried.to_numpy() == 0].astype(int))
                            for o in range(len(stores)) if o != s])
            bst = lgb.train({'objective': 'binary', 'learning_rate': 0.05, 'num_leaves': 31, 'min_data_in_leaf': 50,
                             'verbose': -1, 'seed': SEED}, lgb.Dataset(tr[FEATS], tr.y), 300)
            sc = {m: F[s][m].to_numpy() for m in methods[:-1]}
            sc['hybrid_ranker'] = bst.predict(F[s][FEATS])
            for m in methods:
                rows.append({'mask': mask_i, 'store': stores[s], 'method': m, 'hidden': int(hidden[s].sum()),
                             **evaluate(sc[m], hidden[s], cand)})
        print(f"mask {mask_i + 1}/{N_MASKS} done")
    ev = pd.DataFrame(rows)
    summary = ev.groupby('method')[[f'recall@{k}' for k in KS] + ['ndcg@100']].mean()
    per_store = ev[ev.method == 'hybrid_ranker'].groupby('store')[['recall@100', 'ndcg@100', 'hidden']].mean()
    print(summary.round(4).to_string()); print(per_store.round(3).to_string())

    # ---- final recommendations on the full (unmasked) matrix, ranker trained on all stores' masks
    hidden = np.zeros_like(A, bool)
    for s in range(len(stores)):
        elig = np.flatnonzero((A[s] > 0) & (A.sum(0) >= 2))
        hidden[s, rng.choice(elig, int(HIDE * len(elig)), replace=False)] = True
    Am = np.where(hidden, 0.0, A)
    Fm = {s: features(Am, meta, s) for s in range(len(stores))}
    tr = pd.concat([Fm[o][Fm[o].carried == 0].assign(y=hidden[o][Fm[o].carried.to_numpy() == 0].astype(int))
                    for o in range(len(stores))])
    bst = lgb.train({'objective': 'binary', 'learning_rate': 0.05, 'num_leaves': 31, 'min_data_in_leaf': 50,
                     'verbose': -1, 'seed': SEED}, lgb.Dataset(tr[FEATS], tr.y), 300)
    jac_full = pd.DataFrame([[((A[i] > 0) & (A[j] > 0)).sum() / max(((A[i] > 0) | (A[j] > 0)).sum(), 1)
                              for j in range(len(stores))] for i in range(len(stores))], index=stores, columns=stores)
    recs = []
    for s in range(len(stores)):
        F = features(A, meta, s)
        cand = F.carried.to_numpy() == 0
        score = np.where(cand, bst.predict(F[FEATS]), -np.inf)
        top = np.argsort(-score)[:TOP_N_OUT]
        sims = jac_full.iloc[s].drop(stores[s]).sort_values(ascending=False)
        for rank, i in enumerate(top, 1):
            listed_by = [stores[o] for o in range(len(stores)) if o != s and A[o, i] > 0]
            best = next((st for st in sims.index if st in listed_by), None)
            recs.append({'store_id': stores[s], 'rank': rank, 'canonical_product_key': keys[i],
                         'product_name': meta.product_name.iloc[i], 'brand': meta.brand.iloc[i],
                         'category': meta.category.iloc[i], 'score': float(score[i]),
                         'listed_by_n_other_stores': len(listed_by),
                         'why': (f"listed by {len(listed_by)} of {len(stores) - 1} other REAL stores"
                                 + (f", incl. the most similar listing {best}" if best == sims.index[0] else '')
                                 + f"; this store lists {F.brand_affinity.iloc[i]:.0%} of the {meta.brand.iloc[i]} "
                                   f"range and {F.subcategory_affinity.iloc[i]:.0%} of the subcategory")})
    recs = pd.DataFrame(recs)
    # the contract needs observation_key: attach the REAL listing that made the product visible (any store)
    first_obs = r.groupby('canonical_product_key').observation_key.first()
    recs['observation_key'] = recs.canonical_product_key.map(first_obs)
    recs['data_status'] = 'REAL'
    recs['prediction'] = recs.score
    recs['claim'] = 'not seen in this store\'s REAL 2026-07-10 listing; may be a collection gap, not an assortment gap'

    # does listing similarity follow geography? (REAL coordinates)
    st = pd.read_csv(L.REF / 'STORES.csv')
    st = st[st.store_id.isin(stores)].set_index('store_id').loc[stores]
    lat, lon = np.radians(st.latitude.to_numpy()), np.radians(st.longitude.to_numpy())
    dist = 6371 * np.arccos(np.clip(np.sin(lat[:, None]) * np.sin(lat) + np.cos(lat[:, None]) * np.cos(lat)
                                    * np.cos(lon[:, None] - lon), -1, 1))
    iu = np.triu_indices(len(stores), 1)
    from scipy.stats import spearmanr
    geo = spearmanr(dist[iu], jac_full.to_numpy()[iu])
    metrics = {
        'claim_limit': ('REAL-ONLY. Gaps are products similar REAL stores list that this store\'s 2026-07-10 listing '
                        'did not show. Collection depth differs a lot between stores (1,259 to 5,608 listed products), '
                        'so a gap may be a collection gap. Not customer preference, not sales uplift.'),
        'stores': len(stores), 'products': len(keys),
        'products_by_n_stores': pd.Series(A.sum(0)).value_counts().sort_index().astype(int).to_dict(),
        'evaluation': {'protocol': f'hide {HIDE:.0%} of each store\'s listed products that another store also lists; '
                                   f'{N_MASKS} masks; ranker leave-one-store-out',
                       'mean_by_method': summary.round(5).to_dict(orient='index'),
                       'hybrid_by_store': per_store.round(4).to_dict(orient='index')},
        'hybrid_vs_popularity_recall@100': float(summary.loc['hybrid_ranker', 'recall@100'] / summary.loc['popularity', 'recall@100']),
        'store_similarity_jaccard': jac_full.round(4).to_dict(),
        'similarity_vs_distance_spearman': {'rho': float(geo.statistic), 'p': float(geo.pvalue),
                                            'note': 'negative rho = nearer stores list more alike'},
        'feature_gain': dict(zip(FEATS, bst.feature_importance('gain').round(1).tolist())),
    }
    save_model_outputs(NAME, recs, params={'hide': HIDE, 'masks': N_MASKS, 'svd_rank': RANK, 'features': FEATS,
                                           'ranker': 'lightgbm binary, 300 rounds'},
                       metrics=metrics, training_data=r, split={'evaluation': 'hide-and-recover, leave-one-store-out'},
                       target='hidden listed product (implicit feedback)', training_source='data/raw via src.load (REAL rows)',
                       notes='Deliverable 10. REAL ONLY. Store x product carry matrix of the 2026-07-10 snapshot.')
    _figure(summary, jac_full, dist, stores)
    print(json.dumps({k: metrics[k] for k in ('hybrid_vs_popularity_recall@100', 'similarity_vs_distance_spearman')}, indent=1))
    print(recs.groupby('store_id').head(3)[['store_id', 'rank', 'product_name', 'why']].to_string())


def _figure(summary, jac, dist, stores):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from src.model_output import MODELS_DIR
    ink, muted, grid = '#1f2328', '#6e7781', '#d0d7de'
    fig, ax = plt.subplots(1, 2, figsize=(14, 5.2))
    fig.suptitle('Deliverable 10 · assortment gaps  —  REAL Blinkit carry matrix, 2026-07-10 (a gap may be a collection gap)',
                 fontsize=12, color=ink, x=0.01, ha='left')
    a = ax[0]
    for m, col in zip(summary.index, ['#bc4c00', '#0969da', '#6e7781', '#1a7f37', '#8250df']):
        a.plot(KS, [summary.loc[m, f'recall@{k}'] for k in KS], 'o-', color=col, lw=2.2 if m == 'hybrid_ranker' else 1.3,
               label=m)
    a.set_xlabel('K (recommendations per store)'); a.set_ylabel('recall of hidden REAL listings')
    a.set_title('A · hide-and-recover, leave-one-store-out', fontsize=10, loc='left'); a.legend(frameon=False, fontsize=8.5)
    a = ax[1]
    im = a.imshow(jac.to_numpy(), cmap='Blues')
    a.set_xticks(range(len(stores))); a.set_xticklabels([s[-3:] for s in stores])
    a.set_yticks(range(len(stores))); a.set_yticklabels([s[-3:] for s in stores])
    for i in range(len(stores)):
        for j in range(len(stores)):
            if i != j:
                a.text(j, i, f"{jac.iat[i, j]:.2f}\n{dist[i, j]:.1f}km", ha='center', va='center', fontsize=6.5,
                       color='white' if jac.iat[i, j] > jac.to_numpy().max() * 0.6 else ink)
    a.set_title('B · listing similarity (Jaccard) and distance between REAL stores', fontsize=10, loc='left')
    for a_ in ax[:1]:
        a_.spines[['top', 'right']].set_visible(False); a_.grid(color=grid, lw=0.5, alpha=0.6)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    d = MODELS_DIR / NAME / 'figures'; d.mkdir(exist_ok=True)
    fig.savefig(d / 'assortment_gaps.png', dpi=130); plt.close(fig)


if __name__ == '__main__':
    main()
