"""Deliverable 13: the analyst's refusal policy, provenance verifier, offline engine and Claude tool loop.

The Claude loop is driven by a mocked client (no network, no credentials): the mock asks for one tool call, then
returns a final JSON answer containing one claim mislabelled REAL from a SYNTHETIC source and one invented number.
The verifier must relabel the first and flag the second.
"""
import json
from types import SimpleNamespace

import pytest

from src.analyst import agent, guard
from src.analyst.tools import kb, tool_schemas


@pytest.mark.parametrize('q', [
    "Forecast next week's demand for Amul milk", 'What is Blinkit revenue?', 'price elasticity of snacks',
    'Which category sells out the fastest?', 'How many customers ordered from Flipkart?', 'market share by platform',
    'Which products sell the most?'])
def test_refuses_unsupported_questions(q):
    assert guard.refusal(q) is not None


@pytest.mark.parametrize('q', [
    'What is the store demand pressure index?', 'How accurate is the price forecast?',
    'What is the minimum order value on Blinkit?', 'Out of stock rate by category on the real snapshot'])
def test_does_not_refuse_supported_questions(q):
    assert guard.refusal(q) is None


def test_verifier_relabels_and_flags_invented_numbers():
    src = 'outputs/models/price_forecast_lgbm/metrics.json'
    claims = [{'text': 'test MAE is 9.66', 'provenance': 'REAL', 'source_file': src, 'source_detail': 'test'},
              {'text': 'skill is 42.42%', 'provenance': 'SYNTHETIC', 'source_file': src, 'source_detail': 'test'}]
    out = guard.verify(claims, json.dumps({'mae': 9.660895}), kb())
    assert out[0]['provenance'] == 'SYNTHETIC' and not out[0]['verified']
    assert any('42.42' in i for i in out[1]['issues'])


def test_offline_real_answer_is_real_and_correct():
    a = agent.answer_offline('What share of listings were out of stock on the real snapshot?')
    assert a['claims'][0]['provenance'] == 'REAL'
    assert '6.17%' in a['claims'][0]['text']
    assert a['all_claims_verified']


def test_offline_synthetic_answer_carries_banner():
    a = agent.answer_offline('Does Swiggy Instamart follow Blinkit prices?')
    assert a['banner'] == guard.SYNTHETIC_BANNER
    assert any(c['provenance'] == 'SYNTHETIC' for c in a['claims'])


def test_tool_schemas_are_strict():
    for t in tool_schemas():
        assert t['strict'] is True
        assert t['input_schema']['additionalProperties'] is False
        assert set(t['input_schema']['required']) == set(t['input_schema']['properties'])


class _FakeMessages:
    def __init__(self, script):
        self.script, self.calls = script, []

    def create(self, **kw):
        self.calls.append(kw)
        return self.script[len(self.calls) - 1]


def test_claude_loop_with_mocked_client(monkeypatch):
    anthropic = pytest.importorskip('anthropic')
    final = {'refused': False, 'refusal_reason': None, 'answer_summary': 'The forecast beats both baselines.',
             'claims': [{'text': 'test MAE 9.66 vs naive 10.56', 'provenance': 'REAL',
                         'source_file': 'outputs/models/price_forecast_lgbm/metrics.json', 'source_detail': 'test'},
                        {'text': 'it is 99.9% accurate', 'provenance': 'SYNTHETIC',
                         'source_file': 'outputs/models/price_forecast_lgbm/metrics.json', 'source_detail': 'test'}],
             'caveats': []}
    script = [
        SimpleNamespace(stop_reason='tool_use', stop_details=None, content=[
            SimpleNamespace(type='tool_use', id='tu_1', name='get_model_metrics',
                            input={'model': 'price_forecast_lgbm', 'key': 'test'})]),
        SimpleNamespace(stop_reason='end_turn', stop_details=None,
                        content=[SimpleNamespace(type='text', text=json.dumps(final))]),
    ]
    fake = _FakeMessages(script)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(anthropic, 'Anthropic', lambda *a, **k: SimpleNamespace(beta=SimpleNamespace(messages=fake)))
    a = agent.answer_claude('How accurate is the next-price forecast?')

    assert a['mode'] == agent.MODEL
    first = fake.calls[0]
    assert first['model'] == 'claude-opus-5' and first['output_config']['format']['type'] == 'json_schema'
    assert first['system'][0]['cache_control'] == {'type': 'ephemeral'}
    assert first['extra_body'] == {'fallbacks': 'default'}
    # the tool result went back as a single user message answering the tool_use id
    second_msgs = fake.calls[1]['messages']
    assert second_msgs[-1]['role'] == 'user' and second_msgs[-1]['content'][0]['tool_use_id'] == 'tu_1'
    c0, c1 = a['claims']
    assert c0['provenance'] == 'SYNTHETIC' and not c0['verified']        # mislabelled REAL -> relabelled
    assert any('99.9' in i for i in c1['issues'])                         # invented number flagged
    assert a['banner'] == guard.SYNTHETIC_BANNER


