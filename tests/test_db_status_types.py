"""Guards on how the status columns are persisted.

Both statuses are stored as VARCHAR rather than a native Postgres ENUM, but
must still come back to Python as enum members. Getting that wrong is quiet:
the schema looks right, every read returns a plausible string, and the failure
only surfaces where a router calls `.status.value` — which is how it escaped
into a running server the first time.
"""
from __future__ import annotations

from sqlalchemy import Enum as SAEnum, create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from sqlmodel import SQLModel, select

import server.db as db
from server.db import Application, ApplicationStatus, Run, RunStatus, User

from .conftest import migrate

_STATUS_TABLES = {"run": RunStatus, "application": ApplicationStatus}


def test_status_columns_are_not_native_enums():
    """A native ENUM needs an ALTER TYPE per added status and can never drop
    one. The rendered Postgres DDL must be VARCHAR with no CREATE TYPE."""
    for table in _STATUS_TABLES:
        col = SQLModel.metadata.tables[table].c.status
        assert isinstance(col.type, SAEnum), f"{table}.status lost its Enum type"
        assert col.type.native_enum is False, f"{table}.status became a native enum"

        ddl = str(
            CreateTable(SQLModel.metadata.tables[table]).compile(
                dialect=postgresql.dialect()
            )
        )
        status_line = next(
            line for line in ddl.splitlines() if line.strip().startswith("status ")
        )
        assert "VARCHAR" in status_line, status_line


def test_status_column_length_has_headroom():
    """Without an explicit length, SQLAlchemy sizes the column to the longest
    current member, so adding a longer status later silently needs a migration."""
    for table, enum_cls in _STATUS_TABLES.items():
        col = SQLModel.metadata.tables[table].c.status
        longest = max(len(m.value) for m in enum_cls)
        assert col.type.length > longest, (
            f"{table}.status is exactly {col.type.length} wide; a longer status "
            "would need a migration"
        )


def test_status_round_trips_as_enum_not_str(tmp_path, monkeypatch):
    """Routers call `status.value`. Mapping the column to a bare String would
    return plain strings and break every one of them at runtime."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'roundtrip.db').as_posix()}")
    migrate(engine)
    monkeypatch.setattr(db, "engine", engine)

    # Rows need an owner now that user_id is NOT NULL.
    with db.session() as s:
        owner = User(email="owner@example.com", password_hash="x", is_owner=True)
        s.add(owner)
        s.commit()
        s.refresh(owner)
        s.add(Run(user_id=owner.id, status=RunStatus.running))
        s.add(
            Application(
                user_id=owner.id,
                company="Acme",
                title="SWE",
                folder_path=str(tmp_path),
                status=ApplicationStatus.interviewing,
            )
        )
        s.commit()

    with db.session() as s:
        run = s.exec(select(Run)).one()
        app = s.exec(select(Application)).one()

    assert isinstance(run.status, RunStatus), f"got {type(run.status)}"
    assert isinstance(app.status, ApplicationStatus), f"got {type(app.status)}"
    # The actual call shape used across the routers.
    assert run.status.value == "running"
    assert app.status.value == "interviewing"
