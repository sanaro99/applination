from datetime import timedelta
import pytest
from server import db
from server.db import Run, User, BatchRunState, BatchJob, Application
from server.batch_store import claim_run, release_run, save_state, load_state, begin_submission
from server.time_utils import utc_now
from .conftest import make_engine


@pytest.fixture
def batch_run(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, 'engine', engine)
    with db.session() as s:
        u = User(email='batch@example.com', password_hash='x')
        s.add(u); s.commit(); s.refresh(u)
        run = Run(user_id=u.id, execution_mode='batch')
        s.add(run); s.commit(); s.refresh(run)
        s.add(BatchRunState(run_id=run.id, user_id=u.id))
        s.commit()
        return run.id, u.id


def test_single_claim_owner_scope_and_immutable_snapshot(batch_run):
    run, user = batch_run
    assert claim_run(run, user, 'a')
    assert not claim_run(run, user, 'b')
    assert not claim_run(run, user + 1, 'c')
    save_state(run, user, 'a', {'version': 1, 'master': {'name': 'original'}})
    assert load_state(run, user)['master']['name'] == 'original'
    with pytest.raises(LookupError):
        load_state(run, user + 1)
    release_run(run, user, 'a')
    assert claim_run(run, user, 'b')


def test_stale_lease_recovery(batch_run):
    run, user = batch_run
    assert claim_run(run, user, 'a')
    with db.session() as s:
        row = s.get(BatchRunState, run)
        row.lease_until = utc_now() - timedelta(seconds=1)
        s.add(row); s.commit()
    assert claim_run(run, user, 'b')
    with pytest.raises(LookupError):
        save_state(run, user, 'a', {})


def test_stale_worker_cannot_cross_paid_submission_boundary(batch_run):
    run, user = batch_run
    assert claim_run(run, user, 'a')
    with db.session() as s:
        job = BatchJob(run_id=run, user_id=user, provider='openai', model='gpt-6-luna', state='prepared')
        s.add(job); s.commit(); s.refresh(job)
        job_id = job.id
        row = s.get(BatchRunState, run)
        row.lease_until = utc_now() - timedelta(seconds=1)
        s.add(row); s.commit()
    assert claim_run(run, user, 'b')
    with pytest.raises(LookupError):
        begin_submission(job_id, run, user, 'a')
    begin_submission(job_id, run, user, 'b')
    with pytest.raises(LookupError):
        begin_submission(job_id, run, user, 'b')
    with db.session() as s:
        assert s.get(BatchJob, job_id).state == 'submitting'


def test_batch_publication_is_fenced_and_unique(batch_run):
    from server.runs import _persist_application
    from sqlalchemy.exc import IntegrityError
    from sqlmodel import select
    run, user = batch_run
    assert claim_run(run, user, 'owner')
    event = dict(company='A', title='B', folder='/output/a', batch_item_key=f'{run}:item',
                 batch_lease_owner='stale')
    with pytest.raises(LookupError):
        _persist_application(run, user, event)
    event['batch_lease_owner'] = 'owner'
    _persist_application(run, user, event)
    with pytest.raises(IntegrityError):
        _persist_application(run, user, event)
    with db.session() as s:
        assert len(s.exec(select(Application)).all()) == 1
