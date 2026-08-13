"""FastAPI entrypoint."""
from __future__ import annotations
import asyncio
import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from .applications import router as applications_router
from .auth import require_user, resolve_user, router as auth_router
from .db import init_db
from .limits import limiter
from .deps import load_config
from .events import bus
from .runs import router as runs_router
from .single_job import router as single_job_router
from .config_api import router as config_router
from .tweak import router as tweak_router
from .stats import router as stats_router
from .ranked import router as ranked_router
from .ops import router as ops_router
from .chat import router as chat_router
from .studio import router as studio_router
from .onboarding import (
    router as onboarding_router,
    status_router as onboarding_status_router,
)
from .inbox import router as inbox_router
from .reminders import router as reminders_router
from .pricing import router as pricing_router

ROOT = Path(__file__).resolve().parent.parent

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s :: %(message)s")
log = logging.getLogger("server")

# Paths reachable without a session. Everything else 401s — see _auth_middleware.
#
# This is the second of two independent layers. The first is
# `dependencies=[Depends(require_user)]` on every include_router below, which is
# the one that produces good per-route behaviour. It also fails *open*: a router
# added later without that argument would be silently public. The middleware
# fails *closed* instead, so the mistake has to be made twice, and making a path
# public becomes a deliberate edit to this set.
#
# tests/test_authz.py::test_every_route_is_protected_or_explicitly_public
# enumerates app.routes and asserts each one is covered by exactly this list.
PUBLIC_PATHS: frozenset[str] = frozenset({
    "/api/health",
    "/api/auth/login",
    "/api/auth/signup",
    "/api/auth/logout",   # clearing a cookie you may no longer have is harmless
    "/docs",
    "/docs/oauth2-redirect",
    "/openapi.json",
    "/redoc",
})

# Note what is deliberately *not* here: /api/inbox/oauth/callback. Google
# redirects the browser to it, which looks like it would need to be public — but
# that is a top-level GET navigation, and SameSite=Lax sends cookies on exactly
# those. Keeping it authenticated means the pending OAuth state can be looked up
# under the right user instead of being trusted from the query string.


def _is_public(path: str) -> bool:
    return path in PUBLIC_PATHS


def create_app() -> FastAPI:
    app = FastAPI(title="Applination api", version="0.1.0")

    origins = os.environ.get(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.limiter = limiter

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limited(request, exc):  # noqa: ANN001
        return JSONResponse(
            {"detail": "rate limit exceeded; slow down and retry shortly"},
            status_code=429,
        )

    @app.middleware("http")
    async def _auth_middleware(request, call_next):  # noqa: ANN001
        """Fail closed: anything not explicitly public needs a session.

        Layer 2 of 2 — see PUBLIC_PATHS. CORS preflights are exempt because a
        browser sends OPTIONS without credentials, and 401ing it would break the
        real request that follows.
        """
        path = request.url.path
        if request.method == "OPTIONS" or _is_public(path):
            return await call_next(request)

        user = resolve_user(request)
        if user is None:
            return JSONResponse({"detail": "not authenticated"}, status_code=401)

        # /files serves the one global output tree, which is still the owner's
        # alone until PR 3 gives each user their own root. Without this, any
        # signed-up account could read the owner's resumes and cover letters by
        # walking /files — no database scoping would catch it, because no
        # database row is involved.
        if path.startswith("/files") and not user.is_owner:
            return JSONResponse(
                {"detail": "owner-only until per-user output lands"},
                status_code=403,
            )

        # Hand the resolved id to the rate limiter (and save the routers a
        # second lookup) without bypassing the per-route dependency.
        request.state.user_id = user.id
        return await call_next(request)

    cfg = load_config()
    out_root = Path(cfg["output"]["root"])
    if not out_root.is_absolute():
        out_root = ROOT / out_root
    out_root.mkdir(parents=True, exist_ok=True)
    app.mount("/files", StaticFiles(directory=str(out_root)), name="files")

    @app.on_event("startup")
    async def _on_startup() -> None:
        init_db()
        bus.bind_loop(asyncio.get_running_loop())
        app.state._poller_task = asyncio.create_task(_scheduled_run_poller())
        log.info("server started; output mounted at /files -> %s", out_root)

    @app.on_event("shutdown")
    async def _on_shutdown() -> None:
        task = getattr(app.state, "_poller_task", None)
        if task is not None:
            task.cancel()

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    # The auth router is the only one mounted without require_user — login and
    # signup obviously cannot require a session. Its own routes that do
    # (/me, /change-password) declare the dependency individually.
    app.include_router(auth_router)

    # Layer 1 of 2: every other router is protected at the mount point, so a new
    # endpoint inside any of them is authenticated the moment it is written.
    protected = (
        runs_router,
        applications_router,
        single_job_router,
        config_router,
        tweak_router,
        stats_router,
        ranked_router,
        ops_router,
        chat_router,
        studio_router,
        onboarding_router,
        onboarding_status_router,
        inbox_router,
        reminders_router,
        pricing_router,
    )
    for r in protected:
        app.include_router(r, dependencies=[Depends(require_user)])

    return app


async def _scheduled_run_poller() -> None:
    """Fire due scheduled runs. One task for the whole app; wakes every 60s.

    Runs the (synchronous, DB-backed) dispatch in a thread so it never blocks
    the event loop. Scheduled runs persist in the DB, so a restart re-arms them.
    """
    from .runs import dispatch_due_scheduled_runs

    while True:
        try:
            await asyncio.to_thread(dispatch_due_scheduled_runs)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduled-run poller tick failed")
        await asyncio.sleep(60)


app = create_app()
