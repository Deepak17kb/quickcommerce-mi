"""
price_direction.py — deliverable 3, next price move UP / DOWN / FLAT (`future_price_direction`). SYNTHETIC.

    python -m src.features.price_grid         # once
    python -m src.models.price_direction

WHAT THIS MAY AND MAY NOT CLAIM
  Every row with a next observation is SYNTHETIC. Skill here shows the pipeline extracts the v15.1 generator's
  planted mean reversion and leader/follower response through real-style price grids. It says nothing about the
  real up/down behaviour of any platform.

METHOD
  LightGBM multiclass on every allowed feature + category + the price-grid table (src/features/price_grid.py:
  grid step, time stuck at the current price, position on the grid). An ablation drops the grid table.
  Baselines are lookup tables learned on train, so they give calibrated probabilities, not hard guesses:
    prior          P(class)
    persistence    P(class | direction of the last move)
    reversion      P(class | price above / at / below its 7-snapshot mean)
    rule_combo     P(class | last move x reversion x grid coarseness)          <- the bar
  Bar: beat rule_combo on test log loss AND macro-F1.

EXTRAS
  price-drop radar  rank listings by P(DOWN); precision and lift at fixed alert budgets ("wait, it will drop")
  model agreement   the direction implied by deliverable 2's price forecast vs this classifier, on the same rows
"""
import json

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import balanced_accuracy_score, confusion_matrix, f1_score, log_loss

import src.features.price_grid as PG
import src.features.stock_clock as SC
import src.load as L
from src.model_output import MODELS_DIR, save_model_outputs

NAME = 'price_direction'
TARGET = 'future_price_direction'
CLASSES = ['DOWN', 'FLAT', 'UP']
SEED = 20260923
PARAMS = {'objective': 'multiclass', 'num_class': 3, 'learning_rate': 0.05, 'num_leaves': 127,
          'min_data_in_leaf': 200, 'feature_fraction': 0.8, 'bagging_fraction': 0.8, 'bagging_freq': 1,
          'lambda_l2': 2.0, 'verbose': -1, 'seed': SEED}
BUDGETS = (0.05, 0.10, 0.20)


def sign3(x):
    return np.where(x > 1e-9, 'up', np.where(x < -1e-9, 'down', 'same'))


def rule_keys(d):
    last = pd.Series(sign3(d.price_change.fillna(0).to_numpy()), index=d.index)
    rev = pd.Series(sign3((d.selling_price - d.price_7d_avg).fillna(0).to_numpy()), index=d.index)
    coarse = np.where(d.grid_step_pct >= 0.05, 'coarse', 'fine')
    return {'prior': pd.Series('all', index=d.index), 'persistence': last, 'reversion': rev,
            'rule_combo': last + '|' + rev + '|' + coarse}


def fit_table(keys, y):
    t = pd.crosstab(keys, y).reindex(columns=CLASSES, fill_value=0)
    prior = y.value_counts(normalize=True).reindex(CLASSES).to_numpy()
    return (t + 20 * prior).div(t.sum(1) + 20, axis=0)


def table_predict(table, keys, prior):
    p = table.reindex(keys.to_numpy()).to_numpy(copy=True)
    p[np.isnan(p).any(1)] = prior
    return p


def scores(y, P):
    yi = pd.Categorical(y, categories=CLASSES).codes
    pred = P.argmax(1)
    return {'log_loss': float(log_loss(yi, np.clip(P, 1e-7, 1), labels=[0, 1, 2])),
            'macro_f1': float(f1_score(yi, pred, average='macro')),
            'balanced_accuracy': float(balanced_accuracy_score(yi, pred)),
            'accuracy': float((yi == pred).mean()),
            'recall_by_class': dict(zip(CLASSES, (confusion_matrix(yi, pred, labels=[0, 1, 2]).diagonal()
                                                   / np.bincount(yi, minlength=3)).round(4).tolist()))}


