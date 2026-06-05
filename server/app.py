"""FastAPI entrypoint."""
from __future__ import annotations
import asyncio
import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .applications import router as applications_router
from .db import init_db
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
from .onboarding import router as onboarding_router
from .inbox import router as inbox_router
from .reminders import router as reminders_router

ROOT = Path(__file__).resolve().parent.parent

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s :: %(message)s")
log = logging.getLogger("server")


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
        log.info("server started; output mounted at /files -> %s", out_root)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    app.include_router(runs_router)
    app.include_router(applications_router)
    app.include_router(single_job_router)
    app.include_router(config_router)
    app.include_router(tweak_router)
    app.include_router(stats_router)
    app.include_router(ranked_router)
    app.include_router(ops_router)
    app.include_router(chat_router)
    app.include_router(studio_router)
    app.include_router(onboarding_router)
    app.include_router(inbox_router)
    app.include_router(reminders_router)

    return app


app = create_app()
