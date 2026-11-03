"""Durable, bounded document generation. Discovery never enters this queue."""
from datetime import timedelta
import json
import threading
import uuid

from fastapi import HTTPException
from sqlalchemy import update
from sqlmodel import select

from .db import session, User, Run, RunStatus, Application
from .discovery_models import GenerationRequest, JobMatch, DiscoveredJob
from .scoping import owned, find_owned
from .time_utils import utc_now


class GenerationLeaseLost(RuntimeError):
    """A recovered/retried request no longer belongs to this worker."""


def claim_is_current(s, request_id: int, token: str) -> bool:
    """Fence publication in the *same transaction* as its application/run writes."""
    now = utc_now()
    result = s.execute(update(GenerationRequest).where(GenerationRequest.id == request_id,
        GenerationRequest.state == 'running', GenerationRequest.lease_token == token,
        GenerationRequest.lease_until > now).values(lease_until=now + timedelta(minutes=3)))
    return result.rowcount == 1


def check_claim(request_id: int, token: str) -> None:
    with session() as s:
        if not claim_is_current(s, request_id, token):
            raise GenerationLeaseLost('Generation ownership expired')
        s.commit()


def fence_provider(provider, request_id: int, token: str):
    class FencedProvider:
        def __getattr__(self, name):
            value = getattr(provider, name)
            if name not in {'json_call', 'text_call'}:
                return value
            def call(*args, **kwargs):
                check_claim(request_id, token)
                return value(*args, **kwargs)
            return call
    return FencedProvider()


def _reconcile_output(s, request, run) -> bool:
    app = s.exec(owned(select(Application).where(Application.run_id == request.run_id), Application, request.user_id)).first()
    if app is None:
        return False
    request.state, request.error = 'done', ''
    request.updated_at, request.lease_token, request.lease_until = utc_now(), '', None
    if run:
        run.status, run.applications_created, run.error, run.finished_at = RunStatus.done, 1, None, utc_now()
        s.add(run)
    if request.match_id:
        match = find_owned(s, JobMatch, request.match_id, request.user_id)
        if match:
            posting = s.get(DiscoveredJob, match.posting_id)
            aliases = s.exec(owned(select(JobMatch).join(DiscoveredJob, DiscoveredJob.id == JobMatch.posting_id)
                .where(DiscoveredJob.url == posting.url), JobMatch, request.user_id)).all() if posting.url else [match]
            for alias in aliases:
                alias.application_id = app.id
                s.add(alias)
    s.add(request)
    return True


def enqueue_generation(payload, user_id: int, match_id: int | None = None) -> int:
    with session() as s:
        # Serialize reservations for this account, including concurrent clicks.
        s.exec(select(User).where(User.id == user_id).with_for_update()).one()
        if match_id is not None:
            match = find_owned(s, JobMatch, match_id, user_id)
            if match is None:
                raise HTTPException(404, 'Job not found')
            posting = s.get(DiscoveredJob, match.posting_id)
            if posting.url:
                anchor = s.exec(owned(select(JobMatch).join(DiscoveredJob, DiscoveredJob.id == JobMatch.posting_id)
                    .where(DiscoveredJob.url == posting.url), JobMatch, user_id).order_by(JobMatch.id)).first()
                match_id = anchor.id
            existing = s.exec(owned(select(GenerationRequest).where(GenerationRequest.match_id == match_id), GenerationRequest, user_id).with_for_update()).first()
            if existing:
                if existing.state != 'error':
                    return existing.run_id
                run = find_owned(s, Run, existing.run_id, user_id)
                if _reconcile_output(s, existing, run):
                    s.commit()
                    return existing.run_id
                existing.state, existing.error, existing.updated_at = 'queued', '', utc_now()
                existing.lease_token, existing.lease_until = '', None
                run.status, run.finished_at, run.error = RunStatus.queued, None, None
                s.add(run); s.add(existing); s.commit()
                return existing.run_id
        pending = s.exec(owned(select(GenerationRequest).where(GenerationRequest.state.in_(['queued', 'running'])), GenerationRequest, user_id)).all()
        if len(pending) >= 20:
            raise HTTPException(429, 'Document queue is full. Wait for an existing request to finish.')
        run = Run(user_id=user_id, status=RunStatus.queued)
        s.add(run); s.flush()
        s.add(GenerationRequest(user_id=user_id, match_id=match_id, run_id=run.id, payload=payload.model_dump_json()))
        s.commit(); s.refresh(run)
        return run.id


