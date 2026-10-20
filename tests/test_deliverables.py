"""Regression guards on the saved results of deliverables 3-12 (fast: they read metrics.json, nothing is refitted).

Each threshold is the claim the deliverable's doc makes. If a rerun drifts past one, either the data changed or the
pipeline broke: find out which before updating the number. Skipped when a model has not been run yet.
"""
import json

import pytest

from src.model_output import MODELS_DIR


def metrics(name):
    p = MODELS_DIR / name / 'metrics.json'
    if not p.exists():
        pytest.skip(f'{name} has not been run')
    return json.loads(p.read_text(encoding='utf-8'))


def manifest(name):
    return json.loads((MODELS_DIR / name / 'manifest.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('name,scope', [
    ('stockout_classifier', 'SYNTHETIC'), ('stockout_survival', 'SYNTHETIC'), ('restock_interval', 'SYNTHETIC'),
    ('price_response', 'SYNTHETIC'), ('eta_forecast', 'SYNTHETIC'), ('price_direction', 'SYNTHETIC'),
    ('anomaly_real', 'REAL'), ('anomaly_temporal', 'SYNTHETIC'), ('assortment_gaps', 'REAL'),
    ('simulate_whatif', 'SYNTHETIC'), ('optimize_price_cut', 'SYNTHETIC'), ('optimize_restock_priority', 'SYNTHETIC'),
    # the extensions (2026-09-24)
    ('simulate_grid', 'SYNTHETIC'), ('optimize_promo_frontier', 'SYNTHETIC'), ('optimize_restock_lab', 'SYNTHETIC'),
    ('listing_chain', 'SYNTHETIC'), ('optimize_price_headroom', 'SYNTHETIC'), ('simulate_unavailable', 'SYNTHETIC'),
    ('simulate_store_adds', 'SYNTHETIC'), ('simulate_store_adds_real', 'REAL'), ('optimize_restock_objective', 'SYNTHETIC'),
    ('product_matcher_ai_proxy_check', 'REAL'), ('product_matcher_behaviour_check', 'SYNTHETIC'),
    # 2026-10-13: matcher v2 (trained partly on constructed rows), the store-label audit and the collection planner
    ('product_matcher_v2', 'SYNTHETIC'), ('product_matcher_v2_behaviour_check', 'SYNTHETIC'),
    ('product_matcher_v2_ai_proxy_check', 'SYNTHETIC'), ('real_store_label_audit', 'REAL'),
    ('real_store_label_audit_synthetic_control', 'SYNTHETIC'), ('collection_planner', 'SYNTHETIC')])
def test_claim_scope_and_frozen_raw(name, scope):
    metrics(name)
    m = manifest(name)
    assert m['claim_scope'].startswith('REAL-ONLY' if scope == 'REAL' else 'SYNTHETIC-DERIVED')
    assert m['raw_hashes_match_verified_baseline'] is True


def test_stockout_classifier_beats_bar():
    assert all(metrics('stockout_classifier')['beats_bar_on_log_loss'].values())


def test_survival_recovers_weibull_shape_and_frailty():
    rec = {r['parameter']: r for r in metrics('stockout_survival')['parameter_recovery']}
    k = next(r for p, r in rec.items() if p.startswith('k (Weibull shape)'))
    assert k['ci_low'] <= 2.0 <= k['ci_high']
    s = next(r for p, r in rec.items() if p.startswith('frailty sd'))
    assert s['ci_low'] <= 0.5 <= s['ci_high']


def test_restock_finds_hidden_groups():
    r = metrics('restock_interval')['recovery']
    assert r['latent_groups']['K_chosen'] == 3 and r['latent_groups']['adjusted_rand_vs_planted'] >= 0.99
    assert all(x['covers_zero'] for x in r['negative_control_unplanted_effects'])


