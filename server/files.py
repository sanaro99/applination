"""Serving generated documents — the replacement for the /files mount.

``server/app.py`` used to do::

    app.mount("/files", StaticFiles(directory=output_root))

which was fine when there was one output tree belonging to one person. Under
multi-user it is a hole nothing else can plug: StaticFiles resolves a path on
disk, so no amount of database scoping is involved and no ownership check ever
runs. Any logged-in account could read any other's resume and cover letters by
guessing ``/files/2026-08-13/Company_Role/resume.pdf``.

Every document is now fetched through this router, which joins the requested
path onto *the requesting user's own* output root and proves the result stayed
inside it (``user_paths.resolve_within``). Cookies ride along on same-origin
``<img>`` and ``<a>`` requests, so downloads and previews keep working with no
change beyond the URL prefix.
"""
from __future__ import annotations

import logging
import mimetypes

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .auth import require_user
from .db import User
from .deps import output_root
from .user_paths import PathEscape, resolve_within

router = APIRouter(prefix="/api/files", tags=["files"])
log = logging.getLogger("server.files")


@router.get("/{rel_path:path}")
def get_file(
    rel_path: str,
    download: bool = False,
    user: User = Depends(require_user),
) -> FileResponse:
    """Serve one file from the user's own output tree.

    404 rather than 403 on a containment failure, matching ``scoping.py``: a
    distinct 403 would confirm that some *other* user's file exists at that
    path, which is exactly the information being withheld.
    """
    if not rel_path or rel_path.endswith("/"):
        raise HTTPException(404, "not found")

    base = output_root(user)
    try:
        target = resolve_within(base, rel_path)
    except PathEscape:
        # Worth a log line: a legitimate UI never produces one of these.
        log.warning(
            "user %s requested a path outside their output root: %r",
            user.id, rel_path,
        )
        raise HTTPException(404, "not found") from None

    if not target.is_file():
        raise HTTPException(404, "not found")

    media_type, _ = mimetypes.guess_type(target.name)
    return FileResponse(
        target,
        media_type=media_type or "application/octet-stream",
        # Passing `filename` sets Content-Disposition: attachment, which would
        # turn the application detail page's inline PDF preview into a download
        # prompt. Only opt in when the caller explicitly asks to download.
        filename=target.name if download else None,
        # These are the user's own private documents; a shared cache holding
        # them would outlive the session that was allowed to see them.
        headers={"Cache-Control": "private, max-age=0, must-revalidate"},
    )
