"""Transactional source leases and catalog publication (no Run coupling)."""
from datetime import timedelta
import json
import uuid

from sqlalchemy import delete, or_, update
from sqlmodel import select

from .db import session
from .discovery_models import DiscoverySource, DiscoveredJob, DiscoveryAttempt
from .time_utils import utc_now
from src.discovery.identity import canonical_url, fingerprint
from src.discovery.sources import FetchResult


def claim_source(source_id: int, *, now=None) -> str | None:
    now = now or utc_now()
    token = uuid.uuid4().hex
    with session() as s:
        result = s.execute(update(DiscoverySource).where(
            DiscoverySource.id == source_id, DiscoverySource.enabled == True,
            DiscoverySource.next_due <= now,
            or_(DiscoverySource.lease_until == None, DiscoverySource.lease_until < now),
        ).values(lease_token=token, lease_until=now + timedelta(seconds=180)))
        s.commit()
        return token if result.rowcount == 1 else None


def renew_source(source_id: int, token: str) -> bool:
    now = utc_now()
    with session() as s:
        result = s.execute(update(DiscoverySource).where(
            DiscoverySource.id == source_id, DiscoverySource.lease_token == token,
            DiscoverySource.lease_until >= now,
        ).values(lease_until=now + timedelta(seconds=180)))
        s.commit()
        return result.rowcount == 1


def publish_source(source_id: int, token: str, result: FetchResult, *, now=None) -> bool:
    now = now or utc_now()
    with session() as s:
        # Lock/fence before mutating postings; stale workers cannot publish.
        locked = s.exec(select(DiscoverySource).where(DiscoverySource.id == source_id,
            DiscoverySource.lease_token == token, DiscoverySource.lease_until >= now).with_for_update()).first()
        if not locked:
            return False
        existing = {x.external_id: x for x in s.exec(select(DiscoveredJob).where(DiscoveredJob.source_id == source_id)).all()}
        seen = set()
        valid_snapshot = result.complete
        if result.not_modified:
            for row in existing.values():
                if row.active:
                    row.last_seen = now
                    s.add(row)
        for job in result.jobs:
            if not job.title or not job.company or not job.url.startswith(('https://', 'http://')):
                valid_snapshot = False
                continue
            ext = str(job.external_id or canonical_url(job.url))[:1000]
            if not ext:
                valid_snapshot = False
                continue
            seen.add(ext)
            row = existing.get(ext)
            if row is None:
                row = DiscoveredJob(source_id=source_id, external_id=ext, title=job.title, company=job.company,
                                    url=job.url, first_seen=now)
                existing[ext] = row
            if not job.description and row.description:
                job.description = row.description
            row.title, row.company, row.location = job.title[:1000], job.company[:500], job.location[:1000]
            row.description, row.url = job.description[:100000], canonical_url(job.url)[:4096]
            row.remote, row.employment_type, row.posted_at = job.remote, job.employment_type, job.posted_at
            row.content_hash, row.last_seen, row.active = fingerprint(job), now, True
            s.add(row)
        if valid_snapshot and not result.not_modified:
            for ext, row in existing.items():
                if ext not in seen:
                    row.active = False
                    s.add(row)
        locked.last_success, locked.last_error, locked.failures = now, '', 0
        validators = dict(result.validators)
        if not valid_snapshot and not result.not_modified:
            # A later 304 refreshes the entire known snapshot. A partially
            # parsed response cannot establish that snapshot's validator.
            validators.pop('etag', None)
            validators.pop('modified', None)
        locked.validators = json.dumps(validators)
        locked.next_due = now + timedelta(seconds=max(600, locked.interval_seconds))
        locked.lease_token, locked.lease_until = '', None
        s.add(locked)
        s.add(DiscoveryAttempt(source_id=source_id, count=len(seen), outcome='not_modified' if result.not_modified else 'complete' if valid_snapshot else 'partial'))
        s.execute(delete(DiscoveryAttempt).where(DiscoveryAttempt.source_id == source_id,
            DiscoveryAttempt.created_at < now - timedelta(days=7)))
        s.commit()
        return True


def fail_source(source_id: int, token: str, error: str, *, retry_after=0, auth_failure=False) -> None:
    now = utc_now()
    with session() as s:
        row = s.exec(select(DiscoverySource).where(DiscoverySource.id == source_id,
            DiscoverySource.lease_token == token, DiscoverySource.lease_until >= now).with_for_update()).first()
        if not row:
            return
        row.failures = min(20, row.failures + 1)
        row.last_error = error[:300]
        row.enabled = not auth_failure
        row.next_due = now + timedelta(seconds=max(row.interval_seconds, retry_after, min(86400, 600 * 2 ** min(row.failures, 7))))
        row.lease_token, row.lease_until = '', None
        s.add(row)
        s.add(DiscoveryAttempt(source_id=source_id, outcome='authentication' if auth_failure else 'error'))
        s.commit()
