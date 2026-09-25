"""The backend as the desktop shell sees it: CORS for the Tauri webview,
and the serve entry point's port announcement and stdin shutdown."""

from __future__ import annotations

import subprocess
import sys
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from src.backend.common.config import PROJECT_ROOT
from src.backend.serve import PORT_ANNOUNCEMENT
from src.backend.version import __version__


def _preflight(client: TestClient, origin: str) -> httpx.Response:
    return client.options(
        "/api/courses",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-app-token, content-type",
        },
    )


@pytest.mark.parametrize("origin", ["http://tauri.localhost", "tauri://localhost"])
def test_the_tauri_webview_may_call_the_api(origin: str) -> None:
    from src.backend.main import create_app

    client = TestClient(create_app())
    response = _preflight(client, origin)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_other_origins_are_not_admitted(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.backend.main import create_app

    client = TestClient(create_app())
    response = _preflight(client, "https://example.com")
    assert "access-control-allow-origin" not in response.headers

    monkeypatch.setenv("APP_CORS_ORIGINS", "http://localhost:5173")
    dev = TestClient(create_app())
    allowed = _preflight(dev, "http://localhost:5173")
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cross_origin_requests_still_need_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.backend.main import create_app

    monkeypatch.setenv("APP_API_TOKEN", "launch-secret")
    client = TestClient(create_app())
    origin = {"Origin": "http://tauri.localhost"}
    assert client.get("/api/courses", headers=origin).status_code == 401
    ok = client.get("/api/courses", headers={**origin, "X-App-Token": "launch-secret"})
    assert ok.status_code == 200


def test_serve_announces_its_port_and_stops_when_stdin_closes() -> None:
    process = subprocess.Popen(
        [sys.executable, "-m", "src.backend.serve", "--watch-stdin"],
        cwd=PROJECT_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert process.stdout is not None and process.stdin is not None
        line = process.stdout.readline().strip()
        assert line.startswith(PORT_ANNOUNCEMENT), line
        port = int(line.removeprefix(PORT_ANNOUNCEMENT))

        deadline = time.monotonic() + 60
        while True:
            try:
                health = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=2)
                break
            except httpx.HTTPError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.2)
        assert health.json() == {"status": "ok", "version": __version__}

        process.stdin.close()
        assert process.wait(timeout=30) == 0
    finally:
        if process.poll() is None:
            process.kill()
