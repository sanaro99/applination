"""Opt-in batch coordinator, run on short ticks by the existing server scheduler."""
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from pathlib import Path
import secrets
import threading
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from .auth import require_user
from .db import BatchJob, BatchRunState, Run, RunStatus, User, Application, session
from .deps import load_config, paths_for
from .scoping import get_owned, owned
from .time_utils import utc_now
from .batch_store import claim_run, renew_run, release_run, load_state, save_state, owned_jobs, start_heartbeat, begin_submission
from .events import bus
from src.batch.adapters import get_batch_adapter, split_requests
from src.batch.capabilities import ROUTES, validate_batch_route
from src.batch.stages import PendingRequest, BatchFailure
from src.batch.workflow import ReplayTailor, prepare_ranking, prepare_generation, job_from_dict

router = APIRouter(prefix='/api', tags=['batch runs'])
log = logging.getLogger(__name__)
TASKS = ('ranking', 'tailoring', 'tailoring_premium', 'cover_letter', 'critique', 'answer_questions')


def validate_routes(routes, user_id):
    if not routes or any(task not in routes for task in TASKS):
        raise ValueError('Choose a batch provider and model for every generation task.')
    cfg = load_config(user_id)
    for task in TASKS:
        route = routes[task]
        sub = cfg.get('llm', {}).get(route['provider'], {})
        validate_batch_route(route['provider'], sub.get('base_url', ''), route['model'])
        if not sub.get('api_key'):
            raise ValueError(f"Add your own {route['provider']} API key in Providers first.")


def adapter_for(provider, user_id):
    return get_batch_adapter(provider, load_config(user_id).get('llm', {}).get(provider, {}))


def _snapshot(run):
    from src.main import fetch_all
    from src.master_resume import load_master
    from src.reference_loader import load_stories, load_example_letters, load_guidelines
    from .runs import _build_excluded_keys
    cfg = load_config(run.user_id)
    paths = paths_for(run.user_id)
    # Persist only generation/search options. No API keys or other credentials.
    options = {k: cfg[k] for k in ('user', 'search', 'output')}
    options['llm'] = {k: cfg.get('llm', {}).get(k, False) for k in (
        'tailoring_premium_top_n', 'critique_cover_letters', 'critique_top_n')}
    options['output'] = {**options['output'], 'root': str(paths.resolve_output(cfg))}
    if run.no_pdf:
        options['output']['produce_pdf'] = False
    if run.max_jobs is not None:
        options['search'] = {**options['search'], 'max_jobs_per_day': run.max_jobs}
    return dict(version=1, cfg=options, routes=json.loads(run.batch_routes),
        master=load_master(paths.resume_path),
        bio=paths.bio_path.read_text(encoding='utf-8') if paths.bio_path.exists() else '',
        stories=load_stories(paths.stories_dir), examples=load_example_letters(paths.cover_letter_examples_dir),
        guidelines=load_guidelines(paths.guidelines_dir),
        jobs=[asdict(j) for j in fetch_all({**cfg, 'search': options['search']}, log)], excluded=list(_build_excluded_keys(run.user_id)),
        transcript={}, applications={}, day=utc_now().date().isoformat(),
        dry_run=run.dry_run, no_cache=run.no_cache)


def _set_run(run_id, user_id, status, **fields):
    with session() as s:
        run = s.exec(owned(select(Run).where(Run.id == run_id), Run, user_id)).first()
        if run:
            run.status = status
            for key, value in fields.items():
                setattr(run, key, value)
            s.add(run); s.commit()


def _save_job(job):
    with session() as s:
        s.add(job); s.commit(); s.refresh(job); s.expunge(job)