def _work(request_id: int, token: str) -> None:
    from .single_job import GenerateBody, _worker
    with session() as s:
        # noscope: worker acts only on the fenced request dispatched to it.
        request = s.get(GenerationRequest, request_id)
        if not request or not claim_is_current(s, request_id, token):
            return
        user_id, run_id, payload = request.user_id, request.run_id, GenerateBody(**json.loads(request.payload))
        s.commit()
    stop = threading.Event()

    def heartbeat():
        while not stop.wait(30):
            with session() as s:
                if not claim_is_current(s, request_id, token):
                    return
                s.commit()

    threading.Thread(target=heartbeat, daemon=True).start()
    try:
        _worker(run_id, user_id, payload, generation_claim=(request_id, token))
    finally:
        stop.set()
        with session() as s:
            # noscope: completing only this request after rechecking its token.
            if claim_is_current(s, request_id, token):
                request = s.get(GenerationRequest, request_id)
                run = find_owned(s, Run, run_id, user_id)
                if not _reconcile_output(s, request, run):
                    request.state = 'error'
                    request.error = (run.error if run else '') or 'Document generation did not complete. Retry explicitly.'
                    request.updated_at, request.lease_token, request.lease_until = utc_now(), '', None
                s.add(request); s.commit()


def dispatch_generation_queue() -> None:
    now = utc_now()
    dispatch = []
    with session() as s:
        # One DB row serializes capacity decisions across API instances.
        if s.exec(select(User).order_by(User.id).limit(1).with_for_update()).first() is None:
            return
        # noscope: queue dispatch/recovery intentionally scans all accounts.
        rows = s.exec(select(GenerationRequest).where(GenerationRequest.state.in_(['queued', 'running'])).order_by(GenerationRequest.created_at).with_for_update()).all()
        running = []
        for row in rows:
            if row.state == 'running':
                expiry = row.lease_until
                if expiry and expiry.replace(tzinfo=now.tzinfo) > now:
                    running.append(row)
                else:
                    run = find_owned(s, Run, row.run_id, row.user_id)
                    if _reconcile_output(s, row, run):
                        continue
                    row.state, row.error = 'error', 'Generation interrupted; provider work may have been billed. Retry explicitly.'
                    row.lease_token, row.lease_until = '', None
                    if run:
                        run.status, run.error, run.finished_at = RunStatus.error, row.error, now
                        s.add(run)
                    s.add(row)
        busy = {x.user_id for x in running}
        slots = max(0, 2 - len(running))
        for row in rows:
            if not slots or row.state != 'queued' or row.user_id in busy:
                continue
            # Preserve pre-cutover immediate work; historical batches never gate this queue.
            existing = s.exec(owned(select(Run).where(Run.status == RunStatus.running, Run.execution_mode == 'immediate'), Run, row.user_id)).first()
            if existing:
                continue
            user = s.get(User, row.user_id)
            if user is None or user.disabled:
                row.state, row.error = 'error', 'Account unavailable'
                s.add(row)
                continue
            row.state, row.lease_token, row.lease_until, row.updated_at = 'running', uuid.uuid4().hex, now + timedelta(minutes=3), now
            s.add(row)
            dispatch.append((row.id, row.lease_token))
            busy.add(row.user_id); slots -= 1
        s.commit()
    for request_id, token in dispatch:
        threading.Thread(target=_work, args=(request_id, token), daemon=True).start()
