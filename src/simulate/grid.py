"""
grid.py — precomputed what-if grid for the interactive lab and the analyst's simulate tool. SYNTHETIC.

    python -m src.simulate.grid            # -> outputs/models/simulate_grid/ (grid.json + contract files)

Every (mover platform x price move x competitor view) cell is one PriceWorld run. Moves are cuts of 1-10% and, since
the price-increase extension, raises of 1-10%. Products of different categories never
interact in the engine (a follower responds only to the leader's price of the SAME product), so a run that cuts every
category by c gives, for each category, exactly what cutting that category alone by c gives. One run therefore serves
all 13 categories and the panel-wide "All" row at once: 4 movers x 20 moves x 2 views + 1 baseline = 161 runs.

Each cell carries `direction` ('cut' | 'raise'), `cut_pct` (the size of the move, always positive, kept for the cut
readers) and `move_pct` (signed: -5 is a 5% cut, +5 a 5% raise). A cell without `direction` is a cut.

Common random numbers: every run uses the same seed, so a scenario and its baseline share every random draw and the
change bands are paired, not the difference of two independent bands.

Claim scope: positioning under the fitted, generated dynamics (cheapest-of-4 share). Never demand or revenue.
"""
import json
from functools import lru_cache

import numpy as np
import pandas as pd

import src.load as L
from src.model_output import MODELS_DIR, save_model_outputs
from src.simulate.engine import PLATFORMS, PriceWorld

NAME = 'simulate_grid'
CUTS = list(range(1, 11))          # percent
RAISES = list(range(1, 11))        # percent
N_SIMS = 12
HORIZON = 12
SEED = 11
MIN_KEYS = 30


def summarise(res, groups):
    """Per group x platform: mean and 90% band of cheapest share over sims, plus the mean path over the horizon."""
    out = {}
    sk, kt = res['cheapest_by_sim_key'], res['cheapest_by_key_t']
    for g, keys in groups.items():
        per_sim = np.nanmean(sk[:, :, keys], axis=2)                         # (sim, platform)
        path = np.nanmean(kt[:, keys, :], axis=1)                            # (platform, t)
        out[g] = {'per_sim': per_sim, 'path': path}
    return out


