"""Ranked-pool (job triage) endpoints.

Surfaces the full scored job pool for a run — including jobs the ranker did not
auto-select — and lets the user 'rescue' any of them by generating an
application on demand.
"""
from __future__ import annotations
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import select

from .db import RankedJob, session
from .single_job import GenerateBody, start_generation

router = APIRouter(tags=["ranked"])
log = logging.getLogger("server.ranked")


class RankedOut(BaseModel):
    id: int
    run_id: int
    company: str
    title: str
    location: str
    url: str
    source: str
    remote: bool
    match_score: int
    match_reason: str
    selected: bool
    dismissed: bool
    application_id: int | None


def _to_out(r: RankedJob) -> RankedOut:
    return RankedOut(
        id=r.id,  # type: ignore[arg-type]
        run_id=r.run_id,
        company=r.company,
        title=r.title,
        location=r.location,
        url=r.url,
        source=r.source,
        remote=r.remote,
        match_score=r.match_score,
        match_reason=r.match_reason,
        selected=r.selected,
        dismissed=r.dismissed,
        application_id=r.application_id,
    )


@router.get("/api/runs/{run_id}/ranked", response_model=list[RankedOut])
def list_ranked(
    run_id: int,
    only: str = Query("all", pattern="^(all|selected|rejected|generated|dismissed)$"),
) -> list[RankedOut]:
    with session() as s:
        q = select(RankedJob).where(RankedJob.run_id == run_id)
        rows = s.exec(q).all()
    rows.sort(key=lambda r: r.match_score, reverse=True)
    if only == "selected":
        rows = [r for r in rows if r.selected]
    elif only == "rejected":
        rows = [r for r in rows if not r.selected]
    elif only == "generated":
        rows = [r for r in rows if r.application_id is not None]
    elif only == "dismissed":
        rows = [r for r in rows if r.dismissed]
    return [_to_out(r) for r in rows]


class DismissBody(BaseModel):
    dismissed: bool = True


@router.post("/api/ranked/{ranked_id}/dismiss", response_model=RankedOut)
def dismiss_ranked(ranked_id: int, body: DismissBody) -> RankedOut:
    """Mark a ranked job 'not interested' (or undo). Dismissed jobs are kept out
    of future runs' selection and triage pool via the cross-run dedup set."""
    with session() as s:
        r = s.get(RankedJob, ranked_id)
        if r is None:
            raise HTTPException(404, "ranked job not found")
        r.dismissed = body.dismissed
        s.add(r)
        s.commit()
        s.refresh(r)
        return _to_out(r)


class RescueOut(BaseModel):
    run_id: int


@router.post("/api/ranked/{ranked_id}/generate", response_model=RescueOut)
def generate_ranked(ranked_id: int) -> RescueOut:
    with session() as s:
        r = s.get(RankedJob, ranked_id)
        if r is None:
            raise HTTPException(404, "ranked job not found")
        if r.application_id is not None:
            raise HTTPException(409, "this job was already generated")
        if not (r.description or "").strip():
            raise HTTPException(
                400, "no stored job description to generate from"
            )
        body = GenerateBody(
            company=r.company,
            title=r.title,
            location=r.location,
            remote=r.remote,
            description=r.description,
            url=r.url,
            source=r.source or "ranked",
            match_score=r.match_score,
            match_reason=r.match_reason,
            ranked_id=r.id,
        )

    return RescueOut(run_id=start_generation(body))
