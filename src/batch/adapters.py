"""Native provider transport. Batch creation is deliberately never retried."""
import json
from .capabilities import ROUTES


def request_body(provider, r):
    system = r['system']
    if r.get('json_mode') and not r.get('schema') and provider == 'openai':
        system = system.rstrip() + ('\n\nReturn ONLY a valid JSON object. No prose before or after. '
                                    'No markdown code fences. Start your response with { and end with }.')
    if r.get('json_mode') and not r.get('schema') and provider == 'claude':
        system = system.rstrip() + ('\n\nReturn ONLY a valid JSON object. No prose, no code fences. '
                                    'Start with { and end with }.')
    if provider == 'openai':
        body = dict(model=r['model'], instructions=system, input=r['user'],
                    max_output_tokens=max(16, r['max_tokens']),
                    reasoning={'effort': {'off': 'none', 'low': 'low', 'on': 'medium'}.get(r['thinking'], 'medium')})
        if r.get('schema'):
            body['text'] = {'format': {'type': 'json_schema', 'name': 'structured_output',
                                       'schema': r['schema'], 'strict': True}}
        return body
    if provider == 'claude':
        body = dict(model=r['model'], system=system, max_tokens=r['max_tokens'],
                    messages=[{'role': 'user', 'content': r['user']}])
        if r.get('schema'):
            body.update(tools=[{'name': 'emit_structured_response',
                               'description': 'Emit the final structured response. Always call this tool exactly once with the answer.',
                               'input_schema': r['schema']}],
                        tool_choice={'type': 'tool', 'name': 'emit_structured_response'})
        return body
    from src.providers.gemini_provider import _generation_config_kwargs
    return dict(contents=r['user'], config=_generation_config_kwargs(
        r['model'], system_instruction=system, max_output_tokens=r['max_tokens'],
        response_mime_type='application/json' if r.get('json_mode') else None,
        response_json_schema=r.get('schema')),
        metadata={'key': r['request_id']})


def split_requests(provider, requests, *, max_count=None, max_bytes=None):
    route = ROUTES[provider]
    max_count = max_count or route['max_count']
    max_bytes = max_bytes or route['max_bytes']
    chunks, chunk, size = [], [], 2
    for r in requests:
        n = len(json.dumps({'custom_id': r['request_id'], 'request': request_body(provider, r)},
                           ensure_ascii=False).encode('utf-8')) + 128
        if n + 2 > max_bytes:
            raise ValueError('Single batch request exceeds provider input-size limit.')
        if chunk and (len(chunk) >= max_count or size + n > max_bytes):
            chunks.append(chunk)
            chunk, size = [], 2
        chunk.append(r)
        size += n
    if chunk:
        chunks.append(chunk)
    return chunks


def _dict(obj):
    return obj if isinstance(obj, dict) else obj.model_dump(mode='json', exclude_none=True)


def normalize_result(provider, item):
    item = _dict(item)
    key = item.get('custom_id') or item.get('metadata', {}).get('key')
    error, content, usage = item.get('error'), None, {}
    if provider == 'openai':
        response = item.get('response') or {}
        body = response.get('body') or {}
        error = error or body.get('error')
        if response.get('status_code', 500) != 200 or body.get('status') != 'completed':
            error = error or {'message': 'Response failed, refused or incomplete'}
        content = ''.join(c.get('text', '') for o in body.get('output', [])
                          for c in o.get('content', []) if c.get('type') == 'output_text')
        usage = body.get('usage', {})
    elif provider == 'claude':
        result = item.get('result', {})
        if result.get('type') != 'succeeded':
            error = result.get('error') or {'message': result.get('type', 'missing result')}
        msg = result.get('message') or {}
        blocks = msg.get('content', [])
        content = next((b['input'] for b in blocks if b.get('type') == 'tool_use'), None)
        if content is None:
            content = ''.join(b.get('text', '') for b in blocks if b.get('type') == 'text')
        if msg.get('stop_reason') in ('max_tokens', 'refusal'):
            error = {'message': msg['stop_reason']}
        usage = msg.get('usage', {})
    else:
        response = item.get('response') or {}
        candidates = response.get('candidates') or []
        if not candidates:
            error = error or {'message': 'No candidates returned'}
        content = ''.join(p.get('text', '') for c in candidates
                          for p in c.get('content', {}).get('parts', []) if not p.get('thought'))
        if candidates and candidates[0].get('finish_reason') not in ('STOP', None):
            error = {'message': candidates[0]['finish_reason']}
        usage = response.get('usage_metadata', {})
    if content is None or content == '':
        error = error or {'message': 'Empty result'}
    return dict(request_id=key, state='failed' if error else 'succeeded', content=content,
                usage=usage, error=json.dumps(error) if error else None)