def test_price_response_correction_recovers_planted_beta():
    for r in metrics('price_response')['response_recovery']:
        lo, hi = r['corrected_ci']
        assert lo <= r['planted_beta'] <= hi
        assert r['naive_beta'] < 0.6 * r['planted_beta']          # the attenuation the method corrects


def test_eta_beats_baselines():
    assert all(metrics('eta_forecast')['beats'].values())


def test_direction_beats_bar():
    assert all(metrics('price_direction')['beats_bar'].values())


def test_anomaly_finds_real_defect():
    ev = metrics('anomaly_real')['detector_eval_vs_known_defect']['unit_price_z (|z|)']
    assert ev['precision_at_100'] >= 0.5


def test_simulator_reproduces_status_quo():
    val = metrics('simulate_whatif')['validation']['cheapest_share']
    for p, v in val.items():
        assert abs(v['simulated']['mean'] - v['observed_in_data']) < 0.01


def test_restock_priority_beats_rules():
    pol = {p['policy']: p['reduction_vs_none_pct'] for p in metrics('optimize_restock_priority')['policies']}
    assert pol['priority_index'] > max(pol['random'], pol['longest_out_first'])


def test_whatif_grid_static_overstates_leader_gain():
    m = metrics('simulate_grid')
    assert m['static_over_strategic_median'] > 1.2


def test_promo_frontier_costs_are_positive_and_small():
    rows = metrics('optimize_promo_frontier')['by_category']
    assert all(0 < r['oos_added_at_10pct_pp'] < 3 for r in rows)
    assert all(r['share_gain_at_10pct_pp'] > 5 for r in rows)


def test_restock_lab_orders_policies():
    m = metrics('optimize_restock_lab')
    for cap, r in m['reduction_pct_by_capacity'].items():
        assert r['clairvoyant_oracle'] >= r['priority_index'] - 0.5      # the benchmark is not beaten
        assert r['priority_index'] > r['random']


# ---------------------------------------------------------------- the product x store chain
def _chain_records():
    d = MODELS_DIR / 'listing_chain' / 'chains'
    files = sorted(d.glob('*.json')) if d.exists() else []
    if not files:
        pytest.skip('listing chain not built')
    return [json.loads(f.read_text(encoding='utf-8')) for f in files]


def test_listing_chain_has_the_seven_stages_in_order():
    from src.chain.listing import STAGES
    assert STAGES == ['1_observe', '2_applicability', '3_prediction_record', '4_price_grid', '5_simulation',
                      '6_optimization', '7_explanation']
    for r in _chain_records():
        assert r['stages'] == STAGES
        assert [k for k in r if k in STAGES] == STAGES                    # stored in stage order
        assert list(r['2_applicability']) == ['1_product_matcher', '2_next_price', '3_direction', '4_stock_next',
                                              '5_eta_next', '6_anomaly', '7_time_to_stockout', '8_restock',
                                              '9_competitor_response', '10_assortment_gap']


def test_listing_chain_applicability_is_consistent():
    for r in _chain_records():
        A, P, d = r['2_applicability'], r['3_prediction_record'], r['1_observe']['decision_snapshot']
        assert not (A['7_time_to_stockout']['applies'] and A['8_restock']['applies'])
        assert A['7_time_to_stockout']['applies'] == (d['in_stock'] == 1)
        for k, v in A.items():                                             # a skipped model carries no prediction
            if not v['applies'] and k in P:
                assert P[k].get('applies') is False and P[k]['why']
        assert A['10_assortment_gap']['applies'] is False                   # a listed product is never a gap here


