"""Independent source polling and per-user rematching. Never invokes AI."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import logging
import os
import threading
import time

import requests
from sqlalchemy import or_, update
from sqlmodel import select

from .db import session, User, UserSecret, Setting, RankedJob, Application
from .deps import load_config_redacted, paths_for, load_config
from .discovery_models import DiscoverySource, DiscoverySubscription, DiscoveryState, DiscoveredJob, JobMatch
from .discovery_store import claim_source, renew_source, publish_source, fail_source
from .scoping import owned, find_owned
from .time_utils import utc_now
from src.discovery.identity import digest, canonical_url
from src.discovery.matching import score_job
from src.discovery.sources import fetch_source
from src.master_resume import load_master
from src.scrapers.schema import Job, dedupe_key
from src.target_rules import role_keywords, wants_internship_source

log = logging.getLogger(__name__)
_host_lock = threading.Lock()
_host_next: dict[str, float] = {}


def discovery_enabled() -> bool:
    return os.environ.get('CONTINUOUS_DISCOVERY_ENABLED', '0').lower() in {'1', 'true', 'yes'}


def source_specs(user_id: int, cfg: dict):
    sources = cfg.get('sources') or {}
    search = cfg.get('search') or {}
    include_internships = wants_internship_source(
        role_keywords(search),
        search.get('job_type') if search.get('job_type', 'auto') != 'auto' else None,
    )
    for kind in ('greenhouse', 'lever', 'ashby', 'smartrecruiters'):
        block = sources.get(kind) or {}
        if not block.get('enabled', kind == 'ashby'):
            continue
        companies = list(block.get('companies') or []) + list(block.get('extra_companies') or [])
        if kind == 'greenhouse' and block.get('use_builtin_list', True):
            from src.scrapers.greenhouse_companies import BUILT_IN_SLUGS
            companies += BUILT_IN_SLUGS
        if kind == 'ashby' and not companies:
            companies = ['notion', 'ramp', 'openai', 'linear', 'cohere', 'replit', 'supabase', 'plaid']
        for slug in sorted(set(companies)):
            yield kind, {'slug': slug}, 600
    for kind in ('remotive', 'themuse'):
        if (sources.get(kind) or {}).get('enabled', False):
            yield kind, {}, 600
    if (sources.get('simplify_github') or {}).get('enabled', False) and include_internships:
        yield 'github', {'repo': 'SimplifyJobs/Summer2026-Internships', 'branch': 'dev'}, 600
    if (sources.get('github_lists') or {}).get('enabled', True):
        entries = (sources.get('github_lists') or {}).get('repositories', [
            {'repo': 'SimplifyJobs/New-Grad-Positions', 'branch': 'dev'},
        ])
        for entry in entries:
            if 'internship' in entry['repo'].casefold() and not include_internships:
                continue
            yield 'github', {'repo': entry['repo'], 'branch': entry.get('branch', 'main')}, 600
    search = cfg.get('search') or {}
    if (sources.get('himalayas') or {}).get('enabled', False):
        for query in (search.get('keywords') or [])[:20]:
            yield 'himalayas', {'query': query, 'country': (search.get('countries') or ['us'])[0].upper(), 'owner': user_id}, 600
    for item in (sources.get('workday') or {}).get('boards', []) if (sources.get('workday') or {}).get('enabled') else []:
        yield 'workday', {k: item[k] for k in ('slug', 'site', 'host')}, 3600
    # Credentialed aggregators require explicit background opt-in in addition
    # to their ordinary source switch. All calls share one per-owner budget.
    discovery = cfg.get('discovery') or {}
    if discovery.get('aggregators_enabled', False):
        for kind in ('jsearch', 'adzuna'):
            if (sources.get(kind) or {}).get('enabled'):
                for country in (search.get('countries') or ['us'])[:5]:
                    yield kind, {'query': ' OR '.join((search.get('keywords') or [])[:20]), 'country': country,
                                 'owner': user_id, 'budget': max(1, min(1000, int(discovery.get('aggregator_daily_budget', 10))))}, 21600


def sync_user(user_id: int, cfg: dict) -> None:
    specs = list(source_specs(user_id, cfg))
    with session() as s:
        s.exec(select(User).where(User.id == user_id).with_for_update()).one()
        state = find_owned(s, DiscoveryState, user_id, user_id)
        if state is None:
            s.add(DiscoveryState(user_id=user_id))
        current = {x.source_id: x for x in s.exec(owned(select(DiscoverySubscription), DiscoverySubscription, user_id)).all()}
        wanted = set()
        for kind, params, interval in specs:
            if kind in {'jsearch', 'adzuna'}:
                revisions = s.exec(select(UserSecret.name, UserSecret.updated_at).where(UserSecret.user_id == user_id,
                    UserSecret.name.startswith(f'sources.{kind}.'))).all()
                params['credential_revision'] = digest([list(row) for row in revisions])
            key = f'user:{user_id}:' + digest([kind, params]) if 'owner' in params else f'public:{kind}:' + digest(params)
            source = s.exec(select(DiscoverySource).where(DiscoverySource.key == key)).first()
            if source is None:
                source = DiscoverySource(key=key, kind=kind, params=json.dumps(params), interval_seconds=interval)
                s.add(source); s.flush()
            wanted.add(source.id)
            if source.id not in current:
                s.add(DiscoverySubscription(user_id=user_id, source_id=source.id))
        for sid, row in current.items():
            source = s.get(DiscoverySource, sid)
            if sid not in wanted and source.kind != 'history':
                s.delete(row)
        s.commit()


def _as_job(row: DiscoveredJob, source: str = '') -> Job:
    return Job(source, row.company, row.title, row.location, row.url, row.description,
               posted_at=row.posted_at, remote=row.remote, external_id=row.external_id, employment_type=row.employment_type)


def backfill_history(user_id: int) -> None:
    """Idempotent additive import; no network, AI, deletions or run rewrites."""
    key = f'user:{user_id}:history'
    with session() as s:
        s.exec(select(User).where(User.id == user_id).with_for_update()).one()
        source = s.exec(select(DiscoverySource).where(DiscoverySource.key == key)).first()
        if source is not None:
            return
        source = DiscoverySource(key=key, kind='history', enabled=False)
        s.add(source); s.flush()
        s.add(DiscoverySubscription(user_id=user_id, source_id=source.id))
        rows = s.exec(owned(select(RankedJob), RankedJob, user_id).order_by(RankedJob.created_at.desc()).limit(5000)).all()
        seen = {}
        for old in rows:
            ext = digest(canonical_url(old.url) or [old.company, old.title, old.location])
            if ext in seen:
                match = seen[ext]
                match.dismissed = match.dismissed or old.dismissed
                match.application_id = match.application_id or old.application_id
                continue
            posting = DiscoveredJob(source_id=source.id, external_id=ext, company=old.company,
                title=old.title, location=old.location, url=old.url, description=old.description,
                remote=old.remote, first_seen=old.created_at, last_seen=old.created_at)
            s.add(posting); s.flush()
            match = JobMatch(user_id=user_id, posting_id=posting.id, dismissed=old.dismissed,
                             score=old.match_score, reason=old.match_reason, application_id=old.application_id)
            s.add(match)
            seen[ext] = match
        s.commit()


def rematch_user(user_id: int, cfg: dict | None = None, master: dict | None = None) -> None:
    cfg = cfg if cfg is not None else load_config_redacted(user_id)
    if master is None:
        path = paths_for(user_id).resume_path
        master = load_master(path) if path.exists() else {}
    profile_hash = digest([cfg.get('search'), master, 'rules-v1'])
    with session() as s:
        # Serialize alias inheritance with user actions and generation reservations.
        s.exec(select(User).where(User.id == user_id).with_for_update()).one()
        state = find_owned(s, DiscoveryState, user_id, user_id)
        if state is None or not state.enabled:
            return
        sources = s.exec(owned(select(DiscoverySubscription), DiscoverySubscription, user_id)).all()
        ids = [x.source_id for x in sources]
        postings = s.exec(select(DiscoveredJob).where(DiscoveredJob.source_id.in_(ids)).order_by(DiscoveredJob.last_seen.desc()).limit(10000)).all()
        matches = {x.posting_id: x for x in s.exec(owned(select(JobMatch), JobMatch, user_id)).all()}
        alias_rows = s.exec(owned(select(JobMatch, DiscoveredJob.url).join(DiscoveredJob,
            DiscoveredJob.id == JobMatch.posting_id), JobMatch, user_id)).all()
        actions = {}
        for match, url in alias_rows:
            if not url:
                continue
            key = canonical_url(url)
            group = actions.setdefault(key, {'saved': False, 'dismissed': False, 'applied': False, 'application_id': None})
            for flag in ('saved', 'dismissed', 'applied'):
                group[flag] = group[flag] or getattr(match, flag)
            group['application_id'] = group['application_id'] or match.application_id
        subscribed_postings = {p.id for p in postings}
        for mid, match in matches.items():
            if mid not in subscribed_postings:
                match.eligible = False
                match.fingerprint = ''  # membership changed; re-entry must rescore
                s.add(match)
        apps = s.exec(owned(select(Application), Application, user_id)).all()
        by_url = {canonical_url(x.url): x for x in apps if x.url}
        legacy = {dedupe_key(x.company, x.title): x for x in apps if not x.url}
        for posting in postings:
            match = matches.get(posting.id)
            inherited = actions.get(canonical_url(posting.url), {}) if posting.url else {}
            if match:
                for flag, value in inherited.items():
                    setattr(match, flag, value)
                s.add(match)
            sig = digest([profile_hash, posting.content_hash, posting.active])
            if match and match.fingerprint == sig:
                # Application status is independent from matching cache.
                app = by_url.get(canonical_url(posting.url)) or legacy.get(dedupe_key(posting.company, posting.title))
                if app:
                    match.application_id = app.id
                    match.applied = app.status.value != 'generated'
                    s.add(match)
                continue
            match = match or JobMatch(user_id=user_id, posting_id=posting.id)
            for flag, value in inherited.items():
                setattr(match, flag, value)
            search = cfg.get('search') or {}
            result = score_job(_as_job(posting), search, master) if posting.active else None
            if result and result[0] < int(search.get('min_match_score', 0)):
                result = None
            match.eligible = result is not None
            if result:
                match.score, match.reason = result
            match.fingerprint = sig
            app = by_url.get(canonical_url(posting.url)) or legacy.get(dedupe_key(posting.company, posting.title))
            if app:
                match.application_id = app.id
                match.applied = app.status.value != 'generated'
            s.add(match)
        state.fingerprint, state.last_matched, state.error = profile_hash, utc_now(), ''
        s.add(state); s.commit()


def has_live_subscribers(source_id: int) -> bool:
    with session() as s:
        # noscope: public-board work may continue for any active subscriber.
        row = s.exec(select(DiscoverySubscription).join(DiscoveryState,
            DiscoveryState.user_id == DiscoverySubscription.user_id).join(User, User.id == DiscoveryState.user_id)
            .where(DiscoverySubscription.source_id == source_id, DiscoveryState.enabled == True, User.disabled == False)).first()
        return row is not None


class SourceHTTP:
    def __init__(self, source_id, token, params, kind):
        self.source_id, self.token, self.params, self.kind, self.calls = source_id, token, params, kind, 0

    def __call__(self, method, url, **kwargs):
        from urllib.parse import urlsplit
        if not has_live_subscribers(self.source_id):
            raise RuntimeError('No enabled subscriber for source')
        self.calls += 1
        if self.calls > 30 or not renew_source(self.source_id, self.token):
            raise RuntimeError('Source request limit or lease expired')
        owner = self.params.get('owner')
        if self.kind in {'jsearch', 'adzuna'}:
            with session() as s:
                # Lock owner row first to serialize budget reservations across sources.
                s.exec(select(User).where(User.id == owner).with_for_update()).one()
                rows = s.exec(select(DiscoverySource).where(DiscoverySource.key.startswith(f'user:{owner}:'),
                    DiscoverySource.kind.in_(['jsearch', 'adzuna']))).all()
                day = utc_now().date().isoformat()
                used = sum(x.requests_used for x in rows if x.budget_day == day)
                if used >= self.params.get('budget', 10):
                    raise RuntimeError('Daily source request budget exhausted')
                row = next(x for x in rows if x.id == self.source_id)
                row.requests_used = row.requests_used + 1 if row.budget_day == day else 1
                row.budget_day = day
                s.add(row); s.commit()
            cfg = load_config(owner)
            block = cfg.get('sources', {}).get(self.kind, {})
            if self.kind == 'jsearch':
                kwargs['headers']['x-rapidapi-key'] = block.get('rapidapi_key', '')
                kwargs['headers']['x-rapidapi-host'] = 'jsearch.p.rapidapi.com'
            else:
                kwargs.setdefault('params', {}).update(app_id=block.get('app_id', ''), app_key=block.get('app_key', ''))
        host = urlsplit(url).netloc
        with _host_lock:
            wait = max(0, _host_next.get(host, 0) - time.monotonic())
            _host_next[host] = time.monotonic() + wait + 0.25
        if wait:
            time.sleep(min(wait, 10))
        if not has_live_subscribers(self.source_id):
            raise RuntimeError('No enabled subscriber for source')
        response = requests.request(method, url, allow_redirects=False, **kwargs)
        if 300 <= response.status_code < 400 and response.status_code != 304:
            raise RuntimeError('Source redirect requires adapter review')
        return response


def poll_source(source_id: int, token: str) -> None:
    with session() as s:
        source = s.get(DiscoverySource, source_id)
        kind, params, validators = source.kind, json.loads(source.params), json.loads(source.validators)
    try:
        result = fetch_source(kind, params, validators, request=SourceHTTP(source_id, token, params, kind))
        publish_source(source_id, token, result)
    except Exception as exc:
        status = getattr(getattr(exc, 'response', None), 'status_code', 0)
        retry_after = 0
        header = getattr(getattr(exc, 'response', None), 'headers', {}).get('Retry-After', '')
        try:
            retry_after = int(header) if header.isdigit() else max(0, (parsedate_to_datetime(header) - utc_now()).total_seconds())
        except (ValueError, TypeError, AttributeError):
            pass
        # Provider exceptions can contain URLs/keys. Record types/status only.
        fail_source(source_id, token, f'{type(exc).__name__} (HTTP {status or "unavailable"})', retry_after=retry_after, auth_failure=status in {401, 403})


def discovery_tick() -> None:
    if not discovery_enabled():
        return
    with session() as s:
        users = s.exec(select(User).where(User.disabled == False)).all()
    for user in users:
        if user.email == 'demo@applination.app':
            continue
        try:
            cfg = load_config_redacted(user.id)
            # noscope: scheduler reads only this explicit user's onboarding marker.
            with session() as s:
                ready = s.get(Setting, (user.id, 'onboarded'))
            if not ((ready and ready.value == '1') or paths_for(user.id).resume_path.exists()) or not cfg.get('search', {}).get('keywords'):
                continue
            sync_user(user.id, cfg)
            backfill_history(user.id)
            rematch_user(user.id, cfg)
        except Exception:
            log.exception('Unable to refresh discovery state for user %s', user.id)
    with session() as s:
        # noscope: scheduler selects enabled subscribers across accounts.
        subscribed = select(DiscoverySubscription.source_id).join(DiscoveryState, DiscoveryState.user_id == DiscoverySubscription.user_id).join(User, User.id == DiscoveryState.user_id).where(DiscoveryState.enabled == True, User.disabled == False)
        due = s.exec(select(DiscoverySource).where(DiscoverySource.id.in_(subscribed), DiscoverySource.enabled == True,
            DiscoverySource.next_due <= utc_now(), or_(DiscoverySource.lease_until == None, DiscoverySource.lease_until < utc_now()))
            .order_by(DiscoverySource.next_due, DiscoverySource.id).limit(64)).all()
    def poll(source):
        if not discovery_enabled() or not has_live_subscribers(source.id):
            return
        token = claim_source(source.id)
        if token:
            poll_source(source.id, token)
    # Claim only when a worker actually starts, not while waiting in a queue.
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix='discovery') as pool:
        list(pool.map(poll, due))
