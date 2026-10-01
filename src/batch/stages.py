"""Suspend existing generation at its next AI call, then replay saved answers.

Using the real generation functions preserves prompts, factual checks and
bounded revision logic. No provider SDK or synchronous fallback is reachable.
Control-flow signals inherit BaseException so ordinary provider retry handlers
cannot turn a pending or failed batch into another paid call.
"""
from copy import deepcopy
import hashlib
import json
from src.providers.base import LLMProvider, _parse_json


class PendingRequest(BaseException):
    pass


class BatchFailure(BaseException):
    pass


class ReplayProvider(LLMProvider):
    def __init__(self, provider, model, task, application_key, transcript, thinking='on'):
        self.name, self.model, self.task = provider, model, task
        self.application_key, self.transcript, self.thinking = application_key, transcript, thinking
        self.index = 0

    def _call(self, system, user, max_tokens, schema, json_mode):
        request = dict(task=self.task, model=self.model, system=system, user=user,
                       max_tokens=max_tokens, schema=schema, json_mode=json_mode,
                       thinking=self.thinking)
        identity = [self.application_key, self.task, self.index, request]
        self.index += 1
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        entry = self.transcript.setdefault(key, {
            'request': {**request, 'request_id': key}, 'provider': self.name,
            'application_key': self.application_key, 'state': 'prepared',
        })
        if entry['state'] == 'succeeded':
            return deepcopy(entry['content'])
        if entry['state'] in ('failed', 'cancelled'):
            raise BatchFailure(entry.get('error') or 'Batch item failed')
        raise PendingRequest(key)

    def text_call(self, system, user, max_tokens=1000):
        return self._post_process_text(self._call(system, user, max_tokens, None, False))

    def json_call(self, system, user, max_tokens=2000, *, schema=None):
        content = self._call(system, user, max_tokens, schema, True)
        return content if isinstance(content, dict) else _parse_json(content)


def replay_chains(routes: dict, application_key: str, transcript: dict) -> dict:
    return {task: [ReplayProvider(route['provider'], route['model'], task,
                                  application_key, transcript, route.get('thinking', 'on'))]
            for task, route in routes.items()}
