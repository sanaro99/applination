"""A single configured provider can repair a failed cover-letter draft."""

from src.providers.base import LLMProvider
from src.tailor import Tailor, validate_cover_letter


class _ThreeAttemptProvider(LLMProvider):
    name = "cover-test"

    def __init__(self):
        self.calls = 0
        self.last_prompt = ""

    def text_call(self, system, user, max_tokens=1000):
        self.calls += 1
        self.last_prompt = user
        if self.calls == 1:
            return ""
        if self.calls == 2:
            return "Too short."
        paragraph = (
            "Acme needs dependable software that helps engineering teams respond to production "
            "issues. I have worked on reliability problems where a clear diagnosis mattered as "
            "much as the implementation. The opportunity to apply that experience to this role "
            "is compelling because the team works on systems that people depend on every day. "
        )
        return "\n\n".join([paragraph * 2, paragraph * 2, paragraph * 2])


def test_third_attempt_revises_on_primary_when_no_fallback_provider_exists():
    provider = _ThreeAttemptProvider()
    tailor = Tailor({"cover_letter": [provider]})
    letter = tailor._cover_letter_retry_ladder("Write a letter", "For Acme", [provider])
    assert provider.calls == 3
    assert tailor.last_letter_debug["status"] == "ok"
    assert "REVISE THIS PREVIOUS DRAFT" in provider.last_prompt
    assert letter.startswith("Acme needs dependable software")


def test_complete_concise_letter_is_not_rejected_for_missing_arbitrary_padding():
    sentence = "Acme needs reliable software and I have built tools that help engineers solve production problems."
    letter = "\n\n".join([" ".join([sentence] * 4)] * 3)
    assert 160 <= len(letter.split()) < 220
    assert validate_cover_letter(letter) == []
    assert any(issue.startswith("word_count_low") for issue in validate_cover_letter(
        "\n\n".join([sentence] * 3)
    ))
