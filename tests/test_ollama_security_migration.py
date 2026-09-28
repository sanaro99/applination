"""Security upgrades and rollbacks cannot resurrect old worker credentials."""
import hashlib

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

import server.db as db
from .conftest import ROOT, make_engine, register, pair_ollama


def revision_config(engine):
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False).replace("%", "%%"))
    return config


def test_upgrade_invalidates_old_credentials_and_erases_old_leased_prompts(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    from server.app import app

    with TestClient(app) as owner, TestClient(app) as worker:
        user_id = register(owner, "upgrade-worker@example.com")["id"]
        config = revision_config(engine)
        command.downgrade(config, "c62f8d9a04b1")
        old_key = "legacy-one-key-worker-with-no-expiration"
        grant_id = hashlib.sha256(old_key.encode()).hexdigest()
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO localollamagrant (token_hash, user_id, created_at, last_seen_at) "
                "VALUES (:hash, :user, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ), {"hash": grant_id, "user": user_id})
            connection.execute(text(
                "INSERT INTO localollamatask (id, user_id, status, payload, result, error, lease_hash, created_at) "
                "VALUES ('old-task', :user, 'leased', 'private prompt', '', '', 'old-lease', CURRENT_TIMESTAMP)"
            ), {"user": user_id})
        command.upgrade(config, "head")
        assert worker.get("/api/local-ollama/worker/ping", headers={"Authorization": f"Bearer {old_key}"}).status_code == 401
        status = owner.get("/api/local-ollama/status").json()
        assert status["online"] is False and status["workers"][0]["state"] == "expired"
        with db.session() as session:
            assert session.get(db.User, user_id).email == "upgrade-worker@example.com"
            task = session.get(db.LocalOllamaTask, "old-task")
            assert task.status == "error" and task.payload == "" and task.lease_hash == ""


def test_downgrade_and_reupgrade_do_not_revive_consumed_codes_or_sessions(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    from server.app import app

    with TestClient(app) as owner, TestClient(app) as worker:
        register(owner, "rollback-worker@example.com")
        token = pair_ollama(owner, worker)
        config = revision_config(engine)
        command.downgrade(config, "c62f8d9a04b1")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM localollamagrant")).scalar_one() == 0
        command.upgrade(config, "head")
        assert worker.get("/api/local-ollama/worker/ping", headers={"Authorization": f"Bearer {token}"}).status_code == 401
