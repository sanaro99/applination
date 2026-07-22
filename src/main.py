"""
internship_bot — daily orchestrator.

Usage:
  python -m src.main                 # normal run
  python -m src.main --dry-run       # fetch + rank only (no LLM tailor, no files)
  python -m src.main --no-pdf        # skip PDF conversion
"""
from __future__ import annotations
import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from .scrapers import Job
from .scrapers import remotive, themuse, greenhouse, adzuna, jsearch, simplify_github, lever
from .providers import get_task_chains
from .tailor import Tailor
from .profile import derive_profile, role_is_above_level
from .job_cache import JobCache
from .reference_loader import (
    load_stories, match_stories,
    load_example_letters, match_example_letter,
    load_guidelines, match_guidelines,
)
from .resume_builder import build_resume_onepage
from .cover_letter import build_cover_letter
from .excel_writer import build_tracker
from .pdf_convert import docx_to_pdf


ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------
def setup_logging():
    """Attach INFO file + stdout logging to the root logger, idempotently.

    Uses explicit handlers rather than logging.basicConfig(): basicConfig is a
    no-op once the root logger already has handlers, which is ALWAYS the case
    under uvicorn (the web server). That silently left the day's FileHandler
    constructed-but-unattached, so run_<date>.log files were created empty and
    nothing was ever written when a run was triggered from the web app.

    Idempotent because the server calls this once per run: it de-dupes the
    stdout handler and keeps exactly one day-file handler, swapping to a new
    file (and closing the old one) when the date rolls over on a long-lived
    process.
    """
    logs_dir = ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)
    log_file = logs_dir / f"run_{date.today().isoformat()}.log"
    want_path = os.path.abspath(str(log_file))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s :: %(message)s")

    # Drop any stale day-file handler (yesterday's file) and detect whether the
    # current day's handler is already attached.
    have_today_file = False
    for h in list(root.handlers):
        if isinstance(h, logging.FileHandler):
            base = getattr(h, "baseFilename", "") or ""
            if os.path.dirname(base) != os.path.abspath(str(logs_dir)):
                continue  # not one of ours — leave it alone
            if base == want_path:
                have_today_file = True
            else:
                root.removeHandler(h)
                h.close()

    if not have_today_file:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(fmt)
        root.addHandler(fh)

    have_stdout = any(
        isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
        and getattr(h, "stream", None) is sys.stdout
        for h in root.handlers
    )
    if not have_stdout:
        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(logging.INFO)
        sh.setFormatter(fmt)
        root.addHandler(sh)

    return logging.getLogger("internship_bot")


# ---------------------------------------------------------------------
def load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def user_profile_blurb(master: dict, user_info: dict) -> str:
    """Short text blurb summarizing the candidate, used for job ranking."""
    skills = []
    for group, items in master.get("skills", {}).items():
        skills.extend(items[:6])
    projects = [p["name"] for p in master.get("projects", [])]
    return (
        f"{user_info['full_name']} — {master.get('summary_options', [''])[0]}\n"
        f"Key skills: {', '.join(skills[:20])}\n"
        f"Projects: {', '.join(projects[:6])}\n"
    )


# ---------------------------------------------------------------------
def fetch_all(cfg: dict, log) -> list[Job]:
    kws = cfg["search"]["keywords"]
    hrs = cfg["search"]["last_n_hours"]
    countries = cfg["search"].get("countries", ["us"])
    srcs = cfg["sources"]

    jobs: list[Job] = []
    if srcs["remotive"]["enabled"]:
        jobs += remotive.fetch(kws, last_n_hours=hrs)
    if srcs["themuse"]["enabled"]:
        jobs += themuse.fetch(kws, last_n_hours=hrs)
    if srcs["greenhouse"]["enabled"]:
        gh = srcs["greenhouse"]
        jobs += greenhouse.fetch(
            gh.get("extra_companies") or gh.get("companies") or [],
            kws,
            last_n_hours=hrs,
            use_builtin_list=gh.get("use_builtin_list", True),
        )
    if srcs["adzuna"]["enabled"]:
        jobs += adzuna.fetch(
            kws,
            app_id=srcs["adzuna"]["app_id"],
            app_key=srcs["adzuna"]["app_key"],
            countries=countries,
            last_n_hours=hrs,
        )
    if srcs["jsearch"]["enabled"]:
        jobs += jsearch.fetch(
            kws,
            rapidapi_key=srcs["jsearch"]["rapidapi_key"],
            countries=countries,
            last_n_hours=hrs,
        )
    if srcs["simplify_github"]["enabled"]:
        sg = srcs["simplify_github"]
        jobs += simplify_github.fetch(
            kws,
            max_age_days=sg.get("max_age_days", 14),
            us_only=sg.get("us_only", True),
        )
    if srcs["lever"]["enabled"]:
        jobs += lever.fetch(
            srcs["lever"]["companies"],
            kws,
            last_n_hours=srcs["lever"].get("last_n_hours", 24 * 30),
        )

    # Dedupe
    seen = set()
    unique: list[Job] = []
    for j in jobs:
        k = j.dedupe_key()
        if k in seen:
            continue
        seen.add(k)
        unique.append(j)

    log.info("fetched %d jobs, %d after dedupe", len(jobs), len(unique))
    return unique


