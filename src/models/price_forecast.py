"""
price_forecast.py — deliverable 2, next-price forecast (`future_price`). SYNTHETIC.

    python -m src.models.price_forecast

WHAT THIS MAY AND MAY NOT CLAIM
  Every row with a `future_price` is SYNTHETIC: the 30-day panel is generated (CLAUDE.md section 2).
  Beating the baselines here shows the MODELLING PIPELINE recovers the v15.1 generator's planted
  price dynamics. It is NOT a statement about how real quick-commerce prices move, and no number
  from this model may be reported as a market finding. `claim_scope` in the manifest says so.

METHOD
  LightGBM on the price CHANGE (future_price - selling_price), not the level. The level is trivially
  predictable from today's price, so a level model spends its capacity relearning the identity
  function; on the delta the baseline is a constant zero and every gain is real signal. The
  prediction is folded back to a price level before scoring, so the MAEs compare to the baselines
  like for like.

  Split: the pipeline's own `split` column via L.splits (train 15 Sep - 4 Oct, val 5 - 8 Oct,
  test 9 - 14 Oct). Never a random split. Features: L.feature_columns, which drops identifiers and
  targets and raises if either slips in. Early stopping on val; test is touched once.

THE BAR (CLAUDE.md section 6)
  Beat BOTH baselines or report the model as useless:
    naive              tomorrow's price = today's price   test MAE 10.56
    price_avg_to_date  the panel's running mean           test MAE 11.41
  Naive is the stronger of the two on v15.1 data. The verdict below is computed, not asserted.
"""
import json

import lightgbm as lgb
import numpy as np
import pandas as pd

import src.load as L
from src.model_output import save_model_outputs

TARGET = 'future_price'
ANCHOR = 'selling_price'              # naive baseline and the delta anchor
PARAMS = {
    'objective': 'l1',                # MAE is the reported metric; optimise it directly
    'learning_rate': 0.05,
    'num_leaves': 127,
    'min_data_in_leaf': 100,
    'feature_fraction': 0.8,
    'bagging_fraction': 0.8,
    'bagging_freq': 1,
    'lambda_l2': 1.0,
    'num_threads': 0,
    'verbose': -1,
    'seed': 20260919,
}
NUM_BOOST_ROUND = 3000
EARLY_STOPPING = 100


def metrics_for(y_true, y_pred) -> dict:
    err = np.asarray(y_true, float) - np.asarray(y_pred, float)
    return {'mae': float(np.abs(err).mean()),
            'rmse': float(np.sqrt((err ** 2).mean())),
            'median_ae': float(np.median(np.abs(err))),
            'bias': float(err.mean()),
            'n': int(len(err))}


def evaluate(df: pd.DataFrame, pred_level: np.ndarray) -> dict:
    """Model against both mandated baselines, on the price LEVEL."""
    y = df[TARGET].to_numpy(float)
    model = metrics_for(y, pred_level)
    naive = metrics_for(y, df[ANCHOR].to_numpy(float))
    avg = metrics_for(y, df.price_avg_to_date.to_numpy(float))
    return {
        'model': model, 'baseline_naive': naive, 'baseline_price_avg_to_date': avg,
        'skill_vs_naive': float(1 - model['mae'] / naive['mae']),
        'skill_vs_price_avg_to_date': float(1 - model['mae'] / avg['mae']),
        'beats_naive': bool(model['mae'] < naive['mae']),
        'beats_price_avg_to_date': bool(model['mae'] < avg['mae']),
    }


