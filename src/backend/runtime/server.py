"""The supervised llama.cpp server behind the "local" provider preset.

The backend owns its lifecycle (plan §11): download the pinned build,
start `llama-server` on 127.0.0.1 with the chosen model, wait for health,
restart it if it crashes, stop it on shutdown. Reasoning is disabled
server-side (`--reasoning-budget 0`): per-request switches are ignored by
some templates and runners (plan §3).

Accelerator choice is empirical, not probed: the Vulkan build is tried
first (it covers Intel, AMD and NVIDIA GPUs, including integrated ones);
if it cannot start, the CPU build is used and remembered.

The server must never outlive the app. On Windows it runs inside a job
object that kills it when the backend process exits, however it exits;
everywhere, a pidfile lets the next launch clean up a stale server.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx
from src.backend.common import settings_repo
from src.backend.common.config import get_settings
from src.backend.runtime import hardware, model_store, user_models
from src.backend.runtime.config import CatalogModel, load_runtime_config
from src.backend.runtime.downloads import DownloadError, download_verified

logger = logging.getLogger(__name__)

ACTIVE_MODEL_SETTING = "runtime.active_model"
BACKEND_SETTING = "runtime.backend"
MAX_RESTARTS = 3
RESTART_WINDOW_SECONDS = 300
# A hung `ps`/`taskkill` must not block the supervisor's startup cleanup
# thread forever (that path runs before its event loop and its shutdown).
_PROCESS_PROBE_TIMEOUT = 10.0


class RuntimeUnavailableError(RuntimeError):
    pass


def runtime_dir() -> Path:
    return Path(get_settings().data_dir) / "runtime"


def _exe_name() -> str:
    return "llama-server.exe" if sys.platform == "win32" else "llama-server"


def ensure_binary(asset_key: str) -> Path:
    """The llama-server executable for an archive key, downloading and
    unpacking the pinned build on first use."""
    config = load_runtime_config().llama_cpp
    asset = config.assets.get(asset_key)
    if asset is None:
        raise RuntimeUnavailableError(f"no llama.cpp build for {asset_key}")
    target = runtime_dir() / "llama.cpp" / config.build / asset_key
    existing = next(target.rglob(_exe_name()), None) if target.is_dir() else None
    if existing is not None:
        return existing
    archive = download_verified(
        config.download_url(asset),
        runtime_dir() / "downloads" / asset.file,
        sha256=asset.sha256,
        size_bytes=asset.size_bytes,
    )
    staging = target.with_name(target.name + ".unpacking")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    if asset.file.endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(staging)
    else:
        with tarfile.open(archive) as bundle:
            bundle.extractall(staging, filter="data")
    shutil.rmtree(target, ignore_errors=True)
    staging.replace(target)
    executable = next(target.rglob(_exe_name()), None)
    if executable is None:
        raise RuntimeUnavailableError(f"{asset.file} has no {_exe_name()}")
    if sys.platform != "win32":
        executable.chmod(0o755)
    return executable


class _KillOnCloseJob:
    """Windows job object: every process assigned to it dies when the
    backend exits (the last handle to the job closes with the process)."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined,unused-ignore]

        class BasicLimits(ctypes.Structure):
            _fields_ = [  # noqa: RUF012 - ctypes layout
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (  # noqa: RUF012
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [  # noqa: RUF012 - ctypes layout
                ("BasicLimitInformation", BasicLimits),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        job_object_limit_kill_on_job_close = 0x2000
        job_object_extended_limit_information = 9
        self._kernel32 = kernel32
        self._handle = kernel32.CreateJobObjectW(None, None)
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = job_object_limit_kill_on_job_close
        kernel32.SetInformationJobObject(
            self._handle,
            job_object_extended_limit_information,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        )

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        handle = int(process._handle)  # type: ignore[attr-defined,unused-ignore]
        if not self._kernel32.AssignProcessToJobObject(self._handle, handle):
            # A process already inside a job that forbids nesting cannot be
            # assigned. The pidfile still lets the next launch clean up, so
            # record the gap instead of failing the launch outright.
            logger.warning(
                "could not assign llama-server to the kill-on-close job; "
                "it may outlive the app until the next launch cleans it up"
            )


@dataclass
class ServerStatus:
    state: str  # stopped | starting | running | failed
    model_id: str | None
    backend: str | None
    port: int
    pid: int | None
    error: str | None


class LlamaServer:
    """One supervised llama-server process. Thread-safe; the API calls it
    from request threads and the supervisor from the event loop."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._model: CatalogModel | None = None
        self._backend: str | None = None
        self._state = "stopped"
        self._error: str | None = None
        self._restarts: list[float] = []
        self._job = _KillOnCloseJob() if sys.platform == "win32" else None

    @property
    def port(self) -> int:
        return load_runtime_config().llama_cpp.port

    def status(self) -> ServerStatus:
        with self._lock:
            return ServerStatus(
                state=self._state,
                model_id=self._model.id if self._model else None,
                backend=self._backend,
                port=self.port,
                pid=self._process.pid if self._process else None,
                error=self._error,
            )

    def start(self, model_id: str) -> ServerStatus:
        """Start (or switch to) a model. Blocks until the server answers
        health checks, so callers can use it immediately after."""
        model = user_models.find_model(model_id)
        if model is None:
            raise RuntimeUnavailableError(f"unknown model: {model_id}")
        path = model_store.installed_path(model)
        if path is None:
            raise RuntimeUnavailableError(f"{model.label} is not downloaded yet")
        with self._lock:
            if (
                self._state == "running"
                and self._model is not None
                and self._model.id == model_id
                and self._process is not None
                and self._process.poll() is None
            ):
                return self.status()
            self._stop_locked()
            self._model = model
            self._state = "starting"
            self._error = None
            # Anything raised before the launch loop (a busy settings DB, an
            # unavailable hardware probe) must not strand the server in
            # "starting": the supervisor only recovers a "running" server.
            try:
                preferred = settings_repo.get_setting(BACKEND_SETTING)
                keys = hardware.detect().asset_keys()
                if preferred in keys:
                    keys = [preferred] + [k for k in keys if k != preferred]
                last_error = "no llama.cpp build for this platform"
                for key in keys:
                    try:
                        self._launch_locked(key, model, path)
                    except (
                        RuntimeUnavailableError,
                        DownloadError,
                        httpx.HTTPError,
                        zipfile.BadZipFile,
                        zipfile.LargeZipFile,
                        tarfile.TarError,
                        RuntimeError,
                        NotImplementedError,
                        OSError,
                        ValueError,
                    ) as err:
                        last_error = str(err)
                        logger.warning(
                            "llama-server (%s) failed to start: %s", key, err
                        )
                        self._stop_locked()
                        self._model = model
                        continue
                    self._backend = key
                    self._state = "running"
                    settings_repo.put_setting(BACKEND_SETTING, key)
                    settings_repo.put_setting(ACTIVE_MODEL_SETTING, model.id)
                    return self.status()
            except Exception as err:
                # Convert an unexpected pre-launch failure into the state the
                # UI and supervisor both understand, keeping the real message.
                self._stop_locked()
                self._model = model
                self._state = "failed"
                self._error = str(err)
                raise RuntimeUnavailableError(str(err)) from err
            self._state = "failed"
            self._error = last_error
            raise RuntimeUnavailableError(last_error)

    def _launch_locked(self, asset_key: str, model: CatalogModel, path: Path) -> None:
        config = load_runtime_config().llama_cpp
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", config.port))
        except OSError as err:
            raise RuntimeUnavailableError(
                f"local model port {config.port} is already in use; "
                "stop the other server or choose another runtime port"
            ) from err
        executable = ensure_binary(asset_key)
        gpu = not asset_key.endswith("-cpu")
        threads = max(1, (os.cpu_count() or 2) - 1)
        command = [
            str(executable),
            "--model",
            str(path),
            "--alias",
            model.id,
            "--host",
            "127.0.0.1",
            "--port",
            str(config.port),
            "--ctx-size",
            str(config.context_size),
            "--jinja",
            "--reasoning-budget",
            str(config.reasoning_budget),
            "--threads",
            str(threads),
            "--n-gpu-layers",
            "999" if gpu else "0",
        ]
        log_path = runtime_dir() / "llama-server.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log = log_path.open("ab")
        creationflags = (
            int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if sys.platform == "win32"
            else 0
        )
        try:
            process = subprocess.Popen(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        finally:
            log.close()
        self._process = process
        if self._job is not None:
            self._job.assign(process)
        _pidfile().write_text(str(process.pid), encoding="utf-8")
        self._wait_healthy_locked(process, config.startup_timeout_seconds)

    def _wait_healthy_locked(
        self, process: subprocess.Popen[bytes], timeout: float
    ) -> None:
        deadline = time.monotonic() + timeout
        url = f"http://127.0.0.1:{self.port}/health"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeUnavailableError(
                    f"llama-server exited with code {process.returncode}; "
                    f"see {runtime_dir() / 'llama-server.log'}"
                )
            try:
                if httpx.get(url, timeout=2.0).status_code == 200:
                    if process.poll() is not None:
                        raise RuntimeUnavailableError(
                            "llama-server exited during its health check; "
                            "the runtime port may be in use by another process"
                        )
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise RuntimeUnavailableError("llama-server did not become healthy in time")

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()
            settings_repo.delete_setting(ACTIVE_MODEL_SETTING)

    def _stop_locked(self) -> None:
        process, self._process = self._process, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning(
                        "llama-server (pid %s) did not exit after kill; "
                        "leaving it to the job object",
                        process.pid,
                    )
        try:
            _pidfile().unlink(missing_ok=True)
        except OSError:
            logger.warning("could not remove the llama-server pidfile", exc_info=True)
        self._state = "stopped"
        self._model = None
        self._backend = None

    def check_and_restart(self) -> None:
        """Supervisor tick: restart a crashed server, at most MAX_RESTARTS
        times in RESTART_WINDOW_SECONDS, then report it failed."""
        with self._lock:
            process, model = self._process, self._model
            if self._state != "running" or process is None or model is None:
                return
            if process.poll() is None:
                return
            now = time.monotonic()
            self._restarts = [
                t for t in self._restarts if now - t < RESTART_WINDOW_SECONDS
            ]
            if len(self._restarts) >= MAX_RESTARTS:
                self._state = "failed"
                self._error = "llama-server keeps crashing; see the runtime log"
                return
            self._restarts.append(now)
            logger.warning("llama-server exited (%s); restarting", process.returncode)
            # Keep the decision and restart together: a queued restart must
            # never undo a model switch made by a request thread.
            try:
                self.start(model.id)
            except RuntimeUnavailableError:
                logger.exception("llama-server restart failed")


def _pidfile() -> Path:
    path = runtime_dir() / "llama-server.pid"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _process_executable(pid: int) -> str | None:
    """The executable path of a running process, or None if it is gone or
    cannot be read. Linux has /proc; macOS has no /proc, so ask ps."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            length = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(length.value)
            if kernel.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(length)
            ):
                return buffer.value
            return None
        finally:
            kernel.CloseHandle(handle)
    if sys.platform == "linux":
        try:
            return str(Path(f"/proc/{pid}/exe").resolve(strict=True))
        except OSError:
            return None
    output = subprocess.run(
        ["ps", "-p", str(pid), "-o", "comm="],
        capture_output=True,
        text=True,
        check=False,
        timeout=_PROCESS_PROBE_TIMEOUT,
    ).stdout.strip()
    return output or None


def cleanup_stale_server() -> None:
    """Kill a llama-server left behind by a crashed previous launch (the
    pidfile names it; only a process whose executable lives under our
    runtime directory is touched)."""
    path = _pidfile()
    if not path.exists():
        return
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        path.unlink(missing_ok=True)
        return
    try:
        exe = _process_executable(pid)
        if (
            exe is not None
            and Path(exe).resolve().is_relative_to(runtime_dir().resolve())
            and Path(exe).name in {"llama-server", "llama-server.exe"}
        ):
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    check=False,
                    capture_output=True,
                    timeout=_PROCESS_PROBE_TIMEOUT,
                )
            else:
                os.kill(pid, 15)
    except (OSError, subprocess.SubprocessError):
        pass
    path.unlink(missing_ok=True)


def ensure_running(model_id: str) -> None:
    """Make sure the bundled server is serving `model_id`, starting (or
    switching to) it if needed — so choosing "Local model" in Settings
    just works on the first question, without a separate Start step."""
    current = get_server().status()
    if current.state == "running" and current.model_id == model_id:
        return
    get_server().start(model_id)


_server: LlamaServer | None = None
_server_lock = threading.Lock()


def get_server() -> LlamaServer:
    global _server
    with _server_lock:
        if _server is None:
            _server = LlamaServer()
        return _server