# Category slots for diverse job selection.
# Total must equal (or be <= ) max_jobs_per_day; remainder goes to SWE.
_CATEGORY_SLOTS = {
    "swe":    20,   # General software engineering
    "ml_ai":  12,   # ML / AI / Data Science intern
    "data":    6,   # Data engineering / analytics
    "pm":      6,   # Product management
    "sre":     6,   # SRE / DevOps / Platform
}
_CATEGORY_TOTAL = sum(_CATEGORY_SLOTS.values())  # 50


def _categorize_job(job: Job) -> str:
    t = (job.title or "").lower()
    if any(kw in t for kw in ["product manager", " pm ", "pm intern", "product management",
                               "product manager intern", "associate product"]):
        return "pm"
    if any(kw in t for kw in ["sre", "site reliability", "devops", "platform engineer",
                               "infrastructure", "cloud engineer"]):
        return "sre"
    if any(kw in t for kw in ["data engineer", "data analyst", "analytics engineer",
                               "analytics intern", "business intelligence", "bi intern"]):
        return "data"
    if any(kw in t for kw in ["machine learning", "ml ", " ml", "artificial intelligence",
                               " ai ", "ai intern", "deep learning", "nlp", "computer vision",
                               "data scientist", "research scientist", "research engineer"]):
        return "ml_ai"
    return "swe"


# ---------------------------------------------------------------------
def rank_and_filter(jobs: list[Job], cfg: dict, tailor: Tailor,
                    user_profile: str, log,
                    *, candidate_profile: dict | None = None,
                    excluded_keys: set[str] | None = None) -> list[Job]:
    if not jobs:
        return []
    excluded_keys = excluded_keys or set()

    mini = [
        {"company": j.company, "title": j.title,
         "location": j.location, "desc": j.description}
        for j in jobs
    ]
    scored = tailor.rank_jobs(mini, user_profile)
    scored_map = {s["idx"]: s for s in scored}

    for i, j in enumerate(jobs):
        s = scored_map.get(i, {})
        raw = s.get("score", 50)
        try:
            j.match_score = max(0, min(100, int(float(str(raw).strip()))))
        except (TypeError, ValueError):
            j.match_score = 50  # model returned garbage in score field
        j.match_reason = s.get("reason", "") or ""
        # If the reason looks like a number and score looks like text, they were swapped
        if isinstance(j.match_reason, (int, float)):
            j.match_reason = str(j.match_reason)
        j._category = _categorize_job(j)

    # Deterministic seniority guardrail: drop roles clearly above the
    # candidate's level (Staff/Principal/Director/Lead/exec) regardless of how
    # well their skills overlapped — the LLM scorer over-rewards keyword match
    # and would otherwise tailor a "Staff Product Manager" for a student.
    # Zeroing the score (vs. a separate list) keeps the triage pool in
    # pipeline.py consistent without extra plumbing.
    over_senior = 0
    for j in jobs:
        if role_is_above_level(j.title, candidate_profile):
            j.match_score = 0
            j.match_reason = "Role seniority above candidate level; auto-skipped."
            over_senior += 1
    if over_senior:
        log.info("dropped %d roles above candidate level (seniority guard)", over_senior)

    # Cross-run de-duplication: flag jobs the user already applied to (an
    # Application exists) or explicitly dismissed in a prior run. Flagged jobs
    # are kept out of auto-selection AND the triage pool (pipeline.py honors the
    # same `_excluded` marker) so we never re-tailor or re-surface them.
    excluded = 0
    for j in jobs:
        # Set the marker explicitly (not only when True) so it is fresh per call
        # and a reused Job object never carries a stale exclusion.
        j._excluded = j.dedupe_key() in excluded_keys
        if j._excluded:
            excluded += 1
    if excluded:
        log.info("excluded %d already-applied/dismissed job(s) from this run", excluded)

    threshold = cfg["search"]["min_match_score"]
    filtered = [j for j in jobs
                if j.match_score >= threshold and not getattr(j, "_excluded", False)]
    filtered.sort(key=lambda j: j.match_score, reverse=True)

    max_total = cfg["search"]["max_jobs_per_day"]

    # Build diverse pool: take top-scored per category up to each slot limit.
    # Any unfilled category slots roll over to SWE (the catch-all).
    buckets: dict[str, list[Job]] = {cat: [] for cat in _CATEGORY_SLOTS}
    for j in filtered:
        cat = getattr(j, "_category", "swe")
        if cat not in buckets:
            cat = "swe"
        slot = _CATEGORY_SLOTS.get(cat, 0)
        if len(buckets[cat]) < slot:
            buckets[cat].append(j)

    selected: list[Job] = []
    for cat_jobs in buckets.values():
        selected.extend(cat_jobs)

    # If we have unfilled slots, top-fill from remaining passing jobs (any category)
    selected_ids = {id(j) for j in selected}
    overflow = [j for j in filtered if id(j) not in selected_ids]
    remaining_slots = max_total - len(selected)
    selected.extend(overflow[:remaining_slots])

    # Final sort by score for the Excel / processing order
    selected.sort(key=lambda j: j.match_score, reverse=True)
    top = selected[:max_total]

    cat_counts = {}
    for j in top:
        cat_counts[getattr(j, "_category", "swe")] = cat_counts.get(
            getattr(j, "_category", "swe"), 0) + 1
    log.info("ranked: %d passed threshold >=%d, keeping %d — breakdown: %s",
             len(filtered), threshold, len(top), cat_counts)
    return top


