"""Ranked-pool (job triage) endpoints.

Surfaces the full scored job pool for a run — including jobs the ranker did not
auto-select — and lets the user 'rescue' any of them by generating an
application on demand.
"""
from __future__ import annotations
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import select

from .auth import require_owner, require_user
from .db import RankedJob, Run, User, session
from .scoping import get_owned, owned
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
    user: User = Depends(require_user),
) -> list[RankedOut]:
    with session() as s:
        # Scoped on RankedJob directly rather than by checking the parent Run:
        # the rows carry their own user_id, so this cannot be defeated by a
        # ranked row that somehow points at another user's run.
        q = owned(
            select(RankedJob).where(RankedJob.run_id == run_id),
            RankedJob,
            user,
        )
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
def dismiss_ranked(
    ranked_id: int, body: DismissBody, user: User = Depends(require_user)
) -> RankedOut:
    """Mark a ranked job 'not interested' (or undo). Dismissed jobs are kept out
    of future runs' selection and triage pool via the cross-run dedup set."""
    with session() as s:
        r = get_owned(
            s, RankedJob, ranked_id, user, detail="ranked job not found"
        )
        r.dismissed = body.dismissed
        s.add(r)
        s.commit()
        s.refresh(r)
        return _to_out(r)


class RescueOut(BaseModel):
    run_id: int


@router.post("/api/ranked/{ranked_id}/generate", response_model=RescueOut)
def generate_ranked(
    ranked_id: int,
    # Owner-only until PR 3: generating tailors the one global master resume
    # with the owner's API keys. See runs.start_run.
    user: User = Depends(require_owner),
) -> RescueOut:
    with session() as s:
        r = get_owned(
            s, RankedJob, ranked_id, user, detail="ranked job not found"
        )
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

    return RescueOut(run_id=start_generation(body, user.id))
