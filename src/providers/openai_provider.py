"""OpenAI provider using the Responses API."""
from __future__ import annotations

import logging
import time

from .base import LLMProvider, _parse_json, resolve_api_key

LOG = logging.getLogger(__name__)
_REQUEST_TIMEOUT = 90.0


def _with_retry(fn):
    """Retry only transient failures; credential and schema errors fail fast."""
    for attempt, delay in enumerate((2, 6), start=1):
        try:
            return fn()
        except Exception as exc:  # pragma: no cover - SDK exception classes vary
            message = str(exc).lower()
            if attempt < 2 and any(marker in message for marker in (
                "429", "500", "502", "503", "504", "timeout", "rate limit",
            )):
                LOG.warning(
                    "OpenAI transient error (attempt %d/2), retrying in %ds: %s",
                    attempt, delay, str(exc)[:120],
                )
                time.sleep(delay)
                continue
            raise
    raise RuntimeError("unreachable")


class OpenAIProvider(LLMProvider):
    """Current OpenAI Responses API adapter.

    GPT-5.6 Luna supports structured outputs, so JSON calls use a strict schema
    where the caller supplied one.  The provider is deliberately separate from
    the OpenAI-compatible Groq adapter: OpenAI's native Responses API exposes
    GPT-5.6 reasoning controls and avoids provider-specific compatibility
    assumptions.
    """

    name = "openai"

    def __init__(self, api_key: str, model: str, *, thinking: str = "on"):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise ImportError("pip install openai") from exc

        self.client = OpenAI(
            api_key=resolve_api_key(
                api_key, "OPENAI_API_KEY", provider="OpenAI",
                config_key="llm.openai.api_key",
            ),
            timeout=_REQUEST_TIMEOUT,
            max_retries=0,
        )
        self.model = model
        self.reasoning_effort = {"off": "none", "low": "low", "on": "medium"}.get(
            thinking, "medium"
        )

    def _create(self, system: str, user: str, max_tokens: int, *, text: dict | None = None):
        kwargs: dict = {
            "model": self.model,
            "instructions": system,
            "input": user,
            "max_output_tokens": max_tokens,
            "reasoning": {"effort": self.reasoning_effort},
        }
        if text is not None:
            kwargs["text"] = text
        return self.client.responses.create(**kwargs)

    def text_call(self, system: str, user: str, max_tokens: int = 1000) -> str:
        response = _with_retry(lambda: self._create(system, user, max_tokens))
        return self._post_process_text((response.output_text or "").strip())

    def json_call(
        self,
        system: str,
        user: str,
        max_tokens: int = 2000,
        *,
        schema: dict | None = None,
    ) -> dict:
        if schema is None:
            return super().json_call(system, user, max_tokens, schema=None)

        response = _with_retry(lambda: self._create(
            system,
            user,
            max_tokens,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "structured_output",
                    "schema": schema,
                    "strict": True,
                },
            },
        ))
        return _parse_json(response.output_text or "")