def test_claude_mode_without_credentials_falls_back(monkeypatch):
    """No credential source: offline fallback with a note, and nothing sent. The client's transport is a local mock,
    so this test cannot reach the network even on a machine that is logged in with an `ant auth login` profile."""
    import anthropic
    import httpx
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('ANTHROPIC_AUTH_TOKEN', raising=False)
    sent = []
    bare = anthropic.Anthropic(api_key=None, auth_token=None, http_client=anthropic.DefaultHttpxClient(
        transport=httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(500))))
    a = agent.answer_claude('How accurate is the next-price forecast?', client=bare)
    if sent:
        pytest.skip('a credential source (for example an ant login profile) exists on this machine')
    assert a['mode'] == 'offline' and 'credentials' in a['note']


def test_preflight_real_sdk_against_a_mock_api():
    """The real SDK builds the real request (only the transport is mocked): arguments, headers, tool round trip."""
    from src.analyst import preflight
    report = preflight.main()
    failed = [k for k, v in report['checks'].items() if v is False]
    assert report['passed'] and not failed, failed


@pytest.mark.parametrize('q,tool', [
    ('If Blinkit cuts snacks by 5%, what happens?', 'simulate_price_move'),
    ('What if Instamart lowers prices 3 percent and competitors do not react?', 'simulate_price_move'),
    ('Would a promo on Dairy hurt availability?', 'promo_frontier'),
    ('How much does extra restock capacity buy?', 'restock_capacity'),
    ('How accurate is the price forecast?', None)])
def test_experiment_routing(q, tool):
    pytest.importorskip('src.simulate.grid')
    from src.model_output import MODELS_DIR
    if not (MODELS_DIR / 'simulate_grid' / 'grid.json').exists():
        pytest.skip('what-if grid not built')
    got = agent.parse_experiment(q)
    assert (got[0] if got else None) == tool
    if got and got[0] == 'simulate_price_move' and 'react' in q:
        assert got[1]['competitors_react'] is False


def test_experiment_answer_is_synthetic_and_verified():
    from src.model_output import MODELS_DIR
    if not (MODELS_DIR / 'simulate_grid' / 'grid.json').exists():
        pytest.skip('what-if grid not built')
    a = agent.answer_offline('If Blinkit cuts snacks by 5%, what happens to its cheapest-of-4 share?')
    assert a['banner'] == guard.SYNTHETIC_BANNER
    assert all(c['provenance'] == 'SYNTHETIC' for c in a['claims'])
    assert a['all_claims_verified']


# ---------------------------------------------------------------- the product x store chain
def _chains():
    from src.model_output import MODELS_DIR
    d = MODELS_DIR / 'listing_chain' / 'chains'
    if not d.exists() or not any(d.glob('*.json')):
        pytest.skip('listing chain not built (python -m src.chain.listing --demo)')