def test_listing_chain_grid_baseline_and_optimum():
    for r in _chain_records():
        g, S, Z = r['4_price_grid'], r['5_simulation'], r['6_optimization']
        kinds = [x['kind'] for x in g['rungs']]
        assert kinds.count('hold') == 1 and 'increase' in kinds and 'cut' in kinds
        now = r['1_observe']['decision_snapshot']['selling_price']
        assert all(x['price'] >= g['floor_price'] - 1e-9 for x in g['rungs'] if x['kind'] == 'cut')
        assert all(round(x['price'] - g['remainder']) % g['step'] == 0 for x in g['rungs'])   # every rung on the grid
        assert S['baseline_check']['passed'], r['1_observe']['listing']['product_name']
        st, sa = Z['strategic'], Z['static']
        if st['reachable_within_30pct'] and sa['reachable_within_30pct']:
            assert st['price'] <= sa['price']                              # response never makes the cut shallower
        for view in ('strategic', 'static'):
            if Z[view]['reachable_within_30pct']:
                assert Z[view]['mean_cheapest_share'] >= Z['target'] and Z[view]['price'] <= now
                assert Z[view]['cut_pct'] <= 100 * Z['max_cut'] + 1e-9           # never beyond the stated limit


def test_validate_counts_a_degenerate_tie_as_agreement():
    """Observed share 0 and every simulated share 0 is agreement. The old percentile rule failed it."""
    import numpy as np
    from src.chain.listing import validate

    class Flat:
        def run(self, start, horizon, **kw):
            return np.tile(np.array([110.0, 100.0, 100.0, 100.0]), (50, horizon, 1))

        def platform_price(self, prices):
            return prices

        def observed(self, t):
            return np.array([110.0, 100.0, 100.0, 100.0])

    v = validate(Flat(), 40)
    assert v['observed_blinkit_cheapest_share'] == 0 and v['simulated_share_95_range'] == [0.0, 0.0]
    assert v['share_ok'] and v['passed']


# ---------------------------------------------------------------- price increases
def test_grid_raises_follow_the_planted_structure():
    m = metrics('simulate_grid')
    if 'blinkit_all_change_pp_by_raise' not in m:
        pytest.skip('grid built before raises')
    # nobody follows a follower (deliverable 9): for a follower's raise the two views must agree
    assert m['follower_raise_max_view_gap_pp'] < 0.5
    # followers follow Blinkit UP, so a static comparison overstates what a raise costs Blinkit
    assert m['raise_static_over_strategic_loss_median'] > 1.0
    up = m['blinkit_all_change_pp_by_raise']
    assert all(v['strategic'] < 0 and v['static'] < 0 for v in up.values())       # a raise never gains share


def test_price_headroom_is_consistent():
    m = metrics('optimize_price_headroom')
    for r in m['by_category'] + [m['panel']]:
        for b, h in r['headroom_pct_strategic'].items():                          # response never shrinks headroom
            assert 0 <= r['headroom_pct_static'][b] <= h <= 10
        hs = list(r['headroom_pct_strategic'].values())
        assert hs == sorted(hs)                                                    # a bigger budget never shrinks it
        assert r['withdraw_oos_change_pp_at_5pct'] <= 0.05                         # a shallower promo never adds OOS
        if r['blinkit_listings_on_promo'] == 0:
            assert abs(r['withdraw_oos_change_pp_at_5pct']) < 1e-9


def test_listing_chain_raise_objective():
    for r in _chain_records():
        Z, now = r['6_optimization'], r['1_observe']['decision_snapshot']['selling_price']
        if 'raise' not in Z:
            pytest.skip('chain built before the raise objective')
        assert Z['direction'] == ('raise' if Z['hold_mean_cheapest_share'] >= Z['target'] else 'cut')
        for view in ('strategic', 'static'):
            o = Z['raise'][view]
            if o.get('target_met_at_current_price'):
                assert o['price'] >= now and o['mean_cheapest_share'] >= Z['target']
        for g in r['5_simulation']['ladder']:                                     # the discount moves the right way
            assert g['promo']['mode'] in ('deepen', 'withdraw', 'none')
            if g['kind'] == 'increase':
                assert g['promo']['mode'] in ('withdraw', 'none') and g['promo']['extra_p_oos_within_12_pp'] <= 0.5


