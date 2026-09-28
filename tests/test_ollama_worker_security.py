"""A rewritten worker must obey the server's credential and task permissions."""
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlmodel import select

import server.db as db
from server.time_utils import utc_now
from .conftest import make_engine, register, pair_ollama, PASSWORD


def headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app

    with TestClient(app) as owner, TestClient(app) as worker, TestClient(app) as other:
        user_id = register(owner, "security-owner@example.com")["id"]
        register(other, "security-other@example.com")
        yield owner, worker, other, user_id


def enqueue(user_id, *, format_json=False):
    task_id = uuid.uuid4().hex
    with db.session() as session:
        session.add(db.LocalOllamaTask(id=task_id, user_id=user_id, payload=json.dumps({
            "model": "llama3.2", "system": "private instructions", "user": "private resume",
            "max_tokens": 100, "format_json": format_json,
        })))
        session.commit()
    return task_id


def session_grant(token):
    with db.session() as session:
        grant = session.exec(select(db.LocalOllamaGrant).where(
            db.LocalOllamaGrant.session_hash == hashlib.sha256(token.encode()).hexdigest()
        )).one()
        return grant.token_hash


def test_connection_key_cannot_be_used_as_a_worker_session(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app

    with TestClient(app) as owner, TestClient(app) as worker:
        register(owner, "pair-only@example.com")
        key = owner.post("/api/local-ollama/tokens").json()["token"]
        response = worker.get("/api/local-ollama/worker/ping", headers={
            "Authorization": f"Bearer {key}",
        })
        assert response.status_code == 401, response.text


def test_pairing_requires_matching_browser_approval_and_cannot_be_replayed(clients):
    owner, worker, other, _ = clients
    key = owner.post("/api/local-ollama/tokens").json()["token"]
    grant_id = hashlib.sha256(key.encode()).hexdigest()
    connected = worker.post("/api/local-ollama/worker/connect", headers=headers(key), json={})
    assert connected.status_code == 200, connected.text
    assert connected.headers["cache-control"] == "no-store"
    paired = connected.json()
    assert paired["token"] != key
    assert worker.post("/api/local-ollama/worker/connect", headers=headers(key), json={}).status_code == 401
    assert worker.get("/api/local-ollama/worker/ping", headers=headers(key)).status_code == 401
    for path in ("ping", "next"):
        assert worker.get(f"/api/local-ollama/worker/{path}", headers=headers(paired["token"])).status_code == 401
    assert worker.post("/api/local-ollama/worker/models", headers=headers(paired["token"]), json={"models": []}).status_code == 401
    assert worker.get("/api/local-ollama/worker/approval", headers=headers(paired["token"])).json() == {
        "approved": False, "expires_at": None,
    }
    assert owner.get("/api/local-ollama/status").json()["online"] is False
    url = f"/api/local-ollama/tokens/{grant_id}/approve"
    assert other.post(url, json={"verification_code": paired["verification_code"]}).status_code == 404
    wrong = ("0" if paired["verification_code"][0] != "0" else "1") + paired["verification_code"][1:]
    assert owner.post(url, json={"verification_code": wrong}).status_code == 403
    assert owner.post(url, json={"verification_code": paired["verification_code"]}).status_code == 200
    assert owner.post(url, json={"verification_code": paired["verification_code"]}).status_code == 409
    assert owner.get("/api/local-ollama/status").json()["online"] is False
    assert worker.get("/api/local-ollama/worker/ping", headers=headers(paired["token"])).status_code == 200
    approval = worker.get("/api/local-ollama/worker/approval", headers=headers(paired["token"])).json()
    assert approval["approved"] is True and approval["expires_at"]
    # A worker credential never authenticates regular account routes.
    for path in ("/api/config", "/api/applications", "/api/local-ollama/status"):
        assert worker.get(path, headers=headers(paired["token"])).status_code == 401


@pytest.mark.parametrize("claimed", [False, True])
def test_expired_pairing_or_approval_cannot_activate_a_worker(clients, claimed):
    owner, worker, _, _ = clients
    key = owner.post("/api/local-ollama/tokens").json()["token"]
    grant_id = hashlib.sha256(key.encode()).hexdigest()
    token = key
    if claimed:
        token = worker.post("/api/local-ollama/worker/connect", headers=headers(key), json={}).json()["token"]
    with db.session() as session:
        grant = session.get(db.LocalOllamaGrant, grant_id)
        grant.pairing_expires_at = utc_now() - timedelta(seconds=1)
        session.add(grant)
        session.commit()
    assert worker.post("/api/local-ollama/worker/connect", headers=headers(key), json={}).status_code == 401
    assert worker.get("/api/local-ollama/worker/approval", headers=headers(token)).status_code == 401
    assert owner.post(f"/api/local-ollama/tokens/{grant_id}/approve", json={"verification_code": "0" * 12}).status_code == 409


def test_pairing_code_redemption_is_atomic(clients):
    owner, worker, _, _ = clients
    key = owner.post("/api/local-ollama/tokens").json()["token"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(lambda _: worker.post(
            "/api/local-ollama/worker/connect", headers=headers(key), json={},
        ), range(4)))
    assert sorted(reply.status_code for reply in replies) == [200, 401, 401, 401]


@pytest.mark.parametrize("expired_field", ["expires_at", "last_seen_at"])
def test_expired_or_idle_session_does_not_refresh_itself(clients, expired_field):
    owner, worker, _, _ = clients
    token = pair_ollama(owner, worker)
    with db.session() as session:
        grant = session.get(db.LocalOllamaGrant, session_grant(token))
        setattr(grant, expired_field, utc_now() - timedelta(hours=2))
        session.add(grant)
        session.commit()
    assert worker.get("/api/local-ollama/worker/ping", headers=headers(token)).status_code == 401
    assert owner.get("/api/local-ollama/status").json()["online"] is False


def test_other_worker_on_same_account_cannot_use_a_leaked_lease(clients):
    owner, worker, _, user_id = clients
    first = pair_ollama(owner, worker)
    second = pair_ollama(owner, worker)
    task_id = enqueue(user_id)
    reply = worker.get("/api/local-ollama/worker/next", headers=headers(first))
    assert reply.headers["cache-control"] == "no-store"
    task = reply.json()["task"]
    assert task["id"] == task_id
    prefix = f"/api/local-ollama/worker/tasks/{task_id}"
    assert worker.post(prefix + "/heartbeat", headers=headers(second), json={"lease": task["lease"]}).status_code == 404
    assert worker.post(prefix + "/result", headers=headers(second), json={"lease": task["lease"], "content": "forged"}).status_code == 404
    assert worker.post(prefix + "/result", headers=headers(first), json={"lease": task["lease"], "content": "original"}).status_code == 200
    assert worker.post(prefix + "/result", headers=headers(first), json={"lease": task["lease"], "content": "replayed"}).status_code == 404
    with db.session() as session:
        saved = session.get(db.LocalOllamaTask, task_id)
        assert saved.result == "original" and saved.payload == "" and saved.lease_hash == ""


def test_expired_lease_cannot_heartbeat_or_submit_and_reclaim_changes_lease(clients):
    owner, worker, _, user_id = clients
    token = pair_ollama(owner, worker)
    task_id = enqueue(user_id)
    task = worker.get("/api/local-ollama/worker/next", headers=headers(token)).json()["task"]
    with db.session() as session:
        saved = session.get(db.LocalOllamaTask, task_id)
        saved.lease_until = utc_now() - timedelta(seconds=1)
        session.add(saved)
        session.commit()
    prefix = f"/api/local-ollama/worker/tasks/{task_id}"
    assert worker.post(prefix + "/heartbeat", headers=headers(token), json={"lease": task["lease"]}).status_code == 404
    assert worker.post(prefix + "/result", headers=headers(token), json={"lease": task["lease"], "content": "late"}).status_code == 404
    reclaimed = worker.get("/api/local-ollama/worker/next", headers=headers(token)).json()["task"]
    assert reclaimed["lease"] != task["lease"]
    assert worker.post(prefix + "/result", headers=headers(token), json={"lease": reclaimed["lease"], "content": "current"}).status_code == 200


def test_concurrent_result_submission_cannot_overwrite_the_first_answer(clients):
    owner, worker, _, user_id = clients
    token = pair_ollama(owner, worker)
    task_id = enqueue(user_id)
    task = worker.get("/api/local-ollama/worker/next", headers=headers(token)).json()["task"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(lambda n: worker.post(
            f"/api/local-ollama/worker/tasks/{task_id}/result", headers=headers(token),
            json={"lease": task["lease"], "content": str(n)},
        ), range(4)))
    assert sorted(reply.status_code for reply in replies) == [200, 404, 404, 404]


def test_revocation_cancels_lease_and_erases_queued_prompt(clients):
    owner, worker, _, user_id = clients
    token = pair_ollama(owner, worker)
    task_id = enqueue(user_id)
    task = worker.get("/api/local-ollama/worker/next", headers=headers(token)).json()["task"]
    assert owner.delete(f"/api/local-ollama/tokens/{session_grant(token)}").status_code == 200
    assert worker.post(f"/api/local-ollama/worker/tasks/{task_id}/result", headers=headers(token),
                       json={"lease": task["lease"], "content": "revoked"}).status_code == 401
    with db.session() as session:
        saved = session.get(db.LocalOllamaTask, task_id)
        assert saved.status == "error" and saved.payload == "" and saved.lease_hash == ""


def test_long_poll_rechecks_revocation_before_releasing_new_prompt(clients, monkeypatch):
    owner, worker, _, user_id = clients
    from server import local_ollama

    token = pair_ollama(owner, worker)
    grant_id = session_grant(token)

    async def revoke_while_waiting(_):
        assert owner.delete(f"/api/local-ollama/tokens/{grant_id}").status_code == 200
        enqueue(user_id)

    monkeypatch.setattr(local_ollama.asyncio, "sleep", revoke_while_waiting)
    reply = worker.get("/api/local-ollama/worker/next", headers=headers(token))
    assert reply.status_code == 401
    assert "private resume" not in reply.text


def test_json_results_and_unexpected_authority_fields_are_rejected(clients):
    owner, worker, _, user_id = clients
    token = pair_ollama(owner, worker)
    assert worker.post("/api/local-ollama/worker/models", headers=headers(token), json={
        "models": [], "user_id": user_id + 1,
    }).status_code == 422
    task_id = enqueue(user_id, format_json=True)
    task = worker.get("/api/local-ollama/worker/next", headers=headers(token)).json()["task"]
    url = f"/api/local-ollama/worker/tasks/{task_id}/result"
    for content in ("not JSON", "[]", "null"):
        assert worker.post(url, headers=headers(token), json={"lease": task["lease"], "content": content}).status_code == 422
    assert worker.post(url, headers=headers(token), json={"lease": task["lease"], "content": '{"ok": true}'}).status_code == 200


def test_declared_and_chunked_oversized_requests_are_rejected(clients):
    owner, worker, _, _ = clients
    from server.local_ollama import MAX_WORKER_BODY

    key = owner.post("/api/local-ollama/tokens").json()["token"]
    oversized = b" " * (MAX_WORKER_BODY + 1)
    url = "/api/local-ollama/worker/connect"
    assert worker.post(url, headers=headers(key), content=oversized).status_code == 413
    assert worker.post(url, headers=headers(key), content=iter([oversized[:500_000], oversized[500_000:]])).status_code == 413


def test_browser_origins_and_query_string_tokens_are_rejected(clients):
    owner, worker, _, _ = clients
    token = pair_ollama(owner, worker)
    assert worker.get("/api/local-ollama/worker/ping", headers={**headers(token), "Origin": "https://attacker.example"}).status_code == 403
    assert worker.get("/api/local-ollama/worker/ping?token=anything", headers=headers(token)).status_code == 403


def test_authenticated_worker_requests_are_rate_limited(clients, monkeypatch):
    owner, worker, _, _ = clients
    from server.limits import limiter

    token = pair_ollama(owner, worker)
    limiter.reset()
    monkeypatch.setattr(limiter, "enabled", True)
    try:
        replies = [worker.get("/api/local-ollama/worker/ping", headers=headers(token)) for _ in range(121)]
        assert all(reply.status_code == 200 for reply in replies[:120])
        assert replies[-1].status_code == 429
    finally:
        limiter.reset()


def test_password_change_revokes_only_that_accounts_workers(clients):
    owner, worker, other, user_id = clients
    token = pair_ollama(owner, worker)
    other_token = pair_ollama(other, worker)
    task_id = enqueue(user_id)
    worker.get("/api/local-ollama/worker/next", headers=headers(token))
    assert owner.post("/api/auth/change-password", json={
        "current_password": PASSWORD, "new_password": "new-long-safe-password-for-tests",
    }).status_code == 200
    assert worker.get("/api/local-ollama/worker/ping", headers=headers(token)).status_code == 401
    assert worker.get("/api/local-ollama/worker/ping", headers=headers(other_token)).status_code == 200
    with db.session() as session:
        task = session.get(db.LocalOllamaTask, task_id)
        assert task.status == "error" and task.payload == ""


def test_browser_approval_rejects_a_foreign_origin_even_with_owner_cookies(clients):
    owner, worker, _, _ = clients
    key = owner.post("/api/local-ollama/tokens").json()["token"]
    grant_id = hashlib.sha256(key.encode()).hexdigest()
    paired = worker.post("/api/local-ollama/worker/connect", headers=headers(key), json={}).json()
    url = f"/api/local-ollama/tokens/{grant_id}/approve"
    assert owner.post(url, json={"verification_code": paired["verification_code"]}, headers={
        "Origin": "https://untrusted.sanchitarora.me",
    }).status_code == 403
    assert worker.get("/api/local-ollama/worker/ping", headers=headers(paired["token"])).status_code == 401
    assert owner.post(url, json={"verification_code": paired["verification_code"]}, headers={
        "Origin": "http://testserver",
    }).status_code == 200


def test_pairing_creation_and_revocation_reject_foreign_browser_origins(clients):
    owner, worker, _, _ = clients
    foreign = {"Origin": "https://untrusted.sanchitarora.me"}
    assert owner.post("/api/local-ollama/tokens", headers=foreign).status_code == 403
    token = pair_ollama(owner, worker)
    assert owner.delete(f"/api/local-ollama/tokens/{session_grant(token)}", headers=foreign).status_code == 403
    assert worker.get("/api/local-ollama/worker/ping", headers=headers(token)).status_code == 200


def test_legacy_indefinite_worker_credential_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app
    from server.local_ollama import _hash

    with TestClient(app) as owner, TestClient(app) as worker:
        user_id = register(owner, "old-worker@example.com")["id"]
        token = "legacy-worker-credential-with-no-expiration"
        with db.session() as session:
            session.add(db.LocalOllamaGrant(
                token_hash=_hash(token), user_id=user_id,
                created_at=utc_now() - timedelta(days=365),
            ))
            session.commit()
        response = worker.get("/api/local-ollama/worker/ping", headers={
            "Authorization": f"Bearer {token}",
        })
        assert response.status_code == 401, response.text
