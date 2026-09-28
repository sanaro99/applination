"""The local worker can answer only its owner's queued model requests."""
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
import pytest

import server.db as db
from .conftest import make_engine, register


def test_local_worker_round_trip_and_tenant_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app
    from server.deps import load_config
    from src.providers import get_provider

    with TestClient(app) as owner, TestClient(app) as other, TestClient(app) as worker:
        owner_id = register(owner, "local-owner@example.com")["id"]
        register(other, "local-other@example.com")
        assert owner.put("/api/onboarding/provider", json={"provider": "ollama"}).status_code == 200
        llm = load_config(owner_id)["llm"]
        assert llm["ollama"]["transport"] == "worker"
        assert llm["primary"] == "ollama"
        assert llm["fallbacks"] == [] and llm["tasks"] == {}
        assert worker.get("/api/local-ollama/status").status_code == 401
        token = owner.post("/api/local-ollama/tokens").json()["token"]
        other_token = other.post("/api/local-ollama/tokens").json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        other_headers = {"Authorization": f"Bearer {other_token}"}
        grant_id = owner.get("/api/local-ollama/status").json()["workers"][0]["id"]
        assert other.delete(f"/api/local-ollama/tokens/{grant_id}").status_code == 404
        assert worker.get("/api/local-ollama/worker/next").status_code == 401
        assert worker.get("/api/applications", headers=headers).status_code == 401
        assert worker.get("/api/local-ollama/worker/next", headers=headers).json() == {"task": None}
        assert owner.get("/api/local-ollama/status").json()["online"] is True

        provider = get_provider("ollama", llm, user_id=owner_id)
        with ThreadPoolExecutor(max_workers=1) as pool:
            reply = pool.submit(provider.text_call, "System instructions", "User prompt", 19)
            task = worker.get("/api/local-ollama/worker/next", headers=headers).json()["task"]
            assert task["payload"] == {
                "model": "llama3.2", "system": "System instructions",
                "user": "User prompt", "max_tokens": 19, "format_json": False,
            }
            url = f"/api/local-ollama/worker/tasks/{task['id']}/result"
            assert worker.post(url, headers=other_headers,
                               json={"lease": task["lease"], "content": "stolen"}).status_code == 404
            assert worker.post(url, headers=headers,
                               json={"lease": "x" * 32, "content": "stolen"}).status_code == 404
            assert worker.post(url, headers=headers,
                               json={"lease": task["lease"], "content": "Local answer"}).status_code == 200
            assert reply.result(timeout=5) == "Local answer"

        pairing = worker.post("/api/extension/pair/start").json()
        assert owner.post("/api/extension/pair/approve", json={
            "user_code": pairing["user_code"],
        }).status_code == 200
        extension_token = worker.post("/api/extension/pair/complete", json={
            "device_code": pairing["device_code"],
        }).json()["token"]
        with ThreadPoolExecutor(max_workers=1) as pool:
            answer = pool.submit(
                worker.post, "/api/extension/data/generate-answer",
                headers={"Authorization": f"Bearer {extension_token}"},
                json={"prompt": "Why this role?", "company": "Acme", "title": "Engineer"},
            )
            task = worker.get("/api/local-ollama/worker/next", headers=headers).json()["task"]
            assert task["payload"]["format_json"] is False
            assert worker.post(
                f"/api/local-ollama/worker/tasks/{task['id']}/result", headers=headers,
                json={"lease": task["lease"], "content": "I like the role."},
            ).status_code == 200
            assert answer.result(timeout=5).json() == {"content": "I like the role."}

        with ThreadPoolExecutor(max_workers=1) as pool:
            interrupted = pool.submit(provider.text_call, "System", "Interrupted prompt", 5)
            assert worker.get("/api/local-ollama/worker/next", headers=headers).json()["task"]
            assert owner.delete(f"/api/local-ollama/tokens/{grant_id}").status_code == 200
            with pytest.raises(RuntimeError, match="disconnected"):
                interrupted.result(timeout=8)
        assert worker.get("/api/local-ollama/worker/next", headers=headers).status_code == 401
        assert owner.get("/api/local-ollama/status").json()["online"] is False


