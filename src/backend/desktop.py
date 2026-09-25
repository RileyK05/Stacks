"""The desktop app entry point (docs/plan-local-first.md §11).

One process: start the backend on a free 127.0.0.1 port with a per-launch
secret, then open a native window (the OS webview — Edge WebView2 on
Windows, WebKit on macOS) at `/#token=<secret>`. The SPA reads the token
from the URL fragment and sends it with every API call, so nothing else on
this machine can drive the API. Closing the window stops everything: the
backend's lifespan stops the model server, and on Windows the job object
guarantees it even if the process dies.

Run from a checkout with `python -m src.backend.desktop`; the packaged
build (scripts/build_desktop.py) runs exactly this.
"""

from __future__ import annotations

import logging
import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

import httpx

APP_NAME = "Course Assistant"
_logger = logging.getLogger("course_assistant.desktop")


def user_data_dir() -> Path:
    """The per-user app-data directory (databases, uploads, models)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "CourseAssistant"


def _bundle_root() -> Path | None:
    """Where PyInstaller unpacked the app, when running packaged."""
    root = getattr(sys, "_MEIPASS", None)
    return Path(root) if root else None


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _configure_environment(port: int, token: str) -> None:
    data_dir = Path(os.environ.get("APP_DATA_DIR", user_data_dir()))
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["APP_DATA_DIR"] = str(data_dir)
    os.environ["APP_ENV"] = "production"
    os.environ["APP_API_TOKEN"] = token
    bundle = _bundle_root()
    if bundle is not None:
        os.environ.setdefault("FRONTEND_DIST", str(bundle / "frontend"))
    logging.basicConfig(
        filename=data_dir / "app.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _logger.info("starting on port %s, data in %s", port, data_dir)


def _serve(port: int) -> tuple[object, threading.Thread]:
    import uvicorn
    from src.backend.main import create_app

    config = uvicorn.Config(
        create_app(), host="127.0.0.1", port=port, log_config=None, access_log=False
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="backend", daemon=True)
    thread.start()
    return server, thread


def _wait_healthy(port: int, token: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/api/health"
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, headers={"X-App-Token": token}, timeout=1.0)
            if response.is_success:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError("the backend did not start")


def main() -> int:
    port = _free_port()
    # A caller-supplied token (automation, tests) is honoured: whoever sets
    # this process's environment already controls it.
    token = os.environ.get("APP_API_TOKEN") or secrets.token_urlsafe(32)
    _configure_environment(port, token)
    server, thread = _serve(port)
    _wait_healthy(port, token)
    url = f"http://127.0.0.1:{port}/#token={token}"

    import webview

    webview.create_window(APP_NAME, url, width=1280, height=860, min_size=(900, 600))
    webview.start()  # blocks until the window closes

    # Window closed: stop the backend so its lifespan stops the model
    # server and the ingestion worker cleanly.
    server.should_exit = True  # type: ignore[attr-defined]
    thread.join(timeout=30)
    _logger.info("closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
