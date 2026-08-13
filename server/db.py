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

from sqlalchemy import Enum as SAEnum
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
#
# native_enum=False gets that VARCHAR while still handing Python an enum member
# back on read. Mapping the column to a bare String instead would return plain
# strings, silently breaking every `status.value` reader in the routers.
def _status_column(enum_cls: type[Enum]) -> SAEnum:
    return SAEnum(
        enum_cls,
        native_enum=False,          # VARCHAR, not CREATE TYPE
        create_constraint=False,    # no CHECK — new statuses stay migration-free
        # Without an explicit length SQLAlchemy sizes the column to the longest
        # current member, so a longer status added later would need a migration
        # — the same trap as a native enum, just quieter. 32 is ample headroom.
        length=32,
        # Persist the member's value ("applied"), not its name. They happen to
        # match today; being explicit keeps that from becoming load-bearing.
        values_callable=lambda e: [m.value for m in e],
    )


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


class User(SQLModel, table=True):
    """An account. ``is_owner`` marks the single user backfilled from the
    pre-multi-user install; it gates the endpoints that still read the one
    global config.yaml / master_data (see PR 3, which makes those per-user)."""
    # NOT "user": that is a reserved word in Postgres, and `SELECT * FROM user`
    # does not error — it silently returns the session username. SQLAlchemy
    # quotes correctly either way, but anyone debugging in psql or pgAdmin would
    # get a confusing wrong answer rather than a clear failure.
    __tablename__ = "appuser"

    id: int | None = Field(default=None, primary_key=True)
    # Stored lowercased — see auth.normalize_email. Uniqueness is enforced by
    # the DB, not just by the signup check, so a race cannot create a duplicate.
    email: str = Field(unique=True, index=True)
    password_hash: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_owner: bool = False
    disabled: bool = False


class UserSession(SQLModel, table=True):
    """A logged-in session. Server-side and opaque: the cookie carries a random
    token, and only its SHA-256 lives here, so a database leak does not hand out
    live sessions. Being a row rather than a JWT is what makes logout and
    password-change able to actually revoke."""
    token_hash: str = Field(primary_key=True)
    user_id: int = Field(foreign_key="appuser.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)


class UserSecret(SQLModel, table=True):
    """A user's LLM API keys and Gmail OAuth token, Fernet-encrypted under the
    server-held APPLINATION_SECRET_KEY. Never written to YAML.

    PR 2 only creates the table and the crypto helpers; the readers that merge
    these into a per-user config are PR 3's job."""
    user_id: int = Field(foreign_key="appuser.id", primary_key=True)
    name: str = Field(primary_key=True)  # e.g. "llm.deepseek.api_key"
    ciphertext: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Run(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="appuser.id", index=True)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None
    status: RunStatus = Field(
        default=RunStatus.queued, sa_type=_status_column(RunStatus)
    )
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
    # Denormalized rather than reached through run_id: a direct predicate is
    # much harder to get wrong than a join, and run_id is nullable anyway
    # (single-job generations have no run).
    user_id: int = Field(foreign_key="appuser.id", index=True)
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
        default=ApplicationStatus.generated,
        sa_type=_status_column(ApplicationStatus),
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
    user_id: int = Field(foreign_key="appuser.id", index=True)
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
    """Tiny per-user key/value store (onboarding flag, Gmail OAuth token, the
    inbox's processed-message ids).

    The primary key is ``(user_id, key)``, not ``key`` alone. With a bare ``key``
    every user would share one namespace, so the second user to connect Gmail
    would overwrite the first user's OAuth token — a credential leak, not just a
    collision."""
    user_id: int = Field(foreign_key="appuser.id", primary_key=True)
    key: str = Field(primary_key=True)
    value: str = ""


class ChatSession(SQLModel, table=True):
    """A Coach conversation. Optionally grounded to an Application so the
    assistant can prep the candidate for one specific job."""
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="appuser.id", index=True)
    title: str = "New chat"
    mode: str = "chat"  # "chat" | "interview"
    application_id: int | None = Field(
        default=None, foreign_key="application.id", index=True
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ChatMessage(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="appuser.id", index=True)
    session_id: int = Field(foreign_key="chatsession.id", index=True)
    role: str  # "user" | "assistant"
    content: str
    meta: str = ""  # small JSON blob: provider name, injected story titles
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SavedAnswer(SQLModel, table=True):
    """A good Coach reply saved to a reusable bank, optionally attached to an
    Application's answers.md."""
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="appuser.id", index=True)
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


# Every table carrying tenant data. `server/scoping.py` filters on these, and
# `tests/test_scope_lint.py` fails the build on a bare select() against one, so
# adding a tenant table here is what wires it into both guards. A model absent
# from this tuple is silently unprotected — which is why the lint test also
# cross-checks it against every SQLModel table that has a `user_id` column.
TENANT_MODELS: tuple[type[SQLModel], ...] = (
    Run,
    Application,
    RankedJob,
    Setting,
    ChatSession,
    ChatMessage,
    SavedAnswer,
)


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
