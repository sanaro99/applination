"""
Mistral AI provider — OpenAI-compatible API endpoint.

Get a key at https://console.mistral.ai/api-keys.
Set it in config.yaml under llm.mistral.api_key, or as MISTRAL_API_KEY env var.

Recommended models:
  mistral-small-latest  — fast, cheap, good for ranking + structured JSON
  mistral-medium-latest — stronger reasoning, good for tailoring + cover letters
  open-mistral-7b       — open-weight, lowest cost
  open-mixtral-8x22b    — high-capacity MoE, best quality on free tier
"""
from __future__ import annotations
import logging
import os
import time

from .base import LLMProvider, _parse_json

LOG = logging.getLogger(__name__)

_BASE_URL = "https://api.mistral.ai/v1"
_REQUEST_TIMEOUT = 90.0
_MAX_RETRIES = 2
_RETRY_DELAYS = [5, 15]


def _with_retry(fn, *args, **kwargs):
    last_exc: Exception | None = None
    for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            if any(s in msg for s in ("429", "503", "502", "timeout", "timed out", "rate limit", "unavailable")):
                LOG.warning("Mistral transient error (attempt %d/%d), retry in %ds: %s",
                            attempt, _MAX_RETRIES, delay, str(e)[:120])
                time.sleep(delay)
                continue
            raise
    raise last_exc  # type: ignore[misc]


class MistralProvider(LLMProvider):
    name = "mistral"

    def __init__(self, api_key: str, model: str = "mistral-small-latest"):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("pip install openai  # Mistral uses an OpenAI-compatible API")

        key = api_key or os.environ.get("MISTRAL_API_KEY", "")
        if not key:
            raise RuntimeError(
                "Mistral needs an API key. Set llm.mistral.api_key in config.yaml "
                "or the MISTRAL_API_KEY environment variable."
            )

        self.client = OpenAI(
            api_key=key,
            base_url=_BASE_URL,
            timeout=_REQUEST_TIMEOUT,
        )
        self.model = model
        LOG.info("Mistral provider initialised: model=%s", model)

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
        # Mistral's chat.completions accepts a JSON schema directly under
        # response_format with type=json_schema. SDK key name varies by
        # version — current mistralai>=1.0 uses {"type":"json_schema",
        # "json_schema":{"schema": <schema>, ...}}. If the SDK rejects this
        # format (422 Unprocessable Entity), we fall back to json_object
        # via the outer try / base.json_call layer.
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
            return _parse_json(self._post_process_text((resp.choices[0].message.content or "").strip()))

        try:
            return _with_retry(_call_json_mode)
        except Exception as e:
            LOG.debug("Mistral JSON mode failed (%s), falling back to text parse", e)
            return super().json_call(system, user, max_tokens, schema=schema)
