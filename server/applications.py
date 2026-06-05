"""Applications CRUD + status."""
from __future__ import annotations
import csv
import io
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import select

from .db import Application, ApplicationStatus, session
from .deps import load_config

router = APIRouter(prefix="/api/applications", tags=["applications"])

# Map a download format to its on-disk extension + MIME type.
_DOC_MEDIA = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document",
}


def _latest_resume_version(folder: Path, fmt: str) -> int:
    """Highest resume version with a rendered file of `fmt` (0 if none)."""
    best = 0
    for p in folder.glob(f"resume*.{fmt}"):
        m = re.match(rf"^resume(?:\.v(\d+))?\.{re.escape(fmt)}$", p.name)
        if not m:
            continue
        best = max(best, int(m.group(1)) if m.group(1) else 1)
    return best


def _friendly_basename(company: str, doc: str, version: int | None) -> str:
    """User-facing filename stem, e.g. 'Sanchit_Arora_resume_Cloudflare'.

    The on-disk names stay canonical (resume.pdf / cover_letter.pdf / resume.vN
    .pdf); this is only the name presented to the user at download time via
    Content-Disposition. version>1 appends '_v{n}'.
    """
    full = ((load_config().get("user") or {}).get("full_name") or "Candidate").strip()
    name_token = re.sub(r"[^A-Za-z0-9]+", "_", full).strip("_") or "Candidate"
    comp = re.sub(r"[^A-Za-z0-9]+", "_", company or "").strip("_") or "Company"
    label = "cover_letter" if doc == "cover" else "resume"
    vsuf = f"_v{version}" if (version and version > 1) else ""
    return f"{name_token}_{label}_{comp}{vsuf}"


def _tags_to_list(raw: str) -> list[str]:
    return [t.strip() for t in (raw or "").split(",") if t.strip()]


def _tags_to_str(tags: list[str]) -> str:
    seen: list[str] = []
    for t in tags:
        t = t.strip()
        if t and t not in seen:
            seen.append(t)
    return ",".join(seen)


def _folder_rel(a: Application) -> str:
    """Path relative to the /files mount: '<date>/<folder>'.

    Derived from the last two components of folder_path (always 'output/<date>/
    <folder>'), so it's correct regardless of what the row stored. Older
    run-created rows stored folder_rel relative to out_root.PARENT, which
    prepended the 'output/' segment — producing /files/output/... that 404s the
    resume/cover-letter previews. Deriving here fixes those rows at read-time.
    """
    src = a.folder_path or a.folder_rel or ""
    parts = [p for p in re.split(r"[\\/]+", src) if p not in ("", ".")]
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return parts[-1] if parts else ""


class AppOut(BaseModel):
    id: int
    run_id: int | None
    company: str
    title: str
    location: str
    url: str
    source: str
    match_score: int
    match_reason: str
    folder_rel: str
    resume_file: str
    cover_file: str
    answers_file: str
    status: ApplicationStatus
    notes: str
    tags: list[str]
    applied_at: datetime | None
    deadline: datetime | None
    created_at: datetime


def _to_out(a: Application) -> AppOut:
    return AppOut(
        id=a.id,  # type: ignore[arg-type]
        run_id=a.run_id,
        company=a.company,
        title=a.title,
        location=a.location,
        url=a.url,
        source=a.source,
        match_score=a.match_score,
        match_reason=a.match_reason,
        folder_rel=_folder_rel(a),
        resume_file=a.resume_file,
        cover_file=a.cover_file,
        answers_file=a.answers_file,
        status=a.status,
        notes=a.notes,
        tags=_tags_to_list(a.tags),
        applied_at=a.applied_at,
        deadline=a.deadline,
        created_at=a.created_at,
    )


@router.get("", response_model=list[AppOut])
def list_apps(
    run_id: int | None = None,
    status: ApplicationStatus | None = None,
    limit: int = 500,
) -> list[AppOut]:
    with session() as s:
        q = select(Application)
        if run_id is not None:
            q = q.where(Application.run_id == run_id)
        if status is not None:
            q = q.where(Application.status == status)
        q = q.order_by(Application.created_at.desc()).limit(limit)
        return [_to_out(a) for a in s.exec(q).all()]


@router.get("/{app_id}", response_model=AppOut)
def get_app(app_id: int) -> AppOut:
    with session() as s:
        a = s.get(Application, app_id)
        if a is None:
            raise HTTPException(404, "application not found")
        return _to_out(a)


