"""Run endpoints: trigger, list, SSE stream."""
from __future__ import annotations
import asyncio
import logging
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from sqlmodel import select

from .db import (
    Application,
    ApplicationStatus,
    RankedJob,
    Run,
    RunStatus,
    session,
)
from .deps import load_config
from .events import bus, sse_format

router = APIRouter(prefix="/api/runs", tags=["runs"])
log = logging.getLogger("server.runs")

# Cooperative cancellation. A pipeline runs in a daemon thread that we cannot
# safely kill, so a stop request just records the desired mode here; the
# pipeline polls it (via the `should_stop` callback) at stage boundaries and
# between jobs. "graceful" lets the in-progress job finish and still writes the
# tracker; "hard" stops without the tracker. A "hard" request is never
# downgraded back to "graceful".
_stop_requests: dict[int, str] = {}
_stop_lock = threading.Lock()


def _request_stop(run_id: int, mode: str) -> None:
    with _stop_lock:
        if _stop_requests.get(run_id) == "hard":
            return
        _stop_requests[run_id] = mode


def _stop_check(run_id: int) -> Callable[[], str | None]:
    def check() -> str | None:
        with _stop_lock:
            return _stop_requests.get(run_id)
    return check


def _clear_stop(run_id: int) -> None:
    with _stop_lock:
        _stop_requests.pop(run_id, None)


# Slider bounds for the per-run count override (5..30). Mirrors the frontend.
_MIN_JOBS, _MAX_JOBS = 5, 30


def _clamp_max_jobs(n: int) -> int:
    return max(_MIN_JOBS, min(_MAX_JOBS, int(n)))


def _active_run_exists() -> bool:
    """True if a run is queued or running (a scheduled run is NOT active)."""
    with session() as s:
        row = s.exec(
            select(Run).where(Run.status.in_([RunStatus.queued, RunStatus.running]))
        ).first()
    return row is not None


def _start_worker_thread(run: Run) -> None:
    """Spawn the pipeline thread for an already-persisted Run row."""
    threading.Thread(
        target=_worker,
        args=(run.id, run.dry_run, run.no_pdf, run.no_cache, run.max_jobs),
        daemon=True,
    ).start()


def dispatch_due_scheduled_runs() -> None:
    """Fire any scheduled runs whose time has come, one at a time.

    Called by the lifespan poller (~60s). Because scheduled runs live in the DB,
    they survive a server restart — the poller re-picks them up. Skips dispatch
    while another run is active so we never run two pipelines at once.
    """
    if _active_run_exists():
        return
    now = datetime.utcnow()
    with session() as s:
        due = s.exec(
            select(Run)
            .where(Run.status == RunStatus.scheduled, Run.scheduled_for <= now)
            .order_by(Run.scheduled_for)
        ).all()
        due_ids = [r.id for r in due]
    for run_id in due_ids:
        if _active_run_exists():
            break  # let the running one finish; retry the rest next tick
        with session() as s:
            run = s.get(Run, run_id)
            if run is None or run.status != RunStatus.scheduled:
                continue
            run.status = RunStatus.queued  # claim it before the thread starts
            s.add(run)
            s.commit()
            s.refresh(run)
        log.info("dispatching scheduled run %d (was due %s)", run_id, run.scheduled_for)
        _start_worker_thread(run)


class StartRunBody(BaseModel):
    dry_run: bool = False
    no_pdf: bool = False
    no_cache: bool = False
    max_jobs: int | None = None  # override search.max_jobs_per_day for this run
    scheduled_for: datetime | None = None  # defer until this UTC time (else run now)


