"""The backend app: the JSON API mounted at `/api`.

The desktop shell (src/frontend/src-tauri) ships the SPA itself and talks
to this app over 127.0.0.1 from its own webview origin, so CORS admits
exactly the Tauri origins (plus APP_CORS_ORIGINS in development, e.g. the
Vite dev server). CORS only decides which pages may read responses; the
per-launch app token (`api/deps.py`) is what actually guards the API.

Once the user connects Office, the lifespan also serves the Office add-in
(pane + `/office` bridge) over HTTPS on a fixed port (`office_addin/`).
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from src.backend.api import (
    artifacts,
    backups,
    companion,
    conversations,
    courses,
    data,
    graph,
    learning,
    mind_maps,
    office_setup,
    runtime,
    settings,
    sources,
    tutor,
)
from src.backend.api.deps import require_app_token
from src.backend.common import backups as backup_service
from src.backend.common import maintenance
from src.backend.common.body_limits import install_body_limits
from src.backend.common.config import get_settings
from src.backend.common.migrate import migrate
from src.backend.common.secrets import CredentialStoreUnavailableError
from src.backend.ingest import worker as ingestion_worker
from src.backend.office_addin import service as office_addin
from src.backend.office_addin.app import create_office, create_office_host
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
    production = get_settings().app_env == "production"
    api = FastAPI(
        title=APP_NAME,
        version=__version__,
        dependencies=[Depends(require_app_token)],
        docs_url=None,
        redoc_url=None,
        openapi_url=None if production else "/openapi.json",
    )
    install_body_limits(api)

    @api.exception_handler(CredentialStoreUnavailableError)
    async def credential_failure(
        request: Request, err: CredentialStoreUnavailableError
    ) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(err)})

    api.include_router(courses.router)
    api.include_router(sources.router)
    api.include_router(tutor.router)
    api.include_router(conversations.router)
    api.include_router(artifacts.router)
    api.include_router(companion.router)
    api.include_router(settings.router)
    api.include_router(runtime.router)
    api.include_router(data.router)
    api.include_router(backups.router)
    api.include_router(learning.router)
    api.include_router(graph.router)
    api.include_router(mind_maps.router)
    api.include_router(office_setup.router)

    @api.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return api


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    del app
    applied = await asyncio.to_thread(migrate)
    if applied:
        logger.info("applied migrations: %s", ", ".join(applied))
    try:
        await asyncio.to_thread(office_addin.start_if_connected)
    except Exception:
        logger.exception("could not start the Office add-in host")
    stop = asyncio.Event()
    tasks = [
        asyncio.create_task(maintenance.run_forever(stop)),
        asyncio.create_task(backup_service.run_forever(stop)),
        asyncio.create_task(ingestion_worker.run_forever(stop)),
        asyncio.create_task(supervisor.run_forever(stop)),
    ]
    for task in tasks:
        task.add_done_callback(_report_service_failure)
    try:
        yield
    finally:
        try:
            await asyncio.to_thread(office_addin.stop)
        except Exception:
            logger.exception("could not stop the Office add-in host")
        stop.set()
        for task in tasks:
            task.cancel()
            with suppress(asyncio.CancelledError):
                try:
                    await task
                except Exception:
                    logger.exception("background service failed during shutdown")


def _report_service_failure(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and (error := task.exception()) is not None:
        logger.error(
            "background service failed",
            exc_info=(type(error), error, error.__traceback__),
        )


def cors_origins() -> list[str]:
    extra = os.getenv("APP_CORS_ORIGINS", "")
    return [*TAURI_ORIGINS, *(o.strip() for o in extra.split(",") if o.strip())]


__all__ = ["create_api", "create_app", "create_office", "create_office_host"]


def create_app() -> FastAPI:
    app = FastAPI(lifespan=_lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
        # A cross-origin webview can only read response headers listed here;
        # the source viewer needs the PDF page count (api/sources.py).
        expose_headers=["X-Page-Count"],
        max_age=600,
    )
    app.mount("/api", create_api())
    return app


app = create_app()
