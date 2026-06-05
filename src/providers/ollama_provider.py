"""
Ollama provider — hits a local Ollama server at http://localhost:11434.

Install Ollama from https://ollama.com and pull a model:
    ollama pull llama3.2
    ollama pull qwen2.5:14b      # if you have the RAM
"""
from __future__ import annotations
import json
import logging

import requests

from .base import LLMProvider, _parse_json

LOG = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: int = 180):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def _chat(self, system: str, user: str, format_json: bool, max_tokens: int) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": 0.4},
        }
        if format_json:
            payload["format"] = "json"   # Ollama's native JSON mode

        try:
            r = requests.post(
                f"{self.base_url}/api/chat", json=payload, timeout=self.timeout,
            )
            r.raise_for_status()
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(
                f"Could not reach Ollama at {self.base_url}. "
                f"Is the server running? ('ollama serve' or the desktop app)"
            ) from e

        data = r.json()
        return (data.get("message", {}).get("content") or "").strip()

    def text_call(self, system: str, user: str, max_tokens: int = 1000) -> str:
        return self._post_process_text(
            self._chat(system, user, format_json=False, max_tokens=max_tokens)
        )

    def json_call(
        self,
        system: str,
        user: str,
        max_tokens: int = 2000,
        *,
        schema: dict | None = None,
    ) -> dict:
        # Ollama's native JSON mode constrains generation to valid JSON but
        # doesn't enforce a custom schema at the wire. When a schema is
        # supplied, fall through to the base implementation which embeds the
        # schema as a contract hint in the system prompt.
        if schema is not None:
            return super().json_call(system, user, max_tokens, schema=schema)
        raw = self._chat(system, user, format_json=True, max_tokens=max_tokens)
        return _parse_json(raw)
