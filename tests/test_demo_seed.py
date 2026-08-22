"""The seeder is the only thing standing between a shared demo account and
permanent vandalism, so idempotency and the completeness of the wipe are the
two properties worth testing."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlmodel import select

import server.db as db
from server.db import Application, ChatMessage, RankedJob, Run, User


@pytest.fixture()
def seeded_env(tmp_path, monkeypatch):
    """A migrated database with the per-user filesystem pointed at tmp_path.

    ``isolated_user_data`` in conftest already redirects USERS_DIR; this only
    has to supply the engine.
    """
    from .conftest import make_engine

    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server import demo as demo_mod

    return demo_mod


def _counts() -> dict[str, int]:
    with db.session() as s:
        return {
            "runs": len(s.exec(select(Run)).all()),
            "apps": len(s.exec(select(Application)).all()),
            "ranked": len(s.exec(select(RankedJob)).all()),
            "messages": len(s.exec(select(ChatMessage)).all()),
        }


def test_ensure_creates_the_account_once(seeded_env):
    first = seeded_env.ensure_demo_user()
    second = seeded_env.ensure_demo_user()
    assert first == second
    with db.session() as s:
        rows = s.exec(
            select(User).where(User.email == seeded_env.DEMO_EMAIL)
        ).all()
    assert len(rows) == 1


def test_the_demo_account_is_not_the_owner(seeded_env):
    """Seeding must not hand the demo the account the CLI defaults to."""
    user_id = seeded_env.ensure_demo_user()
    with db.session() as s:
        assert s.get(User, user_id).is_owner is False


def test_seed_populates_rows_and_files(seeded_env):
    from server.user_paths import user_paths

    user_id = seeded_env.seed_demo()
    counts = _counts()
    assert counts["runs"] >= 2
    assert counts["apps"] >= 8
    assert counts["ranked"] >= 12
    assert counts["messages"] >= 4

    paths = user_paths(user_id)
    assert paths.config_path.is_file()
    assert paths.resume_path.is_file()
    assert paths.bio_path.is_file()
    assert len(list(paths.stories_dir.glob("*.md"))) >= 5


def test_seeded_config_routes_to_the_demo_provider(seeded_env):
    """The whole simulated-AI design rests on this one value surviving the
    copy, so assert on the loaded config rather than on the file."""
    from server.deps import load_config

    user_id = seeded_env.seed_demo()
    assert load_config(user_id)["llm"]["primary"] == "demo"


def test_seed_is_idempotent(seeded_env):
    seeded_env.seed_demo()
    first = _counts()
    seeded_env.seed_demo()
    assert _counts() == first


def test_seed_wipes_visitor_damage(seeded_env):
    user_id = seeded_env.seed_demo()
    with db.session() as s:
        # noscope: test fixture writing as the known demo user.
        s.add(Application(
            user_id=user_id,
            company="Vandalism Inc",
            title="junk",
            folder_path="/tmp/junk",
        ))
        s.commit()

    seeded_env.seed_demo()
    with db.session() as s:
        junk = s.exec(
            select(Application).where(Application.company == "Vandalism Inc")
        ).all()
    assert junk == []


def test_seed_wipes_files_a_visitor_added(seeded_env):
    from server.user_paths import user_paths

    user_id = seeded_env.seed_demo()
    stray = user_paths(user_id).stories_dir / "graffiti.md"
    stray.write_text("---\ntags: []\n---\n", encoding="utf-8")

    seeded_env.seed_demo()
    assert not stray.exists()


def test_seed_leaves_other_accounts_alone(seeded_env):
    """The wipe is a bulk delete keyed on a user id. If that predicate were
    ever dropped it would take every account's data with it."""
    from server.auth import hash_password

    with db.session() as s:
        other = User(email="real@example.com", password_hash=hash_password("x" * 12))
        s.add(other)
        s.commit()
        s.refresh(other)
        other_id = int(other.id)
        # noscope: test fixture writing as a known non-demo user.
        s.add(Application(
            user_id=other_id, company="Real Co", title="Engineer",
            folder_path="/tmp/real",
        ))
        s.commit()

    seeded_env.seed_demo()

    with db.session() as s:
        survived = s.exec(
            select(Application).where(Application.user_id == other_id)
        ).all()
    assert len(survived) == 1


def test_seed_rebases_dates_so_the_demo_never_looks_stale(seeded_env):
    seeded_env.seed_demo()
    with db.session() as s:
        runs = s.exec(select(Run)).all()
        apps = s.exec(select(Application)).all()

    assert (datetime.utcnow() - max(r.started_at for r in runs)).days < 7
    # Deadlines are the surface that rots most visibly: a demo advertising
    # nothing but overdue applications is worse than an empty one.
    upcoming = [a for a in apps if a.deadline and a.deadline > datetime.utcnow()]
    assert upcoming, "no application has a deadline still in the future"


def test_every_application_status_is_represented(seeded_env):
    """The kanban has a column per status. Empty columns make the demo look
    broken rather than new."""
    from server.db import ApplicationStatus

    seeded_env.seed_demo()
    with db.session() as s:
        seen = {a.status for a in s.exec(select(Application)).all()}
    missing = {s_.value for s_ in ApplicationStatus} - {
        s_.value if hasattr(s_, "value") else s_ for s_ in seen
    }
    assert not missing, f"no demo application has status: {sorted(missing)}"


def test_ranked_pool_spans_the_threshold(seeded_env):
    """The triage tab is only interesting if some jobs were rejected."""
    seeded_env.seed_demo()
    with db.session() as s:
        rows = s.exec(select(RankedJob)).all()
    assert any(r.selected for r in rows)
    assert any(not r.selected for r in rows)
    assert any(r.dismissed for r in rows)


def test_is_demo_user(seeded_env):
    user_id = seeded_env.ensure_demo_user()
    with db.session() as s:
        assert seeded_env.is_demo_user(s.get(User, user_id))


def test_a_normal_account_is_not_the_demo(seeded_env):
    from server.auth import hash_password

    user = User(email="someone@example.com", password_hash=hash_password("x" * 12))
    assert not seeded_env.is_demo_user(user)


def test_demo_enabled_follows_the_env_switch(seeded_env, monkeypatch):
    assert seeded_env.demo_enabled() is True
    monkeypatch.setenv("DEMO_ENABLED", "0")
    assert seeded_env.demo_enabled() is False


def test_seeded_applications_point_at_real_documents(seeded_env):
    """A demo whose download buttons 404 is worse than one with no documents."""
    seeded_env.seed_demo()
    with db.session() as s:
        apps = s.exec(
            select(Application).where(Application.resume_file != "")
        ).all()
    if not apps:
        pytest.skip("no documents committed yet; see scripts/build_demo_output.py")
    for app in apps:
        assert (Path(app.folder_path) / app.resume_file).is_file(), app.folder_path
