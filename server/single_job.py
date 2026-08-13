"""Single-job (manual URL or paste) workflow — port of the old Streamlit app.

The frontend hits POST /extract to pull a URL into a job dict, then POST
/generate to run process_job() against a single submitted job. We reuse the
Run table so the existing /api/runs/{id}/stream endpoint streams progress.
"""
from __future__ import annotations
import logging
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import select

from .auth import require_owner
from .db import (
    Application,
    ApplicationStatus,
    RankedJob,
    Run,
    RunStatus,
    User,
    session,
)
from .deps import load_config
from .events import bus
from .limits import LLM_LIMIT, limiter
from .scoping import find_owned

router = APIRouter(prefix="/api/single-job", tags=["single-job"])
log = logging.getLogger("server.single_job")


class ExtractBody(BaseModel):
    url: str


class ExtractedJob(BaseModel):
    company: str = ""
    title: str = ""
    location: str = ""
    remote: bool = False
    description: str = ""
    additional_questions: list[str] = []
    specific_instructions: str = ""
    url: str = ""


@router.post("/extract", response_model=ExtractedJob)
@limiter.limit(LLM_LIMIT)
def extract(
    request: Request,
    body: ExtractBody,
    # Owner-only until PR 3: uses the global config's provider keys.
    user: User = Depends(require_owner),
) -> ExtractedJob:
    if not body.url.strip():
        raise HTTPException(400, "url is required")
    if "linkedin.com" in body.url.lower():
        # LinkedIn blocks automated browsers; let the user fill it manually.
        return ExtractedJob(url=body.url)

    from src.job_extractor import JobExtractor
    from src.providers import get_provider_chain

    cfg = load_config()
    chain = get_provider_chain(cfg["llm"])
    extractor = JobExtractor(chain[0])
    try:
        data: dict[str, Any] = extractor.extract(body.url)
    except Exception as e:  # graceful fallback
        log.warning("extract failed for %s: %s", body.url, e)
        return ExtractedJob(url=body.url)
    return ExtractedJob(**{**data, "url": body.url})


class GenerateBody(BaseModel):
    company: str
    title: str
    location: str = ""
    remote: bool = False
    description: str
    url: str = ""
    additional_questions: list[str] = []
    specific_instructions: str = ""
    # Optional provenance — set when generating a ranked/rescued job rather than
    # a fresh manual submission, so the persisted Application keeps its score.
    source: str = "manual"
    match_score: int = 0
    match_reason: str = "manual submission"
    ranked_id: int | None = None


