"""Shared test fixtures."""
from __future__ import annotations

import os
from pathlib import Path

# Must be set before server.limits is imported: slowapi's Limiter reads the flag
# once, at construction. The authz suite makes many rapid calls as one user and
# would otherwise trip the per-user limit and 429 where it expects a 404.
os.environ.setdefault("APPLINATION_DISABLE_RATE_LIMITS", "1")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import Engine  # noqa: E402

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


# --------------------------------------------------------------------------- #
# Auth helpers
#
# Every endpoint requires a session now, so tests need a logged-in client. Two
# TestClients over the same app keep separate cookie jars, which is what makes
# the cross-tenant assertions in test_authz.py possible.
# --------------------------------------------------------------------------- #
PASSWORD = "correct-horse-battery-staple"


def make_engine(tmp_path: Path, name: str = "test.db"):
    """A migrated, isolated SQLite engine."""
    from sqlalchemy import create_engine

    engine = create_engine(
        f"sqlite:///{(tmp_path / name).as_posix()}",
        connect_args={"check_same_thread": False},
    )
    migrate(engine)
    return engine


def register(client, email: str, password: str = PASSWORD) -> dict:
    """Sign up and stay logged in on this client. Returns the user payload.

    The first account created against a fresh database becomes the owner (see
    auth.signup), so call order decides who is owner.
    """
    r = client.post(
        "/api/auth/signup", json={"email": email, "password": password}
    )
    assert r.status_code == 200, r.text
    return r.json()


def login(client, email: str, password: str = PASSWORD) -> dict:
    r = client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert r.status_code == 200, r.text
    return r.json()
