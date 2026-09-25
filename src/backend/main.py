"""The app: a root ASGI app that serves the built SPA at `/` and mounts
the API at `/api`.

Serving both from one origin means the desktop window just loads
http://127.0.0.1:<port>/ — no CORS, no reverse proxy, and no clash
between API paths and SPA routes (plan §4, §11). The API requires the
per-launch app token when one is configured (`api/deps.py`); the static
SPA does not, and holds no data.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from src.backend.api import courses, settings, sources, tutor
from src.backend.api.deps import require_app_token
from src.backend.common import maintenance
from src.backend.common.config import PROJECT_ROOT
from src.backend.common.migrate import migrate
from src.backend.ingest import worker as ingestion_worker

logger = logging.getLogger(__name__)

DEFAULT_FRONTEND_DIST = PROJECT_ROOT / "src" / "frontend" / "build"
SPA_FALLBACK = "200.html"


def create_api() -> FastAPI:
    """The JSON API (mounted at /api). Tests drive this app directly."""
    api = FastAPI(
        title="Course Assistant",
        dependencies=[Depends(require_app_token)],
    )
    api.include_router(courses.router)
    api.include_router(sources.router)
    api.include_router(tutor.router)
    api.include_router(settings.router)

    @api.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

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
    ]
    try:
        yield
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


def _frontend_dist() -> Path:
    return Path(os.getenv("FRONTEND_DIST", str(DEFAULT_FRONTEND_DIST)))


def create_app() -> FastAPI:
    app = FastAPI(lifespan=_lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/api", create_api())

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        """Static files from the SPA build; anything else gets the SPA
        shell so client-side routes survive a reload."""
        dist = _frontend_dist().resolve()
        fallback = dist / SPA_FALLBACK
        if not fallback.is_file():
            raise HTTPException(404, "frontend not built (run npm run build)")
        candidate = (dist / path).resolve()
        if candidate.is_file() and candidate.is_relative_to(dist):
            return FileResponse(candidate)
        return FileResponse(fallback)

    return app


app = create_app()
