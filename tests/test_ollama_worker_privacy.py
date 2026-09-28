"""The official worker must not send a private prompt to Ollama cloud aliases."""
import pytest

import local_ollama_worker as worker


def test_model_inventory_excludes_cloud_models_and_remote_aliases(monkeypatch):
    monkeypatch.setattr(worker, "_request", lambda *args, **kwargs: {"models": [
        {"name": "llama3.2:latest"},
        {"name": "qwen:cloud"},
        {"name": "qwen:480b-cloud"},
        {"name": "looks-local:latest", "remote_host": "https://ollama.com"},
        {"name": "other-alias:latest", "remote_model": "qwen:cloud"},
    ]})
    assert worker._local_models("http://127.0.0.1:11434") == {"llama3.2:latest"}


def test_remote_alias_is_rechecked_before_the_prompt_is_sent(monkeypatch):
    calls = []

    def request(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/api/tags"):
            return {"models": [{"name": "friendly-alias:latest"}]}
        if url.endswith("/api/show"):
            return {"remote_host": "https://ollama.com", "remote_model": "qwen:cloud"}
        return {"message": {"content": "cloud answer"}}

    monkeypatch.setattr(worker, "_request", request)
    with pytest.raises(RuntimeError, match="cloud|remote"):
        worker._generate("http://127.0.0.1:11434", {
            "model": "friendly-alias:latest", "system": "private", "user": "private resume",
            "max_tokens": 100, "format_json": False,
        })
    assert all(not url.endswith("/api/chat") for url, _ in calls)
    assert "private resume" not in str(calls)


def test_rejected_output_finishes_task_with_error_instead_of_waiting_for_timeout(monkeypatch):
    submissions = []

    def request(url, **kwargs):
        submissions.append(kwargs["body"])
        if len(submissions) == 1:
            raise RuntimeError("HTTP 422: response must be valid JSON")
        return {"ok": True}

    monkeypatch.setattr(worker, "_generate", lambda *args: "invalid response")
    monkeypatch.setattr(worker, "_request", request)
    monkeypatch.setattr(worker, "_heartbeat", lambda *args: None)
    worker._run_task("https://applination.example", "private-worker-key", "http://127.0.0.1:11434", {
        "id": "task", "lease": "lease", "payload": {"model": "llama3.2"},
    })
    assert len(submissions) == 2
    assert submissions[1]["lease"] == "lease" and submissions[1]["error"]
    assert "content" not in submissions[1]
