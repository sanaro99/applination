"""Claude provider — uses the Anthropic SDK directly."""
from __future__ import annotations
import json
import logging
import os

from .base import LLMProvider, _parse_json

LOG = logging.getLogger(__name__)


class ClaudeProvider(LLMProvider):
    name = "claude"

    def __init__(self, api_key: str, model: str):
        try:
            from anthropic import Anthropic
        except ImportError:
            raise ImportError("pip install anthropic")

        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise RuntimeError(
                "Claude provider needs an API key. Set llm.claude.api_key in "
                "config.yaml or the ANTHROPIC_API_KEY env var."
            )
        self.client = Anthropic(api_key=key)
        self.model = model

    def text_call(self, system: str, user: str, max_tokens: int = 1000) -> str:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw = "".join(
            b.text for b in msg.content if getattr(b, "type", "") == "text"
        ).strip()
        return self._post_process_text(raw)

    def json_call(
        self,
        system: str,
        user: str,
        max_tokens: int = 2000,
        *,
        schema: dict | None = None,
    ) -> dict:
        # When a schema is supplied, use Anthropic's tool_use pattern: define
        # a tool whose input_schema matches our schema, then force the model
        # to call it (`tool_choice={"type":"tool","name":...}`). Claude
        # guarantees the tool_use block's `input` field validates against the
        # schema, eliminating JSON parse errors.
        if schema is not None:
            tools = [{
                "name": "emit_structured_response",
                "description": (
                    "Emit the final structured response. Always call this tool "
                    "exactly once with the answer."
                ),
                "input_schema": schema,
            }]
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                tools=tools,
                tool_choice={"type": "tool", "name": "emit_structured_response"},
                messages=[{"role": "user", "content": user}],
            )
            for block in msg.content:
                if getattr(block, "type", "") == "tool_use":
                    return dict(block.input)
            # tool_choice forces a tool call; reaching here means a protocol
            # break. Fall back to text-parse with a strong directive.
            LOG.warning("Claude tool_use returned no tool_use block; falling back to text parse")

        # No schema (or tool_use missing) — use text JSON parsing.
        strict = system.rstrip() + (
            "\n\nReturn ONLY a valid JSON object. No prose, no code fences. "
            "Start with { and end with }."
        )
        raw = self.text_call(strict, user, max_tokens=max_tokens)
        return _parse_json(raw)
