from datetime import timedelta
import json

import pytest
from sqlmodel import select

import server.db as db
from server.single_job import GenerateBody
from server.time_utils import utc_now
from .conftest import make_engine


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'engine', make_engine(tmp_path))
    with db.session() as s:
        for email in ('a@example.com', 'b@example.com', 'c@example.com'):
            s.add(db.User(email=email, password_hash='x'))
        s.commit()


def test_queue_caps_workers_serves_users_and_never_replays_expired_work(engine, monkeypatch):
    from server.discovery_generation import enqueue_generation, dispatch_generation_queue
    from server.discovery_models import GenerationRequest
    starts = []
    class Thread:
        def __init__(self, target=None, args=(), **kw):
            self.args = args
        def start(self):
            starts.append(self.args)
    monkeypatch.setattr('server.discovery_generation.threading.Thread', Thread)
    body = GenerateBody(company='Acme', title='Engineer', description='Python ' * 100)
    ids = [enqueue_generation(body, uid) for uid in (1, 1, 2, 3)]
    dispatch_generation_queue()
    assert len(starts) == 2
    with db.session() as s:
        rows = s.exec(select(GenerationRequest).where(GenerationRequest.state == 'running')).all()
        assert {r.user_id for r in rows} == {1, 2}
        expired = rows[0]
        expired.lease_until = utc_now() - timedelta(minutes=1)
        request_id = expired.id
        s.add(expired); s.commit()
    dispatch_generation_queue()
    with db.session() as s:
        assert s.get(GenerationRequest, request_id).state == 'error'
        assert 'Retry explicitly' in s.get(GenerationRequest, request_id).error
    assert all(args[0] != request_id for args in starts[2:])


def test_lost_generation_claim_fences_provider_calls_and_publication(engine):
    from server.discovery_generation import fence_provider, claim_is_current, GenerationLeaseLost
    from server.discovery_models import GenerationRequest
    from server.discovery_generation import enqueue_generation
    run_id = enqueue_generation(GenerateBody(company='Acme', title='Engineer', description='Python' * 50), 1)
    with db.session() as s:
        req = s.exec(select(GenerationRequest)).one()
        req.state, req.lease_token, req.lease_until = 'running', 'old-owner', utc_now() + timedelta(minutes=3)
        s.add(req); s.commit(); rid = req.id
    calls = []
    class Provider:
        name = 'fake'
        def json_call(self, *a, **kw):
            calls.append('paid')
            return {}
    provider = fence_provider(Provider(), rid, 'old-owner')
    assert provider.json_call() == {}
    with db.session() as s:
        req = s.get(GenerationRequest, rid)
        req.lease_token, req.state = 'new-owner', 'running'
        s.add(req); s.commit()
    with pytest.raises(GenerationLeaseLost):
        provider.json_call()
    with db.session() as s:
        assert not claim_is_current(s, rid, 'old-owner')
    assert calls == ['paid']


def test_expired_worker_cannot_publish_after_explicit_retry(engine, monkeypatch, tmp_path):
    import threading
    from types import SimpleNamespace
    from server import single_job
    from server.discovery_generation import enqueue_generation, dispatch_generation_queue
    from server.discovery_models import GenerationRequest, DiscoverySource, DiscoveredJob, JobMatch
    with db.session() as s:
        source = DiscoverySource(key='test', kind='ashby')
        s.add(source); s.flush()
        posting = DiscoveredJob(source_id=source.id, external_id='a', company='Acme', title='Engineer', url='https://example.com/job')
        s.add(posting); s.flush()
        match = JobMatch(user_id=1, posting_id=posting.id)
        s.add(match); s.commit(); match_id = match.id
    body = GenerateBody(company='Acme', title='Engineer', description='Python ' * 100)
    run_id = enqueue_generation(body, 1, match_id)
    with db.session() as s:
        req = s.exec(select(GenerationRequest)).one()
        req.state, req.lease_token, req.lease_until = 'running', 'old-owner', utc_now() + timedelta(minutes=3)
        s.add(req); s.commit(); rid = req.id
    entered, release = threading.Event(), threading.Event()
    def process(*a, **kw):
        entered.set()
        assert release.wait(10)
        return {'folder_name': 'acme', 'resume_file': 'resume.docx'}
    paths = SimpleNamespace(resume_path=tmp_path / 'resume.yaml', bio_path=tmp_path / 'bio.md',
        stories_dir=tmp_path, cover_letter_examples_dir=tmp_path, guidelines_dir=tmp_path,
        resolve_output=lambda cfg: tmp_path / 'output')
    monkeypatch.setattr(single_job, 'load_config', lambda uid: {'llm': {}, 'user': {}, 'output': {}})
    # This worker unit test has no live SSE loop. Earlier API tests may have
    # closed the process-wide bus's TestClient loop; keep that unrelated state
    # out of the generation ownership/retry regression.
    monkeypatch.setattr(single_job.bus, 'publish_threadsafe', lambda *a, **kw: None)
    monkeypatch.setattr(single_job, 'paths_for', lambda uid: paths)
    monkeypatch.setattr(single_job, 'load_master', lambda path: {})
    monkeypatch.setattr('src.providers.get_task_chains', lambda *a, **kw: {})
    for name in ('load_stories', 'load_example_letters', 'load_guidelines'):
        monkeypatch.setattr('src.reference_loader.' + name, lambda *a: [])
    monkeypatch.setattr('src.main.process_job', process)
    worker = threading.Thread(target=single_job._worker, args=(run_id, 1, body), kwargs={'generation_claim': (rid, 'old-owner')})
    worker.start()
    try:
        assert entered.wait(10)
        with db.session() as s:
            req = s.get(GenerationRequest, rid)
            req.lease_until = utc_now() - timedelta(minutes=1)
            s.add(req); s.commit()
        dispatch_generation_queue()
        assert enqueue_generation(body, 1, match_id) == run_id
    finally:
        release.set(); worker.join(10)
    assert not worker.is_alive()
    with db.session() as s:
        assert s.get(db.Run, run_id).status == db.RunStatus.queued
        assert s.exec(select(db.Application)).all() == []
        assert s.get(GenerationRequest, rid).state == 'queued'


def test_retry_reconciles_already_persisted_documents_without_spending_again(engine):
    from server.discovery_generation import enqueue_generation
    from server.discovery_models import GenerationRequest, DiscoverySource, DiscoveredJob, JobMatch
    body = GenerateBody(company='Acme', title='Engineer', description='Python ' * 100)
    with db.session() as s:
        source = DiscoverySource(key='test', kind='ashby')
        s.add(source); s.flush()
        posting = DiscoveredJob(source_id=source.id, external_id='a', company='Acme', title='Engineer', url='https://example.com/job')
        s.add(posting); s.flush()
        match = JobMatch(user_id=1, posting_id=posting.id)
        s.add(match); s.commit(); mid = match.id
    run_id = enqueue_generation(body, 1, mid)
    with db.session() as s:
        app = db.Application(user_id=1, run_id=run_id, company='Acme', title='Engineer', folder_path='output/acme')
        s.add(app)
        req = s.exec(select(GenerationRequest)).one()
        req.state = 'error'
        s.add(req); s.commit(); app_id = app.id
    assert enqueue_generation(body, 1, mid) == run_id
    with db.session() as s:
        assert s.exec(select(GenerationRequest)).one().state == 'done'
        assert s.get(db.Run, run_id).status == db.RunStatus.done
        assert s.get(JobMatch, mid).application_id == app_id
