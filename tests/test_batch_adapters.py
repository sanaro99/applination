import pytest
from src.batch.adapters import request_body, normalize_result, split_requests
from src.batch.capabilities import validate_batch_route


def request(**kw):
    return dict(request_id='x', task='ranking', model='gpt-6-luna', system='s', user='u',
                max_tokens=3000, schema=None, json_mode=True, thinking='off', **kw)


def test_native_routes_only():
    assert validate_batch_route('openai', '', 'gpt-6-luna')['discount'] == .5
    with pytest.raises(ValueError):
        validate_batch_route('openai', 'https://openrouter.ai/api/v1', 'gpt-6-luna')
    with pytest.raises(ValueError):
        validate_batch_route('ollama', '', 'any')
    with pytest.raises(ValueError):
        validate_batch_route('openai', '', 'invented-model')


def test_openai_payload_preserves_budget_and_reasoning():
    body = request_body('openai', request())
    assert body['max_output_tokens'] == 3000
    assert body['reasoning'] == {'effort': 'none'}
    assert body['instructions'].startswith('s')
    assert body['input'] == 'u'


def test_claude_schema_and_gemini_json_config():
    r = request()
    r['schema'] = {'type': 'object'}
    assert request_body('claude', r)['tools'][0]['input_schema'] == r['schema']
    body = request_body('gemini', r)
    assert body['config']['response_json_schema'] == r['schema']
    assert body['config']['max_output_tokens'] == 3000


def test_errors_and_usage_are_not_lost():
    item = normalize_result('openai', {'custom_id': 'b', 'error': {'code': 'expired'}})
    assert item['request_id'] == 'b'
    assert item['state'] == 'failed'
    item = normalize_result('openai', {'custom_id': 'a', 'response': {'status_code': 200, 'body': {
        'status': 'completed', 'usage': {'input_tokens': 12},
        'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'hello'}]}]}}})
    assert item['content'] == 'hello'
    assert item['usage']['input_tokens'] == 12


def test_chunking_and_single_oversize_request():
    assert len(split_requests('openai', [request(), request()], max_count=1)) == 2
    with pytest.raises(ValueError):
        split_requests('openai', [request()], max_bytes=1)
