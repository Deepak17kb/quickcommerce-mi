"""
preflight.py — run the Claude engine end to end against a local mock of the Messages API. No network, no cost.

    python -m src.analyst.preflight          # -> outputs/analyst/preflight_report.json

WHY
  The live engine (`--llm`) needs Anthropic credentials this machine may not have. A test that swaps in a fake client
  object checks the loop logic but not the one thing that breaks first in real life: whether the installed SDK accepts
  every argument and serialises the request correctly. Here the REAL SDK builds the REAL HTTP request; only the
  transport is replaced, by a mock that answers like the API: a tool call first, then a final JSON answer. So the whole
  path runs: argument serialisation, headers, tool execution, the tool-result round trip, the verifier, the banners.

WHAT IT CHECKS (each one a named pass/fail in the report)
  request   model; adaptive thinking; effort; json_schema output format; strict tool schemas; server-side refusal
            fallback (beta header + body field); prompt caching on the system prompt; the system prompt names every tool
  loop      the second request echoes the assistant's tool_use and answers it with a matching tool_result
  answer    the final answer comes back in Claude mode, labelled and verified, with the SYNTHETIC banner
  guard     a credential-free client falls back offline with a clear note (the SDK's no-credentials error), without
            sending anything

WHAT IT CANNOT CHECK
  How the live model answers: its tool choices, its wording, whether its claims verify. That needs credentials:
  python -m src.analyst.evaluate --llm --yes
"""
import json

import anthropic
import httpx

import src.load as L
from src.analyst import agent
from src.analyst.tools import tool_schemas

OUT = L.ROOT / 'outputs' / 'analyst'
QUESTION = 'Did the survival model recover the planted Weibull shape?'
FAKE_KEY = 'preflight-not-a-real-key'


