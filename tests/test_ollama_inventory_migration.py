"""Adding worker inventories preserves already-paired worker credentials."""
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

import server.db as db
from .conftest import ROOT, make_engine, register


def test_inventory_migration_preserves_existing_worker_grants(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    from server.app import app

    with TestClient(app) as client:
        user_id = register(client, "migration@example.com")["id"]

    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False).replace("%", "%%"))
    command.downgrade(config, "b8e4c71a03d2")
    # Seed the historical schema directly: downgrading the security revision
    # intentionally discards new credentials rather than reviving pairing codes.
    grant_id = "historical-worker-hash"
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO localollamagrant (token_hash, user_id, created_at) VALUES (:hash, :user, CURRENT_TIMESTAMP)"
        ), {"hash": grant_id, "user": user_id})
    command.upgrade(config, "head")
    with db.session() as session:
        grant = session.get(db.LocalOllamaGrant, grant_id)
        assert grant.user_id == user_id
        assert grant.models_json is None
        assert grant.session_hash is None  # Legacy keys require the new approval flow.
