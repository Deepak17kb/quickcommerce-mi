"""Provenance safeguards added by the 2026-10-13 audit: the store-label status reaches every surface that shows a
store-level REAL result, and the web-researched REAL prices are flagged."""
import json

import pandas as pd
import pytest

import src.load as L
from conftest import ROOT, raw_path
from src import provenance as P
from src.model_output import MODELS_DIR


# ------------------------------------------------------------------ the store label
def test_which_claims_rest_on_the_store_label():
    real = {'provenance': 'REAL', 'source_file': 'data/raw (data_status == REAL) via src.load'}
    assert P.is_store_level_claim({**real, 'source_detail': 'query_real_snapshot(median_eta_min, by store_id)'})
    assert P.is_store_level_claim({**real, 'source_detail': 'query_real_snapshot(oos_rate, by area)'})
    assert not P.is_store_level_claim({**real, 'source_detail': 'query_real_snapshot(oos_rate, by category)'})
    assert P.is_store_level_claim({'provenance': 'REAL', 'source_file': 'outputs/models/assortment_gaps/metrics.json'})
    assert P.is_store_level_claim({'provenance': 'REAL', 'source_file': 'docs/COVERAGE_12C.md'})
    assert P.is_store_level_claim({**real, 'stage': '1_observe'})                 # a chain's REAL context row
    assert not P.is_store_level_claim({'provenance': 'REAL', 'source_file': 'outputs/models/anomaly_real/metrics.json'})
    assert not P.is_store_level_claim({'provenance': 'SYNTHETIC', 'source_file': 'outputs/models/assortment_gaps/metrics.json'})
    # geography uses store coordinates from a separate source and no listing rows: not registered
    assert 'store_coverage_geography' not in P.STORE_LEVEL_REAL_OUTPUTS


def test_status_follows_the_saved_audit():
    s = P.store_label_status()
    if s['status'] == 'NOT_AUDITED':
        pytest.skip('store-label audit has not been run')
    assert s['status'] == 'UNVERIFIED' and P.unverified()             # the documented result of 2026-10-13
    for name in P.STORE_LEVEL_REAL_OUTPUTS:
        man = MODELS_DIR / name / 'manifest.json'
        if not man.exists():
            continue
        m = json.loads(man.read_text(encoding='utf-8'))
        assert m['store_label']['status'] == 'UNVERIFIED', f'{name}: run python -m src.provenance'
        assert m['claim_scope'].startswith('REAL-ONLY')              # the rows are real; the store reading is not


def test_analyst_marks_store_level_answers():
    from src.analyst.agent import answer, render
    if P.store_label_status()['status'] == 'NOT_AUDITED':
        pytest.skip('store-label audit has not been run')
    by_store = answer('Median delivery ETA by store on the real snapshot')
    assert by_store['store_label_banner'] and 'STORE LABEL UNVERIFIED' in render(by_store)
    assert any(c.get('store_label') == 'UNVERIFIED' for c in by_store['claims'])
    # a REAL fact that is not grouped by store is never marked, even when a store-level passage is retrieved beside it
    snacks = answer('How many listings did the real snapshot have in Snacks & Munchies?')
    assert snacks['claims'][0].get('store_label') is None
    assert all(P.is_store_level_claim(c) for c in snacks['claims'] if c.get('store_label'))
    plain = answer('Which anomaly detector worked best on the pack_qty defect?')
    assert plain['store_label_banner'] is None and not any(c.get('store_label') for c in plain['claims'])


def test_chain_and_page_carry_the_status():
    chains = sorted((MODELS_DIR / 'listing_chain' / 'chains').glob('*.json'))
    if not chains:
        pytest.skip('listing chain not built')
    for f in chains:
        ro = json.loads(f.read_text(encoding='utf-8'))['1_observe'].get('real_observation')
        if ro and 'store_label' not in ro:
            pytest.skip('chains were built before the store-label status was added: python -m src.chain.listing --demo')
        if ro:
            assert ro['store_label'] == 'UNVERIFIED'
    page = ROOT / 'outputs' / 'showcase' / 'explorer.html'
    if page.exists():
        html = page.read_text(encoding='utf-8')
        if '"storeUnverified"' not in html:
            pytest.skip('explorer page was built before the store-label status was added')
        assert '"storeUnverified":true' in html and 'store label unverified' in html


# ------------------------------------------------------------------ web-researched REAL prices
def test_web_researched_prices_are_flagged_and_match_raw():
    raw_path('Blinkit')
    if not L.PRICE_SOURCE_AUDIT.exists():
        pytest.skip('price-source audit table missing')
    a = pd.read_csv(L.PRICE_SOURCE_AUDIT)
    assert len(a) == 27 and int((~a.price_is_from_blinkit).sum()) == 13
    assert a.source_workbook.nunique() == 1 and a.source_workbook_sha256.str.len().eq(64).all() and a.checked_on.notna().all()
    real = L.real_only(L.load_raw('Blinkit'))
    hit = real[real.product_id.isin(a.product_id)].set_index('product_id')
    assert len(hit) == 27 and hit.data_status.eq('REAL').all()
    assert (hit.loc[a.product_id].selling_price.to_numpy() == a.selling_price_in_raw.to_numpy()).all()
    assert L.web_researched_price_ids() == set(a.product_id)
    assert len(L.real_observed_price_only(real)) == len(real) - 27