def _poll_jobs(run_id, user_id, state, worker):
    now = utc_now()
    for job in owned_jobs(run_id, user_id):
        if job.state == 'prepared':
            # Creation never started. Recover a crash before the uncertainty boundary.
            for key in json.loads(job.request_ids):
                if state['transcript'][key]['state'] != 'succeeded':
                    state['transcript'][key]['state'] = 'prepared'
            job.state = 'superseded'
            _save_job(job)
        if job.state == 'submitting':
            job.state, job.error = 'submission_unknown', 'Submission outcome unknown; reconcile with provider before retrying.'
            _save_job(job)
        if job.state == 'submission_unknown':
            return False
        if job.state not in ('waiting', 'cancel_requested'):
            continue
        if job.poll_count >= 120:
            return False
        due = job.next_poll_at
        if due and due.replace(tzinfo=timezone.utc) > now:
            continue
        job.poll_count += 1
        job.next_poll_at = now + timedelta(seconds=min(900, 60 * 2 ** min(job.poll_count - 1, 4)))
        _save_job(job)  # Count read attempts even when credentials/network are unavailable.
        try:
            adapter = adapter_for(job.provider, user_id)
            status = adapter.status(job.provider_id)
            if status not in ('completed', 'failed', 'expired', 'cancelled'):
                continue
            results = {r['request_id']: r for r in adapter.results(job.provider_id)}
        except Exception as exc:
            # Never repeat submission on a retrieval/auth failure.
            job.error = f'Unable to retrieve batch status/results ({type(exc).__name__}). Check provider credentials.'
            _save_job(job)
            continue
        for key in json.loads(job.request_ids):
            entry = state['transcript'][key]
            if entry['state'] == 'succeeded':
                continue
            result = results.get(key, dict(state='failed', error=f'No result: batch {status}', content=None, usage={}))
            entry.update({k: result.get(k) for k in ('state', 'content', 'usage', 'error')})
        # Save results before marking terminal, so a crash cannot lose consumed outputs.
        save_state(run_id, user_id, worker, state)
        job.state, job.error = status, None
        _save_job(job)
        try:
            adapter.cleanup(job.provider_id)
        except Exception:
            log.info('Batch files retained; provider cleanup was unavailable.')
    return True


def _submit_ready(run_id, user_id, state, worker):
    groups = defaultdict(list)
    for key, entry in state['transcript'].items():
        if entry['state'] == 'prepared':
            groups[(entry['provider'], entry['request']['model'])].append(entry['request'])
    for (provider, model), requests in groups.items():
        for chunk in split_requests(provider, requests):
            if not renew_run(run_id, user_id, worker):
                raise LookupError('Batch lease lost before submission')
            adapter = adapter_for(provider, user_id)  # Credential failure precedes billable submission.
            ids = [r['request_id'] for r in chunk]
            job = BatchJob(run_id=run_id, user_id=user_id, provider=provider, model=model,
                           state='prepared', request_ids=json.dumps(ids))
            _save_job(job)
            for key in ids:
                state['transcript'][key]['state'] = 'waiting'
            save_state(run_id, user_id, worker, state)
            begin_submission(job.id, run_id, user_id, worker)
            job.state = 'submitting'
            try:
                job.provider_id = adapter.submit(chunk, f'run-{run_id}-job-{job.id}')
                if not job.provider_id:
                    raise ValueError('Provider returned no batch identifier')
            except Exception:
                job.state = 'submission_unknown'
                job.error = 'Submission outcome unknown; do not retry until reconciled with the provider.'
                _save_job(job)
                return False
            job.state = 'waiting'
            job.next_poll_at = utc_now() + timedelta(seconds=60)
            _save_job(job)
    return True


