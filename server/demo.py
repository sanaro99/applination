"""The shared demo account, and the seeder that keeps it presentable.

Applination cannot otherwise be shown to anyone: every account is BYOK and
every account's data is personal and gitignored, so a prospective user reaching
the signup page sees a password field and nothing else. So one account, the
fictional ``John Doe``, is committed as a fixture under ``demo_data/`` and
seeded into an ordinary user id at runtime.

Three decisions worth not re-litigating:

* **The account is identified by a constant email, not a database column.** A
  ``User.is_demo`` flag would cost an Alembic migration and a schema change to
  express a fact that is a single known identity.
* **The demo is fully writable and restored nightly.** A read-only demo of an
  interactive product demonstrates nothing. The re-seed is the mitigation, and
  it is only a mitigation because ``scripts/seed_demo.py`` runs from cron.
* **Its LLM calls are simulated rather than blocked** — the account's committed
  ``config.yaml`` sets ``llm.primary: demo``. See
  ``src/providers/demo_provider.py``.

Every query here carries ``# noscope:``. That is not a loophole: the seeder runs
outside any request, against a user id it resolved itself from a constant, and
the scoping helpers in ``server/scoping.py`` exist to bind a query to *the
caller*, which here does not exist.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import delete
from sqlmodel import select

from .auth import hash_password, normalize_email
from .db import (
    Application,
    ApplicationStatus,
    ChatMessage,
    ChatSession,
    RankedJob,
    Run,
    RunStatus,
    SavedAnswer,
    Setting,
    User,
    session,
)
from .user_paths import user_paths

log = logging.getLogger("server.demo")

ROOT = Path(__file__).resolve().parent.parent
DEMO_DATA = ROOT / "demo_data"

DEMO_EMAIL = normalize_email(os.environ.get("DEMO_EMAIL") or "demo@applination.app")


def demo_enabled() -> bool:
    """Whether to advertise and accept demo logins.

    Off if the fixture is absent (someone stripped it from a fork) or if the
    operator set ``DEMO_ENABLED=0`` — a private deployment should not carry a
    door with no lock on it.

    Read from the environment on every call rather than cached at import, so
    the switch works without a restart and so tests can flip it.
    """
    if (os.environ.get("DEMO_ENABLED") or "").strip() == "0":
        return False
    return (DEMO_DATA / "config.yaml").is_file()


def is_demo_user(user: object) -> bool:
    return normalize_email(getattr(user, "email", "") or "") == DEMO_EMAIL


def ensure_demo_user() -> int:
    """Return the demo user's id, creating the account if it is absent.

    The password is random and discarded. Nobody signs in with it — the entry
    point is ``POST /api/auth/demo`` — but leaving the column empty would make
    this row a special case for every path that reads it, ``verify_password``
    included.
    """
    with session() as s:
        # noscope: resolving the demo account itself, outside any request.
        # There is no caller to scope to; the constant email is the predicate.
        user = s.exec(select(User).where(User.email == DEMO_EMAIL)).first()
        if user is None:
            user = User(
                email=DEMO_EMAIL,
                password_hash=hash_password(secrets.token_urlsafe(32)),
                # Never the owner: is_owner marks the account the CLI defaults
                # to, and handing that to a shared public login would point
                # `python -m src.main` at the demo.
                is_owner=False,
            )
            s.add(user)
            s.commit()
            s.refresh(user)
            log.info("created demo account %s (id=%s)", DEMO_EMAIL, user.id)
        return int(user.id)  # type: ignore[arg-type]


def seed_demo(*, reset: bool = True) -> int:
    """Restore the demo account to the committed fixture. Idempotent."""
    user_id = ensure_demo_user()
    if reset:
        _wipe(user_id)
    data = _fixture()
    _seed_files(user_id, data)
    _seed_rows(user_id, data)
    log.info("demo account %s (id=%s) seeded", DEMO_EMAIL, user_id)
    return user_id


# --------------------------------------------------------------------------- #
# Wipe
# --------------------------------------------------------------------------- #
def _wipe(user_id: int) -> None:
    """Delete the demo user's rows and files.

    Order matters: ChatMessage and SavedAnswer carry foreign keys into
    ChatSession and Application, and RankedJob into both Application and Run.
    """
    ordered = (
        ChatMessage,
        SavedAnswer,
        ChatSession,
        RankedJob,
        Application,
        Run,
        Setting,
    )
    with session() as s:
        for model in ordered:
            # noscope: bulk delete of the demo account's own rows, keyed by the
            # id ensure_demo_user() resolved from the constant email. Dropping
            # this predicate would empty the table for every account.
            s.exec(delete(model).where(model.user_id == user_id))
        s.commit()

    root = user_paths(user_id).root
    if root.exists():
        shutil.rmtree(root)


# --------------------------------------------------------------------------- #
# Fixture loading and date rebasing
# --------------------------------------------------------------------------- #
def _fixture() -> dict:
    return json.loads((DEMO_DATA / "seed.json").read_text(encoding="utf-8"))


def _ago(days: float) -> datetime:
    """Relative offsets, resolved against now.

    Absolute dates in the fixture would rot in public: deadlines go negative,
    the upcoming-interviews card empties, and /stats flatlines.
    """
    return datetime.utcnow() - timedelta(days=days)


def _run_days_ago(data: dict, key: str) -> float:
    for run in data.get("runs", []):
        if run["key"] == key:
            return float(run.get("days_ago", 0))
    raise KeyError(f"seed.json references unknown run {key!r}")


def _day_root(data: dict, key: str) -> str:
    return _ago(_run_days_ago(data, key)).strftime("%Y-%m-%d")


# --------------------------------------------------------------------------- #
# Files
# --------------------------------------------------------------------------- #
def _seed_files(user_id: int, data: dict) -> None:
    paths = user_paths(user_id).ensure()
    shutil.copy2(DEMO_DATA / "config.yaml", paths.config_path)
    shutil.copytree(DEMO_DATA / "master_data", paths.master_dir, dirs_exist_ok=True)

    src_output = DEMO_DATA / "output"
    if not src_output.is_dir():
        return
    # The fixture stores document folders without a date component, because the
    # run they belong to is dated relative to now. Each is placed under the day
    # of the run that produced it, so folder_rel and the tree agree.
    folder_to_run = {
        spec["folder"]: spec["run"]
        for spec in data.get("applications", [])
        if spec.get("folder")
    }
    for folder in src_output.iterdir():
        if not folder.is_dir():
            continue
        run_key = folder_to_run.get(folder.name)
        if run_key is None:
            log.warning(
                "demo_data/output/%s belongs to no application in seed.json; "
                "skipping", folder.name,
            )
            continue
        dest = paths.default_output_dir / _day_root(data, run_key) / folder.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(folder, dest, dirs_exist_ok=True)


# --------------------------------------------------------------------------- #
# Rows
# --------------------------------------------------------------------------- #
def _seed_rows(user_id: int, data: dict) -> None:
    paths = user_paths(user_id)

    with session() as s:
        run_ids = _insert_runs(s, user_id, data)
        app_ids = _insert_applications(s, user_id, data, run_ids, paths)
        _insert_ranked(s, user_id, data, run_ids, app_ids)
        _insert_chats(s, user_id, data)
        _insert_saved_answers(s, user_id, data)
        s.commit()


def _insert_runs(s, user_id: int, data: dict) -> dict[str, int]:
    run_ids: dict[str, int] = {}
    for spec in data.get("runs", []):
        started = _ago(spec.get("days_ago", 0))
        run = Run(
            user_id=user_id,
            started_at=started,
            finished_at=started + timedelta(minutes=spec.get("duration_minutes", 6)),
            status=RunStatus(spec.get("status", "done")),
            jobs_found=spec.get("jobs_found", 0),
            applications_created=spec.get("applications_created", 0),
            day_root=started.strftime("%Y-%m-%d"),
        )
        s.add(run)
        s.commit()
        s.refresh(run)
        run_ids[spec["key"]] = int(run.id)  # type: ignore[arg-type]
    return run_ids


def _insert_applications(
    s, user_id: int, data: dict, run_ids: dict[str, int], paths
) -> dict[str, int]:
    app_ids: dict[str, int] = {}
    for spec in data.get("applications", []):
        run_key = spec["run"]
        created = _ago(_run_days_ago(data, run_key))
        folder = spec.get("folder") or ""
        folder_rel = f"{_day_root(data, run_key)}/{folder}" if folder else ""
        app = Application(
            user_id=user_id,
            run_id=run_ids.get(run_key),
            company=spec["company"],
            title=spec["title"],
            location=spec.get("location", ""),
            url=spec.get("url", ""),
            source=spec.get("source", ""),
            match_score=spec.get("match_score", 0),
            match_reason=spec.get("match_reason", ""),
            dedupe_key=_dedupe_key(spec["company"], spec["title"]),
            folder_path=str(paths.default_output_dir / folder_rel)
            if folder_rel
            else "",
            folder_rel=folder_rel,
            resume_file=spec.get("resume_file", ""),
            cover_file=spec.get("cover_file", ""),
            status=ApplicationStatus(spec.get("status", "generated")),
            description=spec.get("description", ""),
            notes=spec.get("notes", ""),
            tags=spec.get("tags", ""),
            applied_at=_offset(spec, "applied_days_ago"),
            deadline=_future(spec, "deadline_in_days"),
            interview_at=_future(spec, "interview_in_days"),
            created_at=created,
        )
        s.add(app)
        s.commit()
        s.refresh(app)
        app_ids[_key(spec["company"], spec["title"])] = int(app.id)  # type: ignore[arg-type]
    return app_ids


def _insert_ranked(
    s, user_id: int, data: dict, run_ids: dict[str, int], app_ids: dict[str, int]
) -> None:
    for spec in data.get("ranked_jobs", []):
        run_key = spec["run"]
        s.add(RankedJob(
            user_id=user_id,
            run_id=run_ids[run_key],
            company=spec["company"],
            title=spec["title"],
            location=spec.get("location", ""),
            url=spec.get("url", ""),
            source=spec.get("source", ""),
            description=spec.get("description", ""),
            remote=spec.get("remote", False),
            match_score=spec.get("match_score", 0),
            match_reason=spec.get("match_reason", ""),
            selected=spec.get("selected", False),
            dismissed=spec.get("dismissed", False),
            dedupe_key=_dedupe_key(spec["company"], spec["title"]),
            application_id=app_ids.get(_key(spec["company"], spec["title"])),
            created_at=_ago(_run_days_ago(data, run_key)),
        ))


def _insert_chats(s, user_id: int, data: dict) -> None:
    for spec in data.get("chat_sessions", []):
        when = _ago(spec.get("days_ago", 1))
        chat = ChatSession(
            user_id=user_id,
            title=spec.get("title", "New chat"),
            mode=spec.get("mode", "chat"),
            created_at=when,
            updated_at=when,
        )
        s.add(chat)
        s.commit()
        s.refresh(chat)
        for i, msg in enumerate(spec.get("messages", [])):
            s.add(ChatMessage(
                user_id=user_id,
                session_id=int(chat.id),  # type: ignore[arg-type]
                role=msg["role"],
                content=msg["content"],
                meta=json.dumps({"provider": "demo"}),
                created_at=when + timedelta(minutes=i),
            ))


def _insert_saved_answers(s, user_id: int, data: dict) -> None:
    for spec in data.get("saved_answers", []):
        s.add(SavedAnswer(
            user_id=user_id,
            title=spec.get("title", ""),
            prompt=spec.get("prompt", ""),
            content=spec["content"],
            tags=spec.get("tags", ""),
            created_at=_ago(spec.get("days_ago", 2)),
        ))


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _offset(spec: dict, field: str) -> datetime | None:
    """A date in the past, from ``<field>`` days ago."""
    return _ago(spec[field]) if field in spec else None


def _future(spec: dict, field: str) -> datetime | None:
    """A date in the future, ``<field>`` days from now."""
    return _ago(-spec[field]) if field in spec else None


def _key(company: str, title: str) -> str:
    return f"{company}|{title}"


def _dedupe_key(company: str, title: str) -> str:
    """Cross-run dedup identity, computed the same way a real run computes it.

    Importing from src/ rather than reimplementing: if these two ever disagreed,
    the demo's seeded applications would stop suppressing their own postings and
    a demo run would re-tailor jobs the account had already applied to.
    """
    from src.scrapers import dedupe_key

    return dedupe_key(company, title)