def main():
    ml = L.load_ml()
    train, val, test = L.splits(ml, TARGET)
    feats = L.feature_columns(train)          # guard: identifiers and targets are refused

    assert ANCHOR in feats, f"{ANCHOR} must be a feature: it anchors the delta"
    for part, name in ((train, 'train'), (val, 'val'), (test, 'test')):
        assert part.data_status.eq('SYNTHETIC').all(), f"{name} unexpectedly contains REAL rows"

    # ---- fit on the price change, not the level
    dtrain = lgb.Dataset(train[feats], label=train[TARGET] - train[ANCHOR], free_raw_data=False)
    dval = lgb.Dataset(val[feats], label=val[TARGET] - val[ANCHOR], reference=dtrain)
    booster = lgb.train(PARAMS, dtrain, num_boost_round=NUM_BOOST_ROUND, valid_sets=[dval],
                        valid_names=['val'],
                        callbacks=[lgb.early_stopping(EARLY_STOPPING, verbose=False),
                                   lgb.log_evaluation(200)])
    best = booster.best_iteration

    def predict(d):
        return d[ANCHOR].to_numpy(float) + booster.predict(d[feats], num_iteration=best)

    val_pred, test_pred = predict(val), predict(test)
    val_eval, test_eval = evaluate(val, val_pred), evaluate(test, test_pred)

    # ---- where the signal is
    gain = pd.Series(booster.feature_importance('gain'), index=feats).sort_values(ascending=False)
    by_platform = {}
    for p, g in test.assign(_p=test_pred).groupby('platform'):
        e = evaluate(g, g._p.to_numpy())
        by_platform[str(p)] = {'mae': round(e['model']['mae'], 4),
                               'mae_naive': round(e['baseline_naive']['mae'], 4),
                               'skill_vs_naive': round(e['skill_vs_naive'], 4), 'n': e['model']['n']}

    verdict = ('USEFUL: beats both mandated baselines on test.'
               if test_eval['beats_naive'] and test_eval['beats_price_avg_to_date'] else
               'USELESS BY THE PROJECT RULE (CLAUDE.md section 6): it does not beat both baselines. '
               'Report it as such; do not ship it as a working forecaster.')

    metrics = {
        'verdict': verdict,
        'claim_limit': ('SYNTHETIC panel. These numbers show the pipeline recovers the v15.1 '
                        'generator\'s planted price dynamics. They are not market findings and say '
                        'nothing about real price movement.'),
        'test': test_eval, 'val': val_eval,
        'test_by_platform': by_platform,
        'best_iteration': int(best),
        'rows': {'train': len(train), 'val': len(val), 'test': len(test)},
        'n_features': len(feats),
        'top_features_by_gain': {k: float(v) for k, v in gain.head(20).items()},
        'baseline_reference_in_claude_md': {'naive_test_mae': 10.56, 'price_avg_to_date_test_mae': 11.41},
    }

    pred = pd.DataFrame({
        'observation_key': test.observation_key.to_numpy(),
        'data_status': test.data_status.to_numpy(),
        'platform': test.platform.to_numpy(),
        'snapshot_date': test.date.astype(str).to_numpy(),
        'prediction': test_pred,
        'actual_future_price': test[TARGET].to_numpy(float),
        'anchor_selling_price': test[ANCHOR].to_numpy(float),
        'baseline_naive': test[ANCHOR].to_numpy(float),
        'baseline_price_avg_to_date': test.price_avg_to_date.to_numpy(float),
        'abs_error_model': np.abs(test[TARGET].to_numpy(float) - test_pred),
        'abs_error_naive': np.abs(test[TARGET].to_numpy(float) - test[ANCHOR].to_numpy(float)),
    })

    save_model_outputs(
        'price_forecast_lgbm', pred,
        params={**PARAMS, 'num_boost_round': NUM_BOOST_ROUND, 'early_stopping': EARLY_STOPPING,
                'best_iteration': int(best), 'library': f'lightgbm {lgb.__version__}',
                'learns': 'future_price - selling_price (delta), folded back to a level for scoring',
                'feature_selection': 'src.load.feature_columns (schema roles; IDs and targets refused)'},
        metrics=metrics, training_data=train,
        split={'source': "pipeline 'split' column via src.load.splits", 'fit': 'train',
               'early_stopping_on': 'val', 'evaluated_on': 'test',
               'train': '15 Sep - 4 Oct', 'val': '5 - 8 Oct', 'test': '9 - 14 Oct'},
        target=TARGET, feature_columns=feats,
        notes=('Deliverable 2. SYNTHETIC ONLY — every row carrying future_price is generated, so this '
               'demonstrates the pipeline recovers planted dynamics and is not a market finding. '
               'Predicts the price CHANGE and folds it back to a level. Scored against both mandated '
               'baselines (naive, price_avg_to_date) on the untouched test split. holdout_real is '
               'absent by construction: the single REAL snapshot has no next observation, so '
               'future_price is null there (CLAUDE.md section 3.6).'))

    print('\n' + '=' * 70)
    print(f"best iteration {best} of {NUM_BOOST_ROUND}")
    for name, e in (('val', val_eval), ('test', test_eval)):
        print(f"{name:>5}  model MAE {e['model']['mae']:.4f} | naive {e['baseline_naive']['mae']:.4f} "
              f"| avg_to_date {e['baseline_price_avg_to_date']['mae']:.4f} "
              f"| skill vs naive {e['skill_vs_naive']:+.1%}")
    print(verdict)
    print(json.dumps(by_platform, indent=1))
    print('saved outputs/models/price_forecast_lgbm')


if __name__ == '__main__':
    main()