def test_worker_rejects_uninstalled_models(monkeypatch):
    import local_ollama_worker as worker

    calls = []
    def fake_request(url, **kwargs):
        calls.append(url)
        if url.endswith("/api/tags"):
            return {"models": [{"name": "llama3.2:latest"}]}
        return {"message": {"content": "done"}}

    monkeypatch.setattr(worker, "_request", fake_request)
    payload = {"model": "llama3.2", "system": "s", "user": "u", "max_tokens": 5,
               "format_json": False}
    assert worker._generate("http://127.0.0.1:11434", payload) == "done"
    assert calls[-1].endswith("/api/chat")
    payload["model"] = "cloud-model"
    try:
        worker._generate("http://127.0.0.1:11434", payload)
    except RuntimeError as exc:
        assert "not installed locally" in str(exc)
    else:
        raise AssertionError("A cloud model was sent to Ollama")
    assert len(calls) == 3  # no second /api/chat call


def test_worker_model_inventory_is_owned_updated_and_online_only(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app
    from server.local_ollama import ONLINE_FOR
    from datetime import datetime

    with TestClient(app) as owner, TestClient(app) as other, TestClient(app) as worker:
        register(owner, "inventory-owner@example.com")
        register(other, "inventory-other@example.com")
        assert owner.put("/api/onboarding/provider", json={"provider": "ollama"}).status_code == 200
        assert other.put("/api/onboarding/provider", json={"provider": "ollama"}).status_code == 200
        token = owner.post("/api/local-ollama/tokens").json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert worker.post("/api/local-ollama/worker/models", json={"models": []}).status_code == 401
        offline = owner.post("/api/providers/ollama/models", json={})
        assert offline.status_code == 503
        assert "Start your local Ollama worker" in offline.json()["detail"]

        assert worker.get("/api/local-ollama/worker/ping", headers=headers).status_code == 200
        outdated = owner.post("/api/providers/ollama/models", json={})
        assert outdated.status_code == 409
        assert "updated local Ollama worker" in outdated.json()["detail"]

        report = worker.post("/api/local-ollama/worker/models", headers=headers,
                             json={"models": ["z-model:latest", "a-model:latest", "a-model:latest"]})
        assert report.status_code == 200, report.text
        assert owner.post("/api/providers/ollama/models", json={}).json() == {
            "models": ["a-model:latest", "z-model:latest"],
        }
        assert other.post("/api/providers/ollama/models", json={}).status_code == 503
        assert worker.post("/api/local-ollama/worker/models", headers=headers,
                           json={"models": ["invalid model"]}).status_code == 422
        assert worker.post("/api/local-ollama/worker/models", headers=headers,
                           json={"models": ["new-model:latest"]}).status_code == 200
        assert owner.post("/api/providers/ollama/models", json={}).json() == {"models": ["new-model:latest"]}
        assert worker.post("/api/local-ollama/worker/models", headers=headers,
                           json={"models": []}).status_code == 200
        assert owner.post("/api/providers/ollama/models", json={}).json() == {"models": []}

        grant_id = owner.get("/api/local-ollama/status").json()["workers"][0]["id"]
        with db.session() as s:
            grant = s.get(db.LocalOllamaGrant, grant_id)
            grant.last_seen_at = datetime.utcnow() - ONLINE_FOR - ONLINE_FOR
            s.add(grant)
            s.commit()
        assert owner.post("/api/providers/ollama/models", json={}).status_code == 503
        assert owner.delete(f"/api/local-ollama/tokens/{grant_id}").status_code == 200
        assert worker.post("/api/local-ollama/worker/models", headers=headers,
                           json={"models": ["new-model:latest"]}).status_code == 401


def test_worker_publishes_only_local_installed_models(monkeypatch):
    import local_ollama_worker as worker

    calls = []

    def request(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/api/tags"):
            return {"models": [{"name": "z-model:latest"}, {"name": "a-model:latest"}]}
        return {"ok": True}

    monkeypatch.setattr(worker, "_request", request)
    worker._publish_models("https://applination.example", "worker-private", "http://127.0.0.1:11434")
    assert calls[0] == ("http://127.0.0.1:11434/api/tags", {"timeout": 10})
    assert calls[1][0] == "https://applination.example/api/local-ollama/worker/models"
    assert calls[1][1]["body"] == {"models": ["a-model:latest", "z-model:latest"]}
    assert calls[1][1]["token"] == "worker-private"
