"""DeepSeek v4 defaults to thinking (CoT). For simple structured tasks we can
turn it off via extra_body={"thinking": {"type": "disabled"}} — cheaper, faster,
and no CoT-eats-the-budget truncation. Verify the provider + per-task wiring.
"""
from src.providers.deepseek_provider import DeepSeekProvider, _REASONING_MAX_CAP
from src.providers.factory import get_task_chains


def test_disable_thinking_sets_toggle_and_skips_budget_headroom():
    p = DeepSeekProvider(api_key="x", model="deepseek-v4-flash", disable_thinking=True)
    assert p._extra == {"extra_body": {"thinking": {"type": "disabled"}}}
    # No CoT to make room for -> the raw request stands.
    assert p._budget(3000) == 3000
    assert p._reasoning_active() is False


def test_thinking_on_by_default_keeps_reasoning_headroom():
    p = DeepSeekProvider(api_key="x", model="deepseek-v4-flash")
    assert p._extra == {}
    # v4-flash reasons by default -> budget expanded (capped) so content survives.
    assert p._budget(6000) == _REASONING_MAX_CAP
    assert p._reasoning_active() is True


def test_task_thinking_false_propagates_to_deepseek_chain():
    cfg = {
        "primary": "deepseek",
        "fallbacks": [],
        "deepseek": {"api_key": "x", "model": "deepseek-v4-flash"},
        "tasks": {"ranking": {"thinking": False}, "tailoring": {}},
    }
    chains = get_task_chains(cfg)
    assert chains["ranking"][0].disable_thinking is True   # explicitly off
    assert chains["tailoring"][0].disable_thinking is False  # default on
