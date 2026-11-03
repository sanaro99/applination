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