def _worker(run_id: int, user_id: int, payload: GenerateBody) -> None:
    """Background thread: process a single job and stream events."""
    from src.main import setup_logging, process_job
    from src.pipeline import _EventLogHandler
    from src.scrapers.schema import Job
    from src.providers import get_task_chains
    from src.tailor import Tailor
    from src.reference_loader import (
        load_stories,
        load_example_letters,
        load_guidelines,
    )

    pipeline_log = setup_logging()

    def emit(evt: dict) -> None:
        bus.publish_threadsafe(run_id, evt)

    # Forward all INFO+ log records as SSE log events (same pattern as
    # run_pipeline in pipeline.py; single_job bypasses that path so we wire it
    # up here instead).
    evt_handler = _EventLogHandler(emit)
    evt_handler.setLevel(logging.INFO)
    evt_handler.setFormatter(logging.Formatter("%(message)s"))
    root_log = logging.getLogger()
    root_log.setLevel(logging.INFO)
    root_log.addHandler(evt_handler)

    try:
        with session() as s:
            # noscope: background thread acting on the run it was spawned for.
            run = s.get(Run, run_id)
            if run is None:
                return
            run.status = RunStatus.running
            run.log_path = str(Path("logs") / f"run_{date.today().isoformat()}.log")
            s.add(run)
            s.commit()

        try:
            cfg = load_config()
            master_path = Path(__file__).resolve().parent.parent / "master_data"
            import yaml
            master = yaml.safe_load(
                (master_path / "resume.yaml").read_text(encoding="utf-8")
            )
            bio_path = master_path / "bio.md"
            bio = bio_path.read_text(encoding="utf-8") if bio_path.exists() else ""
            all_stories = load_stories(master_path / "stories")
            all_examples = load_example_letters(master_path / "cover_letters" / "examples")
            all_guidelines = load_guidelines(master_path / "guidelines")

            task_chains = get_task_chains(cfg["llm"])
            tailor = Tailor(task_chains=task_chains,
                            critique_cover_letters=cfg["llm"].get(
                                "critique_cover_letters", False))

            out_cfg = dict(cfg["output"])
            day = date.today().isoformat()
            day_root = Path(out_cfg["root"]) / day
            day_root.mkdir(parents=True, exist_ok=True)

            job = Job(
                source="manual",
                company=payload.company,
                title=payload.title,
                location=payload.location,
                url=payload.url,
                description=payload.description,
                remote=payload.remote,
                additional_questions=payload.additional_questions,
                specific_instructions=payload.specific_instructions,
            )

            emit({"type": "stage_started", "stage": "tailor", "total": 1})
            emit({
                "type": "job_started",
                "idx": 1, "total": 1,
                "company": job.company, "title": job.title,
                "score": payload.match_score,
                "source": payload.source,
                "url": job.url,
                "location": job.location,
            })
            result = process_job(
                job, master, cfg["user"], bio,
                all_stories, all_examples, all_guidelines,
                day_root, tailor, out_cfg, pipeline_log,
            )
            # Use the ACTUAL folder process_job wrote to (suffixed _2/_3 for a
            # same-day re-generation) so this row's downloads never resolve to
            # a prior generation's leftover files in a shared folder.
            folder_name = result.get("folder_name") or job.safe_folder_name()
            folder = day_root / folder_name
            emit({
                "type": "job_completed",
                "idx": 1, "total": 1,
                "company": job.company, "title": job.title,
                "score": payload.match_score,
                "folder": str(folder.as_posix()),
                "folder_rel": f"{day}/{folder_name}",
                "resume_file": result.get("resume_file", ""),
                "cover_file": result.get("cover_file", ""),
                "answers_file": result.get("answers_file", ""),
                "error": result.get("error", ""),
            })
            emit({"type": "stage_completed", "stage": "tailor", "applications": 1})

            # Persist Application row
            if not result.get("error"):
                with session() as s:
                    app = Application(
                        run_id=run_id,
                        user_id=user_id,
                        company=job.company,
                        title=job.title,
                        location=job.location,
                        url=job.url,
                        source=payload.source,
                        match_score=payload.match_score,
                        match_reason=payload.match_reason,
                        description=job.description or "",
                        folder_path=str(folder),
                        folder_rel=f"{day}/{folder_name}",
                        resume_file=result.get("resume_file", ""),
                        cover_file=result.get("cover_file", ""),
                        answers_file=result.get("answers_file", ""),
                        status=ApplicationStatus.generated,
                    )
                    s.add(app)
                    s.commit()
                    s.refresh(app)
                    # Link the originating ranked-pool row, if this was a rescue.
                    if payload.ranked_id is not None:
                        rj = find_owned(s, RankedJob, payload.ranked_id, user_id)
                        if rj is not None:
                            rj.application_id = app.id
                            s.add(rj)
                            s.commit()

            with session() as s:
                # noscope: background thread finalising its own run.
                run = s.get(Run, run_id)
                if run:
                    run.status = RunStatus.done
                    run.finished_at = datetime.utcnow()
                    run.applications_created = 0 if result.get("error") else 1
                    run.day_root = str(day_root.as_posix())
                    s.add(run)
                    s.commit()

            emit({
                "type": "done",
                "applications": 0 if result.get("error") else 1,
                "jobs_found": 1,
                "day_root": str(day_root.as_posix()),
                "dry_run": False,
            })
        except Exception as e:
            log.exception("single-job failed: %s", e)
            with session() as s:
                # noscope: background thread recording failure of its own run.
                run = s.get(Run, run_id)
                if run:
                    run.status = RunStatus.error
                    run.finished_at = datetime.utcnow()
                    run.error = str(e)
                    s.add(run)
                    s.commit()
            bus.publish_threadsafe(run_id, {"type": "error", "msg": str(e)})
    finally:
        root_log.removeHandler(evt_handler)


class GenerateOut(BaseModel):
    run_id: int


def start_generation(body: GenerateBody, user_id: int) -> int:
    """Create a Run and spawn the generation worker. Returns the run id.

    Shared by the manual single-job flow and the ranked-job 'rescue' flow.
    ``user_id`` stamps the Run and everything the worker writes under it.
    """
    with session() as s:
        run = Run(
            user_id=user_id,
            status=RunStatus.queued,
            dry_run=False,
            no_pdf=False,
            no_cache=False,
        )
        s.add(run)
        s.commit()
        s.refresh(run)
        run_id: int = run.id  # type: ignore[assignment]

    threading.Thread(
        target=_worker, args=(run_id, user_id, body), daemon=True
    ).start()
    return run_id


@router.post("/generate", response_model=GenerateOut)
@limiter.limit(LLM_LIMIT)
def generate(
    request: Request,
    body: GenerateBody,
    # Owner-only until PR 3: tailors the global master resume with the global
    # provider keys. See runs.start_run.
    user: User = Depends(require_owner),
) -> GenerateOut:
    if not body.company.strip() or not body.title.strip():
        raise HTTPException(400, "company and title are required")
    if not body.description.strip():
        raise HTTPException(400, "description is required")

    return GenerateOut(run_id=start_generation(body, user.id))
