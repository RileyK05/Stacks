from __future__ import annotations

import contextlib
import re
import sqlite3
from pathlib import Path

from src.backend.common.db import Connection, connect

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_MIGRATION_RE = re.compile(r"^(\d{3})_.+\.sql$")

# Numbers used by the retired Office-editor builds (removed 2026-09-27).
# Databases from those builds record them as applied, so a new migration
# with one of these numbers would be silently skipped there.
RETIRED_VERSIONS = frozenset({"006", "007"})


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


def _compatible_script(conn: Connection, version: str, script: str) -> str:
    if version != "012":
        return script
    base = {
        "artifact_id",
        "version",
        "title",
        "content",
        "sources",
        "author",
        "note",
        "created_at",
    }
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(artifact_versions)")
    }
    extra = columns - base
    if not extra:
        return script
    allowed = {"file_sha256", "filename", "file_size", "mime_type", "ops"}
    if extra - allowed:
        raise RuntimeError("unrecognized historical artifact fields; upgrade stopped")
    # Retired Office builds had file/revision fields. Preserve them in the
    # exported provenance envelope before the immutable 012 rebuild runs.
    version_fields = ["'version', v.version"] + [
        f"'{key}', " + (f"json(v.{key})" if key == "ops" else f"v.{key}")
        for key in sorted(extra)
    ]
    artifact_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(artifacts)")
    }
    file_fields = [
        f"'{key}', artifacts.{key}"
        for key in sorted(allowed - {"ops"})
        if key in artifact_columns
    ]
    preserve = (
        "UPDATE artifacts SET origin = json_set(origin, '$.legacy_office_versions', "
        "json((SELECT json_group_array(json_object("
        + ", ".join(version_fields)
        + ")) FROM artifact_versions v WHERE v.artifact_id = artifacts.artifact_id))"
        + (
            ", '$.legacy_office_file', json_object(" + ", ".join(file_fields) + ")"
            if file_fields
            else ""
        )
        + ");\n"
    )
    projection = (
        "artifact_id, version, title, content, sources, author, note, created_at"
    )
    return preserve + script.replace(
        "INSERT INTO artifact_versions SELECT * FROM kept_artifact_versions;",
        f"INSERT INTO artifact_versions SELECT {projection} "
        "FROM kept_artifact_versions;",
    )


def _migration_script(script: str, version: str) -> str:
    if not re.fullmatch(r"\d{3}", version):
        raise ValueError(f"unrecognized migration version: {version!r}")
    return (
        "BEGIN IMMEDIATE;\n"
        f"{script}\n"
        f"INSERT INTO schema_migrations (version) VALUES ('{version}');\n"
        "COMMIT;"
    )


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
            script = _compatible_script(conn, version, script)
            conn.executescript(_migration_script(script, version))
            applied.append(version)
    except BaseException:
        if conn.in_transaction:
            # A failed rollback must not replace the migration's own error.
            with contextlib.suppress(sqlite3.Error):
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
