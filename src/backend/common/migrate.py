from __future__ import annotations

import re
from pathlib import Path

from src.backend.common.db import Connection, connect

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_MIGRATION_RE = re.compile(r"^(\d{3})_.+\.sql$")


def _ensure_tracking_table(conn: Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     TEXT PRIMARY KEY,
            applied_at  TIMESTAMP NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
        )
        """
    )


def _applied_versions(conn: Connection) -> set[str]:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row["version"] for row in rows}


def _pending_migrations() -> list[tuple[str, Path]]:
    pending: list[tuple[str, Path]] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = _MIGRATION_RE.match(path.name)
        if match:
            pending.append((match.group(1), path))
    return pending


def migrate(path: Path | None = None) -> list[str]:
    """Apply any unapplied migrations in order. Returns applied versions.

    Each migration runs as one script inside an explicit transaction, so a
    failing migration leaves the database at the previous version rather
    than half-applied. Safe to call on every startup."""
    applied: list[str] = []
    conn = connect(path)
    try:
        _ensure_tracking_table(conn)
        conn.commit()
        done = _applied_versions(conn)
        for version, migration in _pending_migrations():
            if version in done:
                continue
            script = migration.read_text(encoding="utf-8")
            conn.executescript(
                "BEGIN IMMEDIATE;\n"
                f"{script}\n"
                f"INSERT INTO schema_migrations (version) VALUES ('{version}');\n"
                "COMMIT;"
            )
            applied.append(version)
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return applied


if __name__ == "__main__":
    applied = migrate()
    if applied:
        print(f"Applied: {', '.join(applied)}")
    else:
        print("Database is up to date.")
