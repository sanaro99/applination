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
        assert client.post("/api/local-ollama/tokens").status_code == 200
        grant_id = client.get("/api/local-ollama/status").json()["workers"][0]["id"]

    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False).replace("%", "%%"))
    command.downgrade(config, "b8e4c71a03d2")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT token_hash FROM localollamagrant")).scalar_one() == grant_id
    command.upgrade(config, "head")
    with db.session() as session:
        grant = session.get(db.LocalOllamaGrant, grant_id)
        assert grant.user_id == user_id
        assert grant.models_json is None
