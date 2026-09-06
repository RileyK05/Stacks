from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from src.backend.api import archives, auth, courses, enrollments, sources
from src.backend.common import archive_maintenance


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    del app
    stop = asyncio.Event()
    task = asyncio.create_task(archive_maintenance.run_forever(stop))
    try:
        yield
    finally:
        stop.set()
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
