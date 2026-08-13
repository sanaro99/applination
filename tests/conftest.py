"""Shared test fixtures."""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

ROOT = Path(__file__).resolve().parent.parent


def migrate(engine: Engine) -> None:
    """Bring a test database up to head using the real migrations.

    Tests run the actual Alembic revisions rather than ``create_all`` so that a
    migration which drifts from the models fails the suite instead of only
    failing in production. ``server.db.init_db`` also refuses to start against a
    database with no Alembic revision, which ``create_all`` would not satisfy.

    Tests use SQLite for speed and isolation; production is Postgres. The
    baseline migration is dialect-neutral, so this stays honest — but a future
    revision using Postgres-only DDL will need a Postgres-backed test instead.
    """
    cfg = Config(str(ROOT / "alembic.ini"))
    # Leave pytest's (and the app's) logging alone — see env.py.
    cfg.attributes["configure_logger"] = False
    # Set before invoking alembic so env.py leaves it alone (see env.py).
    cfg.set_main_option(
        "sqlalchemy.url",
        engine.url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    command.upgrade(cfg, "head")