def main():
    ml = PG.attach(SC.attach(L.load_ml()))
    ml = ml[ml[TARGET].isin(CLASSES) | ml[TARGET].isna()]
    train, val, test = L.splits(ml, TARGET)
    train, val, test = (x[x[TARGET].isin(CLASSES)] for x in (train, val, test))
    for part in (train, val, test):
        assert part.data_status.eq('SYNTHETIC').all()

    cats = sorted(train.category.unique())
    base = [f for f in L.feature_columns(train) if f not in SC.NEW_COLUMNS + PG.NEW_COLUMNS]
    full = L.check_feature_set(base + SC.NEW_COLUMNS + PG.NEW_COLUMNS + ['category'])
    ablate = L.check_feature_set(base + SC.NEW_COLUMNS + ['category'])
    y = {k: v[TARGET].astype(str) for k, v in (('train', train), ('val', val), ('test', test))}
    yi = {k: pd.Categorical(v, categories=CLASSES).codes for k, v in y.items()}

    def prep(d, feats):
        return d[feats].assign(category=pd.Categorical(d.category, categories=cats))

    boosters = {}
    for tag, feats in (('model', full), ('ablation_no_grid_features', ablate)):
        b = lgb.train(PARAMS, lgb.Dataset(prep(train, feats), yi['train'], categorical_feature=['category']), 3000,
                      valid_sets=[lgb.Dataset(prep(val, feats), yi['val'], categorical_feature=['category'])],
                      callbacks=[lgb.early_stopping(100, verbose=False), lgb.log_evaluation(500)])
        boosters[tag] = (b, feats)

    prior = y['train'].value_counts(normalize=True).reindex(CLASSES).to_numpy()
    k_tr, k_te = rule_keys(train), rule_keys(test)
    probs = {}
    for name in ('prior', 'persistence', 'reversion', 'rule_combo'):
        tab = fit_table(k_tr[name], y['train'])
        probs[name] = table_predict(tab, k_te[name], prior)
    for tag, (b, feats) in boosters.items():
        probs[tag] = b.predict(prep(test, feats), num_iteration=b.best_iteration)
    res = {k: scores(y['test'], v) for k, v in probs.items()}
    bar = res['rule_combo']
    beats = {'log_loss': res['model']['log_loss'] < bar['log_loss'], 'macro_f1': res['model']['macro_f1'] > bar['macro_f1']}
    verdict = ('USEFUL: beats the rule_combo lookup on test log loss and macro-F1.' if all(beats.values())
               else f'NOT USEFUL by the bar: {beats}')

    # ---- price-drop radar
    pdn = probs['model'][:, 0]
    is_down = (y['test'] == 'DOWN').to_numpy()
    radar = []
    for bgt in BUDGETS:
        n = int(len(pdn) * bgt)
        top = np.argsort(-pdn)[:n]
        top_rule = np.argsort(-probs['rule_combo'][:, 0])[:n]
        radar.append({'budget': bgt, 'precision_model': float(is_down[top].mean()),
                      'precision_rule_combo': float(is_down[top_rule].mean()), 'base_rate': float(is_down.mean()),
                      'lift_model': float(is_down[top].mean() / is_down.mean())})

    # ---- agreement with deliverable 2 (price forecast) on the same rows
    agree = None
    try:
        d2 = pd.read_parquet(MODELS_DIR / 'price_forecast_lgbm' / 'predictions.parquet',
                             columns=['observation_key', 'prediction', 'anchor_selling_price'])
        j = test[['observation_key']].reset_index(drop=True).assign(_i=np.arange(len(test))).merge(d2, on='observation_key')
        delta = j.prediction - j.anchor_selling_price
        # deliverable 2 predicts a continuous level; call a move only when it predicts at least half a grid step
        half_step = 0.5 * test.grid_step_to_date.to_numpy()[j._i]
        d2_dir = np.where(delta > half_step, 'UP', np.where(delta < -half_step, 'DOWN', 'FLAT'))
        d3_dir = np.array(CLASSES)[probs['model'][j._i].argmax(1)]
        truth = y['test'].to_numpy()[j._i]
        agree = {'rows': int(len(j)), 'agreement': float((d2_dir == d3_dir).mean()),
                 'deliverable2_direction_accuracy': float((d2_dir == truth).mean()),
                 'deliverable3_accuracy_same_rows': float((d3_dir == truth).mean()),
                 'deliverable2_direction_macro_f1': float(f1_score(truth, d2_dir, average='macro', labels=CLASSES)),
                 'rule': 'deliverable 2 move = predicted change beyond half a grid step'}
    except FileNotFoundError:
        pass

    b, feats = boosters['model']
    gain = pd.Series(b.feature_importance('gain'), index=feats).sort_values(ascending=False)
    grid_gain_share = float(gain[PG.NEW_COLUMNS].sum() / gain.sum())
    move_by_grid = (test.assign(moved=(y['test'] != 'FLAT').to_numpy(),
                                grid=pd.cut(test.grid_step_pct, [0, 0.01, 0.03, 0.06, 0.12, 10]))
                        .groupby('grid', observed=True).moved.mean().round(4))

    metrics = {
        'claim_limit': ('SYNTHETIC panel. Direction skill shows the pipeline extracts planted mean reversion and '
                        'leader/follower response through price grids. Not real up/down behaviour of any platform.'),
        'verdict': verdict, 'test': res, 'beats_bar': beats, 'bar': 'rule_combo',
        'gain_from_grid_features_log_loss': 1 - res['model']['log_loss'] / res['ablation_no_grid_features']['log_loss'],
        'grid_features_share_of_gain': grid_gain_share,
        'move_rate_by_grid_step_pct': {str(k): float(v) for k, v in move_by_grid.items()},
        'price_drop_radar': radar, 'agreement_with_deliverable_2': agree,
        'class_balance_test': y['test'].value_counts(normalize=True).round(4).to_dict(),
        'best_iteration': int(b.best_iteration),
        'top_features_by_gain': {k: float(v) for k, v in gain.head(15).items()},
    }
    out = pd.DataFrame({'observation_key': test.observation_key.to_numpy(), 'data_status': test.data_status.to_numpy(),
                        'platform': test.platform.to_numpy(), 'snapshot_date': test.date.astype(str).to_numpy(),
                        'prediction': np.array(CLASSES)[probs['model'].argmax(1)],
                        'p_down': probs['model'][:, 0], 'p_flat': probs['model'][:, 1], 'p_up': probs['model'][:, 2],
                        'actual_direction': y['test'].to_numpy()})
    mdir = save_model_outputs(
        NAME, out, params={**PARAMS, 'best_iteration': int(b.best_iteration), 'classes': CLASSES,
                           'extra_feature_tables': ['data/ml/stock_clock.parquet', 'data/ml/price_grid.parquet']},
        metrics=metrics, training_data=train,
        split={'source': "pipeline 'split' column via src.load.splits", 'fit': 'train',
               'early_stopping_on': 'val', 'evaluated_on': 'test'},
        target=TARGET, feature_columns=feats,
        notes='Deliverable 3. SYNTHETIC ONLY. Multiclass direction with price-grid features, lookup-table baselines.')
    _figures(mdir, res, radar, move_by_grid, gain)
    print('\n' + '=' * 72)
    for k, v in res.items():
        print(f"{k:>28}  logloss {v['log_loss']:.4f}  macroF1 {v['macro_f1']:.4f}  balAcc {v['balanced_accuracy']:.4f}")
    print(verdict); print(json.dumps(radar, indent=1)); print(json.dumps(agree, indent=1))
    print(move_by_grid.to_string())


