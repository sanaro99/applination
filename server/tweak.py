"""Resume tweak endpoint — wraps src/tweak.py for the UI."""
from __future__ import annotations
import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .db import Application, session
from .deps import load_config

router = APIRouter(prefix="/api/applications", tags=["tweak"])
log = logging.getLogger("server.tweak")


class TweakBody(BaseModel):
    instruction: str
    provider: str | None = None


class TweakOut(BaseModel):
    docx_filename: str
    pdf_filename: str | None = None
    version: int


class VersionsOut(BaseModel):
    versions: list[dict]


class CoverLetterOut(BaseModel):
    text: str
    has_text: bool


class CoverLetterBody(BaseModel):
    text: str


class CoverLetterSaveOut(BaseModel):
    ok: bool
    pdf_filename: str | None = None


def _parse_version(stem: str) -> int:
    """resume -> 1, resume.v2 -> 2, ... (stem has the .docx already stripped)."""
    m = re.match(r"^resume(?:\.v(\d+))?$", stem)
    return int(m.group(1)) if (m and m.group(1)) else 1


def _list_versions(folder: Path) -> list[dict]:
    if not folder.exists():
        return []
    items: list[dict] = []
    for p in folder.glob("resume*.docx"):
        items.append({
            "version": _parse_version(p.stem),
            "docx": p.name,
            "pdf": p.with_suffix(".pdf").name
                if (folder / p.with_suffix(".pdf").name).exists() else None,
            "json": p.with_suffix(".json").name
                if (folder / p.with_suffix(".json").name).exists() else None,
        })
    # Sort by numeric version so the "latest" is unambiguous (lexical sort puts
    # v10 before v2; the previewed/latest version must be the highest number).
    items.sort(key=lambda d: d["version"])
    return items


@router.get("/{app_id}/resume-versions", response_model=VersionsOut)
def list_versions(app_id: int) -> VersionsOut:
    with session() as s:
        a = s.get(Application, app_id)
        if a is None:
            raise HTTPException(404, "application not found")
    return VersionsOut(versions=_list_versions(Path(a.folder_path)))


@router.get("/{app_id}/cover-letter", response_model=CoverLetterOut)
def get_cover_letter(app_id: int) -> CoverLetterOut:
    with session() as s:
        a = s.get(Application, app_id)
        if a is None:
            raise HTTPException(404, "application not found")
    p = Path(a.folder_path) / "cover_letter.txt"
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    return CoverLetterOut(text=text, has_text=p.exists())


@router.put("/{app_id}/cover-letter", response_model=CoverLetterSaveOut)
def put_cover_letter(app_id: int, body: CoverLetterBody) -> CoverLetterSaveOut:
    """Persist an edited cover-letter body and re-render docx (+pdf)."""
    with session() as s:
        a = s.get(Application, app_id)
        if a is None:
            raise HTTPException(404, "application not found")
        company, title, location = a.company, a.title, a.location

    folder = Path(a.folder_path)
    if not folder.exists():
        raise HTTPException(404, f"folder missing: {folder}")

    text = body.text.strip()
    if not text:
        raise HTTPException(400, "cover letter text is required")

    (folder / "cover_letter.txt").write_text(text, encoding="utf-8")

    cfg = load_config()
    from src.cover_letter import build_cover_letter
    from src.pdf_convert import docx_to_pdf

    cover_docx = folder / "cover_letter.docx"
    try:
        # Match the render call in main.py (defaults: Calibri 11pt, 1" margins).
        build_cover_letter(
            text,
            cfg.get("user", {}),
            {"company": company, "title": title, "location": location},
            cover_docx,
        )
    except Exception as e:
        log.exception("cover letter render failed: %s", e)
        raise HTTPException(500, f"cover letter render failed: {e}") from e

    pdf_name: str | None = None
    if cfg.get("output", {}).get("produce_pdf", True):
        try:
            pdf_path = docx_to_pdf(cover_docx)
            pdf_name = pdf_path.name if pdf_path else None
        except Exception as e:
            log.warning("pdf convert failed: %s", e)

    return CoverLetterSaveOut(ok=True, pdf_filename=pdf_name)


@router.post("/{app_id}/tweak", response_model=TweakOut)
def tweak(app_id: int, body: TweakBody) -> TweakOut:
    if not body.instruction.strip():
        raise HTTPException(400, "instruction is required")

    with session() as s:
        a = s.get(Application, app_id)
        if a is None:
            raise HTTPException(404, "application not found")

    folder = Path(a.folder_path)
    if not folder.exists():
        raise HTTPException(404, f"folder missing: {folder}")

    resume_json_path = folder / "resume.json"
    job_json_path = folder / "job.json"
    if not resume_json_path.exists():
        raise HTTPException(404, "resume.json missing — re-run tailoring first")

    resume_json = json.loads(resume_json_path.read_text(encoding="utf-8"))
    job_json = (
        json.loads(job_json_path.read_text(encoding="utf-8"))
        if job_json_path.exists()
        else {"company": a.company, "title": a.title}
    )

    cfg = load_config()
    from src.tweak import apply_tweak, _next_version, render_docx
    from src.providers import get_provider, get_provider_with_fallback
    from src.pdf_convert import docx_to_pdf

    llm_cfg = cfg.get("llm", {})
    provider = (
        get_provider(body.provider, llm_cfg) if body.provider
        else get_provider_with_fallback(llm_cfg)
    )

    # Determine next version by inspecting existing files
    versions = _list_versions(folder)
    base_docx = folder / "resume.docx"
    latest_docx = base_docx
    for v in versions:
        latest_docx = folder / v["docx"]

    updated_json = apply_tweak(resume_json, job_json, body.instruction, provider)

    next_docx, next_json = _next_version(latest_docx)
    next_json.write_text(json.dumps(updated_json, indent=2), encoding="utf-8")
    try:
        render_docx(updated_json, cfg.get("user", {}), next_docx, cfg)
    except Exception as e:
        log.exception("docx render failed: %s", e)
        raise HTTPException(500, f"docx render failed: {e}") from e

    pdf_path: Path | None = None
    if cfg.get("output", {}).get("produce_pdf", True):
        try:
            pdf_path = docx_to_pdf(next_docx)
        except Exception as e:
            log.warning("pdf convert failed: %s", e)
            pdf_path = None

    # Extract version number from filename
    stem = next_docx.stem
    version = 2
    if "." in stem:
        try:
            version = int(stem.rsplit(".v", 1)[-1])
        except ValueError:
            pass

    return TweakOut(
        docx_filename=next_docx.name,
        pdf_filename=pdf_path.name if pdf_path else None,
        version=version,
    )
