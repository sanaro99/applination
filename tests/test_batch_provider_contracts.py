"""Exercise real installed SDK serialization with network-free HTTP fixtures."""
import json
import httpx
import pytest
from src.batch.adapters import NativeBatchAdapter, normalize_result
from src.schemas import RESUME_SCHEMA


def request(model):
    return dict(request_id='item-1', task='tailoring', model=model,
                system='Write a truthful resume.', user='Example evidence.',
                max_tokens=3000, thinking='off', json_mode=True, schema=RESUME_SCHEMA)


@pytest.mark.parametrize('reason', ['max_tokens', 'refusal', 'model_context_window_exceeded', 'pause_turn'])
def test_claude_unfinished_output_is_never_publishable(reason):
    result = normalize_result('claude', {'custom_id':'item-1', 'result': {'type':'succeeded',
        'message': {'content':[{'type':'text','text':'A partial cover letter'}],
                    'stop_reason':reason, 'usage':{'output_tokens':30}}}})
    assert result['state'] == 'failed'
    assert reason in result['error']
    assert result['usage']['output_tokens'] == 30


def test_claude_installed_sdk_batch_round_trip():
    from anthropic import Anthropic
    calls = []
    batch = dict(id='msgbatch_fixture', type='message_batch', processing_status='ended',
        request_counts=dict(processing=0,succeeded=1,errored=0,canceled=0,expired=0),
        created_at='2026-10-02T00:00:00Z', expires_at='2026-10-03T00:00:00Z',
        ended_at='2026-10-02T00:01:00Z', results_url='https://api.anthropic.com/results/fixture')
    row = dict(custom_id='item-1',result=dict(type='succeeded',message=dict(id='msg_fixture',
        type='message',role='assistant',model='claude-haiku-4-5',stop_reason='tool_use',
        content=[dict(type='tool_use',id='tool_fixture',name='emit_structured_response',input={'answer':'ok'})],
        usage=dict(input_tokens=10,output_tokens=20))))
    def handler(req):
        calls.append(req)
        if req.url.path == '/results/fixture':
            return httpx.Response(200,text=json.dumps(row)+'\n',headers={'content-type':'application/x-jsonl'})
        return httpx.Response(200,json=batch)
    client = Anthropic(api_key='test-only',max_retries=0,http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    adapter = NativeBatchAdapter('claude','test-only',client=client)
    assert adapter.submit([request('claude-haiku-4-5')],'fixture') == 'msgbatch_fixture'
    payload = json.loads(calls[0].content)['requests'][0]
    assert payload['custom_id'] == 'item-1'
    assert payload['params']['tools'][0]['input_schema'] == RESUME_SCHEMA
    assert payload['params']['tool_choice']['name'] == 'emit_structured_response'
    assert adapter.status('msgbatch_fixture') == 'completed'
    result = adapter.results('msgbatch_fixture')[0]
    assert result['request_id'] == 'item-1'
    assert result['content'] == {'answer':'ok'}
    assert result['state'] == 'succeeded'
    assert result['usage']['output_tokens'] == 20
    adapter.cancel('msgbatch_fixture')
    assert calls[-1].url.path.endswith('/cancel')
    client.close()


def test_gemini_installed_sdk_batch_round_trip():
    from google import genai
    from google.genai import types
    calls = []
    batch = dict(name='batches/fixture',metadata=dict(state='JOB_STATE_SUCCEEDED',
        output=dict(inlinedResponses=dict(inlinedResponses=[dict(metadata={'key':'item-1'},response=dict(
            candidates=[dict(content=dict(parts=[dict(text='private thought',thought=True),dict(text='{"answer":"ok"}')]),
                             finishReason='STOP')],usageMetadata=dict(promptTokenCount=10,candidatesTokenCount=20)))]))))
    def handler(req):
        calls.append(req)
        return httpx.Response(200,json=batch)
    client = genai.Client(api_key='test-only',http_options=types.HttpOptions(
        client_args={'transport':httpx.MockTransport(handler)},retry_options=types.HttpRetryOptions(attempts=1)))
    adapter = NativeBatchAdapter('gemini','test-only',client=client)
    assert adapter.submit([request('gemini-2.5-flash')],'fixture') == 'batches/fixture'
    payload = json.loads(calls[0].content)
    assert 'Example evidence.' in json.dumps(payload)
    assert 'responseJsonSchema' in json.dumps(payload)
    assert 'item-1' in json.dumps(payload)
    wire_request = payload['batch']['inputConfig']['requests']['requests'][0]
    assert wire_request['metadata'] == {'key':'item-1'}
    assert wire_request['request']['generationConfig']['responseJsonSchema'] == RESUME_SCHEMA
    assert wire_request['request']['generationConfig']['thinkingConfig']['thinking_budget'] == 0
    assert adapter.status('batches/fixture') == 'completed'
    result = adapter.results('batches/fixture')[0]
    assert result['request_id'] == 'item-1'
    assert result['content'] == '{"answer":"ok"}'
    assert result['state'] == 'succeeded'
    assert result['usage']['candidates_token_count'] == 20
    adapter.cancel('batches/fixture')
    assert calls[-1].url.path.endswith(':cancel')
    client.close()


@pytest.mark.parametrize('reason',['MAX_TOKENS','SAFETY','RECITATION'])
def test_gemini_unfinished_output_retains_usage_and_error(reason):
    from google.genai import types
    item = types.InlinedResponse(metadata={'key':'item-1'},response=types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(parts=[types.Part(text='partial')]),finish_reason=reason)],
        usage_metadata=types.GenerateContentResponseUsageMetadata(candidates_token_count=20)))
    result = normalize_result('gemini',item)
    assert result['request_id'] == 'item-1'
    assert result['state'] == 'failed'
    assert reason in result['error']
    assert result['usage']['candidates_token_count'] == 20