# ---------------------------------------------------------------- product unavailable (simulate_unavailable)
def test_unavailable_structure():
    m = metrics('simulate_unavailable')
    for p, d in m['who_inherits'].items():
        assert d[p]['change_pp'][1] < 0                                      # an outage costs the platform itself
        assert all(v['change_pp'][1] > -0.1 for q, v in d.items() if q != p)  # and nobody else loses
    L_ = m['blinkit_outage_by_length_pp']
    assert L_['1'] > L_['2'] > L_['4'] > L_['8']                            # longer outages cost more
    assert L_['0'] > L_['drawn_from_restock_model']                         # restoring at once beats waiting
    # the planted FAST restock groups (deliverable 8) lose least; SLOW ones most
    c = m['blinkit_outage_by_category']
    fast = [c[k]['blinkit_change_pp'] for k in ('Dairy, Bread & Eggs', 'Fruits & Vegetables') if k in c]
    slow = [c[k]['blinkit_change_pp'] for k in ('Home & Cleaning', 'Other / General Merchandise') if k in c]
    assert fast and slow and min(fast) > max(slow)


def test_no_substitution_in_the_generator():
    s = metrics('simulate_unavailable')['substitution_check']
    assert s['odds_ratio_ci95_cluster_by_product'][0] <= 1.0                  # not above 1: no substitution planted


# ---------------------------------------------------------------- store adds products (simulate_store_adds[_real])
def test_store_adds_dilution_and_provenance():
    m = metrics('simulate_store_adds')
    assert manifest('simulate_store_adds_real')['claim_scope'].startswith('REAL-ONLY')
    assert not manifest('simulate_store_adds')['claim_scope'].startswith('REAL-ONLY')
    at50 = [x['operations'] for x in m['by_store'] if x['n'] == 50]
    assert all(o['existing_oos_change_pct_scaled_capacity'] <= o['existing_oos_change_pct_fixed_capacity'] for o in at50)
    assert m['summary_at_50']['median_existing_oos_change_pct_fixed_capacity'] > 0   # fixed effort is diluted


# ---------------------------------------------------------------- richer restock objective
def test_restock_objective_frontier():
    m = metrics('optimize_restock_objective')
    fr = {f['alpha']: f for f in m['frontier_alpha']}
    assert fr[1.0]['J1_reduction_pct'] == max(f['J1_reduction_pct'] for f in fr.values())   # 12b's index wins on J1
    assert max(f['J2_reduction_pct'] for f in fr.values()) > fr[1.0]['J2_reduction_pct']   # weighting helps on J2
    pol = {p['policy']: p for p in m['policies']}
    assert pol['oracle_win_weighted']['J2_reduction_pct'] >= max(f['J2_reduction_pct'] for f in fr.values())
    assert all(v['J1_cost_pp'] > 0 for v in m['paired_vs_plain_index'].values())             # weighting costs J1


# ---------------------------------------------------------------- engine: outages and inactive listings stay paired
def test_engine_outage_and_active_are_paired():
    import numpy as np
    from src.simulate.engine import StockWorld
    W = StockWorld.load()
    st = W.initial_state().iloc[:400].reset_index(drop=True)
    m = np.zeros(len(st), bool); m[:20] = True
    a = W.simulate(st, n_sims=2, seed=3, return_states=True)['in_stock_path']
    b = W.simulate(st, n_sims=2, seed=3, return_states=True, outage={'mask': m, 'length': None})['in_stock_path']
    assert (a[:, :, ~m] == b[:, :, ~m]).all()                              # untouched listings: identical paths
    assert b[:, 0, m].mean() < a[:, 0, m].mean() or a[:, 0, m].mean() == 0
    from src.optimize.restock_priority import policy_priority
    c = W.simulate(st, n_sims=2, seed=3, policy=policy_priority, capacity_share=0.02, return_states=True)
    d = W.simulate(st, n_sims=2, seed=3, policy=policy_priority, capacity_share=0.02, return_states=True,
                   active=np.ones(len(st), bool))
    assert (c['in_stock_path'] == d['in_stock_path']).all()                # all-active == no mask
