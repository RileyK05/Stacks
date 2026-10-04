"""The bundled local model runtime: catalog, verified downloads, model
lookup, server launch/fallback, and the runtime API. No test downloads
anything or starts a real llama-server."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from src.backend.runtime import downloads, hardware, model_store, server
from src.backend.runtime.config import CatalogModel, load_runtime_config

GIB = 1024**3


def _model(payload: bytes, **overrides: Any) -> CatalogModel:
    values: dict[str, Any] = {
        "id": "tiny",
        "label": "Tiny",
        "tier": "starter",
        "repo": "org/tiny",
        "file": "tiny.gguf",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
        "min_ram_gb": 8,
        "license": "MIT",
    }
    values.update(overrides)
    return CatalogModel(**values)


# --- catalog + hardware -----------------------------------------------------


def test_catalog_is_well_formed_and_bundles_only_supported_architectures() -> None:
    config = load_runtime_config()
    ids = [model.id for model in config.models]
    assert len(ids) == len(set(ids))
    assert ids[0] == "minicpm5-2b", "the Phase 0 default leads the catalog"
    assert not any(model_id.startswith("k2-horizon") for model_id in ids), (
        "k2-horizon is not a llama.cpp architecture at the pinned build"
    )
    assert config.llama_cpp.reasoning_budget == 0
    for key in ("windows-x64-vulkan", "windows-x64-cpu", "macos-arm64"):
        assert key in config.llama_cpp.assets


@pytest.mark.parametrize(
    ("ram_gb", "expected"),
    [(8, "minicpm5-2b"), (32, "minicpm5-2b")],
)
def test_recommendation_is_the_first_fitting_starter(
    ram_gb: int, expected: str
) -> None:
    machine = hardware.Hardware("windows", "x64", ram_gb * GIB, 8)
    assert hardware.recommended_model(load_runtime_config(), machine).id == expected


def test_fit_uses_machine_ram() -> None:
    config = load_runtime_config()
    small = hardware.Hardware("windows", "x64", 8 * GIB, 4)
    ling = config.model("ling-3.0-tiny")
    assert ling is not None and not hardware.fits(ling, small)
    assert hardware.fits(config.models[0], small)


def test_asset_order_prefers_gpu_then_cpu() -> None:
    assert hardware.Hardware("windows", "x64", GIB, 1).asset_keys() == [
        "windows-x64-vulkan",
        "windows-x64-cpu",
    ]
    assert hardware.Hardware("macos", "arm64", GIB, 1).asset_keys() == ["macos-arm64"]
    assert hardware.Hardware("windows", "arm64", GIB, 1).asset_keys() == []


def test_detect_reads_real_ram() -> None:
    assert hardware.detect().ram_bytes > GIB


# --- verified downloads -----------------------------------------------------


class _FakeStream:
    def __init__(self, status: int, body: bytes) -> None:
        self.status_code = status
        self._body = body
        self.headers: dict[str, str] = {}

    def __enter__(self) -> _FakeStream:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "bad",
                request=httpx.Request("GET", "http://x"),
                response=httpx.Response(self.status_code),
            )

    def iter_bytes(self, size: int):
        for start in range(0, len(self._body), 4):
            yield self._body[start : start + 4]


def _serve(monkeypatch: pytest.MonkeyPatch, payload: bytes) -> list[dict]:
    seen: list[dict] = []

    def fake_stream(method, url, headers=None, **kwargs):
        seen.append(dict(headers or {}))
        offset = int(headers["Range"].split("=")[1].rstrip("-")) if headers else 0
        response = _FakeStream(206 if offset else 200, payload[offset:])
        if offset:
            response.headers["Content-Range"] = (
                f"bytes {offset}-{len(payload) - 1}/{len(payload)}"
            )
        return response

    monkeypatch.setattr(httpx, "stream", fake_stream)
    return seen


def test_download_verifies_checksum_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"gguf-model-bytes-0123456789"
    seen = _serve(monkeypatch, payload)
    dest = tmp_path / "m.gguf"
    (tmp_path / "m.gguf.part").write_bytes(payload[:10])  # an interrupted download
    progress: list[int] = []
    downloads.download_verified(
        "http://x/m.gguf",
        dest,
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        progress=lambda done, total: progress.append(done),
    )
    assert dest.read_bytes() == payload
    assert seen == [{"Range": "bytes=10-"}], "resumed from the partial file"
    assert progress[-1] == len(payload)
    assert not (tmp_path / "m.gguf.part").exists()


def test_download_rejects_a_checksum_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(monkeypatch, b"tampered-bytes!")
    with pytest.raises(downloads.DownloadError, match="checksum mismatch"):
        downloads.download_verified(
            "http://x/m.gguf",
            tmp_path / "m.gguf",
            sha256="0" * 64,
            size_bytes=len(b"tampered-bytes!"),
        )
    assert not (tmp_path / "m.gguf").exists()
    assert not (tmp_path / "m.gguf.part").exists(), "a bad file never lingers"


def test_download_retries_from_scratch_when_the_resume_range_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"gguf-model-bytes-0123456789"
    dest = tmp_path / "m.gguf"
    (tmp_path / "m.gguf.part").write_bytes(payload[:10])  # stale partial
    requests: list[dict] = []

    def fake_stream(method, url, headers=None, **kwargs):
        requests.append(dict(headers or {}))
        if headers:
            # The stored asset changed: the server can no longer serve our
            # offset, so it answers 416. A stale .part used to fail forever.
            return _FakeStream(416, b"")
        return _FakeStream(200, payload)

    monkeypatch.setattr(httpx, "stream", fake_stream)
    downloads.download_verified(
        "http://x/m.gguf",
        dest,
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )
    assert dest.read_bytes() == payload
    assert requests == [{"Range": "bytes=10-"}, {}], "reset once, then full GET"
    assert not (tmp_path / "m.gguf.part").exists()


# --- model lookup -----------------------------------------------------------


def test_locate_prefers_the_apps_own_copy() -> None:
    payload = b"own-copy"
    model = _model(payload)
    assert model_store.locate(model, verify=True) == (None, "missing")
    own = model_store.models_dir() / model.file
    own.parent.mkdir(parents=True, exist_ok=True)
    own.write_bytes(payload)
    assert model_store.locate(model, verify=False) == (own, "app")


def test_delete_model_check_and_removal_are_atomic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A concurrent start_download must never slip between the "no active
    # download" guard and the unlink: the state pop happens under the lock.
    payload = b"delete-me"
    model = _model(payload)
    own = model_store.owned_path(model)
    own.parent.mkdir(parents=True, exist_ok=True)
    own.write_bytes(payload)
    observed: dict[str, bool] = {}

    class _RecordingDict(dict):
        def pop(self, *args: Any, **kwargs: Any) -> Any:
            observed["pop_locked"] = model_store._lock.locked()
            return super().pop(*args, **kwargs)

    monkeypatch.setattr(model_store, "_downloads", _RecordingDict())
    assert model_store.delete_model(model) is True
    assert not own.exists()
    assert observed["pop_locked"] is True


def test_external_copy_is_verified_once_then_remembered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"lm-studio-copy"
    model = _model(payload)
    external = tmp_path / "lmstudio" / "org" / model.file
    external.parent.mkdir(parents=True)
    external.write_bytes(payload)
    monkeypatch.setattr(model_store, "_external_roots", lambda: [tmp_path / "lmstudio"])

    assert model_store.locate(model, verify=False) == (external, "external-unverified")
    assert model_store.installed_path(model) == external
    hashed: list[Path] = []
    monkeypatch.setattr(model_store, "sha256_of", lambda path: hashed.append(path))
    assert model_store.locate(model, verify=True) == (external, "external")
    assert hashed == [], "a verified file is not hashed again"


def test_external_copy_with_a_different_hash_is_not_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = _model(b"pinned-revision")
    external = tmp_path / "lmstudio" / model.file
    external.parent.mkdir(parents=True)
    external.write_bytes(b"older-revision!")  # same size, different bytes
    monkeypatch.setattr(model_store, "_external_roots", lambda: [tmp_path / "lmstudio"])
    assert model_store.installed_path(model) is None


# --- server launch ----------------------------------------------------------


class _FakeProcess:
    def __init__(self, exit_code: int | None) -> None:
        self.pid = 4242
        self.returncode = exit_code
        self._handle = 0

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode or 0

    def kill(self) -> None:
        self.returncode = -9


def _fake_launch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, exit_codes: dict[str, int | None]
) -> list[list[str]]:
    payload = b"model"
    model = _model(payload, id="minicpm5-2b", file="MiniCPM5-2B-Q4_K_M.gguf")
    config = load_runtime_config()
    patched = config.model_copy(
        update={"models": [model] + [m for m in config.models if m.id != model.id]}
    )
    monkeypatch.setattr(server, "load_runtime_config", lambda: patched)
    monkeypatch.setattr(model_store, "installed_path", lambda m: tmp_path / m.file)
    monkeypatch.setattr(
        server.hardware,
        "detect",
        lambda: hardware.Hardware("windows", "x64", 16 * GIB, 8),
    )
    monkeypatch.setattr(
        server, "ensure_binary", lambda key: tmp_path / key / "llama-server"
    )
    commands: list[list[str]] = []

    def fake_popen(command, **kwargs):
        commands.append(command)
        key = Path(command[0]).parent.name
        return _FakeProcess(exit_codes[key])

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(httpx, "get", lambda url, timeout=None: httpx.Response(200))
    return commands


def test_start_disables_reasoning_and_binds_localhost(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands = _fake_launch(monkeypatch, tmp_path, {"windows-x64-vulkan": None})
    manager = server.LlamaServer()
    manager._job = None
    status = manager.start("minicpm5-2b")
    assert (status.state, status.backend) == ("running", "windows-x64-vulkan")
    command = commands[0]
    assert command[command.index("--reasoning-budget") + 1] == "0"
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--alias") + 1] == "minicpm5-2b"
    assert command[command.index("--n-gpu-layers") + 1] == "999"
    manager.stop()
    assert manager.status().state == "stopped"


def test_start_falls_back_to_cpu_when_vulkan_cannot_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands = _fake_launch(
        monkeypatch, tmp_path, {"windows-x64-vulkan": 1, "windows-x64-cpu": None}
    )
    manager = server.LlamaServer()
    manager._job = None
    status = manager.start("minicpm5-2b")
    assert status.backend == "windows-x64-cpu"
    assert commands[1][commands[1].index("--n-gpu-layers") + 1] == "0"


def test_start_refuses_a_model_that_is_not_downloaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_store, "installed_path", lambda m: None)
    manager = server.LlamaServer()
    manager._job = None
    with pytest.raises(server.RuntimeUnavailableError, match="not downloaded"):
        manager.start("minicpm5-2b")


def test_unexpected_prelaunch_failure_does_not_strand_starting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A busy settings DB / unavailable hardware probe before the launch loop
    # used to escape with state still "starting", which the supervisor never
    # recovers. It must surface as a failed, reported state instead.
    commands = _fake_launch(monkeypatch, tmp_path, {"windows-x64-vulkan": None})
    real_get = server.settings_repo.get_setting

    def flaky_setting(key: str) -> Any:
        if key == server.BACKEND_SETTING:
            raise RuntimeError("database is locked")
        return real_get(key)

    monkeypatch.setattr(server.settings_repo, "get_setting", flaky_setting)
    manager = server.LlamaServer()
    manager._job = None
    with pytest.raises(server.RuntimeUnavailableError, match="database is locked"):
        manager.start("minicpm5-2b")
    status = manager.status()
    assert status.state == "failed"
    assert status.error == "database is locked"
    assert commands == []


def test_launch_survives_an_unkillable_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # _stop_locked is called from the launch error handler; if waiting after
    # kill() times out it must not raise and re-strand the state machine.
    manager = server.LlamaServer()
    manager._job = None

    class _StuckProcess(_FakeProcess):
        def terminate(self) -> None:
            pass

        def wait(self, timeout: float | None = None) -> int:
            raise subprocess.TimeoutExpired("llama-server", timeout or 0)

        def kill(self) -> None:
            pass

    manager._process = _StuckProcess(None)  # type: ignore[assignment]
    manager._state = "starting"
    manager._stop_locked()
    assert manager.status().state == "stopped"


# --- generation seam + API --------------------------------------------------


def test_local_preset_starts_the_runtime_on_first_use(
    monkeypatch: pytest.MonkeyPatch, _no_local_runtime: list[str]
) -> None:
    from src.backend.common import provider
    from tests.conftest import configure_test_provider

    configure_test_provider(monkeypatch, "ok")
    provider.generate("tutor_answer", "prompt")
    assert _no_local_runtime == ["minicpm5-2b"]


def test_runtime_overview_lists_catalog_with_fit_and_location(
    client: TestClient,
) -> None:
    view = client.get("/runtime").json()
    assert view["server"]["state"] == "stopped"
    assert view["hardware"]["ram_gb"] > 0
    models = {model["id"]: model for model in view["models"]}
    assert models["minicpm5-2b"]["recommended"] is True
    assert models["minicpm5-2b"]["location"] == "missing"
    assert client.post("/runtime/models/nope/download").status_code == 404


def test_runtime_start_reports_why_it_cannot(client: TestClient) -> None:
    response = client.post("/runtime/start", json={"model_id": "minicpm5-2b"})
    assert response.status_code == 409
    assert "not downloaded" in response.json()["detail"]


@pytest.mark.parametrize(
    ("ps_output", "killed"),
    [
        ("{runtime}/macos-arm64/llama-server\n", True),
        ("/Applications/Safari.app/Contents/MacOS/Safari\n", False),
        ("", False),  # the process is gone
    ],
)
def test_stale_server_cleanup_on_macos_only_kills_our_llama_server(
    monkeypatch: pytest.MonkeyPatch, ps_output: str, killed: bool
) -> None:
    # macOS has no /proc: a reused pid must not be killed on the pidfile's word.
    server._pidfile().write_text("4242", encoding="utf-8")
    kills: list[int] = []

    def fake_run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        assert command[:3] == ["ps", "-p", "4242"]
        stdout = ps_output.format(runtime=server.runtime_dir())
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    monkeypatch.setattr(server.sys, "platform", "darwin")
    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(server.os, "kill", lambda pid, _sig: kills.append(pid))

    server.cleanup_stale_server()

    assert kills == ([4242] if killed else [])
    assert not server._pidfile().exists()
