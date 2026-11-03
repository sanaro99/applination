"""Authenticated job feed. Reads stored results; never fetches or invokes AI."""
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import case, cast, String, func
from sqlmodel import select

from .auth import require_user
from .db import Application, ApplicationStatus, User, session
from .discovery_models import DiscoveryState, DiscoverySubscription, DiscoverySource, DiscoveredJob, JobMatch, GenerationRequest
from .discovery_worker import discovery_enabled, backfill_history
from .discovery_generation import enqueue_generation
from .limits import limiter, LLM_LIMIT
from .scoping import owned, get_owned, find_owned
from .single_job import GenerateBody
from .time_utils import utc_now

router = APIRouter(prefix='/api/jobs', tags=['jobs'])


def _state(user_id):
    with session() as s:
        row = find_owned(s, DiscoveryState, user_id, user_id)
        if row is None:
            row = DiscoveryState(user_id=user_id)
            s.add(row); s.commit(); s.refresh(row)
        return row


@router.get('/discovery')
def discovery_status(user: User = Depends(require_user)):
    state = _state(user.id)
    with session() as s:
        subscriptions = s.exec(owned(select(DiscoverySubscription), DiscoverySubscription, user)).all()
        rows = s.exec(select(DiscoverySource).where(DiscoverySource.id.in_([x.source_id for x in subscriptions]))).all()
    sources = [dict(kind=x.kind, last_success=x.last_success, next_due=x.next_due, error=x.last_error,
                    enabled=x.enabled, fetching=bool(x.lease_token), name=__import__('json').loads(x.params).get('slug') or x.kind)
               for x in rows if x.kind != 'history']
    return dict(enabled=state.enabled, administrator_enabled=discovery_enabled(), interval_seconds=600,
                last_matched=state.last_matched, error=state.error, sources=sources)


class DiscoverySettings(BaseModel):
    enabled: bool


@router.patch('/discovery')
def set_discovery(body: DiscoverySettings, user: User = Depends(require_user)):
    _state(user.id)
    with session() as s:
        row = get_owned(s, DiscoveryState, user.id, user)
        row.enabled = body.enabled
        s.add(row); s.commit()
    return discovery_status(user)


def _out(match, posting, source, request=None):
    now = utc_now()
    checked = source.last_success
    stale = checked is None or checked.replace(tzinfo=now.tzinfo) < now - timedelta(seconds=max(3600, source.interval_seconds * 3)) or bool(source.last_error)
    return dict(id=match.id, title=posting.title, company=posting.company, location=posting.location,
                remote=posting.remote, url=posting.url, description=posting.description, source=source.kind,
                posted_at=posting.posted_at, first_seen=posting.first_seen, last_checked=checked,
                stale=stale, active=posting.active, score=match.score, reason=match.reason,
                saved=match.saved, dismissed=match.dismissed, applied=match.applied,
                application_id=match.application_id, can_generate=len(posting.description.strip()) >= 100,
                generation=dict(state=request.state, run_id=request.run_id, error=request.error) if request else None)