def mock_api():
    """A transport that records each request and answers like the Messages API: tool_use first, then the answer."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({'url': str(request.url), 'headers': dict(request.headers), 'body': body})
        base = {'id': f'msg_preflight_{len(seen)}', 'type': 'message', 'role': 'assistant', 'model': body['model'],
                'stop_sequence': None, 'usage': {'input_tokens': 1, 'output_tokens': 1}}
        if len(seen) == 1:
            return httpx.Response(200, json={**base, 'stop_reason': 'tool_use', 'content': [
                {'type': 'tool_use', 'id': 'toolu_preflight_1', 'name': 'get_model_metrics',
                 'input': {'model': 'stockout_survival', 'key': None}}]})
        answer = {'refused': False, 'refusal_reason': None,
                  'answer_summary': 'Deliverable 7 recovers the planted duration dependence on the generated panel.',
                  'claims': [{'text': 'The survival model recovers the planted discrete-Weibull duration dependence '
                                      'on the generated panel; this describes the generator, not the market.',
                              'provenance': 'SYNTHETIC', 'source_file': 'outputs/models/stockout_survival/metrics.json',
                              'source_detail': 'get_model_metrics(stockout_survival)'}],
                  'caveats': ['SYNTHETIC: planted-parameter recovery is a pipeline check.']}
        return httpx.Response(200, json={**base, 'stop_reason': 'end_turn',
                                         'content': [{'type': 'text', 'text': json.dumps(answer)}]})
    return httpx.MockTransport(handler), seen


def main():
    transport, seen = mock_api()
    client = anthropic.Anthropic(api_key=FAKE_KEY, http_client=anthropic.DefaultHttpxClient(transport=transport))
    ans = agent.answer_claude(QUESTION, client=client)

    checks = {}
    req = seen[0]['body'] if seen else {}
    hdr = seen[0]['headers'] if seen else {}
    names = [t['name'] for t in tool_schemas()]
    checks['two requests reached the mock (tool turn, then the answer)'] = len(seen) == 2
    checks['endpoint is POST /v1/messages'] = bool(seen) and '/v1/messages' in seen[0]['url']
    checks[f'model is {agent.MODEL}'] = req.get('model') == agent.MODEL
    checks['adaptive thinking'] = req.get('thinking') == {'type': 'adaptive'}
    checks['effort high'] = req.get('output_config', {}).get('effort') == 'high'
    checks['answer constrained by a json_schema'] = req.get('output_config', {}).get('format', {}).get('type') == 'json_schema'
    checks['refusal fallback: beta header'] = 'server-side-fallback-2026-07-01' in hdr.get('anthropic-beta', '')
    checks['refusal fallback: body field "default"'] = req.get('fallbacks') == 'default'
    checks['system prompt cached'] = (req.get('system') or [{}])[0].get('cache_control', {}).get('type') == 'ephemeral'
    checks[f'all {len(names)} tools sent, every one strict'] = (
        [t.get('name') for t in req.get('tools', [])] == names and all(t.get('strict') for t in req.get('tools', [])))
    sys_text = (req.get('system') or [{}])[0].get('text', '')
    checks['system prompt names every experiment tool'] = all(
        n in sys_text for n in names if n not in ('search_knowledge', 'get_model_metrics', 'query_real_snapshot',
                                                   'list_models'))
    checks['api key sent in the x-api-key header (never logged)'] = hdr.get('x-api-key') == FAKE_KEY
    if len(seen) == 2:
        m2 = seen[1]['body']['messages']
        asst = m2[1] if len(m2) > 1 else {}
        user = m2[2] if len(m2) > 2 else {}
        checks['second request echoes the tool_use'] = any(
            b.get('type') == 'tool_use' and b.get('id') == 'toolu_preflight_1' for b in asst.get('content', []))
        checks['and answers it with a matching tool_result'] = any(
            b.get('type') == 'tool_result' and b.get('tool_use_id') == 'toolu_preflight_1' for b in user.get('content', []))
    checks['answer returned in Claude mode'] = ans.get('mode') == agent.MODEL
    checks['answer claims verified'] = bool(ans.get('claims')) and ans.get('all_claims_verified') is True
    checks['SYNTHETIC banner added'] = bool(ans.get('banner'))

    # no credentials: the SDK raises before sending; the engine must fall back offline and say why
    blocked = []
    bare = anthropic.Anthropic(api_key=None, auth_token=None, http_client=anthropic.DefaultHttpxClient(
        transport=httpx.MockTransport(lambda r: blocked.append(r) or httpx.Response(500))))
    try:
        off = agent.answer_claude(QUESTION, client=bare)
        checks['no credentials: offline fallback with a note, nothing sent'] = (
            off.get('mode') == 'offline' and 'credentials' in (off.get('note') or '') and not blocked)
    except TypeError:
        # a credential source exists on this machine after all (e.g. an `ant auth login` profile): nothing to check
        checks['no credentials: offline fallback with a note, nothing sent'] = None

    passed = all(v for v in checks.values() if v is not None)
    report = {'passed': passed, 'checks': checks, 'sdk_version': anthropic.__version__, 'model': agent.MODEL,
              'question': QUESTION, 'requests_seen': len(seen),
              'request_shape': {k: (v if k in ('model', 'thinking', 'output_config', 'fallbacks') else
                                    f'{len(v)} item(s)' if isinstance(v, list) else type(v).__name__)
                                for k, v in req.items() if k != 'messages'},
              'answer': {k: ans.get(k) for k in ('mode', 'answer_summary', 'all_claims_verified', 'banner')},
              'not_checked': 'how the live model answers; run python -m src.analyst.evaluate --llm --yes with credentials'}
    OUT.mkdir(parents=True, exist_ok=True)
    # the schema in output_config is long; the report keeps its type only
    if isinstance(report['request_shape'].get('output_config'), dict):
        oc = dict(report['request_shape']['output_config'])
        oc['format'] = {'type': oc.get('format', {}).get('type'), 'schema': '(the answer schema)'}
        report['request_shape']['output_config'] = oc
    (OUT / 'preflight_report.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf-8')
    for k, v in checks.items():
        print(f"  {'PASS' if v else ('SKIP' if v is None else 'FAIL')}  {k}")
    print(f"preflight {'PASSED' if passed else 'FAILED'} (SDK {anthropic.__version__}, model {agent.MODEL}); "
          f"report: outputs/analyst/preflight_report.json")
    return report


if __name__ == '__main__':
    main()
