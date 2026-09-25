"""The single database seam: one SQLite file per local user.

Every connection is configured identically here — nothing else in the
codebase opens the database:

- `foreign_keys=ON` (SQLite's default is OFF: cascades and FK checks
  silently do nothing without it), WAL journaling, and a generous busy
  timeout so the ingestion worker and API requests queue on the single
  writer lock instead of failing.
- Transactions begin lazily as `BEGIN IMMEDIATE` on the first write
  (`isolation_level="IMMEDIATE"`): the writer lock is taken up front, so a
  read-then-write transaction can never deadlock on lock upgrade. Reads
  outside a transaction run in autocommit. Callers commit explicitly, as
  before. Keep write transactions short — never hold one across a model
  call.
- Declared column types decode on read: UUID → uuid.UUID, TIMESTAMP →
  aware UTC datetime, JSON → Python value. UUIDs and datetimes adapt on
  write. Rows come back as plain dicts.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from src.backend.common.config import get_settings

Connection = sqlite3.Connection

BUSY_TIMEOUT_SECONDS = 30.0

# Fixed-width UTC ISO-8601 with microseconds. Must match the schema's
# DEFAULT expression (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')) so every
# stored timestamp sorts lexicographically in time order.
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def format_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime(_TIMESTAMP_FORMAT)


def utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_timestamp(raw: bytes) -> datetime:
    parsed = datetime.fromisoformat(raw.decode())
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _parse_uuid(raw: bytes) -> UUID:
    return UUID(raw.decode())


def _parse_json(raw: bytes) -> Any:
    return json.loads(raw)


sqlite3.register_adapter(UUID, str)
sqlite3.register_adapter(datetime, format_timestamp)
sqlite3.register_converter("UUID", _parse_uuid)
sqlite3.register_converter("TIMESTAMP", _parse_timestamp)
sqlite3.register_converter("JSON", _parse_json)


def _dict_row(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
    columns = cursor.description
    return {column[0]: value for column, value in zip(columns, row, strict=True)}


def database_path() -> Path:
    return Path(get_settings().database_path)


def connect(path: Path | None = None) -> Connection:
    """Open a configured connection to the app database."""
    target = path or database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        target,
        timeout=BUSY_TIMEOUT_SECONDS,
        detect_types=sqlite3.PARSE_DECLTYPES,
        isolation_level="IMMEDIATE",
        check_same_thread=False,
    )
    conn.row_factory = _dict_row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    # now_utc() is the SQL-side twin of utc_now(): queries use it instead
    # of CURRENT_TIMESTAMP so SQL-written and Python-written timestamps
    # share one format.
    conn.create_function(
        "now_utc", 0, lambda: format_timestamp(utc_now()), deterministic=False
    )
    return conn


@contextmanager
def connection() -> Iterator[Connection]:
    """Yield a configured connection and close it on exit. An uncommitted
    transaction is rolled back on close."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def json_ids(ids: Any) -> str:
    """Encode a collection of ids for `IN (SELECT value FROM json_each(:ids))`
    — SQLite's stand-in for Postgres `= ANY(:ids)`."""
    return json.dumps([str(item) for item in ids])
