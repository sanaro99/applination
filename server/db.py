"""Postgres persistence via SQLModel.

Schema is owned by Alembic (``server/migrations``), not by ``create_all``.
Adding or changing a model here means generating a revision:

    alembic revision --autogenerate -m "what changed"
    alembic upgrade head
"""
from __future__ import annotations
import os
from datetime import datetime
from enum import Enum
from pathlib import Path

from sqlalchemy import String
from sqlmodel import Field, SQLModel, create_engine, Session

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# Local dev default matches scripts/dev.ps1. Production sets DATABASE_URL via
# the compose env_file.
DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://applination:applination@127.0.0.1:5432/applination"
)


def database_url() -> str:
    return os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL


# pool_pre_ping because a pipeline run lives in a long-running daemon thread and
# can hold a connection idle long enough for Postgres (or anything NAT'd in
# between) to drop it; without this the next statement raises instead of
# transparently reconnecting.
engine = create_engine(
    database_url(),
    echo=False,
    pool_pre_ping=True,
)


# Both status enums are persisted as VARCHAR, not as native Postgres ENUM
# types. A native enum would need an ALTER TYPE (and a migration) every time a
# status is added, and Postgres cannot drop a value from one at all. VARCHAR
# also matches how these columns already exist in the SQLite database we are
# migrating from, so the data copies across untouched.
class RunStatus(str, Enum):
    scheduled = "scheduled"  # deferred to a future time; picked up by the poller
    queued = "queued"
    running = "running"
    done = "done"
    error = "error"
    cancelled = "cancelled"


class ApplicationStatus(str, Enum):
    generated = "generated"
    applied = "applied"
    interviewing = "interviewing"
    rejected = "rejected"
    offer = "offer"
    archived = "archived"


class Run(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None
    status: RunStatus = Field(default=RunStatus.queued, sa_type=String)
    dry_run: bool = False
    no_pdf: bool = False
    no_cache: bool = False
    max_jobs: int | None = None  # per-run override of search.max_jobs_per_day
    scheduled_for: datetime | None = None  # when status==scheduled, UTC time to fire
    log_path: str | None = None
    jobs_found: int = 0
    applications_created: int = 0
    day_root: str | None = None
    error: str | None = None


class Application(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: int | None = Field(default=None, foreign_key="run.id", index=True)
    company: str
    title: str
    location: str = ""
    url: str = ""
    source: str = ""
    match_score: int = 0
    match_reason: str = ""
    dedupe_key: str = Field(default="", index=True)  # company|title identity; cross-run dedup
    folder_path: str  # absolute path on disk
    folder_rel: str = ""  # e.g. "2026-05-10/Company_Role"
    resume_file: str = ""
    cover_file: str = ""
    answers_file: str = ""
    status: ApplicationStatus = Field(
        default=ApplicationStatus.generated, sa_type=String
    )
    description: str = ""  # job description; used by Coach for context
    notes: str = ""
    tags: str = ""  # comma-separated; exposed as a list by the API
    applied_at: datetime | None = None
    deadline: datetime | None = None
    interview_at: datetime | None = None  # set by inbox sync when an invite is parsed
    last_email_at: datetime | None = None  # most recent recruiter email seen by inbox sync
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RankedJob(SQLModel, table=True):
    """A job that was scored by the ranker on a run, whether or not it was
    auto-selected for generation. Powers the triage / 'rescue' view."""
    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id", index=True)
    company: str
    title: str
    location: str = ""
    url: str = ""
    source: str = ""
    description: str = ""  # kept so a rejected job can be generated on demand
    remote: bool = False
    match_score: int = 0
    match_reason: str = ""
    selected: bool = False  # was it in the auto-picked top-N for this run
    dismissed: bool = False  # user said "not interested" — excluded from future runs
    dedupe_key: str = Field(default="", index=True)  # company|title identity; cross-run dedup
    application_id: int | None = Field(default=None, foreign_key="application.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Setting(SQLModel, table=True):
    """Tiny key/value store for app-level flags (e.g. onboarding completion)."""
    key: str = Field(primary_key=True)
    value: str = ""


class ChatSession(SQLModel, table=True):
    """A Coach conversation. Optionally grounded to an Application so the
    assistant can prep the candidate for one specific job."""
    id: int | None = Field(default=None, primary_key=True)
    title: str = "New chat"
    mode: str = "chat"  # "chat" | "interview"
    application_id: int | None = Field(
        default=None, foreign_key="application.id", index=True
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ChatMessage(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="chatsession.id", index=True)
    role: str  # "user" | "assistant"
    content: str
    meta: str = ""  # small JSON blob: provider name, injected story titles
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SavedAnswer(SQLModel, table=True):
    """A good Coach reply saved to a reusable bank, optionally attached to an
    Application's answers.md."""
    id: int | None = Field(default=None, primary_key=True)
    title: str = ""
    prompt: str = ""  # the question this answers (optional)
    content: str
    tags: str = ""  # comma-separated; exposed as a list by the API
    source_message_id: int | None = Field(
        default=None, foreign_key="chatmessage.id"
    )
    application_id: int | None = Field(
        default=None, foreign_key="application.id", index=True
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


def init_db() -> None:
    """Assert the database is reachable and migrated.

    Schema creation is Alembic's job — the container runs `alembic upgrade head`
    before uvicorn starts. This only fails fast with a readable message if that
    did not happen, rather than letting every request 500 on a missing table.
    """
    from alembic.migration import MigrationContext

    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    if current is None:
        raise RuntimeError(
            "database has no Alembic revision — run `alembic upgrade head` "
            f"against {engine.url.render_as_string(hide_password=True)}"
        )


def session() -> Session:
    return Session(engine)