def test_openai_installed_sdk_batch_round_trip():
    from openai import OpenAI
    calls = []
    batch = dict(id='batch_fixture',object='batch',endpoint='/v1/responses',status='completed',
        completion_window='24h',input_file_id='file_input',output_file_id='file_output',error_file_id=None,created_at=0)
    row = dict(custom_id='item-1',response=dict(status_code=200,body=dict(status='completed',
        output=[dict(type='message',content=[dict(type='output_text',text='{"answer":"ok"}')])],
        usage=dict(input_tokens=10,output_tokens=20))))
    def handler(req):
        calls.append(req)
        if req.method == 'DELETE':
            return httpx.Response(200,json={'id':req.url.path.rsplit('/',1)[-1],'object':'file','deleted':True})
        if req.url.path == '/v1/files':
            assert b'"strict": false' in req.content
            assert b'"max_output_tokens": 3000' in req.content
            return httpx.Response(200,json=dict(id='file_input',object='file',purpose='batch',bytes=10,created_at=0,filename='batch.jsonl'))
        if req.url.path.endswith('/content'):
            return httpx.Response(200,text=json.dumps(row)+'\n')
        return httpx.Response(200,json=batch)
    client = OpenAI(api_key='test-only',max_retries=0,http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    adapter = NativeBatchAdapter('openai','test-only',client=client)
    assert adapter.submit([request('gpt-6-luna')],'fixture') == 'batch_fixture'
    payload = json.loads(calls[1].content)
    assert payload['endpoint'] == '/v1/responses'
    assert payload['completion_window'] == '24h'
    assert adapter.status('batch_fixture') == 'completed'
    result = adapter.results('batch_fixture')[0]
    assert result['request_id'] == 'item-1'
    assert result['state'] == 'succeeded'
    assert result['usage']['output_tokens'] == 20
    adapter.cancel('batch_fixture')
    assert calls[-1].url.path.endswith('/cancel')
    adapter.cleanup('batch_fixture')
    assert [r.url.path for r in calls if r.method == 'DELETE'] == ['/v1/files/file_input','/v1/files/file_output']
    client.close()


@pytest.mark.parametrize('model,thinking,expected', [
    ('gemini-2.5-flash','off',0), ('gemini-2.5-flash-lite','off',0),
    ('gemini-2.5-pro','off',128), ('gemini-2.5-flash','low',1024),
    ('gemini-2.5-flash-lite','on',2200), ('gemini-2.5-pro','on',2200)])
def test_gemini_batch_reasoning_leaves_room_for_final_answer(model,thinking,expected):
    from src.batch.adapters import request_body
    r = request(model)
    r.update(thinking=thinking,max_tokens=2200)
    config = request_body('gemini',r)['config']
    assert config['thinking_config']['thinking_budget'] == expected
    assert config['max_output_tokens'] == 2200 + expected
    r['max_tokens'] = 12000
    config = request_body('gemini',r)['config']
    assert config['max_output_tokens'] <= 16000


def test_ordinary_gemini_generation_config_is_unchanged():
    from src.providers.gemini_provider import _generation_config_kwargs
    config = _generation_config_kwargs('gemini-2.5-pro',system_instruction='s',max_output_tokens=2200)
    assert config['max_output_tokens'] == 2200
    assert 'thinking_config' not in config


@pytest.mark.parametrize('state', ['errored','canceled','expired'])
def test_claude_sdk_unsuccessful_result_variants(state):
    from anthropic.types.messages import MessageBatchIndividualResponse
    result = {'type':state}
    if state == 'errored':
        result['error'] = {'type':'error','error':{'type':'invalid_request_error','message':'Invalid schema'}}
    item = MessageBatchIndividualResponse.model_validate({'custom_id':'item-1','result':result})
    normalized = normalize_result('claude',item)
    assert normalized['request_id'] == 'item-1'
    assert normalized['state'] == 'failed'
    assert ('Invalid schema' if state == 'errored' else state) in normalized['error']


def test_gemini_sdk_inline_error_is_preserved():
    from google.genai import types
    item = types.InlinedResponse(metadata={'key':'item-1'},error=types.JobError(code=400,message='Invalid schema'))
    result = normalize_result('gemini',item)
    assert result['state'] == 'failed'
    assert result['request_id'] == 'item-1'
    assert 'Invalid schema' in result['error']
