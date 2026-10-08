"""The add-in's HTTPS server, run inside the backend process.

It runs on its own thread and event loop beside the desktop API, so Office
reaches the pane and the bridge whenever Stacks is running, and it stops
with the backend.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI

_logger = logging.getLogger(__name__)
_STOP_TIMEOUT = 5.0


class PortInUseError(OSError):
    pass


class AddinHost:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._sockets: list[socket.socket] = []
        self.port: int | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, app: FastAPI, *, port: int, cert: Path, key: Path) -> None:
        """Serve ``app`` over HTTPS on localhost:port. Restarts if already
        running (e.g. with a renewed certificate). Raises PortInUseError."""
        with self._lock:
            self._stop_locked()
            sockets = _bind(port)
            self._sockets = sockets
            try:
                config = uvicorn.Config(
                    app,
                    ssl_certfile=str(cert),
                    ssl_keyfile=str(key),
                    lifespan="off",
                    log_config=None,
                    access_log=False,
                )
                server = uvicorn.Server(config)
                thread = threading.Thread(
                    target=server.run,
                    kwargs={"sockets": sockets},
                    name="office-addin-host",
                    daemon=True,
                )
                self._server, self._thread, self.port = server, thread, port
                thread.start()
                deadline = time.monotonic() + _STOP_TIMEOUT
                while (
                    thread.is_alive()
                    and not server.started
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.01)
                if not server.started:
                    raise OSError("the Office HTTPS host did not become ready")
            except BaseException:
                try:
                    self._stop_locked()
                except OSError:
                    _logger.exception(
                        "Office host cleanup timed out after startup failure; "
                        "releasing its sockets without waiting for the thread"
                    )
                    self._release_sockets_locked()
                raise
            _logger.info("Office add-in served on https://localhost:%s", port)

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _release_sockets_locked(self) -> None:
        for sock in self._sockets:
            try:
                sock.close()
            except OSError:
                _logger.warning("could not close an Office host socket", exc_info=True)
        self._sockets = []
        self._server, self._thread, self.port = None, None, None

    def _stop_locked(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None and self._thread is not threading.current_thread():
            if self._thread.ident is not None:
                self._thread.join(_STOP_TIMEOUT)
            if self._thread.is_alive():
                raise OSError(
                    "the Office HTTPS host has not stopped; try again shortly"
                )
        self._release_sockets_locked()


def _bind(port: int) -> list[socket.socket]:
    """Bind loopback on IPv4 and, where available, IPv6: Office resolves
    ``localhost`` and may try ::1 first."""
    try:
        sockets = [_listen(socket.AF_INET, "127.0.0.1", port)]
    except OSError as err:
        raise PortInUseError(
            f"port {port} is already in use (is another copy of Stacks running?)"
        ) from err
    try:
        sockets.append(_listen(socket.AF_INET6, "::1", port))
    except OSError as err:
        _logger.warning("Office IPv6 loopback is unavailable: %s", err)
    return sockets


def _listen(family: socket.AddressFamily, address: str, port: int) -> socket.socket:
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if family == socket.AF_INET6:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        sock.bind((address, port))
        sock.listen(128)
    except OSError:
        sock.close()
        raise
    return sock


HOST = AddinHost()
