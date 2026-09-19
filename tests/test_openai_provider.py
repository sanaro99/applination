from __future__ import annotations

from types import SimpleNamespace

from src.providers.openai_provider import OpenAIProvider


def _provider(response_text: str = "plain response") -> tuple[OpenAIProvider, list[dict]]:
    calls: list[dict] = []

    class Responses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_text=response_text)

    provider = object.__new__(OpenAIProvider)
    provider.client = SimpleNamespace(responses=Responses())
    provider.model = "gpt-5.6-luna"
    provider.reasoning_effort = "low"
    return provider, calls


def test_openai_text_call_uses_responses_api_and_reasoning_effort():
    provider, calls = _provider("<think>private</think>final")

    assert provider.text_call("system", "user", max_tokens=77) == "final"
    assert calls == [{
        "model": "gpt-5.6-luna", "instructions": "system", "input": "user",
        "max_output_tokens": 77, "reasoning": {"effort": "low"},
    }]


def test_openai_json_call_uses_strict_schema():
    provider, calls = _provider('{"answer":"ok"}')
    schema = {
        "type": "object", "properties": {"answer": {"type": "string"}},
        "required": ["answer"], "additionalProperties": False,
    }

    assert provider.json_call("system", "user", schema=schema) == {"answer": "ok"}
    assert calls[0]["text"]["format"] == {
        "type": "json_schema", "name": "structured_output", "schema": schema, "strict": True,
    }
