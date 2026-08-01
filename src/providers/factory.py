"""
Factory that builds the right LLMProvider from config.

Usage:
    provider = get_provider("claude", cfg["llm"])
    provider = get_provider_with_fallback(cfg["llm"])
    provider_chain = get_provider_chain(cfg["llm"])   # list for per-call fallback
    task_chains  = get_task_chains(cfg["llm"])        # per-task provider chains
    try_chain(chain, fn)                              # one-shot per-call fallback
"""
from __future__ import annotations
import logging
from typing import Any, Callable

from .base import LLMProvider

LOG = logging.getLogger(__name__)

# Errors that indicate a provider is quota-exhausted or unavailable at the
# call level (not just at init time) — triggers per-call fallback.
_QUOTA_SIGNALS = ("429", "quota", "resource_exhausted", "503", "unavailable", "504", "timeout", "timed out")

# Providers we've already logged as unavailable this process. A partially
# configured chain (e.g. `claude` left in the global fallbacks with no API key)
# would otherwise emit one WARNING per task chain built — ~13 identical lines
# every run. Dedupe to one WARNING per provider; repeats drop to DEBUG.
_warned_unavailable: set[str] = set()


def _warn_unavailable(name: str, exc: Exception) -> None:
    """Warn once per unavailable provider per process; DEBUG thereafter."""
    if name in _warned_unavailable:
        LOG.debug("Provider '%s' unavailable (already reported): %s", name, exc)
        return
    _warned_unavailable.add(name)
    LOG.warning(
        "Provider '%s' unavailable — excluded from provider chains this run: %s",
        name, exc,
    )

# Recognized task names for per-task provider configuration.
# `tailoring_premium` is the optional reasoning-model chain used for the
# top-N ranked jobs; standard `tailoring` is the fast/cheap default.
_TASK_NAMES = (
    "ranking", "tailoring", "tailoring_premium", "cover_letter",
    "critique", "answer_questions",
    # `relinefit` is the Tier-2 LLM rescue that rewrites bullets to hit exact
    # character-count line budgets. It wants a STRONG model (inherits the global
    # primary, usually deepseek) but NOT chain-of-thought — CoT burns the budget
    # on a bounded mechanical rewrite and returns empty content. Defaults to
    # thinking OFF (see _THINKING_OFF_BY_DEFAULT).
    "relinefit",
    # Prepwork + content-studio tasks. Inherit the global primary/fallbacks
    # until configured under llm.tasks.<name>.
    "coach", "interview", "essay", "content_studio",
)

# Tasks whose chain-of-thought hurts more than it helps: bounded, mechanical
# rewrites where DeepSeek v4 reasoning models spend their whole token budget on
# CoT and return empty content. These default to thinking OFF; a user can still
# force it on per task via `llm.tasks.<task>.thinking: true`.
_THINKING_OFF_BY_DEFAULT = frozenset({"relinefit"})


def get_provider(
    name: str,
    llm_cfg: dict,
    *,
    model_override: str | None = None,
    disable_thinking: bool = False,
) -> LLMProvider:
    """Construct a provider by name.

    `model_override` lets a per-task config swap the default model for that
    provider on a single call site (e.g., critique uses deepseek-v4-flash while
    tailoring keeps deepseek-v4-pro).

    `disable_thinking` turns off chain-of-thought for providers that support a
    non-thinking mode (currently DeepSeek v4). Ignored by providers without one.
    """
    name = name.lower().strip()
    sub = llm_cfg.get(name, {}) or {}

    def _model(default: str) -> str:
        return model_override or sub.get("model", default)

    if name == "claude":
        from .claude_provider import ClaudeProvider
        return ClaudeProvider(
            api_key=sub.get("api_key", ""),
            model=_model("claude-haiku-4-5-20251001"),
        )

    if name == "gemini":
        from .gemini_provider import GeminiProvider
        return GeminiProvider(
            api_key=sub.get("api_key", ""),
            model=_model("gemini-2.0-flash"),
        )

    if name == "ollama":
        from .ollama_provider import OllamaProvider
        return OllamaProvider(
            base_url=sub.get("base_url", "http://localhost:11434"),
            model=_model("llama3.2"),
        )

    if name == "nim":
        from .nim_provider import NIMProvider
        return NIMProvider(
            api_key=sub.get("api_key", ""),
            base_url=sub.get("base_url", "https://integrate.api.nvidia.com/v1"),
            model=_model("meta/llama-3.1-70b-instruct"),
        )

    if name == "openrouter":
        from .openrouter_provider import OpenRouterProvider
        return OpenRouterProvider(
            api_key=sub.get("api_key", ""),
            model=_model("tencent/hunyuan-a13b-instruct:free"),
            site_url=sub.get("site_url", ""),
            site_name=sub.get("site_name", "internship_bot"),
        )

    if name == "deepseek":
        from .deepseek_provider import DeepSeekProvider
        return DeepSeekProvider(
            api_key=sub.get("api_key", ""),
            model=_model("deepseek-v4-flash"),
            disable_thinking=disable_thinking,
        )

    if name == "mistral":
        from .mistral_provider import MistralProvider
        return MistralProvider(
            api_key=sub.get("api_key", ""),
            model=_model("mistral-small-latest"),
        )

    raise ValueError(
        f"Unknown provider '{name}'. Options: claude, gemini, ollama, nim, openrouter, deepseek, mistral."
    )