class NativeBatchAdapter:
    def __init__(self, provider, api_key, client=None):
        self.provider = provider
        if client is not None:
            self.client = client
        elif provider == 'openai':
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key, timeout=60, max_retries=0)
        elif provider == 'claude':
            from anthropic import Anthropic
            self.client = Anthropic(api_key=api_key, timeout=60, max_retries=0)
        else:
            from google import genai
            from google.genai import types
            self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
                timeout=60000, retry_options=types.HttpRetryOptions(attempts=1)))

    def submit(self, requests, submission_key):
        if len(split_requests(self.provider, requests)) != 1:
            raise ValueError('Coordinator must split oversized batches before submission.')
        if self.provider == 'openai':
            data = '\n'.join(json.dumps({'custom_id': r['request_id'], 'method': 'POST',
                'url': '/v1/responses', 'body': request_body('openai', r)}) for r in requests).encode()
            file = self.client.files.create(file=('batch.jsonl', data), purpose='batch')
            try:
                job = self.client.batches.create(input_file_id=file.id, endpoint='/v1/responses',
                    completion_window='24h', metadata={'submission_key': submission_key})
            except BaseException:
                # Do not delete an input that an ambiguously accepted job may need.
                raise
            return job.id
        if self.provider == 'claude':
            return self.client.messages.batches.create(requests=[
                {'custom_id': r['request_id'], 'params': request_body('claude', r)} for r in requests]).id
        return self.client.batches.create(model=requests[0]['model'],
            src=[request_body('gemini', r) for r in requests],
            config={'display_name': submission_key}).name

    def status(self, provider_id):
        if self.provider == 'openai':
            job = self.client.batches.retrieve(provider_id)
            return job.status
        if self.provider == 'claude':
            job = self.client.messages.batches.retrieve(provider_id)
            return 'completed' if job.processing_status == 'ended' else 'in_progress'
        job = self.client.batches.get(name=provider_id)
        return {'JOB_STATE_SUCCEEDED': 'completed', 'JOB_STATE_FAILED': 'failed',
                'JOB_STATE_CANCELLED': 'cancelled', 'JOB_STATE_EXPIRED': 'expired'}.get(job.state.name, 'in_progress')

    def results(self, provider_id):
        if self.provider == 'openai':
            job = self.client.batches.retrieve(provider_id)
            items = []
            for file_id in (job.output_file_id, job.error_file_id):
                if file_id:
                    items.extend(json.loads(line) for line in self.client.files.content(file_id).text.splitlines() if line)
        elif self.provider == 'claude':
            job = self.client.messages.batches.retrieve(provider_id)
            items = list(self.client.messages.batches.results(provider_id)) if job.results_url else []
        else:
            job = self.client.batches.get(name=provider_id)
            items = job.dest.inlined_responses if job.dest else []
        return [normalize_result(self.provider, item) for item in items or []]

    def cancel(self, provider_id):
        if self.provider == 'openai':
            self.client.batches.cancel(provider_id)
        elif self.provider == 'claude':
            self.client.messages.batches.cancel(provider_id)
        else:
            self.client.batches.cancel(name=provider_id)

    def cleanup(self, provider_id):
        if self.provider == 'openai':
            job = self.client.batches.retrieve(provider_id)
            for file_id in (job.input_file_id, job.output_file_id, job.error_file_id):
                if file_id:
                    self.client.files.delete(file_id)


def get_batch_adapter(provider, credentials):
    key = credentials.get('api_key', '')
    if not key:
        raise ValueError(f'Add your own {provider} API key before using batch mode.')
    return NativeBatchAdapter(provider, key)