class RunOut(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime | None
    status: RunStatus
    dry_run: bool
    no_pdf: bool
    no_cache: bool
    max_jobs: int | None
    scheduled_for: datetime | None
    jobs_found: int
    applications_created: int
    day_root: str | None
    error: str | None


def _run_to_out(r: Run) -> RunOut:
    return RunOut(
        id=r.id,  # type: ignore[arg-type]
        started_at=r.started_at,
        finished_at=r.finished_at,
        status=r.status,
        dry_run=r.dry_run,
        no_pdf=r.no_pdf,
        no_cache=r.no_cache,
        max_jobs=r.max_jobs,
        scheduled_for=r.scheduled_for,
        jobs_found=r.jobs_found,
        applications_created=r.applications_created,
        day_root=r.day_root,
        error=r.error,
    )


def _build_excluded_keys() -> set[str]:
    """Identities (company|title) to keep out of this run: anything we already
    generated an application for, plus jobs the user dismissed in triage. Keeps
    the pipeline from re-tailoring or re-surfacing work that's already done.

    Computed from company/title via the shared helper so it works for rows
    predating the stored ``dedupe_key`` column."""
    from src.scrapers import dedupe_key as _dk
    keys: set[str] = set()
    with session() as s:
        for company, title in s.exec(
            select(Application.company, Application.title)
        ).all():
            keys.add(_dk(company, title))
        for company, title in s.exec(
            select(RankedJob.company, RankedJob.title).where(RankedJob.dismissed)
        ).all():
            keys.add(_dk(company, title))
    return keys


def _worker(
    run_id: int,
    dry_run: bool,
    no_pdf: bool,
    no_cache: bool,
    max_jobs: int | None = None,
) -> None:
    """Background thread: execute the pipeline and stream events."""
    from src.main import setup_logging
    from src.pipeline import run_pipeline

    pipeline_log = setup_logging()

    def on_event(evt: dict) -> None:
        bus.publish_threadsafe(run_id, evt)
        etype = evt.get("type")
        if etype == "rank_pool":
            _persist_ranked_pool(run_id, evt)
        elif etype == "job_completed" and not evt.get("error"):
            _persist_application(run_id, evt)

    with session() as s:
        run = s.get(Run, run_id)
        if run is None:
            return
        run.status = RunStatus.running
        run.log_path = str(
            Path("logs") / f"run_{date.today().isoformat()}.log"
        )
        s.add(run)
        s.commit()

    try:
        cfg = load_config()
        if max_jobs is not None:
            cfg["search"]["max_jobs_per_day"] = _clamp_max_jobs(max_jobs)
        summary = run_pipeline(
            cfg,
            dry_run=dry_run,
            no_pdf=no_pdf,
            no_cache=no_cache,
            on_event=on_event,
            log=pipeline_log,
            should_stop=_stop_check(run_id),
            excluded_keys=_build_excluded_keys(),
        )
        with session() as s:
            run = s.get(Run, run_id)
            if run:
                run.status = (
                    RunStatus.cancelled if summary.get("stopped") else RunStatus.done
                )
                run.finished_at = datetime.utcnow()
                run.jobs_found = summary.get("jobs_found", 0)
                run.applications_created = summary.get("applications", 0)
                run.day_root = summary.get("day_root") or None
                s.add(run)
                s.commit()
    except Exception as e:
        log.exception("pipeline failed: %s", e)
        with session() as s:
            run = s.get(Run, run_id)
            if run:
                run.status = RunStatus.error
                run.finished_at = datetime.utcnow()
                run.error = str(e)
                s.add(run)
                s.commit()
        bus.publish_threadsafe(run_id, {"type": "error", "msg": str(e)})
    finally:
        _clear_stop(run_id)


def _persist_ranked_pool(run_id: int, evt: dict) -> None:
    """Store the full scored job pool for a run (idempotent per run)."""
    from src.scrapers import dedupe_key as _dk
    jobs = evt.get("jobs") or []
    with session() as s:
        existing = s.exec(
            select(RankedJob).where(RankedJob.run_id == run_id)
        ).all()
        for r in existing:
            s.delete(r)
        for j in jobs:
            company = j.get("company", "")
            title = j.get("title", "")
            s.add(RankedJob(
                run_id=run_id,
                company=company,
                title=title,
                location=j.get("location", ""),
                url=j.get("url", ""),
                source=j.get("source", ""),
                description=j.get("description", "") or "",
                remote=bool(j.get("remote", False)),
                match_score=int(j.get("score") or 0),
                match_reason=j.get("reason", "") or "",
                selected=bool(j.get("selected", False)),
                dedupe_key=_dk(company, title),
            ))
        s.commit()


def _persist_application(run_id: int, evt: dict) -> None:
    folder = evt.get("folder") or ""
    if not folder:
        return
    folder_path = Path(folder)
    # folder_rel is relative to out_root (the dir mounted at /files), i.e.
    # "<date>/<folder>" — NOT relative to out_root.parent, which prepended the
    # "output/" segment and 404'd the previews. Use the last two path components
    # (folder is always output/<date>/<folder>), matching single_job.py.
    rel_parts = [p for p in folder_path.parts if p not in ("", ".")]
    rel = "/".join(rel_parts[-2:]) if len(rel_parts) >= 2 else folder_path.name
    from src.scrapers import dedupe_key as _dk
    company = evt.get("company", "")
    title = evt.get("title", "")
    with session() as s:
        app = Application(
            run_id=run_id,
            company=company,
            title=title,
            location=evt.get("location", ""),
            url=evt.get("url", ""),
            source=evt.get("source", ""),
            match_score=int(evt.get("score") or 0),
            match_reason=evt.get("reason", "") or "",
            dedupe_key=_dk(company, title),
            description=evt.get("description", "") or "",
            folder_path=str(folder_path),
            folder_rel=rel,
            resume_file=evt.get("resume_file", ""),
            cover_file=evt.get("cover_file", ""),
            answers_file=evt.get("answers_file", ""),
            status=ApplicationStatus.generated,
        )
        s.add(app)
        s.commit()
        s.refresh(app)
        # Link the matching ranked-pool row so the triage view shows it generated.
        _link_ranked(s, run_id, evt, app.id)


def _link_ranked(s, run_id: int, evt: dict, app_id: int | None) -> None:
    if app_id is None:
        return
    url = (evt.get("url") or "").strip()
    company = evt.get("company", "")
    title = evt.get("title", "")
    q = select(RankedJob).where(
        RankedJob.run_id == run_id, RankedJob.application_id == None  # noqa: E711
    )
    if url:
        q = q.where(RankedJob.url == url)
    else:
        q = q.where(RankedJob.company == company, RankedJob.title == title)
    match = s.exec(q).first()
    if match:
        match.application_id = app_id
        s.add(match)
        s.commit()


@router.post("", response_model=RunOut)
def start_run(body: StartRunBody | None = None) -> RunOut:
    # Body is optional: an empty POST starts a normal (non-dry) run with defaults.
    body = body or StartRunBody()
    max_jobs = _clamp_max_jobs(body.max_jobs) if body.max_jobs is not None else None

    # Schedule for later if a future time was given (else run immediately).
    now = datetime.utcnow()
    sched = body.scheduled_for
    if sched is not None and sched.tzinfo is not None:
        sched = sched.astimezone(timezone.utc).replace(tzinfo=None)
    is_scheduled = sched is not None and sched > now

    if not is_scheduled and _active_run_exists():
        raise HTTPException(409, "A run is already in progress. Wait for it to finish.")

    with session() as s:
        run = Run(
            dry_run=body.dry_run,
            no_pdf=body.no_pdf,
            no_cache=body.no_cache,
            max_jobs=max_jobs,
            scheduled_for=sched if is_scheduled else None,
            status=RunStatus.scheduled if is_scheduled else RunStatus.queued,
        )
        s.add(run)
        s.commit()
        s.refresh(run)
        out = _run_to_out(run)
        # Detached copy so the worker thread can read fields after the session closes.
        thread_run = Run(**run.model_dump())

    if is_scheduled:
        log.info("run %d scheduled for %s UTC (max_jobs=%s)", out.id, sched, max_jobs)
        return out

    _start_worker_thread(thread_run)
    return out


class StopRunBody(BaseModel):
    graceful: bool = True


@router.post("/{run_id}/stop", response_model=RunOut)
def stop_run(run_id: int, body: StopRunBody | None = None) -> RunOut:
    """Request cancellation of an in-flight run.

    `graceful=true` finishes the job currently being tailored and still writes
    the Excel tracker; `graceful=false` stops as soon as that job returns,
    skipping the tracker. Either way the run ends with status `cancelled`.

    The body is optional; an empty POST defaults to a graceful stop.
    """
    graceful = body.graceful if body is not None else True
    with session() as s:
        r = s.get(Run, run_id)
        if r is None:
            raise HTTPException(404, "run not found")
        # A scheduled run has no worker thread yet — cancel it directly.
        if r.status == RunStatus.scheduled:
            r.status = RunStatus.cancelled
            r.finished_at = datetime.utcnow()
            s.add(r)
            s.commit()
            return _run_to_out(r)
        if r.status not in (RunStatus.running, RunStatus.queued):
            raise HTTPException(
                409, f"run #{run_id} is not active (status={r.status.value})"
            )
    mode = "graceful" if graceful else "hard"
    _request_stop(run_id, mode)
    log.info("stop requested for run %d (%s)", run_id, mode)
    # Surface a non-terminal event so live subscribers can show "stopping…".
    bus.publish_threadsafe(run_id, {"type": "stopping", "graceful": graceful})
    with session() as s:
        r = s.get(Run, run_id)
        return _run_to_out(r)


@router.get("", response_model=list[RunOut])
def list_runs(limit: int = 50) -> list[RunOut]:
    with session() as s:
        rows = s.exec(select(Run).order_by(Run.started_at.desc()).limit(limit)).all()
        return [_run_to_out(r) for r in rows]


@router.get("/{run_id}", response_model=RunOut)
def get_run(run_id: int) -> RunOut:
    with session() as s:
        r = s.get(Run, run_id)
        if r is None:
            raise HTTPException(404, "run not found")
        return _run_to_out(r)


@router.get("/{run_id}/log")
def run_log(run_id: int) -> dict:
    """Return the run's log file contents (tail if oversized)."""
    from .deps import ROOT
    with session() as s:
        r = s.get(Run, run_id)
        if r is None:
            raise HTTPException(404, "run not found")
    if not r.log_path:
        return {"text": "", "path": ""}
    log_path = Path(r.log_path)
    if not log_path.is_absolute():
        log_path = ROOT / log_path
    if not log_path.exists():
        return {"text": "", "path": str(log_path)}
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"text": f"<log read error: {e}>", "path": str(log_path)}
    if len(text) > 400_000:
        text = text[-400_000:]
    return {"text": text, "path": str(log_path)}


@router.get("/{run_id}/stream")
async def stream_run(run_id: int):
    async def gen():
        async for evt in bus.subscribe(run_id):
            yield {"data": sse_format(evt).removeprefix("data: ").rstrip("\n\n")}
            if evt.get("type") in ("done", "error", "cancelled"):
                break
    return EventSourceResponse(gen())