def main():
    W = PriceWorld.load()
    cat = W.key_category.to_numpy()
    counts = pd.Series(cat).value_counts()
    cats = sorted(counts[counts >= MIN_KEYS].index)
    groups = {'All': np.arange(W.n_keys), **{c: np.flatnonzero(cat == c) for c in cats}}
    base = summarise(W.simulate({}, horizon=HORIZON, n_sims=N_SIMS, respond=True, seed=SEED), groups)
    cells, rows = [], []
    moves = [('cut', c) for c in CUTS] + [('raise', c) for c in RAISES]
    for mover in PLATFORMS:
        for direction, cut in moves:
            sign = -1 if direction == 'cut' else 1
            for respond in (False, True):
                r = summarise(W.simulate({mover: np.full(W.n_keys, sign * cut / 100)}, horizon=HORIZON, n_sims=N_SIMS,
                                         respond=respond, seed=SEED), groups)
                view = 'strategic' if respond else 'static'
                for g in groups:
                    d = 100 * (r[g]['per_sim'] - base[g]['per_sim'])                # paired change, pp
                    cell = {'mover': mover, 'direction': direction, 'cut_pct': cut, 'move_pct': sign * cut,
                            'view': view, 'group': g, 'skus': int(len(groups[g])),
                            'share': {p: round(float(r[g]['per_sim'][:, j].mean()), 5) for j, p in enumerate(PLATFORMS)},
                            'base': {p: round(float(base[g]['per_sim'][:, j].mean()), 5) for j, p in enumerate(PLATFORMS)},
                            'change_pp': {p: [round(float(np.quantile(d[:, j], q)), 3) for q in (0.05, 0.5, 0.95)]
                                          for j, p in enumerate(PLATFORMS)},
                            'mover_path': [round(float(v), 5) for v in r[g]['path'][PLATFORMS.index(mover)]],
                            'base_path': [round(float(v), 5) for v in base[g]['path'][PLATFORMS.index(mover)]]}
                    cells.append(cell)
                    rows.append({'mover': mover, 'direction': direction, 'cut_pct': cut, 'move_pct': sign * cut,
                                 'view': view, 'group': g,
                                 'mover_share': cell['share'][mover], 'mover_base': cell['base'][mover],
                                 'mover_change_pp': cell['change_pp'][mover][1]})
            print(f'  {mover} {direction} {cut}% done')
    grid = {'claim_limit': ('SYNTHETIC: cheapest-of-4 share under the fitted, generated dynamics. Positioning only; '
                            'never demand, orders or revenue.'),
            'platforms': PLATFORMS, 'cuts_pct': CUTS, 'raises_pct': RAISES, 'groups': list(groups), 'horizon_snapshots': HORIZON,
            'n_sims': N_SIMS, 'cells': cells}
    tab = pd.DataFrame(rows)
    ml = L.load_ml(with_targets=False)[['observation_key', 'data_status', 'platform', 'split']]
    anchors = ml[(ml.data_status == 'SYNTHETIC') & (ml.split == 'test')].groupby('platform').observation_key.first()
    pred = tab.assign(observation_key=tab.mover.map(anchors), data_status='SYNTHETIC', prediction=tab.mover_share)
    ba = tab[(tab.mover == 'Blinkit') & (tab.group == 'All')]
    blk = ba[ba.direction == 'cut'].pivot(index='cut_pct', columns='view', values='mover_change_pp')
    up = ba[ba.direction == 'raise'].pivot(index='cut_pct', columns='view', values='mover_change_pp')
    fol = tab[(tab.mover != 'Blinkit') & (tab.group == 'All') & (tab.direction == 'raise')]
    fol_gap = fol.pivot_table(index=['mover', 'cut_pct'], columns='view', values='mover_change_pp')
    metrics = {'claim_limit': grid['claim_limit'], 'runs': 1 + len(PLATFORMS) * len(moves) * 2, 'cells': len(cells),
               'blinkit_all_change_pp_by_cut': blk.round(3).to_dict(orient='index'),
               'static_over_strategic_median': float((blk['static'] / blk['strategic']).median()),
               'blinkit_all_change_pp_by_raise': up.round(3).to_dict(orient='index'),
               # a raise loses share; followers follow Blinkit up, so the static view overstates the loss
               'raise_static_over_strategic_loss_median': float((up['static'] / up['strategic']).median()),
               # |share lost by raising x%| / share gained by cutting x%, fitted response (1 = symmetric)
               'raise_loss_over_cut_gain_strategic': {int(c): round(float(-up.loc[c, 'strategic'] / blk.loc[c, 'strategic']), 3)
                                                      for c in CUTS if blk.loc[c, 'strategic'] > 0},
               # nobody follows a follower, so for a follower's raise the two views must agree
               'follower_raise_max_view_gap_pp': float((fol_gap['static'] - fol_gap['strategic']).abs().max())}
    mdir = save_model_outputs(NAME, pred, params={'cuts_pct': CUTS, 'n_sims': N_SIMS, 'horizon': HORIZON, 'seed': SEED,
                                                  'engine': 'src/simulate/engine.py PriceWorld'},
                              metrics=metrics, training_data=ml[ml.split == 'train'].assign(snapshot_date=''),
                              split={'uses': 'fitted price_response outputs'}, target='cheapest-of-4 share by scenario',
                              notes='Precomputed what-if grid (deliverable 11 extension). SYNTHETIC ONLY.')
    (mdir / 'grid.json').write_text(json.dumps(grid, separators=(',', ':')), encoding='utf-8')
    print(json.dumps(metrics, indent=1))


@lru_cache(maxsize=1)
def load_grid() -> dict:
    return json.loads((MODELS_DIR / NAME / 'grid.json').read_text(encoding='utf-8'))


def lookup(mover: str, cut_pct: float, group: str = 'All', view: str = 'strategic', direction: str = 'cut') -> dict | None:
    """The grid cell nearest to a requested scenario (the move's size rounded to the nearest whole percent, 1-10)."""
    g = load_grid()
    c = int(min(max(round(cut_pct), CUTS[0]), CUTS[-1]))
    for cell in g['cells']:
        if (cell['mover'] == mover and cell['cut_pct'] == c and cell['group'] == group and cell['view'] == view
                and cell.get('direction', 'cut') == direction):
            return cell
    return None


if __name__ == '__main__':
    main()