@pytest.mark.parametrize('q,product,store', [
    ('explain this listing', None, None),
    ('Why is Frooti risky at BBSR-008?', 'frooti', '008'),
    ('What should Blinkit do about the sugar price at BLK-BBSR-003?', 'sugar', '003'),
    ('Explain the sweet corn listing at store 003', 'sweet corn', '003')])
def test_listing_routing(q, product, store):
    tool, args = agent.parse_experiment(q)
    assert tool == 'explain_listing' and args['product'] == product and args['store'] == store


def test_explain_listing_evidence_leaves_out_stage_7():
    _chains()
    from src.analyst.tools import explain_listing
    r = explain_listing()
    assert r['stages'][-1] == '7_explanation' and '7_explanation' not in r
    assert all(k in r for k in r['stages'][:6])


def test_explain_listing_is_stage_ordered_labelled_and_verified():
    _chains()
    a = agent.answer_offline('explain this listing')
    stages = [int(c['stage'].split('_')[0]) for c in a['claims']]
    assert stages == sorted(stages) and set(range(1, 7)) <= set(stages)
    assert a['all_claims_verified'] and a['banner'] == guard.SYNTHETIC_BANNER
    real = [c for c in a['claims'] if c['provenance'] == 'REAL']
    assert real and all(c['source_file'].startswith(('data/raw', 'outputs/models/anomaly_real',
                                                      'outputs/models/assortment_gaps')) for c in real)
    assert any(c['provenance'] == 'METHOD' and c['source_file'] == 'src/chain/listing.py' for c in a['claims'])


@pytest.mark.parametrize('q,expect', [('sugar', 'Whole Farm Grocery Sugar'), ('sweet corn', 'Sweet Corn'),
                                      ('frooti', 'Frooti')])
def test_explain_listing_matches_the_named_product(q, expect):
    """Scoring by name coverage once sent "sugar" to a sugar-free lassi; the query must be covered, not the name."""
    _chains()
    from src.analyst.tools import explain_listing
    store = {'sugar': '003', 'sweet corn': '003', 'frooti': '008'}[q]
    assert expect in explain_listing(q, store)['1_observe']['listing']['product_name']


# ---------------------------------------------------------------- price increases
@pytest.mark.parametrize('q,tool,direction', [
    ('If Blinkit raises snacks prices by 5%, what happens?', 'simulate_price_move', 'raise'),
    ('What if Instamart increases prices 3 percent?', 'simulate_price_move', 'raise'),
    ('If Blinkit cuts snacks by 5%, what happens?', 'simulate_price_move', 'cut'),
    ('How much headroom does Blinkit have in Beverages?', 'price_headroom', None),
    ('How far can Blinkit raise dairy prices without losing cheapest share?', 'price_headroom', None)])
def test_raise_routing(q, tool, direction):
    from src.model_output import MODELS_DIR
    if not (MODELS_DIR / 'simulate_grid' / 'grid.json').exists():
        pytest.skip('what-if grid not built')
    got = agent.parse_experiment(q)
    assert got[0] == tool
    if direction:
        assert got[1]['direction'] == direction


@pytest.mark.parametrize('q', ['If Blinkit raises snacks prices by 5%, what happens to its cheapest-of-4 share?',
                               'How much headroom does Blinkit have in Beverages?'])
def test_raise_answers_are_synthetic_and_verified(q):
    from src.model_output import MODELS_DIR
    if not (MODELS_DIR / 'optimize_price_headroom' / 'metrics.json').exists():
        pytest.skip('headroom not built')
    a = agent.answer_offline(q)
    assert a['banner'] == guard.SYNTHETIC_BANNER and a['all_claims_verified']
    assert all(c['provenance'] == 'SYNTHETIC' for c in a['claims'])


