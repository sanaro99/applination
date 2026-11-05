import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

import server.db as db
from server.app import create_app
from .conftest import make_engine, register


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'engine', make_engine(tmp_path))
    app = create_app()
    a, b = TestClient(app), TestClient(app)
    ua, ub = register(a, 'a@example.com'), register(b, 'b@example.com')
    return a, b, ua['id'], ub['id']


def seed(uid):
    from server.discovery_models import DiscoverySource, DiscoveredJob, JobMatch
    with db.session() as s:
        source = DiscoverySource(key=f'test:{uid}', kind='ashby')
        s.add(source); s.flush()
        posting = DiscoveredJob(source_id=source.id, external_id='1', title='Engineer', company='Acme',
                                url='https://example.com/job/1', description='Requirements: Python. ' * 20)
        s.add(posting); s.flush()
        match = JobMatch(user_id=uid, posting_id=posting.id, score=70, reason='Python')
        s.add(match); s.commit(); s.refresh(match)
        return match.id


def test_feed_is_scoped_and_dismiss_is_reversible(clients):
    a, b, uid, _ = clients
    mid = seed(uid)
    assert a.get('/api/jobs').status_code == 200
    assert b.patch(f'/api/jobs/{mid}', json={'dismissed': True}).status_code == 404
    assert a.patch(f'/api/jobs/{mid}', json={'dismissed': True}).status_code == 200
    assert not a.get('/api/jobs').json()['items']
    assert a.patch(f'/api/jobs/{mid}', json={'dismissed': False}).status_code == 200
    assert a.get('/api/jobs').json()['items'][0]['id'] == mid


def test_paused_batch_cannot_block_idempotent_selected_generation(clients, monkeypatch):
    from server.discovery_models import GenerationRequest
    a, b, uid, _ = clients
    mid = seed(uid)
    with db.session() as s:
        s.add(db.Run(user_id=uid, status=db.RunStatus.batch_paused, execution_mode='batch'))
        s.commit()
    first = a.post(f'/api/jobs/{mid}/generate')
    second = a.post(f'/api/jobs/{mid}/generate')
    assert first.status_code == second.status_code == 200
    assert first.json()['run_id'] == second.json()['run_id']
    assert b.post(f'/api/jobs/{mid}/generate').status_code == 404
    with db.session() as s:
        assert len(s.exec(select(GenerationRequest)).all()) == 1


def test_run_launch_is_retired_but_history_and_feed_remain(clients):
    a, _, _, _ = clients
    response = a.post('/api/runs', json={})
    assert response.status_code == 410
    assert '/jobs' in response.json()['detail']
    assert a.get('/api/runs').status_code == 200
    assert a.get('/api/jobs').status_code == 200


def test_applied_without_documents_appears_in_tracker_and_pause_is_private(clients):
    a, b, uid, _ = clients
    mid = seed(uid)
    assert a.patch(f'/api/jobs/{mid}', json={'applied': True}).status_code == 200
    apps = a.get('/api/applications').json()
    assert len(apps) == 1 and apps[0]['status'] == 'applied' and not apps[0]['resume_file']
    assert not b.get('/api/applications').json()
    assert a.patch('/api/jobs/discovery', json={'enabled': False}).status_code == 200
    assert not a.get('/api/jobs/discovery').json()['enabled']
    assert b.get('/api/jobs/discovery').json()['enabled']


def test_same_direct_url_across_sources_shares_actions_and_generation(clients):
    a, _, uid, _ = clients
    from server.discovery_models import DiscoverySource, DiscoveredJob, JobMatch
    first = seed(uid)
    with db.session() as s:
        src = DiscoverySource(key='second', kind='greenhouse')
        s.add(src); s.flush()
        posting = DiscoveredJob(source_id=src.id, external_id='other', title='Engineer', company='Acme',
                                url='https://example.com/job/1', description='Requirements: Python. ' * 20)
        s.add(posting); s.flush()
        match = JobMatch(user_id=uid, posting_id=posting.id, score=80)
        s.add(match); s.commit(); s.refresh(match); second = match.id
    assert len(a.get('/api/jobs').json()['items']) == 1
    assert a.post(f'/api/jobs/{first}/generate').json()['run_id'] == a.post(f'/api/jobs/{second}/generate').json()['run_id']
    a.patch(f'/api/jobs/{second}', json={'dismissed': True})
    assert not a.get('/api/jobs').json()['items']


def test_partial_source_success_does_not_refresh_unseen_posting(clients):
    from datetime import timedelta
    from server.time_utils import utc_now
    from server.discovery_models import DiscoverySource, DiscoveredJob
    a, _, uid, _ = clients
    seed(uid)
    old_date = utc_now() - timedelta(days=90)
    with db.session() as s:
        posting = s.exec(select(DiscoveredJob)).one()
        posting.last_seen = old_date
        source = s.get(DiscoverySource, posting.source_id)
        source.last_success = utc_now()
        s.add(posting); s.add(source); s.commit()
    job = a.get('/api/jobs').json()['items'][0]
    assert job['stale']
    assert job['last_checked'].startswith(old_date.date().isoformat())


def test_parallel_first_feed_reads_create_one_discovery_state(clients, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from server import discovery_api
    from server.discovery_models import DiscoveryState
    _, _, uid, _ = clients
    barrier = threading.Barrier(2)
    original = discovery_api.find_owned
    def find(*args, **kwargs):
        row = original(*args, **kwargs)
        if args[1] is DiscoveryState and row is None:
            barrier.wait(5)
        return row
    monkeypatch.setattr(discovery_api, 'find_owned', find)
    with ThreadPoolExecutor(max_workers=2) as pool:
        states = list(pool.map(discovery_api._state, [uid, uid]))
    assert all(row.user_id == uid for row in states)
    with db.session() as s:
        assert len(s.exec(select(DiscoveryState)).all()) == 1