def get_provider_with_fallback(llm_cfg: dict) -> LLMProvider:
    """Try primary, then each fallback in order. Returns first working provider."""
    primary = llm_cfg.get("primary", "claude")
    fallbacks = llm_cfg.get("fallbacks", []) or []

    errors = []
    for name in [primary, *fallbacks]:
        try:
            p = get_provider(name, llm_cfg)
            LOG.info("Using LLM provider: %s", p.name)
            return p
        except Exception as e:
            LOG.warning("Provider '%s' unavailable: %s", name, e)
            errors.append(f"{name}: {e}")
    raise RuntimeError(
        "No LLM provider available. Errors:\n  " + "\n  ".join(errors)
    )


def get_provider_chain(llm_cfg: dict) -> list[LLMProvider]:
    """Return all working providers in priority order (primary first, then fallbacks).

    Used to enable per-call fallback: if the primary hits a quota error mid-run,
    the caller can switch to the next provider in the chain.
    """
    primary = llm_cfg.get("primary", "claude")
    fallbacks = llm_cfg.get("fallbacks", []) or []
    chain: list[LLMProvider] = []

    for name in [primary, *fallbacks]:
        try:
            p = get_provider(name, llm_cfg)
            chain.append(p)
        except Exception as e:
            _warn_unavailable(name, e)

    if not chain:
        raise RuntimeError("No LLM providers available. Check API keys in config.yaml.")

    LOG.info("Provider chain: %s", [p.name for p in chain])
    return chain


def is_quota_error(exc: Exception) -> bool:
    """Return True if this exception looks like a quota/rate-limit/unavailable error."""
    msg = str(exc).lower()
    return any(sig in msg for sig in _QUOTA_SIGNALS)


def try_chain(
    chain: list[LLMProvider],
    fn: Callable[[LLMProvider], Any],
    *,
    any_error: bool = False,
    task_name: str = "",
) -> Any:
    """Call fn(provider) against each provider in chain until one succeeds.

    Args:
        chain:      Ordered list of providers to try (primary first).
        fn:         Callable that takes a single LLMProvider and returns a result.
                    Should raise on failure.
        any_error:  If True, retry the next provider on ANY exception (useful when
                    some models return malformed output rather than HTTP errors).
                    If False (default), only retry on quota/rate-limit signals.
        task_name:  Label used in log messages only.

    Returns the first successful fn(provider) result.
    Raises the last exception if all providers fail.
    """
    last_exc: Exception | None = None
    for provider in chain:
        try:
            return fn(provider)
        except Exception as e:
            if any_error or is_quota_error(e):
                LOG.warning(
                    "%s failed on provider '%s' (%s) — trying next in chain",
                    task_name or "call", provider.name, str(e)[:120],
                )
                last_exc = e
                continue
            raise  # non-retryable — propagate immediately
    if last_exc:
        raise last_exc
    raise RuntimeError(f"Provider chain is empty for task '{task_name}'")


def get_task_chains(llm_cfg: dict) -> dict[str, list[LLMProvider]]:
    """Build per-task provider chains from config.

    For each task, uses the task-specific primary/fallbacks defined under
    ``llm.tasks.<task_name>`` if present; otherwise falls back to the global
    ``llm.primary`` / ``llm.fallbacks`` values.

    Returns a dict keyed by task name, each value is a non-empty list of
    LLMProvider instances in priority order.
    """
    global_primary = llm_cfg.get("primary", "claude")
    global_fallbacks = llm_cfg.get("fallbacks", []) or []
    tasks_cfg = llm_cfg.get("tasks", {}) or {}

    result: dict[str, list[LLMProvider]] = {}
    for task in _TASK_NAMES:
        task_cfg = tasks_cfg.get(task, {}) or {}
        primary = task_cfg.get("primary", global_primary)
        fallbacks = task_cfg.get("fallbacks", global_fallbacks) or []
        # `models: {provider_name: model_id}` lets a task pin a non-default model
        # for one or more providers (e.g. use deepseek-v4-flash for critique while
        # tailoring keeps the slower deepseek-v4-pro). Falls back to the
        # top-level llm.<provider>.model when unset.
        model_overrides = task_cfg.get("models", {}) or {}
        # `thinking: false` disables chain-of-thought for this task's providers
        # (DeepSeek v4 supports a non-thinking mode). Best for simple, structured
        # tasks where CoT adds cost/latency without quality. Defaults to on for
        # most tasks; tasks in _THINKING_OFF_BY_DEFAULT default to off (a user
        # can still re-enable them with `thinking: true`).
        thinking_default = task not in _THINKING_OFF_BY_DEFAULT
        disable_thinking = task_cfg.get("thinking", thinking_default) is False

        chain: list[LLMProvider] = []
        for name in [primary, *fallbacks]:
            try:
                chain.append(get_provider(
                    name, llm_cfg,
                    model_override=model_overrides.get(name),
                    disable_thinking=disable_thinking,
                ))
            except Exception as e:
                _warn_unavailable(name, e)

        if not chain:
            raise RuntimeError(
                f"No LLM providers available for task '{task}'. "
                "Check API keys in config.yaml."
            )

        LOG.info("Task '%s' chain: %s", task, [p.name for p in chain])
        result[task] = chain

    return result
