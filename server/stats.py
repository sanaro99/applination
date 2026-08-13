"""Aggregated stats for the dashboard."""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import select

from .auth import require_user
from .db import Application, ApplicationStatus, Run, RunStatus, User, session
from .scoping import owned

router = APIRouter(prefix="/api/stats", tags=["stats"])


class StatsOut(BaseModel):
    total_applications: int
    avg_score: float
    runs_total: int
    runs_30d: int
    by_status: dict[str, int]
    by_source: dict[str, int]
    top_companies: list[dict]
    daily: list[dict]
    score_buckets: list[dict]


@router.get("", response_model=StatsOut)
def stats(user: User = Depends(require_user)) -> StatsOut:
    with session() as s:
        apps = s.exec(owned(select(Application), Application, user)).all()
        runs = s.exec(owned(select(Run), Run, user)).all()

    total = len(apps)
    avg_score = (
        round(sum(a.match_score for a in apps) / total, 1) if total else 0.0
    )

    by_status = {s.value: 0 for s in ApplicationStatus}
    for a in apps:
        by_status[a.status.value] += 1

    by_source_c = Counter((a.source or "unknown") for a in apps)
    by_source = dict(by_source_c.most_common())

    top_companies = [
        {"company": c, "count": n}
        for c, n in Counter(a.company for a in apps).most_common(15)
    ]

    # Daily app counts for last 30 days
    cutoff = datetime.utcnow() - timedelta(days=29)
    daily_c: Counter[str] = Counter()
    for a in apps:
        if a.created_at < cutoff:
            continue
        daily_c[a.created_at.date().isoformat()] += 1
    daily = sorted(
        [{"date": d, "count": n} for d, n in daily_c.items()],
        key=lambda x: x["date"],
    )

    # Score histogram in 10-pt buckets
    buckets: dict[str, int] = {f"{i}-{i+9}": 0 for i in range(0, 100, 10)}
    for a in apps:
        b = min((a.match_score // 10) * 10, 90)
        buckets[f"{b}-{b+9}"] += 1
    score_buckets = [{"bucket": k, "count": v} for k, v in buckets.items()]

    runs_30d = sum(
        1 for r in runs
        if r.started_at >= cutoff and r.status != RunStatus.queued
    )

    return StatsOut(
        total_applications=total,
        avg_score=avg_score,
        runs_total=len(runs),
        runs_30d=runs_30d,
        by_status=by_status,
        by_source=by_source,
        top_companies=top_companies,
        daily=daily,
        score_buckets=score_buckets,
    )
