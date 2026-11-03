import pytest
from sqlmodel import select

import server.db as db
from src.scrapers.schema import Job
from .conftest import make_engine


@pytest.fixture
def setup(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, 'engine', engine)
    with db.session() as s:
        u = db.User(email='test@example.com', password_hash='x')
        s.add(u); s.commit(); s.refresh(u); uid = u.id
        s.add(db.Run(user_id=uid, status=db.RunStatus.batch_paused, execution_mode='batch'))
        s.commit()
    return uid


def test_rematching_independent_of_batch_and_profile_edit_does_not_refetch(setup, monkeypatch):
    from server.discovery_worker import sync_user, rematch_user
    from server.discovery_models import DiscoverySource, JobMatch
    from server.discovery_store import claim_source, publish_source
    from src.discovery.sources import FetchResult
    uid = setup
    cfg = {'search': {'keywords': ['engineer'], 'job_type': 'any'}, 'sources': {'ashby': {'enabled': True, 'companies': ['acme']}}}
    sync_user(uid, cfg)
    with db.session() as s:
        source = s.exec(select(DiscoverySource).where(DiscoverySource.kind == 'ashby')).one()
        sid = source.id
    publish_source(sid, claim_source(sid), FetchResult([Job('ashby:acme', 'Acme', 'Engineer', 'US', 'https://a/1', 'Python', external_id='1')], complete=True))
    monkeypatch.setattr('requests.request', lambda *a, **k: pytest.fail('matching must not fetch'))
    import src.providers
    monkeypatch.setattr(src.providers, 'get_task_chains', lambda *a, **k: pytest.fail('discovery must not call AI'))
    rematch_user(uid, cfg, {'skills': {'Languages': ['Python']}})
    with db.session() as s:
        row = s.exec(select(JobMatch)).one()
        assert row.user_id == uid and row.eligible
        row.dismissed = True; s.add(row); s.commit()
    cfg['search']['keywords'] = ['designer']
    rematch_user(uid, cfg, {'skills': {}})
    with db.session() as s:
        row = s.exec(select(JobMatch)).one()
        assert not row.eligible and row.dismissed


def test_paid_sources_require_explicit_opt_in(setup):
    from server.discovery_worker import source_specs
    cfg = {'search': {'keywords': ['engineer']}, 'sources': {'jsearch': {'enabled': True}, 'adzuna': {'enabled': True}}}
    assert not any(kind in {'jsearch', 'adzuna'} for kind, _, _ in source_specs(setup, cfg))


def test_backoff_never_shortens_configured_interval(setup):
    from server.discovery_models import DiscoverySource
    from server.discovery_store import claim_source, fail_source
    from server.time_utils import utc_now
    with db.session() as s:
        row = DiscoverySource(key='slow', kind='ashby', interval_seconds=21600)
        s.add(row); s.commit(); s.refresh(row); sid = row.id
    now = utc_now()
    fail_source(sid, claim_source(sid, now=now), 'HTTP 429', retry_after=30)
    with db.session() as s:
        row = s.get(DiscoverySource, sid)
        assert (row.next_due.replace(tzinfo=now.tzinfo) - now).total_seconds() >= 21600


def test_paid_request_budget_counts_each_page_before_network(setup, monkeypatch):
    import json
    from server.discovery_models import DiscoverySource
    from server.discovery_store import claim_source
    from server.discovery_worker import SourceHTTP
    calls = []
    monkeypatch.setattr('server.discovery_worker.load_config', lambda uid: {'sources': {'jsearch': {'rapidapi_key': 'fixture-secret'}}})
    monkeypatch.setattr('requests.request', lambda *a, **k: calls.append(k) or type('Response', (), {'status_code': 200})())
    params = {'owner': setup, 'budget': 1}
    monkeypatch.setattr('server.discovery_worker.has_live_subscribers', lambda sid: True)
    with db.session() as s:
        row = DiscoverySource(key=f'user:{setup}:paid', kind='jsearch', params=json.dumps(params))
        s.add(row); s.commit(); s.refresh(row); sid = row.id
    request = SourceHTTP(sid, claim_source(sid), params, 'jsearch')
    request('GET', 'https://jsearch.p.rapidapi.com/search', headers={})
    with pytest.raises(RuntimeError, match='budget exhausted'):
        request('GET', 'https://jsearch.p.rapidapi.com/search', headers={})
    assert len(calls) == 1
    with db.session() as s:
        assert 'fixture-secret' not in s.get(DiscoverySource, sid).params


