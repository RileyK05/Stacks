"""The add-in's HTTPS server, run inside the backend process.

It runs on its own thread and event loop beside the desktop API, so Office
reaches the pane and the bridge whenever Stacks is running, and it stops
with the backend.
"""

from __future__ import annotations

import contextlib
import logging
import socket
import threading
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
            thread.start()
            self._server, self._thread, self.port = server, thread, port
            _logger.info("Office add-in served on https://localhost:%s", port)

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(_STOP_TIMEOUT)
        self._server, self._thread, self.port = None, None, None


def _bind(port: int) -> list[socket.socket]:
    """Bind loopback on IPv4 and, where available, IPv6: Office resolves
    ``localhost`` and may try ::1 first."""
    try:
        sockets = [_listen(socket.AF_INET, "127.0.0.1", port)]
    except OSError as err:
        raise PortInUseError(
            f"port {port} is already in use (is another copy of Stacks running?)"
        ) from err
    with contextlib.suppress(OSError):
        sockets.append(_listen(socket.AF_INET6, "::1", port))
    return sockets


def _listen(family: socket.AddressFamily, address: str, port: int) -> socket.socket:
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        if family == socket.AF_INET6:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        sock.bind((address, port))
        sock.listen(128)
    except OSError:
        sock.close()
        raise
    return sock


HOST = AddinHost()
