import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from src.backend.common import migrate as migrate_module
from src.backend.common.db import connect, connection, format_timestamp
from src.backend.common.migrate import migrate


def _course(conn: sqlite3.Connection, name: str = "C") -> UUID:
    course_id = uuid4()
    conn.execute(
        "INSERT INTO courses (course_id, name) VALUES (?, ?)", (course_id, name)
    )
    return course_id


def _source(conn: sqlite3.Connection, course_id: UUID) -> UUID:
    source_id = uuid4()
    conn.execute(
        "INSERT INTO sources (source_id, course_id, filename, mime_type, source_type)"
        " VALUES (?, ?, 'f.txt', 'text/plain', 'notes')",
        (source_id, course_id),
    )
    return source_id


def test_migrations_apply_to_a_fresh_file_and_are_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "fresh.db"
    expected = sorted(f.name[:3] for f in migrate_module.MIGRATIONS_DIR.glob("*.sql"))
    assert expected[:3] == ["001", "002", "003"]
    assert migrate(path) == expected
    assert migrate(path) == []
    conn = connect(path)
    try:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
        }
    finally:
        conn.close()
    for expected in (
        "courses",
        "sources",
        "chunks",
        "chunks_fts",
        "chunk_embeddings",
        "ingestion_runs",
        "pending_ingestion",
        "toc_entries_fts",
        "retrieval_traces",
        "usage_ledger",
        "course_memories",
        "app_settings",
    ):
        assert expected in tables
    # Nothing from the hosted multi-user design survives.
    for gone in ("users", "course_enrollments", "user_subscriptions", "premium_codes"):
        assert gone not in tables


def test_failed_migration_leaves_database_at_previous_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_ok.sql").write_text("CREATE TABLE a (x INTEGER);")
    (migrations / "002_bad.sql").write_text(
        "CREATE TABLE b (x INTEGER);\nINSERT INTO nowhere VALUES (1);"
    )
    monkeypatch.setattr(migrate_module, "MIGRATIONS_DIR", migrations)
    path = tmp_path / "partial.db"
    with pytest.raises(sqlite3.OperationalError):
        migrate(path)
    conn = connect(path)
    try:
        names = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master").fetchall()
        }
        versions = [
            row["version"]
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        ]
    finally:
        conn.close()
    assert "a" in names and "b" not in names
    assert versions == ["001"]


def test_foreign_keys_are_enforced_on_every_connection() -> None:
    with connection() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()["foreign_keys"] == 1
        with pytest.raises(sqlite3.IntegrityError):
            _source(conn, uuid4())


def _fts_hits(conn: sqlite3.Connection, term: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM chunks_fts WHERE chunks_fts MATCH ?", (term,)
    ).fetchone()["n"]


def test_deleting_a_course_cascades_and_keeps_fts_in_sync() -> None:
    with connection() as conn:
        course_id = _course(conn)
        source_id = _source(conn, course_id)
        locator_id = uuid4()
        conn.execute(
            "INSERT INTO locators (locator_id, source_id, locator_type, start, label)"
            " VALUES (?, ?, 'page', '1', 'p1')",
            (locator_id, source_id),
        )
        conn.execute(
            "INSERT INTO chunks (chunk_id, source_id, locator_id, chunk_index, text)"
            " VALUES (?, ?, ?, 0, 'orthogonal matrices preserve length')",
            (uuid4(), source_id, locator_id),
        )
        conn.commit()
        assert _fts_hits(conn, "preserving") == 1  # porter: preserving ~ preserve

        conn.execute("UPDATE chunks SET text = 'eigenvalues of symmetric matrices'")
        conn.commit()
        assert _fts_hits(conn, "preserve") == 0
        assert _fts_hits(conn, "eigenvalue") == 1

        conn.execute("DELETE FROM courses WHERE course_id = ?", (course_id,))
        conn.commit()
        for table in ("sources", "locators", "chunks"):
            count = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            assert count["n"] == 0
        assert _fts_hits(conn, "eigenvalue") == 0


def test_timestamps_round_trip_and_sort_lexicographically() -> None:
    """SQL defaults and Python-written timestamps share one fixed-width
    format, so string comparison in SQL is time comparison."""
    early = datetime(2030, 1, 1, 12, 0, 0, 5, tzinfo=UTC)
    late = early + timedelta(microseconds=1)
    assert format_timestamp(early) < format_timestamp(late)
    assert len(format_timestamp(early)) == len(format_timestamp(late)) == 27
    with connection() as conn:
        course_id = _course(conn)
        conn.execute(
            "UPDATE courses SET deleted_at = ?, purge_after = ? WHERE course_id = ?",
            (early, late, course_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT created_at, deleted_at, purge_after, "
            "purge_after > deleted_at AS ordered, length(created_at) AS width "
            "FROM courses"
        ).fetchone()
    assert row["deleted_at"] == early and row["purge_after"] == late
    assert row["ordered"] == 1
    assert row["width"] == 27
    assert row["created_at"].tzinfo is not None


def test_trash_columns_are_set_together() -> None:
    with connection() as conn:
        course_id = _course(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE courses SET deleted_at = ? WHERE course_id = ?",
                (datetime.now(UTC), course_id),
            )


def test_json_columns_reject_invalid_json() -> None:
    with connection() as conn:
        course_id = _course(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO concepts (concept_id, course_id, name, definition,"
                " synonyms) VALUES (?, ?, 'n', 'd', 'not json')",
                (uuid4(), course_id),
            )
        conn.execute(
            "INSERT INTO concepts (concept_id, course_id, name, definition, synonyms)"
            " VALUES (?, ?, 'n', 'd', '[\"alias\"]')",
            (uuid4(), course_id),
        )
        row = conn.execute("SELECT synonyms FROM concepts").fetchone()
    assert row["synonyms"] == ["alias"]


def test_same_file_twice_in_one_course_is_rejected() -> None:
    insert = (
        "INSERT INTO sources (source_id, course_id, filename, mime_type,"
        " source_type, file_hash) VALUES (?, ?, ?, 'text/plain', 'notes', 'abc')"
    )
    with connection() as conn:
        course_id = _course(conn)
        other_course = _course(conn, "Other")
        conn.execute(insert, (uuid4(), course_id, "first.txt"))
        # The same bytes in a different course are fine.
        conn.execute(insert, (uuid4(), other_course, "first.txt"))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, (uuid4(), course_id, "renamed-copy.txt"))
