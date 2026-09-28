"""The ASGI apps behind the Office add-in."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from src.backend.api import office
from src.backend.office_addin.manifest import ADDIN_DIR


def create_office() -> FastAPI:
    """The bridge the task pane calls (mounted at /office by the host).

    Separate from the desktop API: the pane is a web page Microsoft Office
    loads and cannot hold the desktop shell's per-launch token. It reads and
    returns text only; Office owns the document."""
    bridge = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    bridge.include_router(office.router)
    return bridge


def create_office_host() -> FastAPI:
    """What the add-in's HTTPS origin serves: the pane's files at / and the
    bridge at /office. One origin, so the pane needs no CORS and no port
    discovery — it calls its own origin."""
    host = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @host.middleware("http")
    async def no_stale_pane(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Office's webview caches add-in pages hard; an app update must not
        # leave an old pane talking to a new bridge.
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    host.mount("/office", create_office())
    host.mount("/", StaticFiles(directory=ADDIN_DIR, html=True), name="addin")
    return host
