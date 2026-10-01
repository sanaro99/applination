from datetime import timedelta
import pytest
from server import db
from server.db import Run, User, BatchRunState
from server.batch_store import claim_run, release_run, save_state, load_state
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
