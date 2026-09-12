"""Compatibility checks for current Gemini model families."""
from src.providers.gemini_provider import _generation_config_kwargs


def test_gemini_3_omits_sampling_controls():
    config = _generation_config_kwargs(
        "gemini-3.8-flash",
        system_instruction="system",
        max_output_tokens=100,
        response_mime_type="application/json",
    )
    assert "temperature" not in config
    assert config["response_mime_type"] == "application/json"


def test_legacy_gemini_keeps_existing_sampling_control():
    config = _generation_config_kwargs(
        "gemini-2.5-flash",
        system_instruction="system",
        max_output_tokens=100,
    )
    assert config["temperature"] == 0.4
