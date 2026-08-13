"""Run scheduling limits and fairness.

The single-tenant version asked "is *any* run active?" and refused to start if
so. With one account that was correct; with two it means one user's hour-long
run locks everybody else out of the product. These tests pin the replacement:
one run per user, a global ceiling, and round-robin dispatch so a backlog
cannot starve anyone.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlmodel import select

import server.db as db
from server.db import Run, RunStatus

from .conftest import make_engine


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    eng = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", eng)
    return eng


def _user(engine, email: str) -> int:
    from server.db import User

    with db.Session(engine) as s:
        u = User(email=email, password_hash="x")
        s.add(u)
        s.commit()
        s.refresh(u)
        return u.id


def _run(engine, user_id: int, status: RunStatus, scheduled_for=None) -> int:
    with db.Session(engine) as s:
        r = Run(user_id=user_id, status=status, scheduled_for=scheduled_for)
        s.add(r)
        s.commit()
        s.refresh(r)
        return r.id


def test_active_run_check_is_per_user(engine):
    """A's running pipeline must not make B look busy."""
    from server.runs import _active_run_exists

    a, b = _user(engine, "a@example.com"), _user(engine, "b@example.com")
    _run(engine, a, RunStatus.running)

    assert _active_run_exists(a) is True
    assert _active_run_exists(b) is False


def test_scheduled_runs_do_not_count_as_active(engine):
    """A run booked for tonight must not block starting one now."""
    from server.runs import _active_run_exists

    a = _user(engine, "a@example.com")
    _run(engine, a, RunStatus.scheduled, datetime.utcnow() + timedelta(hours=5))
    assert _active_run_exists(a) is False


def test_finished_runs_do_not_count_as_active(engine):
    from server.runs import _active_run_exists

    a = _user(engine, "a@example.com")
    for status in (RunStatus.done, RunStatus.error, RunStatus.cancelled):
        _run(engine, a, status)
    assert _active_run_exists(a) is False


def test_active_run_count_is_global(engine):
    """The install-wide ceiling has to see across users, unlike the per-user
    check — that is the one place a global query is correct."""
    from server.runs import _active_run_count

    a, b = _user(engine, "a@example.com"), _user(engine, "b@example.com")
    _run(engine, a, RunStatus.running)
    _run(engine, b, RunStatus.queued)
    assert _active_run_count() == 2


def test_round_robin_interleaves_users(engine):
    """Ordering by scheduled_for alone would run all of A's backlog before B's
    first job. Round-robin alternates while preserving each user's own order."""
    from server.runs import _round_robin

    now = datetime.utcnow()
    runs = [
        Run(id=1, user_id=1, status=RunStatus.scheduled, scheduled_for=now),
        Run(id=2, user_id=1, status=RunStatus.scheduled,
            scheduled_for=now + timedelta(minutes=1)),
        Run(id=3, user_id=1, status=RunStatus.scheduled,
            scheduled_for=now + timedelta(minutes=2)),
        Run(id=4, user_id=2, status=RunStatus.scheduled,
            scheduled_for=now + timedelta(minutes=3)),
        Run(id=5, user_id=2, status=RunStatus.scheduled,
            scheduled_for=now + timedelta(minutes=4)),
    ]
    assert [r.id for r in _round_robin(runs)] == [1, 4, 2, 5, 3]


def test_round_robin_preserves_order_for_a_single_user(engine):
    from server.runs import _round_robin

    now = datetime.utcnow()
    runs = [
        Run(id=i, user_id=1, status=RunStatus.scheduled,
            scheduled_for=now + timedelta(minutes=i))
        for i in range(1, 4)
    ]
    assert [r.id for r in _round_robin(runs)] == [1, 2, 3]


def test_dispatch_respects_the_per_user_cap(engine, monkeypatch):
    """Two due runs for one user: only the first is dispatched this tick."""
    from server import runs as runs_mod

    started: list[int] = []
    monkeypatch.setattr(runs_mod, "_start_worker_thread", lambda r: started.append(r.id))

    a = _user(engine, "a@example.com")
    past = datetime.utcnow() - timedelta(minutes=5)
    r1 = _run(engine, a, RunStatus.scheduled, past)
    r2 = _run(engine, a, RunStatus.scheduled, past - timedelta(minutes=1))

    runs_mod.dispatch_due_scheduled_runs()
    assert len(started) == 1
    # The earlier-due one wins, and the other is left scheduled for next tick.
    assert started == [r2]
    with db.Session(engine) as s:
        assert s.get(Run, r1).status == RunStatus.scheduled


def test_dispatch_serves_two_users_in_one_tick(engine, monkeypatch):
    """The whole point of the rewrite: A being busy no longer blocks B."""
    from server import runs as runs_mod

    started: list[int] = []
    monkeypatch.setattr(runs_mod, "_start_worker_thread", lambda r: started.append(r.user_id))

    a, b = _user(engine, "a@example.com"), _user(engine, "b@example.com")
    past = datetime.utcnow() - timedelta(minutes=5)
    _run(engine, a, RunStatus.scheduled, past)
    _run(engine, b, RunStatus.scheduled, past)

    runs_mod.dispatch_due_scheduled_runs()
    assert sorted(started) == [a, b]


def test_dispatch_honours_the_global_ceiling(engine, monkeypatch):
    """Three users due at once, ceiling of 2: the third waits for a slot."""
    from server import runs as runs_mod

    started: list[int] = []
    monkeypatch.setattr(runs_mod, "_start_worker_thread", lambda r: started.append(r.user_id))
    monkeypatch.setattr(runs_mod, "MAX_CONCURRENT_RUNS", 2)

    past = datetime.utcnow() - timedelta(minutes=5)
    for email in ("a@example.com", "b@example.com", "c@example.com"):
        _run(engine, _user(engine, email), RunStatus.scheduled, past)

    runs_mod.dispatch_due_scheduled_runs()
    assert len(started) == 2

    # The third is untouched, not dropped — the next tick picks it up.
    with db.Session(engine) as s:
        still_scheduled = s.exec(
            select(Run).where(Run.status == RunStatus.scheduled)
        ).all()
    assert len(still_scheduled) == 1


def test_dispatch_skips_a_user_who_is_already_running(engine, monkeypatch):
    from server import runs as runs_mod

    started: list[int] = []
    monkeypatch.setattr(runs_mod, "_start_worker_thread", lambda r: started.append(r.user_id))

    a, b = _user(engine, "a@example.com"), _user(engine, "b@example.com")
    _run(engine, a, RunStatus.running)  # A is busy
    past = datetime.utcnow() - timedelta(minutes=5)
    _run(engine, a, RunStatus.scheduled, past)
    _run(engine, b, RunStatus.scheduled, past)

    runs_mod.dispatch_due_scheduled_runs()
    assert started == [b]
