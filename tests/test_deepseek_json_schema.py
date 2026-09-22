"""DeepSeek JSON mode receives a complete compact schema contract."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.providers.deepseek_provider import DeepSeekProvider
from src.schemas import RESUME_SCHEMA


def test_json_schema_prompt_is_compact_and_not_truncated():
    calls: list[dict] = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            usage=None,
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))],
        )

    provider = object.__new__(DeepSeekProvider)
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    provider.model = "deepseek-flash"
    provider.disable_thinking = True
    provider._extra = {"extra_body": {"thinking": {"type": "disabled"}}}

    assert provider.json_call("System", "User", schema=RESUME_SCHEMA) == {"ok": True}
    prompt = calls[0]["messages"][0]["content"]
    compact = json.dumps(RESUME_SCHEMA, separators=(",", ":"))
    assert prompt.endswith(compact)
    assert len(compact) > 1_500  # regression guard: this is a substantial schema


def test_authentication_failure_exits_to_provider_chain_without_text_retry():
    calls = 0

    class AuthenticationFailure(RuntimeError):
        status_code = 401

    def create(**kwargs):
        nonlocal calls
        calls += 1
        raise AuthenticationFailure("invalid API key")

    provider = object.__new__(DeepSeekProvider)
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    provider.model = "deepseek-flash"
    provider.disable_thinking = True
    provider._extra = {"extra_body": {"thinking": {"type": "disabled"}}}

    with pytest.raises(AuthenticationFailure):
        provider.json_call("System", "User", schema={"type": "object"})
    assert calls == 1
