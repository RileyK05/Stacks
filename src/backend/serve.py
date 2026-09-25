"""The backend process the desktop shell runs (src/frontend/src-tauri).

    python -m src.backend.serve [--port N] [--watch-stdin]

It binds 127.0.0.1 itself (port 0 by default, so the OS picks a free one)
and prints `STACKS_PORT=<port>` on stdout once it is listening; the shell
reads that line instead of guessing a free port and racing for it.

With `--watch-stdin` it runs until its stdin closes. The shell holds the
write end, so quitting the app — or the app crashing — closes it, and the
backend shuts down cleanly: its lifespan stops the model server and the
ingestion worker. The per-launch token (APP_API_TOKEN) and the data
directory (APP_DATA_DIR) arrive through the environment.
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import threading
from pathlib import Path

import uvicorn
from src.backend.common.config import get_settings
from src.backend.main import create_app
from src.backend.version import __version__

_logger = logging.getLogger("stacks.serve")
PORT_ANNOUNCEMENT = "STACKS_PORT="


def _configure_logging() -> None:
    data_dir = Path(get_settings().data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=data_dir / "backend.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _bind(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", port))
    sock.listen(128)
    sock.set_inheritable(True)
    return sock


def _stop_when_stdin_closes(server: uvicorn.Server) -> None:
    def watch() -> None:
        stream = sys.stdin.buffer if sys.stdin else None
        if stream is not None:
            while stream.read(4096):
                pass
        _logger.info("stdin closed; shutting down")
        server.should_exit = True

    threading.Thread(target=watch, name="stdin-watch", daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stacks-backend")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--watch-stdin", action="store_true")
    args = parser.parse_args(argv)

    os.environ.setdefault("APP_ENV", "production")
    _configure_logging()
    sock = _bind(args.port)
    port = sock.getsockname()[1]

    config = uvicorn.Config(create_app(), log_config=None, access_log=False)
    server = uvicorn.Server(config)
    if args.watch_stdin:
        _stop_when_stdin_closes(server)

    # uvicorn has no "listening" hook, but the socket is already bound and
    # listening: connections queue in the backlog until the app serves them.
    print(f"{PORT_ANNOUNCEMENT}{port}", flush=True)
    _logger.info("Stacks %s backend on port %s", __version__, port)
    server.run(sockets=[sock])
    _logger.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
