"""deepseek-v4-flash is a REASONING model: every call emits reasoning_content
(chain-of-thought) that consumes the token budget before the visible content.
It must be recognized as such so _budget_for() grants headroom; otherwise a
small max_tokens (e.g. the critique call's 500) is fully consumed by CoT and
`content` comes back empty/truncated -> "JSON parse failed" -> retry.

Regression for: recurring parse-failed retries on the default DeepSeek path.
"""
from src.providers.deepseek_provider import (
    _is_reasoning_model,
    _budget_for,
    _REASONING_MAX_CAP,
)


def test_v4_flash_is_recognized_as_reasoning():
    assert _is_reasoning_model("deepseek-v4-flash") is True


def test_v4_pro_still_reasoning():
    assert _is_reasoning_model("deepseek-v4-pro") is True


def test_flash_gets_headroom_for_a_tiny_request():
    # The critique call requests only 500 tokens; CoT alone exceeds that, so
    # the effective budget must be expanded well above the raw request.
    assert _budget_for("deepseek-v4-flash", 500) >= 3000


def test_flash_budget_is_capped():
    # A large request is clamped to the reasoning cap, not multiplied unbounded.
    assert _budget_for("deepseek-v4-flash", 6000) == _REASONING_MAX_CAP


def test_gemini_flash_not_mistaken_for_reasoning():
    # The hint must be specific to DeepSeek v4, not the bare word "flash",
    # or a non-deepseek "*-flash" model would be misclassified.
    assert _is_reasoning_model("gemini-2.5-flash") is False


def test_plain_chat_model_budget_unchanged():
    assert _budget_for("some-non-reasoning-chat", 3000) == 3000
