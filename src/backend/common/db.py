from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.connection import Connection
from src.backend.common.config import get_settings


def connect() -> Connection:
    """Open a Postgres connection from settings. The single seam to the DB."""
    settings = get_settings()
    return psycopg.connect(settings.dsn)


@contextmanager
def connection() -> Iterator[Connection]:
    """Context manager that yields a connection and closes it on exit."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