# ---------------------------------------------------------------- EXTERNAL sources
def test_external_docs_are_labelled_and_sourced():
    import re
    from pathlib import Path
    from src.analyst.tools import kb
    ext = [p for p in kb().passages if p.source_file.startswith('docs/external/')]
    assert ext and all(p.provenance == 'EXTERNAL' for p in ext)
    text = Path(kb().root / 'docs/external/MARKET_CONTEXT_EXTERNAL.md').read_text(encoding='utf-8')
    for sec in re.split(r'(?m)^## ', text)[1:]:                             # every fact section: URL + retrieval date
        assert 'https://' in sec and 'Retrieved 2026-' in sec, sec[:60]


def test_guard_external_rules():
    from src.analyst.tools import kb
    src = 'docs/external/MARKET_CONTEXT_EXTERNAL.md'
    ev = 'Swiggy Instamart 1,171 stores 131 cities https://example.org/a'
    c = guard.verify([{'text': 'Instamart had 1,171 stores in 131 cities.', 'provenance': 'REAL', 'source_file': src,
                       'source_detail': 'x · https://example.org/a'}], ev, kb())[0]
    assert c['provenance'] == 'EXTERNAL' and not c['verified']               # mislabelled -> relabelled, flagged
    c = guard.verify([{'text': 'Instamart had 1,171 stores.', 'provenance': 'EXTERNAL', 'source_file': src,
                       'source_detail': 'no url here'}], ev, kb())[0]
    assert any('URL' in i for i in c['issues'])
    c = guard.verify([{'text': 'k = 1.98', 'provenance': 'EXTERNAL', 'source_detail': 'https://x.y',
                       'source_file': 'outputs/models/stockout_survival/metrics.json'}], 'k 1.98', kb())[0]
    assert c['provenance'] == 'SYNTHETIC'                                   # EXTERNAL label needs an external source


@pytest.mark.parametrize('q', ["What is Blinkit's net order value this quarter?", 'What was Instamart GOV in Q1?'])
def test_order_value_is_refused(q):
    assert guard.refusal(q)


@pytest.mark.parametrize('q', ['What happened in Nov 2025 on the panel?', 'Is newsonair.gov.in a source?'])
def test_order_value_pattern_does_not_overreach(q):
    assert guard.refusal(q) is None


# ---------------------------------------------------------------- the new experiment tools
@pytest.mark.parametrize('q,tool', [
    ('What happens if Blinkit goes out of stock on Home & Cleaning products?', 'outage_impact'),
    ('Who gains when Flipkart Minutes is out of stock?', 'outage_impact'),
    ('Do shoppers substitute to other platforms when Blinkit is unavailable?', 'outage_impact'),
    ('What if store BBSR-003 adds its 25 gap products?', 'store_adds'),
    ('Should restock priority weight listings by cheapest position?', 'restock_objective'),
    ('What happens to stock-outs if Blinkit deepens snack promotions?', 'promo_frontier'),
    ('Which products is store BLK-BBSR-001 missing compared with similar stores?', None),
    ('What share of listings were out of stock on the real snapshot?', None)])
def test_new_tool_routing(q, tool):
    from src.model_output import MODELS_DIR
    if not (MODELS_DIR / 'simulate_grid' / 'grid.json').exists():
        pytest.skip('what-if grid not built')
    got = agent.parse_experiment(q)
    assert (got[0] if got else None) == tool


@pytest.mark.parametrize('q,labels', [
    ('What happens if Blinkit goes out of stock on Home & Cleaning products?', {'SYNTHETIC'}),
    ('What if store BBSR-003 adds its 25 gap products?', {'REAL', 'SYNTHETIC'}),
    ('Should restock priority weight listings by cheapest position?', {'SYNTHETIC'})])
def test_new_tool_answers_verified(q, labels):
    from src.model_output import MODELS_DIR
    for m in ('simulate_unavailable', 'simulate_store_adds', 'simulate_store_adds_real', 'optimize_restock_objective'):
        if not (MODELS_DIR / m / 'metrics.json').exists():
            pytest.skip(f'{m} not built')
    a = agent.answer_offline(q)
    assert a['all_claims_verified'] and {c['provenance'] for c in a['claims']} == labels
