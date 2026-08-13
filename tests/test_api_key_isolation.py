"""The env-var API key fallback, and why it is off by default.

Every provider used to end with ``api_key or os.environ.get("X_API_KEY")``.
On a single-user install that is a convenience. On a multi-user one it is a
billing leak: an account that never entered a key would silently spend the
*server operator's*, because the env var belongs to the process rather than to
anyone in particular. Nothing would look wrong — the run would just work, and
the bill would arrive later.
"""
from __future__ import annotations

import pytest

from src.providers.base import (
    ALLOW_ENV_API_KEYS_VAR,
    env_api_keys_allowed,
    resolve_api_key,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv(ALLOW_ENV_API_KEYS_VAR, raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    yield


def _resolve(key: str = ""):
    return resolve_api_key(
        key, "DEEPSEEK_API_KEY",
        provider="DeepSeek", config_key="llm.deepseek.api_key",
    )


def test_env_fallback_is_off_by_default():
    assert env_api_keys_allowed() is False


def test_a_set_env_var_is_ignored_by_default(monkeypatch):
    """The regression that matters: a key in the environment must not be
    picked up on behalf of a user who has none."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-the-operators-key")
    with pytest.raises(RuntimeError) as e:
        _resolve()
    assert "sk-the-operators-key" not in str(e.value)


def test_the_error_explains_why_a_set_variable_was_ignored(monkeypatch):
    """Otherwise this is an afternoon of debugging: the variable is right
    there, exported, and apparently doing nothing."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-whatever")
    with pytest.raises(RuntimeError) as e:
        _resolve()
    msg = str(e.value)
    assert ALLOW_ENV_API_KEYS_VAR in msg
    assert "DEEPSEEK_API_KEY" in msg


def test_missing_key_error_names_the_config_field():
    with pytest.raises(RuntimeError) as e:
        _resolve()
    assert "llm.deepseek.api_key" in str(e.value)


def test_a_users_own_key_always_wins(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-operator")
    monkeypatch.setenv(ALLOW_ENV_API_KEYS_VAR, "1")
    assert _resolve("sk-mine") == "sk-mine"


@pytest.mark.parametrize("flag", ["1", "true", "TRUE", "yes", "on"])
def test_opt_in_enables_the_fallback(monkeypatch, flag):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-operator")
    monkeypatch.setenv(ALLOW_ENV_API_KEYS_VAR, flag)
    assert _resolve() == "sk-operator"


@pytest.mark.parametrize("flag", ["0", "false", "no", "off", ""])
def test_falsey_values_do_not_enable_it(monkeypatch, flag):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-operator")
    monkeypatch.setenv(ALLOW_ENV_API_KEYS_VAR, flag)
    with pytest.raises(RuntimeError):
        _resolve()


def test_every_keyed_provider_routes_through_the_gate():
    """A provider added later that hand-rolls `os.environ.get` would reopen the
    hole silently, so assert the pattern is gone from the package."""
    import pathlib
    import re

    providers_dir = pathlib.Path(__file__).resolve().parent.parent / "src" / "providers"
    offenders = []
    pattern = re.compile(r"api_key\s+or\s+os\.environ")
    for path in providers_dir.glob("*_provider.py"):
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(path.name)
    assert not offenders, (
        "these providers bypass resolve_api_key and would spend the server "
        f"owner's key for a user who has none: {offenders}"
    )
