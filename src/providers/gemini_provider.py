"""Gemini provider — uses the google-genai SDK (successor to google-generativeai)."""
from __future__ import annotations
import logging
import os
import time

from .base import LLMProvider, _parse_json, resolve_api_key

LOG = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAYS = [2, 5, 15]   # seconds between retries on 503


def _with_retry(fn, *args, **kwargs):
    """Call fn with exponential backoff on 503 / rate-limit errors."""
    for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            msg = str(e)
            if "503" in msg or "UNAVAILABLE" in msg or "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                if attempt < _MAX_RETRIES:
                    LOG.warning("Gemini transient error (attempt %d/%d), retrying in %ds: %s",
                                attempt, _MAX_RETRIES, delay, msg[:120])
                    time.sleep(delay)
                    continue
            raise
    return fn(*args, **kwargs)  # final attempt, let it raise


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str):
        try:
            from google import genai
            from google.genai import types as genai_types
        except ImportError:
            raise ImportError("pip install google-genai")

        key = resolve_api_key(
            api_key, "GOOGLE_API_KEY", "GEMINI_API_KEY",
            provider="Gemini", config_key="llm.gemini.api_key",
        )
        self._client = genai.Client(api_key=key)
        self._types = genai_types
        self.model_name = model

    def text_call(self, system: str, user: str, max_tokens: int = 1000) -> str:
        def _call():
            resp = self._client.models.generate_content(
                model=self.model_name,
                contents=user,
                config=self._types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=max_tokens,
                    temperature=0.4,
                ),
            )
            return (resp.text or "").strip()
        return self._post_process_text(_with_retry(_call))

    def json_call(
        self,
        system: str,
        user: str,
        max_tokens: int = 2000,
        *,
        schema: dict | None = None,
    ) -> dict:
        # Gemini's response_schema enforces the contract server-side. When a
        # schema is provided the API will refuse to return non-conforming
        # JSON, which catches malformed output at the wire.
        config_kwargs = dict(
            system_instruction=system,
            max_output_tokens=max_tokens,
            temperature=0.3,
            response_mime_type="application/json",
        )
        if schema is not None:
            config_kwargs["response_schema"] = schema

        def _call():
            resp = self._client.models.generate_content(
                model=self.model_name,
                contents=user,
                config=self._types.GenerateContentConfig(**config_kwargs),
            )
            return _parse_json(resp.text or "")
        return _with_retry(_call)
