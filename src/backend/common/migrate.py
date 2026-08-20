from __future__ import annotations

import re
from pathlib import Path

from psycopg.connection import Connection
from src.backend.common.db import connection

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_MIGRATION_RE = re.compile(r"^(\d{3})_.+\.sql$")


def _ensure_tracking_table(conn: Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     TEXT PRIMARY KEY,
            applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def _applied_versions(conn: Connection) -> set[str]:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row[0] for row in rows}


def _pending_migrations() -> list[tuple[str, Path]]:
    pending: list[tuple[str, Path]] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = _MIGRATION_RE.match(path.name)
        if match:
            pending.append((match.group(1), path))
    return pending


def migrate() -> list[str]:
    """Apply any unapplied migrations in order. Returns applied versions."""
    applied: list[str] = []
    with connection() as conn:
        _ensure_tracking_table(conn)
        done = _applied_versions(conn)
        for version, path in _pending_migrations():
            if version in done:
                continue
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s)", (version,)
            )
            conn.commit()
            applied.append(version)
    return applied


if __name__ == "__main__":
    applied = migrate()
    if applied:
        print(f"Applied: {', '.join(applied)}")
    else:
        print("No pending migrations.")
