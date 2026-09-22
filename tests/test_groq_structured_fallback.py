"""Groq can reject a strict schema while accepting JSON-object mode."""
from types import SimpleNamespace

from src.providers.groq_provider import GroqProvider


def test_groq_retries_unsupported_schema_as_json_object_before_text_fallback():
    formats = []
    system_prompts = []

    def create(**kwargs):
        mode = (kwargs.get("response_format") or {}).get("type")
        formats.append(mode)
        system_prompts.append(kwargs["messages"][0]["content"])
        if mode == "json_schema":
            raise ValueError("400 response_format json_schema unsupported")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))])

    provider = GroqProvider.__new__(GroqProvider)
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    provider.model = "openai/gpt-oss-120b"
    assert provider.json_call("Return JSON", "Go", max_tokens=100, schema={
        "type": "object", "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"], "additionalProperties": False,
    }) == {"ok": True}
    assert formats == ["json_schema", "json_object"]
    assert '"required":["ok"]' in system_prompts[1]


def test_gpt_oss_uses_low_reasoning_effort_to_leave_room_for_the_final_answer():
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Done"))])

    provider = GroqProvider.__new__(GroqProvider)
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    provider.model = "openai/gpt-oss-120b"
    assert provider.text_call("Write", "Go", max_tokens=100) == "Done"
    assert calls[0]["extra_body"] == {"include_reasoning": False, "reasoning_effort": "low"}
