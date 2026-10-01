import json
from datetime import timedelta
import pytest
from sqlmodel import select
from server import db
from server.db import BatchJob, Run, RunStatus, BatchRunState, User
from server.batch_runs import advance_batch_run
from .conftest import make_engine


@pytest.fixture
def waiting(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, 'engine', engine)
    with db.session() as s:
        u = User(email='waiting@example.com', password_hash='x')
        s.add(u); s.commit(); s.refresh(u)
        run = Run(user_id=u.id, execution_mode='batch', status=RunStatus.waiting)
        s.add(run); s.commit(); s.refresh(run)
        state = {'version': 1, 'transcript': {'item': {'state': 'waiting', 'request': {'request_id': 'item'}}},
                 'routes': {}, 'applications': {}}
        s.add(BatchRunState(run_id=run.id, user_id=u.id, payload=json.dumps(state)))
        job = BatchJob(run_id=run.id, user_id=u.id, provider='openai', model='gpt-6-luna',
                       state='submitting', request_ids='["item"]')
        s.add(job); s.commit()
        return run.id, u.id


def test_ambiguous_submission_is_never_recreated(waiting, monkeypatch):
    import server.batch_runs as br
    run, owner = waiting
    monkeypatch.setattr(br, 'adapter_for', lambda *args: pytest.fail('must not recreate'))
    advance_batch_run(run, owner)
    with db.session() as s:
        assert s.get(Run, run).status == RunStatus.batch_paused
        assert s.exec(select(BatchJob)).first().state == 'submission_unknown'
    advance_batch_run(run, owner)


def test_restart_polls_known_id_without_submission(waiting, monkeypatch):
    import server.batch_runs as br
    from sqlmodel import select
    run, owner = waiting
    calls = []
    class Adapter:
        def status(self, provider_id):
            calls.append(provider_id)
            return 'in_progress'
        def submit(self, *args):
            pytest.fail('never recreate known jobs')
    monkeypatch.setattr(br, 'adapter_for', lambda *args: Adapter())
    with db.session() as s:
        job = s.exec(select(BatchJob)).first()
        job.state = 'waiting'; job.provider_id = 'batch_known'
        s.add(job); s.commit()
    advance_batch_run(run, owner)
    assert calls == ['batch_known']


def test_wrong_owner_cannot_advance(waiting, monkeypatch):
    import server.batch_runs as br
    monkeypatch.setattr(br, 'adapter_for', lambda *args: pytest.fail('must not access credentials'))
    advance_batch_run(waiting[0], waiting[1] + 1)


def test_cancel_abandons_unknown_without_resubmitting_and_releases_run(waiting, monkeypatch):
    import server.batch_runs as br
    run, owner = waiting
    monkeypatch.setattr(br, 'adapter_for', lambda *args: pytest.fail('unknown submission must not be recreated'))
    br.cancel(run, User(id=owner, email='waiting@example.com', password_hash='x'))
    br.advance_batch_run(run, owner)
    with db.session() as s:
        assert s.get(Run, run).status == RunStatus.cancelled
        job = s.exec(select(BatchJob)).first()
        assert job.state == 'abandoned'
        assert 'may still be billed' in job.error


def test_cancel_scheduled_batch_never_fetches_or_submits(waiting, monkeypatch):
    import server.batch_runs as br
    run, owner = waiting
    with db.session() as s:
        row = s.get(Run, run)
        row.status = RunStatus.scheduled
        s.add(row); s.commit()
    monkeypatch.setattr(br, '_snapshot', lambda *args: pytest.fail('scheduled cancellation must not fetch jobs'))
    monkeypatch.setattr(br, 'adapter_for', lambda *args: pytest.fail('scheduled cancellation must not call provider'))
    br.cancel(run, User(id=owner, email='waiting@example.com', password_hash='x'))
    br.advance_batch_run(run, owner)
    with db.session() as s:
        assert s.get(Run, run).status == RunStatus.cancelled


def test_cancel_before_snapshot_never_initializes_run(waiting, monkeypatch):
    import server.batch_runs as br
    run, owner = waiting
    with db.session() as s:
        row = s.get(Run, run)
        row.status = RunStatus.queued
        s.add(row)
        state = s.get(BatchRunState, run)
        state.payload = '{}'
        s.add(state)
        for job in s.exec(select(BatchJob)).all():
            s.delete(job)
        s.commit()
    monkeypatch.setattr(br, '_snapshot', lambda *args: pytest.fail('cancelled run must not fetch jobs'))
    br.cancel(run, User(id=owner, email='waiting@example.com', password_hash='x'))
    br.advance_batch_run(run, owner)
    with db.session() as s:
        assert s.get(Run, run).status == RunStatus.cancelled