@router.get('')
def list_jobs(q: str = Query('', max_length=200), view: Literal['recommended', 'saved', 'dismissed', 'applied', 'all'] = 'recommended',
              sort: Literal['match', 'newest'] = 'match', remote: bool = False,
              offset: int = Query(0, ge=0, le=100000), limit: int = Query(30, ge=1, le=100),
              user: User = Depends(require_user)):
    _state(user.id)
    backfill_history(user.id)
    with session() as s:
        # Canonical cards share exact application URLs, while distinct
        # requisition URLs stay separate even when company/title are equal.
        grouping = case((DiscoveredJob.url != '', DiscoveredJob.url), else_=cast(DiscoveredJob.id, String))
        ranked = owned(select(JobMatch.id.label('match_id'), func.row_number().over(partition_by=grouping,
            order_by=(DiscoveredJob.active.desc(), DiscoveredJob.last_seen.desc(), JobMatch.id)).label('position'))
            .join(DiscoveredJob, DiscoveredJob.id == JobMatch.posting_id), JobMatch, user).subquery()
        query = owned(select(JobMatch, DiscoveredJob, DiscoverySource).join(DiscoveredJob, DiscoveredJob.id == JobMatch.posting_id)
                      .join(DiscoverySource, DiscoverySource.id == DiscoveredJob.source_id), JobMatch, user).where(
                          JobMatch.id.in_(select(ranked.c.match_id).where(ranked.c.position == 1)))
        if view == 'recommended':
            query = query.where(JobMatch.eligible == True, JobMatch.dismissed == False, JobMatch.applied == False, JobMatch.application_id == None, DiscoveredJob.active == True)
        elif view == 'saved':
            query = query.where(JobMatch.saved == True)
        elif view == 'dismissed':
            query = query.where(JobMatch.dismissed == True)
        elif view == 'applied':
            query = query.where(JobMatch.applied == True)
        if q.strip():
            # Literal text search, not user-provided SQL wildcard syntax.
            value = '%' + q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            query = query.where((DiscoveredJob.title.ilike(value, escape='\\')) | (DiscoveredJob.company.ilike(value, escape='\\')) | (DiscoveredJob.location.ilike(value, escape='\\')))
        if remote:
            query = query.where(DiscoveredJob.remote == True)
        query = query.order_by(DiscoveredJob.first_seen.desc(), JobMatch.id.desc()) if sort == 'newest' else query.order_by(JobMatch.score.desc(), DiscoveredJob.first_seen.desc(), JobMatch.id.desc())
        rows = s.exec(query.offset(offset).limit(limit + 1)).all()
        request_rows = s.exec(owned(select(GenerationRequest, DiscoveredJob.url).join(JobMatch, JobMatch.id == GenerationRequest.match_id)
            .join(DiscoveredJob, DiscoveredJob.id == JobMatch.posting_id).where(DiscoveredJob.url.in_([r[1].url for r in rows])), GenerationRequest, user)).all()
        requests = {url: request for request, url in request_rows}
        return dict(items=[_out(m, p, src, requests.get(p.url)) for m, p, src in rows[:limit]],
                    next_offset=offset + limit if len(rows) > limit else None)


class JobUpdate(BaseModel):
    saved: bool | None = None
    dismissed: bool | None = None
    applied: bool | None = None


@router.patch('/{match_id}')
def update_job(match_id: int, body: JobUpdate, user: User = Depends(require_user)):
    with session() as s:
        s.exec(select(User).where(User.id == user.id).with_for_update()).one()
        match = get_owned(s, JobMatch, match_id, user)
        posting = s.get(DiscoveredJob, match.posting_id)
        aliases = s.exec(owned(select(JobMatch).join(DiscoveredJob, DiscoveredJob.id == JobMatch.posting_id)
            .where(DiscoveredJob.url == posting.url), JobMatch, user)).all() if posting.url else [match]
        for key, value in body.model_dump(exclude_none=True).items():
            setattr(match, key, value)
        if body.applied is True:
            app = find_owned(s, Application, match.application_id, user) if match.application_id else None
            if app is None:
                app = Application(user_id=user.id, company=posting.company, title=posting.title,
                    location=posting.location, url=posting.url, source='discovery', description=posting.description,
                    match_score=match.score, match_reason=match.reason, folder_path='', folder_rel='', status=ApplicationStatus.applied,
                    applied_at=utc_now())
                s.add(app); s.flush()
                match.application_id = app.id
            elif app.status == ApplicationStatus.generated:
                app.status, app.applied_at = ApplicationStatus.applied, utc_now()
                s.add(app)
        for alias in aliases:
            for key, value in body.model_dump(exclude_none=True).items():
                setattr(alias, key, value)
            if match.application_id:
                alias.application_id = match.application_id
            s.add(alias)
        s.add(match); s.commit()
        return {'ok': True}


@router.post('/{match_id}/generate')
@limiter.limit(LLM_LIMIT)
def generate_job(request: Request, match_id: int, user: User = Depends(require_user)):
    with session() as s:
        match = get_owned(s, JobMatch, match_id, user)
        posting = s.get(DiscoveredJob, match.posting_id)
        if match.application_id is not None:
            raise HTTPException(409, 'This job is already tracked. Open its application to view documents.')
        if len(posting.description.strip()) < 100:
            raise HTTPException(400, 'A full job description is required. Add this job from its URL in Single job.')
        body = GenerateBody(company=posting.company, title=posting.title, description=posting.description,
                            location=posting.location, url=posting.url, remote=posting.remote, source='discovery',
                            match_score=match.score, match_reason=match.reason)
    return {'run_id': enqueue_generation(body, user.id, match_id)}
