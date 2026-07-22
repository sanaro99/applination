"""
Callable orchestrator for the daily run.

`run_pipeline(cfg, ...)` is the importable equivalent of `python -m src.main`.
It emits typed events through the optional `on_event` callback so a UI / SSE
layer can stream progress. All existing CLI behavior (logging to file +
stdout, identical filesystem outputs) is preserved.
"""
from __future__ import annotations
import json
import logging
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable

from .scrapers import Job
from .providers import get_task_chains
from .tailor import Tailor
from .job_cache import JobCache
from .reference_loader import (
    load_stories,
    load_example_letters,
    load_guidelines,
)
from .excel_writer import build_tracker

from .main import (
    ROOT,
    fetch_all,
    rank_and_filter,
    process_job,
    user_profile_blurb,
)
from .profile import derive_profile

EventCallback = Callable[[dict[str, Any]], None]


class _EventLogHandler(logging.Handler):
    """Forward log records as `log` events to the on_event sink."""

    def __init__(self, on_event: EventCallback):
        super().__init__()
        self.on_event = on_event

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.on_event({
                "type": "log",
                "level": record.levelname,
                "name": record.name,
                "msg": self.format(record),
            })
        except Exception:
            pass


def _noop(_evt: dict) -> None:
    return None


def run_pipeline(
    cfg: dict,
    *,
    dry_run: bool = False,
    no_pdf: bool = False,
    no_cache: bool = False,
    on_event: EventCallback | None = None,
    log: logging.Logger | None = None,
    should_stop: Callable[[], str | None] | None = None,
    excluded_keys: set[str] | None = None,
) -> dict:
    """Execute one full daily run.

    Returns a summary dict: {day_root, applications, jobs_found, dry_run,
    stopped}. `stopped` is None for a normal finish, or "graceful"/"hard" if a
    stop was honored.

    `should_stop`, if given, is polled at stage boundaries and between jobs. It
    returns None to keep going, "graceful" to finish the job currently being
    tailored and then stop (still writing the Excel tracker for completed
    applications), or "hard" to stop as soon as the current job returns without
    writing the tracker. The tailoring of a single job is one blocking call and
    cannot be interrupted mid-flight, so the in-progress job always finishes in
    either mode.

    Caller is responsible for setting up `log` (use `setup_logging()` from
    src.main for the same file/stdout behavior).
    """
    emit: EventCallback = on_event or _noop
    log = log or logging.getLogger("internship_bot")
    stop: Callable[[], str | None] = should_stop or (lambda: None)

    def _stopped_early(mode: str, jobs_found: int) -> dict:
        """Terminal result for a stop requested before any tailoring started."""
        log.info("stop requested (%s); ending run before tailoring", mode)
        emit({
            "type": "cancelled",
            "graceful": mode == "graceful",
            "applications": 0,
            "jobs_found": jobs_found,
            "day_root": "",
            "dry_run": dry_run,
        })
        return {"applications": 0, "jobs_found": jobs_found, "day_root": "",
                "dry_run": dry_run, "stopped": mode}

    handler: _EventLogHandler | None = None
    if on_event is not None:
        handler = _EventLogHandler(on_event)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))
        # Ensure root logger is at INFO so records from all pipeline loggers
        # propagate up and reach the handler (basicConfig is a no-op in uvicorn
        # since the root logger already has handlers, so we set it explicitly).
        root_log = logging.getLogger()
        root_log.setLevel(logging.INFO)
        root_log.addHandler(handler)

    try:
        master = _load_yaml(ROOT / "master_data" / "resume.yaml")
        user = cfg["user"]
        out_cfg = dict(cfg["output"])
        if no_pdf:
            out_cfg["produce_pdf"] = False

        bio_path = ROOT / "master_data" / "bio.md"
        bio = bio_path.read_text(encoding="utf-8") if bio_path.exists() else ""
        all_stories = load_stories(ROOT / "master_data" / "stories")
        all_examples = load_example_letters(
            ROOT / "master_data" / "cover_letters" / "examples"
        )
        all_guidelines = load_guidelines(ROOT / "master_data" / "guidelines")
        log.info(
            "loaded %d stories, %d example letters, %d guidelines",
            len(all_stories), len(all_examples), len(all_guidelines),
        )

        # --- FETCH ---
        emit({"type": "stage_started", "stage": "fetch"})
        t0 = time.time()
        jobs = fetch_all(cfg, log)
        fetch_secs = time.time() - t0
        log.info("fetch took %.1fs", fetch_secs)
        emit({
            "type": "stage_completed",
            "stage": "fetch",
            "duration_s": round(fetch_secs, 1),
            "jobs_found": len(jobs),
        })

        if not jobs:
            log.warning("No jobs found. Check sources / keywords.")
            emit({"type": "done", "applications": 0, "jobs_found": 0,
                  "day_root": "", "dry_run": dry_run})
            return {"applications": 0, "jobs_found": 0, "day_root": "",
                    "dry_run": dry_run}

        if (mode := stop()):
            return _stopped_early(mode, len(jobs))

        # --- LLM PROVIDERS ---
        task_chains = get_task_chains(cfg["llm"])
        critique_cl = cfg["llm"].get("critique_cover_letters", False)
        critique_top_n = int(cfg["llm"].get("critique_top_n", 0) or 0)
        # Top-N ranked jobs route through tailoring_premium (deepseek-v4-pro);
        # the rest use the standard fast chain. Configurable via
        # llm.tailoring_premium_top_n (default 3, 0 disables premium tier).
        premium_top_n = int(cfg["llm"].get("tailoring_premium_top_n", 0) or 0)
        tailor = Tailor(task_chains=task_chains, critique_cover_letters=critique_cl)

        # --- RANK + FILTER ---
        emit({"type": "stage_started", "stage": "rank"})
        profile = user_profile_blurb(master, user)
        top_jobs = rank_and_filter(
            jobs, cfg, tailor, profile, log,
            candidate_profile=derive_profile(master),
            excluded_keys=excluded_keys,
        )
        emit({
            "type": "stage_completed",
            "stage": "rank",
            "kept": len(top_jobs),
            "top": [
                {
                    "company": j.company,
                    "title": j.title,
                    "location": j.location,
                    "score": j.match_score,
                    "reason": j.match_reason,
                    "source": j.source,
                    "url": j.url,
                }
                for j in top_jobs[:20]
            ],
        })
        # Emit the full ranked pool (candidates that passed threshold) so the UI
        # can show what was ranked but not auto-selected, and let the user
        # rescue/generate any of them later. Capped to keep the payload + DB
        # bounded; auto-selected jobs are always included even past the cap.
        threshold = cfg["search"]["min_match_score"]
        selected_ids = {id(j) for j in top_jobs}
        passing = sorted(
            [j for j in jobs
             if j.match_score >= threshold and not getattr(j, "_excluded", False)],
            key=lambda j: j.match_score, reverse=True,
        )
        pool = passing[:200]
        pool_ids = {id(j) for j in pool}
        pool.extend(j for j in top_jobs if id(j) not in pool_ids)
        emit({
            "type": "rank_pool",
            "jobs": [
                {
                    "company": j.company,
                    "title": j.title,
                    "location": j.location,
                    "url": j.url,
                    "source": j.source,
                    "description": j.description,
                    "remote": bool(getattr(j, "remote", False)),
                    "score": j.match_score,
                    "reason": j.match_reason,
                    "selected": id(j) in selected_ids,
                }
                for j in pool
            ],
        })

        if not top_jobs:
            log.warning("No jobs passed match threshold.")
            emit({"type": "done", "applications": 0, "jobs_found": len(jobs),
                  "day_root": "", "dry_run": dry_run})
            return {"applications": 0, "jobs_found": len(jobs), "day_root": "",
                    "dry_run": dry_run}

        if (mode := stop()):
            return _stopped_early(mode, len(jobs))

        day = date.today().isoformat()
        day_root = Path(out_cfg["root"]) / day
        day_root.mkdir(parents=True, exist_ok=True)

        if dry_run:
            log.info("--dry-run; writing ranking summary only.")
            summary = [{
                **j.to_row(),
                "match_score": j.match_score,
                "match_reason": j.match_reason,
            } for j in top_jobs]
            (day_root / "ranked_jobs.json").write_text(
                json.dumps(summary, indent=2), encoding="utf-8"
            )
            log.info("wrote %s", day_root / "ranked_jobs.json")
            emit({
                "type": "done",
                "applications": 0,
                "jobs_found": len(jobs),
                "day_root": str(day_root),
                "dry_run": True,
            })
            return {"applications": 0, "jobs_found": len(jobs),
                    "day_root": str(day_root), "dry_run": True}

        # --- JOB CACHE ---
        cache_ttl = cfg["search"].get("cache_ttl_days", 7)
        cache = JobCache(Path(out_cfg["root"]), ttl_days=cache_ttl,
                         enabled=not no_cache)
        evicted = cache.evict_expired()
        if evicted:
            log.info("job_cache: evicted %d stale entries", evicted)

        # --- TAILOR EACH ---
        emit({"type": "stage_started", "stage": "tailor", "total": len(top_jobs)})
        rows_for_excel = []
        applications_made = 0
        stopped_mode: str | None = None
        for i, j in enumerate(top_jobs, 1):
            if (mode := stop()):
                stopped_mode = mode
                log.info(
                    "stop requested (%s); halting before job %d/%d "
                    "(%d application(s) completed)",
                    mode, i, len(top_jobs), applications_made,
                )
                break
            cache_key = j.dedupe_key()
            cached = cache.get(cache_key)
            if cached:
                log.info(
                    "[%d/%d] %s — %s  (cache hit, score %d, from %s)",
                    i, len(top_jobs), j.company, j.title, j.match_score,
                    cached["date"],
                )
                emit({
                    "type": "job_cached",
                    "idx": i,
                    "total": len(top_jobs),
                    "company": j.company,
                    "title": j.title,
                    "score": j.match_score,
                    "resume_file": cached.get("resume_file", ""),
                    "cover_file": cached.get("cover_file", ""),
                })
                rows_for_excel.append({
                    **j.to_row(),
                    "match_score": j.match_score,
                    "match_reason": j.match_reason,
                    "resume_file": cached.get("resume_file", ""),
                    "cover_file": cached.get("cover_file", ""),
                })
                continue

            should_critique = critique_cl or (i <= critique_top_n)
            quality_tier = "premium" if (premium_top_n > 0 and i <= premium_top_n) else "standard"
            log.info(
                "[%d/%d] %s — %s  (score %d, critique=%s, tier=%s)",
                i, len(top_jobs), j.company, j.title, j.match_score,
                should_critique, quality_tier,
            )
            emit({
                "type": "job_started",
                "idx": i,
                "total": len(top_jobs),
                "company": j.company,
                "title": j.title,
                "score": j.match_score,
                "source": j.source,
                "url": j.url,
                "location": j.location,
            })
            result = process_job(
                j, master, user, bio, all_stories, all_examples, all_guidelines,
                day_root, tailor, out_cfg, log,
                critique_letter=should_critique,
                quality_tier=quality_tier,
            )
            # Use the ACTUAL folder process_job wrote to (may be suffixed
            # _2/_3 for a same-day re-run) so the emitted paths + persisted
            # Application row point at this run's files, never a prior run's.
            folder_name = result.get("folder_name") or j.safe_folder_name()
            emit({
                "type": "job_completed",
                "idx": i,
                "total": len(top_jobs),
                "company": j.company,
                "title": j.title,
                "score": j.match_score,
                "description": j.description,
                "folder": str((day_root / folder_name).as_posix()),
                "folder_rel": folder_name,
                "resume_file": result.get("resume_file", ""),
                "cover_file": result.get("cover_file", ""),
                "answers_file": result.get("answers_file", ""),
                "error": result.get("error", ""),
            })
            rows_for_excel.append({
                **j.to_row(),
                "match_score": j.match_score,
                "match_reason": j.match_reason,
                "resume_file": result.get("resume_file", ""),
                "cover_file": result.get("cover_file", ""),
            })
            if not result.get("error"):
                applications_made += 1
                cache.put(cache_key, {
                    "company": j.company,
                    "title": j.title,
                    "match_score": j.match_score,
                    "resume_file": result.get("resume_file", ""),
                    "cover_file": result.get("cover_file", ""),
                })

        emit({"type": "stage_completed", "stage": "tailor",
              "applications": applications_made})

        # A hard stop skips finalization (no Excel tracker) and ends as
        # cancelled. A graceful stop falls through to write the tracker for the
        # applications that did complete, then ends as cancelled.
        if stopped_mode == "hard":
            log.info(
                "=== stopped (immediate). %d application(s) prepared in %s ===",
                len(rows_for_excel), day_root,
            )
            emit({
                "type": "cancelled",
                "graceful": False,
                "applications": applications_made,
                "jobs_found": len(jobs),
                "day_root": str(day_root.as_posix()),
                "dry_run": False,
            })
            return {
                "applications": applications_made,
                "jobs_found": len(jobs),
                "day_root": str(day_root),
                "dry_run": False,
                "stopped": "hard",
            }

        # --- EXCEL ---
        emit({"type": "stage_started", "stage": "tracker"})
        tracker_path = day_root / f"apps_{day}.xlsx"
        build_tracker(rows_for_excel, tracker_path, day)
        log.info("wrote tracker: %s", tracker_path)
        emit({"type": "stage_completed", "stage": "tracker",
              "tracker_file": str(tracker_path.as_posix())})

        log.info(
            "=== %s. %d application(s) prepared in %s ===",
            "stopped (graceful)" if stopped_mode else "done",
            len(rows_for_excel), day_root,
        )
        emit({
            "type": "cancelled" if stopped_mode else "done",
            "graceful": stopped_mode == "graceful",
            "applications": applications_made,
            "jobs_found": len(jobs),
            "day_root": str(day_root.as_posix()),
            "dry_run": False,
        })
        return {
            "applications": applications_made,
            "jobs_found": len(jobs),
            "day_root": str(day_root),
            "dry_run": False,
            "stopped": stopped_mode,
        }
    finally:
        if handler is not None:
            logging.getLogger().removeHandler(handler)


def _load_yaml(path: Path) -> dict:
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
