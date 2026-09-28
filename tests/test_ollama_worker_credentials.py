"""Saved credentials are protected and pairing secrets never appear in output."""
import hashlib
import json
import os
import warnings
from datetime import timedelta

import pytest

import local_ollama_worker as worker
from server.time_utils import utc_now


def test_saved_session_round_trip_without_world_readable_plaintext(tmp_path):
    path = tmp_path / "credentials" / "worker.json"
    site = "https://applination.example"
    token = "dummy-secret-session-" + "s" * 48
    expires = (utc_now() + timedelta(hours=1)).isoformat()
    worker._save_session(path, site, token, expires)
    assert worker._load_session(path, site) == {"token": token, "expires_at": expires}
    assert worker._load_session(path, "https://different.example") == {}
    if os.name == "nt":
        assert token not in path.read_text()
        assert "token" not in json.loads(path.read_text())
    else:
        assert path.stat().st_mode & 0o077 == 0
        assert path.parent.stat().st_mode & 0o077 == 0


def test_expired_legacy_and_corrupt_sessions_are_not_reused(tmp_path):
    path = tmp_path / "worker.json"
    site = "https://applination.example"
    token = "dummy-secret-session-" + "s" * 48
    path.write_text(json.dumps({"site": site, "token": token}))
    assert worker._load_session(path, site) == {}
    worker._save_session(path, site, token, (utc_now() - timedelta(seconds=1)).isoformat())
    assert worker._load_session(path, site) == {}
    path.write_text("not json")
    assert worker._load_session(path, site) == {}


@pytest.mark.skipif(os.name != "nt", reason="Windows protects sessions with DPAPI")
def test_dpapi_failure_never_saves_plaintext(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise OSError("DPAPI unavailable")

    monkeypatch.setattr(worker, "_dpapi", denied)
    path = tmp_path / "worker.json"
    with pytest.raises(OSError):
        worker._save_session(path, "https://applination.example", "private" * 8, utc_now().isoformat())
    assert not path.exists()


def test_pairing_uses_hidden_input_and_waits_for_browser_approval(monkeypatch, capsys):
    code = "dummy-pairing-code-" + "c" * 48
    token = "dummy-session-token-" + "t" * 48
    expires = (utc_now() + timedelta(hours=1)).isoformat()
    prompts, requests, approvals = [], [], [False, True]

    def hidden_input(prompt):
        prompts.append(prompt)
        return code

    def request(url, **kwargs):
        requests.append((url, kwargs))
        if url.endswith("/connect"):
            assert kwargs["token"] == code and kwargs["body"] == {}
            return {"token": token}
        assert url.endswith("/approval") and kwargs["token"] == token
        return {"approved": approvals.pop(0), "expires_at": expires}

    monkeypatch.setattr(worker.getpass, "getpass", hidden_input)
    monkeypatch.setattr(worker, "_request", request)
    monkeypatch.setattr(worker.time, "sleep", lambda _: None)
    assert worker._pair("https://applination.example") == {"token": token, "expires_at": expires}
    printed = capsys.readouterr().out
    assert code not in printed and token not in printed
    assert hashlib.sha256(token.encode()).hexdigest()[:12] in printed
    assert len(requests) == 3 and len(prompts) == 1


def test_pairing_fails_closed_if_terminal_cannot_hide_input(monkeypatch):
    def insecure_input(prompt):
        warnings.warn("Cannot hide input", worker.getpass.GetPassWarning)
        raise AssertionError("The pairing code would have been echoed")

    monkeypatch.setattr(worker.getpass, "getpass", insecure_input)
    with pytest.raises(RuntimeError, match="interactive terminal"):
        worker._pair("https://applination.example")
