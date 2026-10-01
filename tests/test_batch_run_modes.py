from copy import deepcopy
from pathlib import Path
from datetime import timedelta
import json
import pytest
import yaml
from server import db
from server.db import Run, RunStatus, User, BatchRunState, BatchJob
from server.time_utils import utc_now
from .conftest import make_engine


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, 'engine', engine)
    with db.session() as s:
        u = User(email='modes@example.com', password_hash='x')
        s.add(u); s.commit(); s.refresh(u)
        run = Run(user_id=u.id, execution_mode='batch', status=RunStatus.waiting)
        s.add(run); s.commit(); s.refresh(run)
        s.add(BatchRunState(run_id=run.id, user_id=u.id))
        s.commit()
        return run.id, u.id


def test_waiting_run_reserves_owner_but_not_global_worker_slot(env):
    from server.runs import _active_run_exists, _active_run_count
    assert _active_run_exists(env[1])
    assert _active_run_count() == 0


def test_ordinary_worker_dispatch_never_constructs_batch_adapter(monkeypatch):
    import server.runs as runs
    calls = []
    class Thread:
        def __init__(self, **kwargs):
            calls.append(kwargs['target'])
        def start(self):
            pass
    monkeypatch.setattr(runs.threading, 'Thread', Thread)
    monkeypatch.setattr('server.batch_runs.adapter_for', lambda *a: pytest.fail('ordinary run constructed batch client'))
    runs._start_worker_thread(Run(id=3, user_id=1))
    assert calls == [runs._worker]


def test_batch_creation_failure_cannot_leave_an_unrecoverable_run(env, monkeypatch):
    from sqlalchemy import event
    from sqlmodel import select
    from server.runs import start_run, StartRunBody
    monkeypatch.setattr('server.batch_runs.validate_routes', lambda *args: None)
    def fail_state_insert(*args):
        raise RuntimeError('simulated crash during durable state creation')
    event.listen(BatchRunState, 'before_insert', fail_state_insert)
    try:
        with pytest.raises(RuntimeError):
            start_run(StartRunBody(execution_mode='batch', scheduled_for=utc_now() + timedelta(hours=1)),
                      User(id=env[1], email='modes@example.com', password_hash='x'))
    finally:
        event.remove(BatchRunState, 'before_insert', fail_state_insert)
    with db.session() as s:
        assert len(s.exec(select(Run)).all()) == 1  # Only the fixture's original run remains.


def test_snapshot_fetches_with_source_settings_but_does_not_persist_secrets(env, monkeypatch):
    from server import batch_runs as br
    from server.deps import paths_for
    from src.master_resume import load_master
    root = Path(__file__).resolve().parents[1]
    cfg = yaml.safe_load((root / 'demo_data/config.yaml').read_text(encoding='utf-8'))
    cfg['sources']['adzuna']['app_key'] = 'source-secret'
    cfg['llm']['openai'] = {'api_key': 'llm-secret'}
    monkeypatch.setattr(br, 'load_config', lambda *a: deepcopy(cfg))
    monkeypatch.setattr('src.master_resume.load_master', lambda *a: load_master(root / 'demo_data/master_data/resume.yaml'))
    received = []
    monkeypatch.setattr('src.main.fetch_all', lambda config, log: received.append(config) or [])
    with db.session() as s:
        run = s.get(Run, env[0])
        state = br._snapshot(run)
    assert received[0]['sources']['adzuna']['app_key'] == 'source-secret'
    encoded = json.dumps(state, default=str)
    assert 'source-secret' not in encoded and 'llm-secret' not in encoded


def test_poll_ceiling_pauses_without_cancel_or_submit(env, monkeypatch):
    from server import batch_runs as br
    run, owner = env
    with db.session() as s:
        row = s.get(BatchRunState, run)
        row.payload = json.dumps(dict(version=1, transcript={}, applications={}, routes={}))
        s.add(row)
        s.add(BatchJob(run_id=run, user_id=owner, provider='openai', model='gpt-6-luna',
            provider_id='batch_known', state='waiting', poll_count=120))
        s.commit()
    monkeypatch.setattr(br, 'adapter_for', lambda *args: pytest.fail('poll ceiling must not spend or cancel'))
    br.advance_batch_run(run, owner)
    with db.session() as s:
        assert s.get(Run, run).status == RunStatus.batch_paused


def test_read_errors_do_not_turn_into_submission_retries(env, monkeypatch):
    from server import batch_runs as br
    from sqlmodel import select
    run, owner = env
    with db.session() as s:
        row = s.get(BatchRunState, run)
        row.payload = json.dumps(dict(version=1, transcript={'item': {'state':'waiting'}}, applications={}, routes={}))
        s.add(row)
        s.add(BatchJob(run_id=run, user_id=owner, provider='openai', model='gpt-6-luna',
            provider_id='batch_known', state='waiting', request_ids='["item"]'))
        s.commit()
    class Adapter:
        def status(self, *args):
            raise RuntimeError('credentials revoked')
        def submit(self, *args):
            pytest.fail('poll failures must not resubmit')
    monkeypatch.setattr(br, 'adapter_for', lambda *a: Adapter())
    br.advance_batch_run(run, owner)
    with db.session() as s:
        job = s.exec(select(BatchJob)).first()
        assert job.poll_count == 1
        assert job.provider_id == 'batch_known'
        assert job.next_poll_at is not None