def _figures(mdir, res, radar, move_by_grid, gain):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    ink, muted, grid = '#1f2328', '#6e7781', '#d0d7de'
    c_model, c_base = '#0969da', '#bc4c00'
    fig, ax = plt.subplots(1, 3, figsize=(16, 5.2))
    fig.suptitle('Deliverable 3 · price direction (UP / DOWN / FLAT)  —  SYNTHETIC panel: pipeline check, not a market finding',
                 fontsize=12, color=ink, x=0.01, ha='left')
    a = ax[0]
    names = list(res)
    a.barh(names[::-1], [res[k]['macro_f1'] for k in names][::-1],
           color=[c_model if k == 'model' else muted for k in names][::-1])
    for i, k in enumerate(names[::-1]):
        a.text(res[k]['macro_f1'], i, f" {res[k]['macro_f1']:.3f}", va='center', fontsize=8.5)
    a.set_xlabel('test macro-F1'); a.set_title('A · classifier vs calibrated lookup rules', fontsize=10, loc='left')
    a = ax[1]
    x = [str(k) for k in move_by_grid.index]
    a.bar(range(len(x)), move_by_grid.values, color=c_model)
    a.set_xticks(range(len(x))); a.set_xticklabels([s.replace(', ', '–') for s in x], rotation=20, fontsize=8)
    a.set_xlabel('one grid step as a share of price'); a.set_ylabel('share of snapshots where the price moves')
    a.set_title('B · coarse grids make prices sticky', fontsize=10, loc='left')
    a = ax[2]
    b = [r['budget'] for r in radar]
    a.plot(b, [r['precision_model'] for r in radar], 'o-', color=c_model, label='model P(DOWN)')
    a.plot(b, [r['precision_rule_combo'] for r in radar], 's--', color=c_base, label='rule_combo')
    a.axhline(radar[0]['base_rate'], color=grid, ls=':', label='base rate')
    a.set_xlabel('alert budget (share of listings flagged)'); a.set_ylabel('precision: the price did drop')
    a.set_title('C · "wait, it will drop" radar', fontsize=10, loc='left'); a.legend(frameon=False, fontsize=8.5)
    for a in ax:
        a.spines[['top', 'right']].set_visible(False); a.grid(color=grid, lw=0.5, alpha=0.6); a.set_axisbelow(True)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    (mdir / 'figures').mkdir(exist_ok=True)
    fig.savefig(mdir / 'figures' / 'price_direction.png', dpi=130)
    plt.close(fig)


if __name__ == '__main__':
    main()
