from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from src.backend.api import archives, auth, courses, enrollments, sources
from src.backend.common import archive_maintenance
from src.backend.ingest import worker as ingestion_worker


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    del app
    stop = asyncio.Event()
    maintenance_task = asyncio.create_task(
        archive_maintenance.run_forever(stop)
    )
    ingestion_task = asyncio.create_task(ingestion_worker.run_forever(stop))
    try:
        yield
    finally:
        stop.set()
        for task in (maintenance_task, ingestion_task):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


def create_app() -> FastAPI:
    app = FastAPI(title="Course Assistant", lifespan=_lifespan)
    app.include_router(auth.router)
    app.include_router(courses.router)
    app.include_router(enrollments.router)
    app.include_router(sources.router)
    app.include_router(archives.router)
    return app


app = create_app()