@router.get("/{app_id}/download")
def download_doc(
    app_id: int,
    doc: str = "resume",
    fmt: str = "pdf",
    version: int | None = None,
) -> FileResponse:
    """Stream a document with a friendly, ATS-ready filename.

    Files are served cross-origin from the /files static mount, where the
    browser's `download` attribute is ignored — so a dedicated endpoint that
    sets Content-Disposition is the only reliable way to control the saved
    filename. `doc` is 'resume' or 'cover'. For a resume, omitting `version`
    serves the latest tweak with a clean name (the resume you'd submit); an
    explicit `version=N` serves that exact tweak (suffixed _vN for N>1).
    On-disk names are unchanged.
    """
    if doc not in ("resume", "cover"):
        raise HTTPException(400, "doc must be 'resume' or 'cover'")
    if fmt not in _DOC_MEDIA:
        raise HTTPException(400, "fmt must be 'pdf' or 'docx'")
    with session() as s:
        a = s.get(Application, app_id)
        if a is None:
            raise HTTPException(404, "application not found")
        company, folder_path = a.company, a.folder_path

    folder = Path(folder_path)
    if doc == "cover":
        disk_name, name_version = f"cover_letter.{fmt}", None
    elif version is None:
        # "Current" resume → latest rendered version, clean (un-suffixed) name.
        latest = _latest_resume_version(folder, fmt)
        if latest == 0:
            raise HTTPException(404, f"no resume .{fmt} for this application")
        disk_name = f"resume.{fmt}" if latest == 1 else f"resume.v{latest}.{fmt}"
        name_version = None
    else:
        disk_name = f"resume.{fmt}" if version <= 1 else f"resume.v{version}.{fmt}"
        name_version = version

    path = folder / disk_name
    if not path.exists():
        raise HTTPException(404, f"{disk_name} not found for this application")

    filename = f"{_friendly_basename(company, doc, name_version)}.{fmt}"
    return FileResponse(path, media_type=_DOC_MEDIA[fmt], filename=filename)


class PatchBody(BaseModel):
    status: ApplicationStatus | None = None
    notes: str | None = None
    tags: list[str] | None = None
    applied_at: datetime | None = None
    deadline: datetime | None = None


@router.patch("/{app_id}", response_model=AppOut)
def patch_app(app_id: int, body: PatchBody) -> AppOut:
    # Use the set of explicitly-provided fields so callers can clear a value
    # (send null) vs. leave it untouched (omit the key).
    provided = body.model_fields_set
    with session() as s:
        a = s.get(Application, app_id)
        if a is None:
            raise HTTPException(404, "application not found")
        if body.status is not None:
            a.status = body.status
            if body.status == ApplicationStatus.applied and a.applied_at is None:
                a.applied_at = datetime.utcnow()
        if "notes" in provided and body.notes is not None:
            a.notes = body.notes
        if "tags" in provided and body.tags is not None:
            a.tags = _tags_to_str(body.tags)
        if "applied_at" in provided:
            a.applied_at = body.applied_at
        if "deadline" in provided:
            a.deadline = body.deadline
        s.add(a)
        s.commit()
        s.refresh(a)
        return _to_out(a)


class BulkBody(BaseModel):
    ids: list[int]
    status: ApplicationStatus | None = None
    add_tags: list[str] | None = None


@router.post("/bulk", response_model=list[AppOut])
def bulk_update(body: BulkBody) -> list[AppOut]:
    if not body.ids:
        raise HTTPException(400, "no application ids provided")
    updated: list[AppOut] = []
    with session() as s:
        rows = s.exec(
            select(Application).where(Application.id.in_(body.ids))  # type: ignore[attr-defined]
        ).all()
        for a in rows:
            if body.status is not None:
                a.status = body.status
                if (
                    body.status == ApplicationStatus.applied
                    and a.applied_at is None
                ):
                    a.applied_at = datetime.utcnow()
            if body.add_tags:
                merged = _tags_to_list(a.tags) + body.add_tags
                a.tags = _tags_to_str(merged)
            s.add(a)
        s.commit()
        for a in rows:
            s.refresh(a)
            updated.append(_to_out(a))
    return updated


@router.post("/export")
def export_csv(body: BulkBody | None = None) -> Response:
    """Export selected (or all) applications as a CSV download."""
    ids = body.ids if body else []
    with session() as s:
        q = select(Application)
        if ids:
            q = q.where(Application.id.in_(ids))  # type: ignore[attr-defined]
        q = q.order_by(Application.created_at.desc())
        rows = s.exec(q).all()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "company", "title", "location", "source", "match_score",
        "status", "tags", "url", "applied_at", "deadline", "created_at",
    ])
    for a in rows:
        w.writerow([
            a.company, a.title, a.location, a.source, a.match_score,
            a.status.value if hasattr(a.status, "value") else a.status,
            a.tags, a.url,
            a.applied_at.isoformat() if a.applied_at else "",
            a.deadline.isoformat() if a.deadline else "",
            a.created_at.isoformat() if a.created_at else "",
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=applications.csv"},
    )
