"""Cloudflare Workers AI provider via its OpenAI-compatible endpoint."""
from __future__ import annotations

import logging
import time

from .base import LLMProvider, _parse_json, resolve_api_key

LOG = logging.getLogger(__name__)
_REQUEST_TIMEOUT = 90.0


def _with_retry(fn):
    last: Exception | None = None
    for attempt in range(1, 4):
        try:
            return fn()
        except Exception as exc:  # pragma: no cover - SDK errors vary by version
            last = exc
            message = str(exc).lower()
            if attempt < 3 and any(marker in message for marker in ("429", "503", "504", "timeout", "rate limit")):
                delay = 2 if attempt == 1 else 6
                LOG.warning("Cloudflare transient error (attempt %d/3), retrying in %ds: %s", attempt, delay, str(exc)[:120])
                time.sleep(delay)
                continue
            raise
    raise last  # type: ignore[misc]


class CloudflareProvider(LLMProvider):
    name = "cloudflare"

    def __init__(self, api_token: str, account_id: str, model: str):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise ImportError("pip install openai") from exc
        if not account_id.strip():
            raise RuntimeError("Cloudflare needs llm.cloudflare.account_id in your config.")
        token = resolve_api_key(
            api_token, "CLOUDFLARE_API_TOKEN", provider="Cloudflare",
            config_key="llm.cloudflare.api_token",
        )
        self.client = OpenAI(
            api_key=token,
            base_url=f"https://api.cloudflare.com/client/v4/accounts/{account_id.strip()}/ai/v1",
            timeout=_REQUEST_TIMEOUT,
        )
        self.model = model

    def text_call(self, system: str, user: str, max_tokens: int = 1000) -> str:
        def call():
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.3,
                max_tokens=max_tokens,
            )
            return (response.choices[0].message.content or "").strip()
        return self._post_process_text(_with_retry(call))

    def json_call(self, system: str, user: str, max_tokens: int = 2000, *, schema: dict | None = None) -> dict:
        def call():
            response_format: dict = {"type": "json_object"}
            if schema is not None:
                response_format = {
                    "type": "json_schema",
                    "json_schema": {"name": "structured_output", "schema": schema, "strict": True},
                }
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    temperature=0.2,
                    max_tokens=max_tokens,
                    response_format=response_format,
                )
            except Exception:
                return super(CloudflareProvider, self).json_call(system, user, max_tokens, schema=schema)
            return _parse_json(response.choices[0].message.content or "")
        return _with_retry(call)