def test_new_alias_inherits_actions_and_resubscription_restores_eligibility(setup):
    from server.discovery_models import DiscoverySource, DiscoveredJob, JobMatch
    from server.discovery_worker import sync_user, rematch_user
    cfg = {'search': {'keywords': ['engineer'], 'job_type': 'any'}, 'sources': {'ashby': {'enabled': True, 'companies': ['a', 'b']}, 'github_lists': {'enabled': False}}}
    sync_user(setup, cfg)
    with db.session() as s:
        sources = s.exec(select(DiscoverySource).order_by(DiscoverySource.id)).all()
        source_ids = [x.id for x in sources]
        a = DiscoveredJob(source_id=sources[0].id, external_id='1', company='Acme', title='Engineer', url='https://a/1', content_hash='one')
        s.add(a); s.commit()
    rematch_user(setup, cfg, {})
    with db.session() as s:
        match = s.exec(select(JobMatch)).one()
        match.saved = match.dismissed = True
        s.add(match)
        b = DiscoveredJob(source_id=source_ids[1], external_id='2', company='Acme', title='Engineer', url='https://a/1', content_hash='two')
        s.add(b); s.commit()
    rematch_user(setup, cfg, {})
    with db.session() as s:
        assert all(x.saved and x.dismissed for x in s.exec(select(JobMatch)).all())
    cfg['sources']['ashby']['enabled'] = False
    sync_user(setup, cfg); rematch_user(setup, cfg, {})
    cfg['sources']['ashby']['enabled'] = True
    sync_user(setup, cfg); rematch_user(setup, cfg, {})
    with db.session() as s:
        assert all(x.eligible for x in s.exec(select(JobMatch)).all())


def test_paused_subscriber_prevents_late_requests(setup, monkeypatch):
    import json
    from server.discovery_worker import sync_user, has_live_subscribers, SourceHTTP
    from server.discovery_models import DiscoverySource, DiscoveryState
    from server.discovery_store import claim_source
    sync_user(setup, {'sources': {'ashby': {'companies': ['acme']}, 'github_lists': {'enabled': False}}})
    with db.session() as s:
        source = s.exec(select(DiscoverySource)).one()
        sid = source.id
    assert has_live_subscribers(sid)
    token = claim_source(sid)
    with db.session() as s:
        state = s.get(DiscoveryState, setup); state.enabled = False
        s.add(state); s.commit()
    assert not has_live_subscribers(sid)
    monkeypatch.setattr('requests.request', lambda *a, **k: pytest.fail('paused sources cannot fetch'))
    with pytest.raises(RuntimeError, match='subscriber'):
        SourceHTTP(sid, token, {}, 'ashby')('GET', 'https://example.com', headers={})
    # One account's pause does not halt a shared public board for another.
    from server.discovery_models import DiscoverySubscription
    with db.session() as s:
        user = db.User(email='other@example.com', password_hash='x')
        s.add(user); s.flush()
        s.add(DiscoveryState(user_id=user.id, enabled=True))
        s.add(DiscoverySubscription(user_id=user.id, source_id=sid))
        s.commit()
    assert has_live_subscribers(sid)


def test_resubscribed_unchanged_posting_is_rematched(setup):
    from server.discovery_models import DiscoverySource, DiscoveredJob, JobMatch
    from server.discovery_worker import sync_user, rematch_user
    cfg = {'search': {'keywords': ['engineer'], 'job_type': 'any'}, 'sources': {'ashby': {'companies': ['acme']}, 'github_lists': {'enabled': False}}}
    sync_user(setup, cfg)
    with db.session() as s:
        src = s.exec(select(DiscoverySource)).one()
        s.add(DiscoveredJob(source_id=src.id, external_id='1', company='Acme', title='Engineer', url='https://a/1', content_hash='same'))
        s.commit()
    rematch_user(setup, cfg, {})
    cfg['sources']['ashby']['enabled'] = False
    sync_user(setup, cfg); rematch_user(setup, cfg, {})
    cfg['sources']['ashby']['enabled'] = True
    sync_user(setup, cfg); rematch_user(setup, cfg, {})
    with db.session() as s:
        assert s.exec(select(JobMatch)).one().eligible