# ---------------------------------------------------------------------
def _unique_job_folder(day_root: Path, base_name: str) -> Path:
    """Pick a non-colliding output folder for one generation.

    The first generation of a company+role on a given day uses ``base_name``
    unchanged. A second generation the same day (a deliberate re-run, e.g.
    comparing a resume before/after a prompt change) gets ``base_name_2``,
    then ``_3``, etc. Isolating each run keeps its resume/cover files distinct
    so a newer run's download never resolves to an older run's leftover
    ``resume.vN`` files sharing the same folder.
    """
    folder = day_root / base_name
    if not folder.exists():
        return folder
    n = 2
    while (day_root / f"{base_name}_{n}").exists():
        n += 1
    return day_root / f"{base_name}_{n}"


def process_job(
    job: Job,
    master: dict,
    user: dict,
    bio: str,
    all_stories: list[dict],
    all_examples: list[dict],
    all_guidelines: list[dict],
    day_root: Path,
    tailor: Tailor,
    out_cfg: dict,
    log,
    *,
    critique_letter: bool = False,
    quality_tier: str = "standard",
) -> dict:
    folder = _unique_job_folder(day_root, job.safe_folder_name())
    folder.mkdir(parents=True, exist_ok=True)

    # Calibrate the bullet line-fit bands to the actual render font BEFORE
    # tailoring, so the deterministic fitter + LLM rescue target the real
    # printed line width (config: output.base_font_size). Idempotent.
    from .line_fitter import configure_for_font
    configure_for_font(out_cfg.get("base_font_size", 10.0))

    jd_dict = {
        "company": job.company,
        "title": job.title,
        "location": job.location,
        "description": job.description,
    }

    # 1. Match RAG context BEFORE tailoring so graph can use them
    stories = match_stories(job.description or "", job.company or "", job.title or "", all_stories)
    guidelines = match_guidelines(job.description or "", job.title or "", all_guidelines)
    example_letter = match_example_letter(
        job.description or "", job.company or "", job.title or "", all_examples
    )

    # 2. Tailor resume with narrative + guideline context.
    # quality_tier controls which provider chain is used: "premium" routes
    # through tailoring_premium (deepseek-v4-pro) for top-ranked jobs, while
    # "standard" uses the fast default chain.
    try:
        tailored = tailor.tailor_resume(
            master, jd_dict,
            stories=stories, guidelines=guidelines,
            quality_tier=quality_tier,
        )
    except Exception as e:
        log.exception("tailoring failed for %s / %s: %s", job.company, job.title, e)
        return {"error": str(e), "folder_name": folder.name}

    # Save the structured JSON alongside the docx (needed by tweak.py)
    (folder / "resume.json").write_text(
        json.dumps(tailored, indent=2), encoding="utf-8"
    )

    # Snapshot pipeline metrics so we can diagnose per-step bullet quality and
    # overall latency without re-running. Captures band counts at each step,
    # line_fitter expansion/trim counts, and wall-clock duration.
    metrics = getattr(tailor, "last_tailor_metrics", None) or {}
    if metrics:
        metrics_with_meta = {
            "company": job.company,
            "title": job.title,
            "quality_tier": quality_tier,
            **metrics,
        }
        (folder / "pipeline_metrics.json").write_text(
            json.dumps(metrics_with_meta, indent=2, default=str), encoding="utf-8",
        )

    resume_docx = folder / "resume.docx"
    build_resume_onepage(
        tailored, user, resume_docx,
        master=master,
        font=out_cfg["font_name"],
        base_size=out_cfg["base_font_size"],
        margins=out_cfg["margins_inches"],
    )

    # 3. Cover letter — guidelines are matched once above (line 263) and
    # passed through here so cover-letter-specific guidance (hook patterns,
    # recruiter scan rules) lands in the writer's prompt.
    try:
        letter_body = tailor.write_cover_letter(
            source={},
            job=jd_dict,
            user=user,
            bio=bio,
            stories=stories,
            example_letter=example_letter,
            guidelines=guidelines,
            profile=derive_profile(master),
            critique=critique_letter,
        )
    except Exception as e:
        log.warning("cover letter failed: %s", e)
        letter_body = ""

    cover_docx = folder / "cover_letter.docx"
    if letter_body:
        build_cover_letter(letter_body, user, {
            "company": job.company, "title": job.title, "location": job.location,
        }, cover_docx)
        # Snapshot the plain-text body alongside the docx for tweak workflows
        # and for diffing across runs. The .debug.json captures every retry +
        # critique attempt so we can postmortem any future model regressions.
        (folder / "cover_letter.txt").write_text(letter_body, encoding="utf-8")
        debug = getattr(tailor, "last_letter_debug", None)
        if debug:
            (folder / "cover_letter.debug.json").write_text(
                json.dumps(debug, indent=2), encoding="utf-8",
            )

    # 4. Save JD snapshot
    (folder / "job.json").write_text(
        json.dumps({
            **job.to_row(),
            "tailored_summary_preview": tailored.get("summary", "")[:160],
        }, indent=2), encoding="utf-8"
    )

    # 4b. Answer additional application questions (manual flow; no-op when empty)
    answers_path = None
    if getattr(job, "additional_questions", None):
        try:
            answers = tailor.answer_questions(
                job.additional_questions,
                jd_dict,
                user,
                bio,
                stories,
                specific_instructions=getattr(job, "specific_instructions", ""),
                # Without master/profile the model has no factual record to
                # answer from and fabricates experience to fill the gap.
                master=master,
                profile=derive_profile(master),
            )
            if answers:
                lines = [f"## {a['question']}\n\n{a['answer']}\n" for a in answers]
                answers_path = folder / "answers.md"
                answers_path.write_text("\n".join(lines), encoding="utf-8")
        except Exception as e:
            log.warning("answer_questions failed for %s / %s: %s", job.company, job.title, e)

    # 5. PDF
    resume_pdf = None
    cover_pdf = None
    if out_cfg.get("produce_pdf", True):
        resume_pdf = docx_to_pdf(resume_docx)
        if cover_docx.exists():
            cover_pdf = docx_to_pdf(cover_docx)

    return {
        "folder_name": folder.name,
        "resume_file": str((resume_pdf or resume_docx).relative_to(day_root.parent)),
        "cover_file": str((cover_pdf or cover_docx).relative_to(day_root.parent))
                       if cover_docx.exists() else "",
        "answers_file": str(answers_path.relative_to(day_root.parent)) if answers_path else "",
    }


# ---------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch + rank only; skip tailoring and file generation.")
    ap.add_argument("--no-pdf", action="store_true",
                    help="Skip PDF conversion (only write .docx).")
    ap.add_argument("--no-cache", action="store_true",
                    help="Ignore job cache and re-process all jobs from scratch.")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    args = ap.parse_args()

    log = setup_logging()
    log.info("=== internship_bot run started ===")

    cfg = load_yaml(Path(args.config))

    # Delegate to the importable orchestrator; identical filesystem output.
    from .pipeline import run_pipeline
    run_pipeline(
        cfg,
        dry_run=args.dry_run,
        no_pdf=args.no_pdf,
        no_cache=args.no_cache,
        log=log,
    )


if __name__ == "__main__":
    main()
