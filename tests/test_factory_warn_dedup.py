"""A provider left in the chain config without credentials (e.g. `claude` in the
global fallbacks with no API key) must be reported ONCE per process, not once
per task chain — which previously spammed ~13 identical WARNING lines into every
run log.
"""
import logging

import src.providers.factory as factory
from src.providers.factory import get_task_chains


def test_unavailable_provider_warns_once(monkeypatch, caplog):
    # Reset the process-level dedup set so the test is order-independent.
    factory._warned_unavailable.clear()

    def fake_get_provider(name, cfg, **kwargs):
        if name == "claude":
            raise RuntimeError("Claude provider needs an API key.")

        class _P:
            pass

        p = _P()
        p.name = name
        return p

    monkeypatch.setattr(factory, "get_provider", fake_get_provider)

    # Every task inherits the global fallbacks -> claude appears in all ~10 task
    # chains, so the un-deduped code would warn once per task.
    cfg = {"primary": "deepseek", "fallbacks": ["claude"]}
    with caplog.at_level(logging.WARNING, logger="src.providers.factory"):
        chains = get_task_chains(cfg)

    # Chains still build correctly around the unavailable provider.
    assert chains["ranking"][0].name == "deepseek"

    claude_warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "claude" in r.getMessage().lower()
    ]
    assert len(claude_warnings) == 1, (
        f"expected exactly one claude-unavailable warning, got {len(claude_warnings)}"
    )
