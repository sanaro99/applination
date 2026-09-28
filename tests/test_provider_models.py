"""Public browsing stays separate from private account model discovery."""
from types import SimpleNamespace

import pytest
import requests

from server import provider_models


def response(payload):
    return SimpleNamespace(status_code=200, raise_for_status=lambda: None, json=lambda: payload)


def test_public_catalog_uses_native_ids_and_filters_non_text_and_deprecated_models(monkeypatch):
    provider_models._public_catalog.cache_clear()
    calls = []
    text = {"input": ["text", "image"], "output": ["text"]}

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return response({"openai": {"models": {
            "first": {"id": "gpt-text", "modalities": text},
            "deprecated": {"id": "gpt-old", "modalities": text, "status": "deprecated"},
            "image": {"id": "image-model", "modalities": {"input": ["text"], "output": ["image"]}},
            "audio": {"id": "audio-model", "modalities": {"input": ["audio"], "output": ["text"]}},
            "bad": {"id": "bad model", "modalities": text},
            "malformed": {"id": "broken", "modalities": {"input": None, "output": ["text"]}},
        }}, "anthropic": {"models": {"one": {"id": "claude-text", "modalities": text}}}})

    monkeypatch.setattr(provider_models.requests, "get", get)
    try:
        assert provider_models.public_models("openai") == ["gpt-text"]
        assert provider_models.public_models("claude") == ["claude-text"]
        assert len(calls) == 1
        assert calls[0][0] == "https://models.dev/api.json"
        assert calls[0][1]["headers"] == {}
        assert calls[0][1]["allow_redirects"] is False
    finally:
        provider_models._public_catalog.cache_clear()


def test_anthropic_model_discovery_reads_all_pages(monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append(kwargs["params"].copy())
        if "after_id" not in kwargs["params"]:
            return response({"data": [{"id": "claude-first"}], "has_more": True, "last_id": "claude-first"})
        return response({"data": [{"id": "claude-second"}], "has_more": False})

    monkeypatch.setattr(provider_models.requests, "get", get)
    assert provider_models.discover_models("claude", "test-key") == ["claude-first", "claude-second"]
    assert calls == [{"limit": 100}, {"limit": 100, "after_id": "claude-first"}]


def test_pagination_cannot_hold_a_request_open_indefinitely(monkeypatch):
    clock = iter([0, 0, 21])
    monkeypatch.setattr(provider_models.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(provider_models.requests, "get", lambda *a, **kw: response({
        "data": [{"id": "claude-first"}], "has_more": True, "last_id": "claude-first",
    }))
    with pytest.raises(requests.Timeout, match="time budget"):
        provider_models.discover_models("claude", "test-key")


@pytest.mark.parametrize("payload", [{}, [], {"data": None}, {"data": "invalid"}])
def test_invalid_provider_model_responses_are_rejected(payload, monkeypatch):
    monkeypatch.setattr(provider_models.requests, "get", lambda *a, **kw: response(payload))
    with pytest.raises(ValueError, match="invalid model list"):
        provider_models.discover_models("openai", "test-key")
