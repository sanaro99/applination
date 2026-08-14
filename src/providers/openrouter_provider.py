"""
OpenRouter provider — routes to 300+ models through a single OpenAI-compatible API.

Get a free key at https://openrouter.ai/keys.
Set it in config.yaml under llm.openrouter.api_key, or as OPENROUTER_API_KEY env var.

Recommended free models (2026):
  tencent/hunyuan-a13b-instruct:free  — Hunyuan A13B (Hy3 preview), good at structured JSON
  google/gemma-3-27b-it:free          — Gemma 3 27B instruction-tuned
  meta-llama/llama-4-scout:free       — Llama 4 Scout
  mistralai/mistral-7b-instruct:free  — Mistral 7B (fast, lightweight)

JSON mode compatibility: OpenRouter passes response_format through to the upstream
model if it supports it; silently falls back to a text parse when it doesn't.
"""
from __future__ import annotations
import logging
import os
import time

from .base import LLMProvider, _parse_json, resolve_api_key

LOG = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 120.0
_MAX_RETRIES = 2
_RETRY_DELAYS = [5, 15]

_OR_BASE_URL = "https://openrouter.ai/api/v1"


def _with_retry(fn, *args, **kwargs):
    last_exc: Exception | None = None
    for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            if any(s in msg for s in ("429", "503", "502", "timeout", "timed out", "rate limit",
                                      "no choices", "unavailable")):
                LOG.warning("OpenRouter transient error (attempt %d/%d), retry in %ds: %s",
                            attempt, _MAX_RETRIES, delay, str(e)[:120])
                time.sleep(delay)
                continue
            raise
    raise last_exc  # type: ignore[misc]


class OpenRouterProvider(LLMProvider):
    name = "openrouter"

    def __init__(self, api_key: str, model: str,
                 site_url: str = "", site_name: str = "internship_bot"):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("pip install openai  # OpenRouter uses the OpenAI SDK")

        key = resolve_api_key(
            api_key, "OPENROUTER_API_KEY",
            provider="OpenRouter", config_key="llm.openrouter.api_key",
        )

        default_headers: dict[str, str] = {}
        if site_url:
            default_headers["HTTP-Referer"] = site_url
        if site_name:
            default_headers["X-Title"] = site_name

        self.client = OpenAI(
            api_key=key,
            base_url=_OR_BASE_URL,
            timeout=_REQUEST_TIMEOUT,
            default_headers=default_headers or None,
        )
        self.model = model
        LOG.info("OpenRouter provider initialised: model=%s", model)

    @staticmethod
    def _extract_content(resp) -> str:
        """Safely extract text from a chat completion response.

        OpenRouter occasionally returns resp.choices = None (not an empty list)
        instead of raising an HTTP error. Guard against that here so callers
        get a RuntimeError they can retry/fallback on rather than a TypeError.
        """
        choices = getattr(resp, "choices", None) or []
        if not choices:
            finish = getattr(resp, "finish_reason", None) or ""
            raise RuntimeError(
                f"OpenRouter returned no choices (finish_reason={finish!r}). "
                "Model may be unavailable or rate-limited."
            )
        return (choices[0].message.content or "").strip()

    def text_call(self, system: str, user: str, max_tokens: int = 1000) -> str:
        def _call():
            resp = self.client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=0.35,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return self._extract_content(resp)
        return self._post_process_text(_with_retry(_call))

    def json_call(
        self,
        system: str,
        user: str,
        max_tokens: int = 2000,
        *,
        schema: dict | None = None,
    ) -> dict:
        """Try JSON mode first; fall back to text parse if the model rejects it."""
        if schema is not None:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_output",
                    "schema": schema,
                    "strict": True,
                },
            }
        else:
            response_format = {"type": "json_object"}

        def _call_json_mode():
            resp = self.client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=0.2,
                response_format=response_format,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return _parse_json(self._post_process_text(self._extract_content(resp)))

        try:
            return _with_retry(_call_json_mode)
        except Exception as e:
            # Many free models don't support response_format=json_object.
            # Fall back to the base class text+parse path.
            LOG.debug("OpenRouter JSON mode failed (%s), falling back to text parse", e)
            return super().json_call(system, user, max_tokens, schema=schema)
