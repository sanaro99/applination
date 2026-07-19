"""SQLite persistence via SQLModel."""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from pathlib import Path

from sqlalchemy import inspect, text
from sqlmodel import Field, SQLModel, create_engine, Session

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "app.db"

engine = create_engine(
    f"sqlite:///{DB_PATH.as_posix()}",
    echo=False,
    connect_args={"check_same_thread": False},
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


class Run(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None
    status: RunStatus = Field(default=RunStatus.queued)
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
    status: ApplicationStatus = Field(default=ApplicationStatus.generated)
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
    """Tiny key/value store for app-level flags (e.g. onboarding completion).
    create_all() builds this automatically — no migration entry needed."""
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


# Columns added to existing tables after their initial release. SQLModel's
# create_all() only creates missing tables — it never ALTERs an existing one —
# so we add new columns by hand. SQLite ADD COLUMN is cheap and idempotent here
# because we guard on the current schema.
_ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "run": [
        ("max_jobs", "INTEGER"),
        ("scheduled_for", "DATETIME"),
    ],
    "application": [
        ("tags", "VARCHAR DEFAULT ''"),
        ("deadline", "DATETIME"),
        ("description", "TEXT DEFAULT ''"),
        ("dedupe_key", "VARCHAR DEFAULT ''"),
        ("interview_at", "DATETIME"),
        ("last_email_at", "DATETIME"),
    ],
    "rankedjob": [
        ("dismissed", "BOOLEAN DEFAULT 0"),
        ("dedupe_key", "VARCHAR DEFAULT ''"),
    ],
    "chatsession": [
        ("mode", "VARCHAR DEFAULT 'chat'"),
    ],
}


def _migrate() -> None:
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue  # create_all() will build it with all columns
            present = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in columns:
                if name not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _migrate()


def session() -> Session:
    return Session(engine)
