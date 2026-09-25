"""The backend app: the JSON API mounted at `/api`.

The desktop shell (src/frontend/src-tauri) ships the SPA itself and talks
to this app over 127.0.0.1 from its own webview origin, so CORS admits
exactly the Tauri origins (plus APP_CORS_ORIGINS in development, e.g. the
Vite dev server). CORS only decides which pages may read responses; the
per-launch app token (`api/deps.py`) is what actually guards the API.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.backend.api import (
    artifacts,
    conversations,
    courses,
    data,
    runtime,
    settings,
    sources,
    tutor,
)
from src.backend.api.deps import require_app_token
from src.backend.common import maintenance
from src.backend.common.migrate import migrate
from src.backend.ingest import worker as ingestion_worker
from src.backend.runtime import supervisor
from src.backend.version import APP_NAME, __version__

logger = logging.getLogger(__name__)

# The webview origin of a bundled Tauri app: WebView2 (Windows) serves it
# from http://tauri.localhost, WebKit (macOS, Linux) from tauri://localhost.
TAURI_ORIGINS = (
    "http://tauri.localhost",
    "https://tauri.localhost",
    "tauri://localhost",
)


def create_api() -> FastAPI:
    """The JSON API (mounted at /api). Tests drive this app directly."""
    api = FastAPI(
        title=APP_NAME,
        version=__version__,
        dependencies=[Depends(require_app_token)],
    )
    api.include_router(courses.router)
    api.include_router(sources.router)
    api.include_router(tutor.router)
    api.include_router(conversations.router)
    api.include_router(artifacts.router)
    api.include_router(settings.router)
    api.include_router(runtime.router)
    api.include_router(data.router)

    @api.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return api


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    del app
    applied = migrate()
    if applied:
        logger.info("applied migrations: %s", ", ".join(applied))
    stop = asyncio.Event()
    tasks = [
        asyncio.create_task(maintenance.run_forever(stop)),
        asyncio.create_task(ingestion_worker.run_forever(stop)),
        asyncio.create_task(supervisor.run_forever(stop)),
    ]
    try:
        yield
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


def cors_origins() -> list[str]:
    extra = os.getenv("APP_CORS_ORIGINS", "")
    return [*TAURI_ORIGINS, *(o.strip() for o in extra.split(",") if o.strip())]


def create_app() -> FastAPI:
    app = FastAPI(lifespan=_lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
        max_age=600,
    )
    app.mount("/api", create_api())
    return app


app = create_app()
