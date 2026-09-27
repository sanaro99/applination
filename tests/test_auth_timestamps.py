"""UTC timestamps must survive the hosted SQLModel/PostgreSQL datetime binder."""
from datetime import datetime, timedelta

from server.auth import create_session
import server.runs as runs


def test_new_session_uses_utc_aware_timestamps():
    class CaptureSession:
        row = None

        def add(self, row):
            self.row = row

        def commit(self):
            pass

    session = CaptureSession()
    create_session(session, 1)
    assert session.row is not None
    for value in (session.row.created_at, session.row.expires_at, session.row.last_seen_at):
        assert value.utcoffset() == timedelta(0)


def test_scheduled_run_query_uses_utc_aware_cutoff(monkeypatch):
    class CaptureSession:
        cutoff = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def exec(self, statement):
            values = [v for v in statement.compile().params.values() if isinstance(v, datetime)]
            assert len(values) == 1
            self.cutoff = values[0]
            class EmptyResult:
                def all(self):
                    return []
            return EmptyResult()

    session = CaptureSession()
    monkeypatch.setattr(runs, "session", lambda: session)
    monkeypatch.setattr(runs, "_active_run_count", lambda: 0)
    runs.dispatch_due_scheduled_runs()
    assert session.cutoff is not None
    assert session.cutoff.utcoffset() == timedelta(0)
