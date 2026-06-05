"""
DeepSeek provider — OpenAI-compatible API.

Get a key at https://platform.deepseek.com/api_keys.
Set it in config.yaml under llm.deepseek.api_key, or as DEEPSEEK_API_KEY env var.

Recommended models:
  deepseek-chat      — DeepSeek-V3, strong reasoning + JSON, cost-effective
  deepseek-reasoner  — DeepSeek-R1, chain-of-thought (thinking tags stripped automatically)
"""
from __future__ import annotations
import logging
import os
import time

from .base import LLMProvider, _parse_json

LOG = logging.getLogger(__name__)

_BASE_URL = "https://api.deepseek.com/v1"
_REQUEST_TIMEOUT = 300.0  # reasoning models can take 2-3 minutes per call
_MAX_RETRIES = 2
_RETRY_DELAYS = [5, 15]

# Models that route through DeepSeek's reasoning pipeline. They emit CoT into
# the separate `reasoning_content` field and `content` stays empty until the
# model finishes thinking — so they need much more max_tokens headroom than a
# vanilla chat model. Detection is name-based: anything matching one of these
# substrings gets the reasoning treatment.
_REASONING_MODEL_HINTS = ("pro", "reasoner", "-r1", "thinking", "v4-pro")
# Multiplier applied to max_tokens when calling a reasoning model. CoT budgets
# of 2-5K tokens are normal, so 6x gives the model room to think AND emit JSON.
_REASONING_TOKEN_MULTIPLIER = 6
# DeepSeek v4-pro's API caps total output at 16000 tokens. Empirically, when
# we request the full cap, reasoning fills 12-14K and content stays empty.
# Setting cap to 12000 leaves ~7-8K for reasoning + ~4K for output, which
# is enough budget AND keeps a sane bound on the per-call latency.
_REASONING_MAX_CAP = 12000


def _is_reasoning_model(model: str) -> bool:
    m = (model or "").lower()
    return any(hint in m for hint in _REASONING_MODEL_HINTS)


def _budget_for(model: str, requested: int) -> int:
    if _is_reasoning_model(model):
        return min(_REASONING_MAX_CAP, max(requested * _REASONING_TOKEN_MULTIPLIER, 4000))
    return requested


def _with_retry(fn, *args, **kwargs):
    last_exc: Exception | None = None
    for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            if any(s in msg for s in ("429", "503", "502", "timeout", "timed out", "rate limit", "overloaded")):
                LOG.warning("DeepSeek transient error (attempt %d/%d), retry in %ds: %s",
                            attempt, _MAX_RETRIES, delay, str(e)[:120])
                time.sleep(delay)
                continue
            raise
    raise last_exc  # type: ignore[misc]


class DeepSeekProvider(LLMProvider):
    name = "deepseek"

    def __init__(self, api_key: str, model: str = "deepseek-chat"):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("pip install openai  # DeepSeek uses the OpenAI-compatible SDK")

        key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not key:
            raise RuntimeError(
                "DeepSeek needs an API key. Set llm.deepseek.api_key in config.yaml "
                "or the DEEPSEEK_API_KEY environment variable."
            )

        self.client = OpenAI(
            api_key=key,
            base_url=_BASE_URL,
            timeout=_REQUEST_TIMEOUT,
            # Cap SDK-internal retries so we don't compound them with our own
            # _with_retry. Previously the SDK's default exponential backoff
            # could stack with ours and turn a single failing call into a
            # 10+ minute hang.
            max_retries=1,
        )
        self.model = model
        LOG.info("DeepSeek provider initialised: model=%s", model)

    def text_call(self, system: str, user: str, max_tokens: int = 1000) -> str:
        budget = _budget_for(self.model, max_tokens)
        def _call():
            resp = self.client.chat.completions.create(
                model=self.model,
                max_tokens=budget,
                temperature=0.35,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            content = (resp.choices[0].message.content or "").strip()
            if not content and _is_reasoning_model(self.model):
                # The model spent its budget on CoT and never produced a final
                # answer. Surface this loudly so the chain falls over to the
                # next provider instead of silently returning empty text.
                raise RuntimeError(
                    f"DeepSeek reasoning model '{self.model}' returned empty content "
                    f"(budget={budget} likely consumed by reasoning_content)"
                )
            return content
        return self._post_process_text(_with_retry(_call))

    def json_call(
        self,
        system: str,
        user: str,
        max_tokens: int = 2000,
        *,
        schema: dict | None = None,
    ) -> dict:
        budget = _budget_for(self.model, max_tokens)

        # DeepSeek's OpenAI-compatible endpoint does NOT currently support the
        # strict `json_schema` response_format ("This response_format type is
        # unavailable now" -> 400). Only `json_object` is available. Use it
        # directly (temperature 0.2) so every JSON call stays on the structured,
        # low-variance path instead of 400-ing and falling back to base
        # text_call (temperature 0.35) — wasteful and noisier. The schema is
        # embedded in the prompt as a contract hint; value validation is
        # enforced in code downstream.
        sys_prompt = system
        if schema is not None:
            import json as _json
            sys_prompt = (
                system.rstrip()
                + "\n\nReturn ONLY a JSON object conforming to this schema:\n"
                + _json.dumps(schema, indent=2)[:2000]
            )

        def _call_json_mode():
            resp = self.client.chat.completions.create(
                model=self.model,
                max_tokens=budget,
                temperature=0.2,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user},
                ],
            )
            content = (resp.choices[0].message.content or "").strip()
            if not content and _is_reasoning_model(self.model):
                raise RuntimeError(
                    f"DeepSeek reasoning model '{self.model}' returned empty JSON content "
                    f"(budget={budget} likely consumed by reasoning_content)"
                )
            return _parse_json(self._post_process_text(content))

        try:
            return _with_retry(_call_json_mode)
        except Exception as e:
            LOG.debug("DeepSeek JSON mode failed (%s), falling back to text parse", e)
            return super().json_call(system, user, max_tokens, schema=schema)
