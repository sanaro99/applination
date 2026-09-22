"""Workflow chains fall through on provider-specific failures, not only quota errors."""
from __future__ import annotations

from src.providers.base import LLMProvider
from src.tailor import Tailor


class _InvalidKey(LLMProvider):
    name = "deepseek"

    def text_call(self, system, user, max_tokens=1000):
        raise RuntimeError("401 invalid API key")

    def json_call(self, system, user, max_tokens=2000, *, schema=None):
        raise RuntimeError("401 invalid API key")


class _RankingFallback(LLMProvider):
    name = "groq"

    def text_call(self, system, user, max_tokens=1000):
        return "ok"

    def json_call(self, system, user, max_tokens=2000, *, schema=None):
        return {"scores": [{"idx": 0, "score": 87, "reason": "Relevant evidence."}]}


def test_ranking_falls_back_when_primary_key_is_invalid():
    tailor = Tailor({"ranking": [_InvalidKey(), _RankingFallback()]})

    result = tailor.rank_jobs(
        [{"title": "Backend Engineer", "company": "Acme", "desc": "Python APIs"}],
        "Software engineer with Python experience.",
    )

    assert result[0]["score"] == 87
    assert result[0]["reason"] == "Relevant evidence."
