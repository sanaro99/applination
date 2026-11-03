from datetime import timedelta

import pytest
from sqlmodel import select

import server.db as db
from server.time_utils import utc_now
from src.scrapers.schema import Job
from .conftest import make_engine


@pytest.fixture
def engine(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, 'engine', engine)
    return engine


def test_additive_schema_and_unique_posting_identity(engine):
    from server.discovery_models import DiscoverySource, DiscoveredJob
    from sqlalchemy.exc import IntegrityError
    with db.session() as s:
        source = DiscoverySource(key='ashby:acme', kind='ashby')
        s.add(source); s.commit(); s.refresh(source)
        s.add(DiscoveredJob(source_id=source.id, external_id='1', title='Engineer', company='Acme', url='https://a/1'))
        s.commit()
        s.add(DiscoveredJob(source_id=source.id, external_id='1', title='Engineer', company='Acme', url='https://a/2'))
        with pytest.raises(IntegrityError):
            s.commit()


def test_leases_fence_stale_workers_and_refresh_unchanged_postings(engine):
    from server.discovery_models import DiscoverySource, DiscoveredJob
    from server.discovery_store import claim_source, publish_source
    from src.discovery.sources import FetchResult
    with db.session() as s:
        source = DiscoverySource(key='ashby:acme', kind='ashby')
        s.add(source); s.commit(); s.refresh(source)
        sid = source.id
    now = utc_now()
    token = claim_source(sid, now=now)
    assert token and claim_source(sid, now=now) is None
    job = Job('ashby:acme', 'Acme', 'Engineer', 'Seattle', 'https://a/1', 'Python', external_id='1')
    assert publish_source(sid, token, FetchResult([job], complete=True), now=now)
    with db.session() as s:
        source = s.get(DiscoverySource, sid)
        source.next_due = now - timedelta(seconds=1)
        s.add(source); s.commit()
    later = now + timedelta(minutes=11)
    token2 = claim_source(sid, now=later)
    assert not publish_source(sid, token, FetchResult([], complete=True), now=later)
    assert publish_source(sid, token2, FetchResult([job], complete=True), now=later)
    with db.session() as s:
        row = s.exec(select(DiscoveredJob)).one()
        assert row.active and row.last_seen.replace(tzinfo=later.tzinfo) == later
    token3 = claim_source(sid, now=later + timedelta(minutes=11))
    assert publish_source(sid, token3, FetchResult([], complete=False), now=later + timedelta(minutes=11))
    with db.session() as s:
        assert s.exec(select(DiscoveredJob)).one().active


def test_304_keeps_snapshot_and_does_not_erase_description(engine):
    from server.discovery_models import DiscoverySource, DiscoveredJob
    from server.discovery_store import claim_source, publish_source
    from src.discovery.sources import FetchResult
    with db.session() as s:
        source = DiscoverySource(key='test', kind='ashby')
        s.add(source); s.commit(); s.refresh(source); sid = source.id
    now = utc_now()
    job = Job('ashby', 'Acme', 'Engineer', 'US', 'https://a/1', 'Full description', external_id='1')
    publish_source(sid, claim_source(sid, now=now), FetchResult([job], complete=True), now=now)
    later = now + timedelta(minutes=11)
    publish_source(sid, claim_source(sid, now=later), FetchResult([], not_modified=True), now=later)
    with db.session() as s:
        row = s.exec(select(DiscoveredJob)).one()
        assert row.description == 'Full description' and row.active
        assert row.last_seen.replace(tzinfo=later.tzinfo) == later


def test_complete_snapshot_closes_missing_jobs_but_empty_details_keep_full_text(engine):
    from server.discovery_models import DiscoverySource, DiscoveredJob
    from server.discovery_store import claim_source, publish_source
    from src.discovery.sources import FetchResult
    with db.session() as s:
        source = DiscoverySource(key='board', kind='ashby')
        s.add(source); s.commit(); s.refresh(source); sid = source.id
    now = utc_now()
    a = Job('ashby', 'Acme', 'Engineer', 'US', 'https://a/1', 'Full description', external_id='1')
    b = Job('ashby', 'Acme', 'Engineer', 'US', 'https://a/2', 'Another description', external_id='2')
    publish_source(sid, claim_source(sid, now=now), FetchResult([a, b], complete=True), now=now)
    a.description = ''
    later = now + timedelta(minutes=11)
    publish_source(sid, claim_source(sid, now=later), FetchResult([a], complete=True), now=later)
    with db.session() as s:
        rows = {r.external_id: r for r in s.exec(select(DiscoveredJob)).all()}
        assert rows['1'].description == 'Full description'
        assert not rows['2'].active


def test_partial_snapshot_cannot_seed_a_304_that_refreshes_unseen_jobs(engine):
    import json
    from server.discovery_models import DiscoverySource
    from server.discovery_store import claim_source, publish_source
    from src.discovery.sources import FetchResult
    with db.session() as s:
        source = DiscoverySource(key='partial', kind='ashby')
        s.add(source); s.commit(); s.refresh(source); sid = source.id
    publish_source(sid, claim_source(sid), FetchResult([], complete=False,
        validators={'etag': 'incomplete', 'modified': 'today', 'details': {'kept': {}}}))
    with db.session() as s:
        validators = json.loads(s.get(DiscoverySource, sid).validators)
        assert 'etag' not in validators and 'modified' not in validators
        assert 'details' in validators
