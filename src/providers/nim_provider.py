"""
Nvidia NIM provider — NIM exposes an OpenAI-compatible endpoint, so we just
point the OpenAI SDK at it with a custom base_url.

Get a key at https://build.nvidia.com. Default endpoint:
    https://integrate.api.nvidia.com/v1

Recommended models by task speed:
  Fast (ranking, quick triage):  meta/llama-3.1-8b-instruct
  Capable (tailoring, letters):  meta/llama-3.1-70b-instruct
                                 nvidia/llama-3.1-nemotron-70b-instruct-hf
"""
from __future__ import annotations
import logging
import os
import time

from .base import LLMProvider, _parse_json, resolve_api_key

LOG = logging.getLogger(__name__)

# Hard timeout per request. NIM 504s at ~5 min on large prompts.
_REQUEST_TIMEOUT = 90.0   # seconds
_MAX_RETRIES = 2
_RETRY_DELAYS = [3, 10]


def _with_retry(fn, *args, **kwargs):
    """Retry on transient NIM errors (504, 429, 503)."""
    for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            msg = str(e)
            if any(sig in msg for sig in ("504", "503", "429", "timeout", "timed out")):
                if attempt <= _MAX_RETRIES:
                    LOG.warning("NIM transient error (attempt %d/%d), retrying in %ds: %s",
                                attempt, _MAX_RETRIES, delay, msg[:120])
                    time.sleep(delay)
                    continue
            raise
    return fn(*args, **kwargs)


class NIMProvider(LLMProvider):
    name = "nim"

    def __init__(self, api_key: str, base_url: str, model: str):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("pip install openai")

        key = resolve_api_key(
            api_key, "NVIDIA_API_KEY",
            provider="NIM", config_key="llm.nim.api_key",
        )
        self.client = OpenAI(
            api_key=key,
            base_url=base_url,
            timeout=_REQUEST_TIMEOUT,
        )
        self.model = model

    def text_call(self, system: str, user: str, max_tokens: int = 1000) -> str:
        def _call():
            resp = self.client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=0.4,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return (resp.choices[0].message.content or "").strip()
        return self._post_process_text(_with_retry(_call))

    def json_call(
        self,
        system: str,
        user: str,
        max_tokens: int = 2000,
        *,
        schema: dict | None = None,
    ) -> dict:
        # NIM models vary in structured-output support. Use json_schema when
        # a schema is supplied; fall through to json_object, then text parse.
        def _call():
            response_format: dict
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
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    temperature=0.3,
                    response_format=response_format,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
            except Exception:
                # Fall back to base text JSON parse if model doesn't support response_format
                return super(NIMProvider, self).json_call(
                    system, user, max_tokens, schema=schema,
                )
            return _parse_json(resp.choices[0].message.content or "")
        return _with_retry(_call)