def _publish_ready(run_id, user_id, state, worker):
    from src.main import process_job
    from src.job_cache import JobCache
    from .runs import _persist_application
    paths = paths_for(user_id)
    output = paths.resolve_output(state['cfg'])
    day_root = output / state['day']
    for key, app in state['applications'].items():
        if not app.get('ready') or app.get('published') or app.get('cached'):
            continue
        job = job_from_dict(app['job'])
        final = day_root / (job.safe_folder_name() + f'_batch_{run_id}_{key[:6]}')
        manifest_path = final / 'batch_manifest.json'
        if not manifest_path.exists():
            # Staging is outside the served output tree. No partial files are published.
            stage = paths.root / '.batch-staging' / str(run_id) / uuid.uuid4().hex
            stage.mkdir(parents=True, exist_ok=True)
            result = process_job(job, state['master'], state['cfg']['user'], state['bio'],
                state['stories'], state['examples'], state['guidelines'], stage,
                ReplayTailor(state['routes'], key, state['transcript']),
                state['cfg']['output'], log, critique_letter=app['critique'], quality_tier=app['quality_tier'])
            if result.get('error'):
                app['render_error'] = result['error']
                continue
            folder = stage / result['folder_name']
            manifest = {**result, 'folder_name': final.name}
            for name in ('resume_file', 'cover_file', 'answers_file'):
                manifest[name] = str((final / Path(result[name]).name).relative_to(output)).replace('\\', '/') if result.get(name) else ''
            (folder / 'batch_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            if not renew_run(run_id, user_id, worker):
                raise LookupError('Batch lease lost before publication')
            day_root.mkdir(parents=True, exist_ok=True)
            folder.replace(final)
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        with session() as s:
            existing = s.exec(owned(select(Application).where(Application.run_id == run_id,
                Application.folder_path == str(final)), Application, user_id)).first()
        if existing is None:
            if not renew_run(run_id, user_id, worker):
                raise LookupError('Batch lease lost before database publication')
            from sqlalchemy.exc import IntegrityError
            try:
                _persist_application(run_id, user_id, {**manifest, **asdict(job),
                    'score': job.match_score, 'reason': job.match_reason, 'folder': str(final),
                    'folder_rel': final.name, 'batch_item_key': f'{user_id}:{run_id}:{key}',
                    'batch_lease_owner': worker})
            except IntegrityError:
                with session() as s:
                    matching = s.exec(owned(select(Application).where(
                        Application.batch_item_key == f'{user_id}:{run_id}:{key}'), Application, user_id)).first()
                    if matching is None:
                        raise
        app.update(published=True, manifest=manifest)
        cache = JobCache(output, ttl_days=state['cfg']['search'].get('cache_ttl_days', 7), enabled=not state['no_cache'])
        cache.put(job.dedupe_key(), manifest)
        save_state(run_id, user_id, worker, state)


def advance_batch_run(run_id, user_id):
    worker = uuid.uuid4().hex
    if not claim_run(run_id, user_id, worker):
        return
    stop = threading.Event()
    def heartbeat():
        while not stop.wait(30):
            try:
                if not renew_run(run_id, user_id, worker):
                    return
            except Exception:
                return
    threading.Thread(target=heartbeat, daemon=True).start()
    state = None
    try:
        with session() as s:
            run = s.exec(owned(select(Run).where(Run.id == run_id), Run, user_id)).first()
            if run is None or run.status in (RunStatus.done, RunStatus.cancelled):
                return
            s.expunge(run)
        state = load_state(run_id, user_id)
        if not state:
            state = _snapshot(run)
            save_state(run_id, user_id, worker, state)
        if state.get('version') != 1:
            raise ValueError('Unsupported batch snapshot version')
        if not _poll_jobs(run_id, user_id, state, worker):
            _set_run(run_id, user_id, RunStatus.batch_paused,
                     error='Batch paused: reconcile submission or explicitly resume status polling.')
            return
        if state.get('cancel_requested'):
            if state.get('ranking_done') and not state.get('dry_run'):
                prepare_generation(state)  # Local validation/replay only; never submit newly ready work.
                _publish_ready(run_id, user_id, state, worker)
            for entry in state.get('transcript', {}).values():
                if entry['state'] == 'prepared':
                    entry['state'] = 'cancelled'
            save_state(run_id, user_id, worker, state)
            active = [j for j in owned_jobs(run_id, user_id) if j.state in ('waiting', 'cancel_requested')]
            if not active:
                _set_run(run_id, user_id, RunStatus.cancelled, finished_at=utc_now())
            return
        if any(e['state'] == 'submission_unknown' for e in state.get('transcript', {}).values()):
            _set_run(run_id, user_id, RunStatus.batch_paused, error='Immediate completion outcome unknown; reconcile before retrying.')
            return
        if not state.get('ranking_done'):
            prepare_ranking(state)
        if state.get('ranking_done'):
            from src.job_cache import JobCache
            cache = JobCache(paths_for(user_id).resolve_output(state['cfg']),
                ttl_days=state['cfg']['search'].get('cache_ttl_days', 7), enabled=not state['no_cache'])
            for key, app in state['applications'].items():
                if 'cache_checked' not in app:
                    app['cache_checked'] = True
                    app['cached'] = cache.get(key)
            if not state['dry_run']:
                prepare_generation(state)
                _publish_ready(run_id, user_id, state, worker)
        save_state(run_id, user_id, worker, state)
        if not _submit_ready(run_id, user_id, state, worker):
            _set_run(run_id, user_id, RunStatus.batch_paused, error='Submission outcome unknown; reconcile with provider.')
            return
        entries = list(state['transcript'].values())
        waiting = any(e['state'] in ('prepared', 'waiting') for e in entries)
        failed = any(e['state'] == 'failed' for e in entries) or state.get('ranking_error') or any(
            a.get('render_error') or any(a.get(k) == 'failed' for k in ('resume', 'letter', 'answers'))
            for a in state['applications'].values())
        count = sum(bool(a.get('published')) for a in state['applications'].values())
        status = RunStatus.waiting if waiting else RunStatus.partial_failed if failed else RunStatus.done
        if status == RunStatus.done and state.get('ranking_done'):
            from src.excel_writer import build_tracker
            day_root = paths_for(user_id).resolve_output(state['cfg']) / state['day']
            day_root.mkdir(parents=True, exist_ok=True)
            rows = [{**a['job'], **(a.get('manifest') or a.get('cached') or {})}
                    for a in state['applications'].values()]
            if state['dry_run']:
                (day_root / f'ranked_jobs_batch_{run_id}.json').write_text(json.dumps(rows, default=str), encoding='utf-8')
            elif rows:
                build_tracker(rows, day_root / f'applications_batch_{run_id}.xlsx', state['day'])
        _set_run(run_id, user_id, status, applications_created=count, jobs_found=len(state.get('jobs', [])),
                 day_root=str(paths_for(user_id).resolve_output(state.get('cfg')) / state.get('day', '')),
                 finished_at=utc_now() if status == RunStatus.done else None,
                 error='Some batch items need review or explicit retry.' if failed else None)
        try:
            bus.publish_threadsafe(run_id, {'type': 'batch_status', 'status': status.value,
                                           'applications': count})
        except RuntimeError:
            # Persisted status is authoritative even if the SSE loop has shut down.
            log.debug('Batch run %s notification loop unavailable', run_id)
    except (PendingRequest, BatchFailure):
        if state is not None:
            save_state(run_id, user_id, worker, state)
        _set_run(run_id, user_id, RunStatus.batch_paused, error='Batch needs review before continuing.')
    except LookupError:
        # A new lease holder owns recovery; the stale worker must not overwrite it.
        return
    except Exception as exc:
        # Avoid logging credential-bearing provider messages or snapshots.
        log.warning('Batch run %s paused (%s)', run_id, type(exc).__name__)
        if state is not None:
            save_state(run_id, user_id, worker, state)
        _set_run(run_id, user_id, RunStatus.batch_paused,
                 error=f'Batch preparation paused ({type(exc).__name__}); inspect settings and resume.')
    finally:
        stop.set()
        release_run(run_id, user_id, worker)


def dispatch_due_batches():
    # Global scheduler selection; each dispatched operation retains owner scoping.
    with session() as s:
        # noscope: global scheduler; selected owner IDs accompany every dispatched operation.
        rows = s.exec(select(Run).where(Run.execution_mode == 'batch',
            Run.status.in_([RunStatus.queued, RunStatus.waiting])).order_by(Run.id)).all()
        ids = [(r.id, r.user_id) for r in rows]
    for run_id, user_id in ids:
        advance_batch_run(run_id, user_id)
    return len(ids)


@router.get('/batch-capabilities')
def capabilities(user: User = Depends(require_user)):
    cfg = load_config(user)
    return [{**validate_batch_route(provider, '', model),
             'configured': bool(cfg.get('llm', {}).get(provider, {}).get('api_key'))}
            for provider, info in ROUTES.items() for model in info['models']]


def _owned_run(run_id, user_id):
    with session() as s:
        run = get_owned(s, Run, run_id, user_id)
        if run.execution_mode != 'batch':
            raise HTTPException(400, 'This is an immediate run.')
        s.expunge(run)
        return run


@router.get('/runs/{run_id}/batch')
def batch_status(run_id: int, user: User = Depends(require_user)):
    run = _owned_run(run_id, user.id)
    state = load_state(run_id, user.id)
    entries = state.get('transcript', {})
    jobs = owned_jobs(run_id, user.id)
    return dict(status=run.status, cancel_requested=state.get('cancel_requested', False),
        counts={name: sum(e['state'] == name for e in entries.values())
                for name in ('prepared', 'waiting', 'succeeded', 'failed')},
        items=[dict(id=key, state=e['state'], task=e['request']['task'],
                    error=e.get('error'),
                    application_key=e.get('application_key'), usage=e.get('usage'),
                    label=state.get('applications', {}).get(e.get('application_key', '').split(':')[0], {}).get('job', {}).get('company'))
               for key, e in entries.items()],
        jobs=[dict(id=j.id, provider=j.provider, model=j.model, state=j.state,
                   provider_id=j.provider_id, next_poll_at=j.next_poll_at, error=j.error) for j in jobs])


class PreviewBody(BaseModel):
    item_ids: list[str]
    action: str


class ConfirmBody(BaseModel):
    preview_token: str


class ReconcileBody(BaseModel):
    job_id: int
    provider_id: str


@router.post('/runs/{run_id}/batch/reconcile')
def reconcile(run_id: int, body: ReconcileBody, user: User = Depends(require_user)):
    _owned_run(run_id, user.id)
    # Never accept URLs: SDK identifiers must refer only to the user's native endpoint.
    import re
    if not re.fullmatch(r'(?:batch_[A-Za-z0-9_-]+|msgbatch_[A-Za-z0-9_-]+|batches/[A-Za-z0-9_-]+)', body.provider_id):
        raise HTTPException(400, 'Enter a native provider batch identifier.')
    worker = uuid.uuid4().hex
    if not claim_run(run_id, user.id, worker):
        raise HTTPException(409, 'Batch is currently processing.')
    heartbeat = start_heartbeat(run_id, user.id, worker)
    try:
        job = next((j for j in owned_jobs(run_id, user.id) if j.id == body.job_id), None)
        if not job or job.state != 'submission_unknown':
            raise HTTPException(409, 'Choose an unresolved submission from this run.')
        adapter = adapter_for(job.provider, user.id)
        if adapter.status(body.provider_id) not in ('completed', 'failed', 'expired', 'cancelled'):
            raise HTTPException(409, 'Wait for the original provider batch to finish before linking its results.')
        results = adapter.results(body.provider_id)
        if {r['request_id'] for r in results} != set(json.loads(job.request_ids)):
            raise HTTPException(409, 'Provider batch request IDs do not match this submission.')
        job.provider_id, job.state, job.next_poll_at, job.error = body.provider_id, 'waiting', None, None
        _save_job(job)
        _set_run(run_id, user.id, RunStatus.waiting, error=None)
    finally:
        heartbeat.set()
        release_run(run_id, user.id, worker)
    return {'status': 'waiting'}


@router.post('/runs/{run_id}/batch/preview')
def preview(run_id: int, body: PreviewBody, user: User = Depends(require_user)):
    _owned_run(run_id, user.id)
    if body.action not in ('retry', 'complete-now'):
        raise HTTPException(400, 'Unsupported recovery action')
    worker = uuid.uuid4().hex
    if not claim_run(run_id, user.id, worker):
        raise HTTPException(409, 'Batch is currently processing; retry shortly.')
    try:
        state = load_state(run_id, user.id)
        selected = sorted(set(body.item_ids))
        entries = state.get('transcript', {})
        if not selected or any(key not in entries or entries[key]['state'] != 'failed' for key in selected):
            raise HTTPException(409, 'Choose only failed items; completed or uncertain submissions cannot be retried.')
        digest = hashlib.sha256(json.dumps({k: entries[k] for k in selected}, sort_keys=True).encode()).hexdigest()
        token = secrets.token_urlsafe(32)
        state['preview'] = dict(token_hash=hashlib.sha256(token.encode()).hexdigest(),
            action=body.action, item_ids=selected, digest=digest, expires=(utc_now() + timedelta(minutes=10)).isoformat())
        save_state(run_id, user.id, worker, state)
        return dict(preview_token=token, item_ids=selected, action=body.action, estimated_cost_usd=None,
                    notice='Cost is unknown. Retry uses discounted batches; OpenAI reasoning batches reserve up to twice the output budget (at most 4,000 extra tokens). Complete-now uses standard API pricing and ordinary token limits.')
    finally:
        release_run(run_id, user.id, worker)


def _recover(run_id, user_id, body, action):
    _owned_run(run_id, user_id)
    worker = uuid.uuid4().hex
    if not claim_run(run_id, user_id, worker):
        raise HTTPException(409, 'Batch is currently processing.')
    heartbeat = start_heartbeat(run_id, user_id, worker)
    try:
        state = load_state(run_id, user_id)
        p = state.get('preview', {})
        if (p.get('action') != action or p.get('token_hash') != hashlib.sha256(body.preview_token.encode()).hexdigest()
            or datetime.fromisoformat(p['expires']) < utc_now()):
            raise HTTPException(409, 'Preview expired; review the selected items again.')
        entries = state['transcript']
        selected = p['item_ids']
        digest = hashlib.sha256(json.dumps({k: entries[k] for k in selected}, sort_keys=True).encode()).hexdigest()
        if digest != p['digest'] or any(entries[k]['state'] != 'failed' for k in selected):
            raise HTTPException(409, 'Items changed; preview again.')
        state.pop('preview')
        state.pop('ranking_error', None)
        save_state(run_id, user_id, worker, state)  # Consume confirmation before paid calls.
        for key in selected:
            entry = entries[key]
            if action == 'retry':
                entry.update(state='prepared', error=None)
            else:
                from src.providers.factory import get_provider
                request = entry['request']
                try:
                    provider = get_provider(entry['provider'], load_config(user_id)['llm'],
                        model_override=request['model'], thinking=request['thinking'], user_id=user_id)
                except Exception:
                    raise HTTPException(400, 'Provider could not be initialized; check your API key and preview again.')
                # Crossing this boundary can spend money; creation failure above cannot.
                entry['state'] = 'submission_unknown'
                save_state(run_id, user_id, worker, state)
                try:
                    content = (provider.json_call(request['system'], request['user'], request['max_tokens'], schema=request['schema'])
                               if request['json_mode'] else provider.text_call(request['system'], request['user'], request['max_tokens']))
                    entry.update(state='succeeded', content=content, error=None)
                except Exception:
                    entry['error'] = 'Immediate completion outcome unknown; reconcile before another paid call.'
                    save_state(run_id, user_id, worker, state)
                    raise HTTPException(502, entry['error'])
            save_state(run_id, user_id, worker, state)
        _set_run(run_id, user_id, RunStatus.waiting, error=None)
    finally:
        heartbeat.set()
        release_run(run_id, user_id, worker)
    return {'status': 'waiting'}


@router.post('/runs/{run_id}/batch/retry')
def retry(run_id: int, body: ConfirmBody, user: User = Depends(require_user)):
    return _recover(run_id, user.id, body, 'retry')


@router.post('/runs/{run_id}/batch/complete-now')
def complete_now(run_id: int, body: ConfirmBody, user: User = Depends(require_user)):
    return _recover(run_id, user.id, body, 'complete-now')


@router.post('/runs/{run_id}/batch/resume')
def resume(run_id: int, user: User = Depends(require_user)):
    _owned_run(run_id, user.id)
    worker = uuid.uuid4().hex
    if not claim_run(run_id, user.id, worker):
        raise HTTPException(409, 'Batch is currently processing.')
    try:
        state = load_state(run_id, user.id)
        if any(j.state == 'submission_unknown' for j in owned_jobs(run_id, user.id)) or any(
            e['state'] == 'submission_unknown' for e in state.get('transcript', {}).values()):
            raise HTTPException(409, 'Reconcile unknown submission with the provider first; automatic resubmission is disabled.')
        for job in owned_jobs(run_id, user.id):
            if job.state in ('waiting', 'cancel_requested'):
                job.poll_count, job.next_poll_at = 0, None
                _save_job(job)
        _set_run(run_id, user.id, RunStatus.waiting, error=None)
    finally:
        release_run(run_id, user.id, worker)
    return {'status': 'waiting'}


@router.post('/runs/{run_id}/batch/cancel')
def cancel(run_id: int, user: User = Depends(require_user)):
    run = _owned_run(run_id, user.id)
    worker = uuid.uuid4().hex
    if not claim_run(run_id, user.id, worker):
        raise HTTPException(409, 'Batch is currently processing; retry shortly.')
    heartbeat = start_heartbeat(run_id, user.id, worker)
    try:
        if run.status == RunStatus.scheduled:
            _set_run(run_id, user.id, RunStatus.cancelled, finished_at=utc_now())
            return {'status': 'cancelled'}
        state = load_state(run_id, user.id)
        if not state and not owned_jobs(run_id, user.id):
            _set_run(run_id, user.id, RunStatus.cancelled, finished_at=utc_now())
            return {'status': 'cancelled'}
        state['cancel_requested'] = True
        save_state(run_id, user.id, worker, state)
        for job in owned_jobs(run_id, user.id):
            if job.state in ('submission_unknown', 'submitting'):
                # Cancellation authorizes abandonment, never a new paid submission.
                job.state = 'abandoned'
                job.error = 'Original submission outcome remains unknown and may still be billed. No resubmission will occur.'
                for key in json.loads(job.request_ids):
                    if state['transcript'][key]['state'] != 'succeeded':
                        state['transcript'][key]['state'] = 'cancelled'
                _save_job(job)
            if job.state == 'waiting' and job.provider_id:
                adapter_for(job.provider, user.id).cancel(job.provider_id)
                job.state, job.next_poll_at = 'cancel_requested', None
                _save_job(job)
        for entry in state.get('transcript', {}).values():
            if entry['state'] == 'submission_unknown':
                entry['state'] = 'cancelled'
        save_state(run_id, user.id, worker, state)
        _set_run(run_id, user.id, RunStatus.waiting, error=None)
    except Exception as exc:
        _set_run(run_id, user.id, RunStatus.batch_paused, error='Provider cancellation unavailable; resume to confirm status.')
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(502, 'Provider cancellation unavailable; already processed requests may be billed.')
    finally:
        heartbeat.set()
        release_run(run_id, user.id, worker)
    return {'status': 'cancellation_requested', 'notice': 'Already processed requests may still be billed.'}
