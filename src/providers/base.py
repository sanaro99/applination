"""
Common interface for every LLM provider.

Each provider implements two methods:
  - text_call(system, user, max_tokens) -> str
  - json_call(system, user, max_tokens) -> dict

JSON calls are expected to return a parseable JSON object (we handle fence
stripping and retries in _parse_json).

All providers MUST run their raw text response through ``_post_process_text``
before returning it. The post-processor strips reasoning-mode XML tags
(<think>, <thinking>, <reasoning>, <analysis>) so chain-of-thought from
reasoning models never leaks into rendered documents.
"""
from __future__ import annotations
import json
import logging
import re

_TRAILING_COMMA_RE = re.compile(r",\s*([\]}])")

# Reasoning-mode tags from open-source reasoning models (DeepSeek R1/V4,
# Qwen3 Thinking, GLM-4 Reasoning, etc.). Stripping these here protects the
# entire downstream pipeline from CoT contamination regardless of which
# provider is active.
_THINKING_TAG_RE = re.compile(
    r"<\s*(think|thinking|reasoning|analysis|scratchpad|reflection)\s*>.*?<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
# A truncated thinking block (no closing tag) means the model hit max_tokens
# while still inside the reasoning section. Drop everything from the opening
# tag forward; the caller's retry ladder will re-issue with more headroom.
_OPEN_THINKING_TAG_RE = re.compile(
    r"<\s*(think|thinking|reasoning|analysis|scratchpad|reflection)\s*>.*$",
    re.IGNORECASE | re.DOTALL,
)

from abc import ABC, abstractmethod

LOG = logging.getLogger(__name__)


def _strip_thinking_tags(text: str) -> str:
    """Remove <think>/<thinking>/<reasoning>/<analysis> blocks from a model response.

    Handles both well-formed (closed) blocks and the truncated case where the
    model ran out of tokens while still inside the block. Returns the text
    with all reasoning content removed and surrounding whitespace collapsed.
    """
    if not text or "<" not in text:
        return text
    out = _THINKING_TAG_RE.sub("", text)
    out = _OPEN_THINKING_TAG_RE.sub("", out)
    return out.strip()


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def text_call(self, system: str, user: str, max_tokens: int = 1000) -> str:
        ...

    def _post_process_text(self, raw: str) -> str:
        """Universal post-processor — every provider should run text through this.

        Right now the only job is stripping reasoning-tag blocks. Centralized
        so future global text fixes (e.g. zero-width-character normalization)
        live in one place rather than scattered across providers.
        """
        return _strip_thinking_tags(raw or "")

    def json_call(
        self,
        system: str,
        user: str,
        max_tokens: int = 2000,
        *,
        schema: dict | None = None,
    ) -> dict:
        """Default: call text_call with a JSON-only instruction and parse.

        Args:
            schema: Optional JSON schema. Provider subclasses that support
                strict structured outputs (DeepSeek json_schema, Mistral
                json_schema, Gemini response_schema, Claude tool_use) should
                pass this through to the API. Subclasses that don't support
                it can either ignore or inject the schema as text context.
                The base implementation embeds it as a contract hint.
        """
        strict_system = (
            system.rstrip()
            + "\n\nReturn ONLY a valid JSON object. No prose before or after. "
              "No markdown code fences. Start your response with { and end with }."
        )
        if schema is not None:
            import json as _json
            strict_system += (
                f"\n\nThe JSON object MUST conform to this schema:\n"
                f"{_json.dumps(schema, indent=2)[:2000]}"
            )
        raw = self.text_call(strict_system, user, max_tokens=max_tokens)
        return _parse_json(raw)


def _parse_json(raw: str) -> dict:
    """Robust JSON parsing: strips code fences, finds JSON span, handles junk."""
    text = raw.strip()

    # Strip code fences
    if text.startswith("```"):
        # Drop the opening fence line
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()

    # If there's still text before/after the JSON, extract the first {...} block
    if not text.startswith("{"):
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            text = m.group(0)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Attempt recovery: if the JSON is truncated (LLM hit max_tokens), try to close
    # any open brackets/braces so the partial JSON becomes parseable.
    recovered = _close_truncated_json(text)
    if recovered != text:
        # Also strip trailing commas — truncation often leaves a dangling comma
        # before the injected closing bracket, e.g. ["x", ]} which is invalid.
        cleaned = _TRAILING_COMMA_RE.sub(r"\1", recovered)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

    LOG.error("JSON parse failed. First 400 chars: %s", raw[:400])
    raise RuntimeError(f"Provider returned invalid JSON (truncated or malformed)")


def _close_truncated_json(text: str) -> str:
    """Best-effort recovery: close open string literals and bracket/brace pairs."""
    depth_brace = 0
    depth_bracket = 0
    in_string = False
    escape = False

    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth_brace += 1
        elif ch == "}":
            depth_brace = max(0, depth_brace - 1)
        elif ch == "[":
            depth_bracket += 1
        elif ch == "]":
            depth_bracket = max(0, depth_bracket - 1)

    # If still inside a string, close it
    suffix = ""
    if in_string:
        suffix += '"'
    # Close any open array/object nesting (innermost first)
    suffix += "]" * depth_bracket + "}" * depth_brace
    return text + suffix if suffix else text
