import os
import shutil
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from src.backend.common import (
    course_memory,
    courses_repo,
    maintenance,
    storage,
    usage_repo,
)
from src.backend.common.db import connection


def _course(name: str = "Course") -> UUID:
    return courses_repo.create_course(name).course_id


def _source(
    course_id: UUID,
    filename: str = "f.txt",
    *,
    file_hash: str | None = None,
) -> UUID:
    source_id = uuid4()
    with connection() as conn:
        conn.execute(
            "INSERT INTO sources (source_id, course_id, filename, mime_type, "
            "source_type, size_bytes, file_hash) "
            "VALUES (?, ?, ?, 'text/plain', 'notes', 7, ?)",
            (source_id, course_id, filename, file_hash),
        )
        conn.commit()
    storage.write_stored(course_id, source_id, b"content")
    return source_id


def _age(path: os.PathLike[str]) -> None:
    os.utime(path, (0, 0))


# --- create / trash / restore / purge --------------------------------------


def test_deleted_course_leaves_list_and_can_be_restored() -> None:
    course_id = _course("Linear Algebra")
    trashed = courses_repo.move_to_trash(course_id)
    assert trashed.deleted_at is not None and trashed.purge_after is not None
    assert trashed.purge_after - trashed.deleted_at == timedelta(days=30)
    assert courses_repo.list_courses() == []
    assert courses_repo.get_course(course_id) is None
    assert [c.course_id for c in courses_repo.list_trash()] == [course_id]

    restored = courses_repo.restore_from_trash(course_id)
    assert not restored.in_trash
    assert [c.course_id for c in courses_repo.list_courses()] == [course_id]
    assert courses_repo.list_trash() == []


def test_trash_and_restore_reject_wrong_state() -> None:
    course_id = _course()
    with pytest.raises(courses_repo.UnknownCourseError):
        courses_repo.restore_from_trash(course_id)
    courses_repo.move_to_trash(course_id)
    with pytest.raises(courses_repo.UnknownCourseError):
        courses_repo.move_to_trash(course_id)
    with pytest.raises(courses_repo.UnknownCourseError):
        courses_repo.move_to_trash(uuid4())


def test_active_course_cannot_be_purged_directly() -> None:
    course_id = _course()
    assert courses_repo.purge_course(course_id) is False
    assert courses_repo.get_course(course_id) is not None


def test_purge_due_respects_retention() -> None:
    kept = _course("Recent")
    due = _course("Old")
    deleted_at = datetime(2030, 1, 1, tzinfo=UTC)
    courses_repo.move_to_trash(due, now=deleted_at)
    courses_repo.move_to_trash(kept, now=deleted_at + timedelta(days=20))

    assert courses_repo.purge_due(now=deleted_at + timedelta(days=29)) == []
    purged = courses_repo.purge_due(now=deleted_at + timedelta(days=31))
    assert purged == [due]
    assert courses_repo.get_any_course(due) is None
    assert courses_repo.get_any_course(kept) is not None


def test_purge_removes_every_derived_row_and_the_files() -> None:
    """The cascade is the purge: build a row in every table hanging off a
    course, purge, and require that nothing referencing it survives except
    the two deliberate survivors (the usage ledger keeps its rows with
    course_id nulled; the course-memory keepsake has no FK at all)."""
    course_id = _course("Everything")
    source_id = _source(course_id, "lecture.pdf", file_hash="a" * 64)
    locator_id, chunk_id = uuid4(), uuid4()
    concept_a, concept_b = uuid4(), uuid4()
    memory_id, toc_id, run_id = uuid4(), uuid4(), uuid4()
    with connection() as conn:
        conn.execute(
            "INSERT INTO locators (locator_id, source_id, locator_type, start, label)"
            " VALUES (?, ?, 'page', '1', 'page 1')",
            (locator_id, source_id),
        )
        conn.execute(
            "INSERT INTO chunks (chunk_id, source_id, locator_id, chunk_index, text)"
            " VALUES (?, ?, ?, 0, 'eigenvalues')",
            (chunk_id, source_id, locator_id),
        )
        conn.execute(
            "INSERT INTO chunk_locators (chunk_id, locator_id) VALUES (?, ?)",
            (chunk_id, locator_id),
        )
        conn.execute(
            "INSERT INTO chunk_embeddings (chunk_id, model, dimension, embedding)"
            " VALUES (?, 'm', 2, ?)",
            (chunk_id, np.zeros(2, dtype="<f4").tobytes()),
        )
        conn.execute(
            "INSERT INTO ingestion_runs (run_id, source_id, pipeline_version)"
            " VALUES (?, ?, '1')",
            (run_id, source_id),
        )
        conn.execute(
            "INSERT INTO ingestion_stage_runs (stage_run_id, run_id, stage,"
            " position, handler_version) VALUES (?, ?, 'extract_text', 0, '1')",
            (uuid4(), run_id),
        )
        conn.execute(
            "INSERT INTO pending_ingestion (source_id, course_id, reason)"
            " VALUES (?, ?, 'x')",
            (source_id, course_id),
        )
        conn.execute(
            "INSERT INTO ingestion_history (history_id, source_id, course_id,"
            " reason, queued_at) VALUES (?, ?, ?, 'x', ?)",
            (uuid4(), source_id, course_id, datetime.now(UTC)),
        )
        for concept in (concept_a, concept_b):
            conn.execute(
                "INSERT INTO concepts (concept_id, course_id, name, definition)"
                " VALUES (?, ?, ?, 'd')",
                (concept, course_id, f"c{concept}"),
            )
        conn.execute(
            "INSERT INTO dependencies (dep_id, prereq_id, dependent_id)"
            " VALUES (?, ?, ?)",
            (uuid4(), concept_a, concept_b),
        )
        conn.execute(
            "INSERT INTO memory_objects (memory_id, concept_id, source_id, kind,"
            " content) VALUES (?, ?, ?, 'concept', 'x')",
            (memory_id, concept_a, source_id),
        )
        conn.execute(
            "INSERT INTO memory_object_evidence (evidence_id, memory_id, chunk_id)"
            " VALUES (?, ?, ?)",
            (uuid4(), memory_id, chunk_id),
        )
        conn.execute(
            "INSERT INTO tables_of_contents (toc_id, course_id, version)"
            " VALUES (?, ?, 1)",
            (toc_id, course_id),
        )
        conn.execute(
            "INSERT INTO toc_entries (entry_id, toc_id, source_id, locator_id,"
            " title, description) VALUES (?, ?, ?, ?, 'Eigen', 'values')",
            (uuid4(), toc_id, source_id, locator_id),
        )
        conn.execute(
            "INSERT INTO retrieval_traces (trace_id, course_id, query)"
            " VALUES (?, ?, 'q')",
            (uuid4(), course_id),
        )
        conn.commit()
    usage_repo.record(
        task="tutor_answer",
        provider="local",
        model="m",
        input_tokens=1,
        output_tokens=1,
        course_id=course_id,
    )

    courses_repo.move_to_trash(course_id)
    assert courses_repo.purge_course(course_id) is True

    with connection() as conn:
        tables = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
                " AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%'"
            ).fetchall()
        ]
        survivors = {
            table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in tables
        }
        ledger = conn.execute(
            "SELECT course_id, course_label FROM usage_ledger"
        ).fetchone()
        fts_rows = conn.execute("SELECT COUNT(*) AS n FROM chunks_fts").fetchone()["n"]
    from src.backend.common.migrate import MIGRATIONS_DIR

    migrations = len(list(MIGRATIONS_DIR.glob("*.sql")))
    expected = {
        "course_memories": 1,
        "usage_ledger": 1,
        "schema_migrations": migrations,
    }
    assert {t: n for t, n in survivors.items() if n} == expected
    assert ledger["course_id"] is None and ledger["course_label"] == "Everything"
    assert fts_rows == 0
    assert not (storage.storage_root() / str(course_id)).exists()


def test_purge_failure_is_isolated_per_course(monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = _course("First"), _course("Second")
    deleted_at = datetime(2030, 1, 1, tzinfo=UTC)
    courses_repo.move_to_trash(first, now=deleted_at)
    courses_repo.move_to_trash(second, now=deleted_at)
    real_purge = courses_repo.purge_course

    def flaky(course_id: UUID) -> bool:
        if course_id == first:
            raise RuntimeError("disk on fire")
        return real_purge(course_id)

    monkeypatch.setattr(courses_repo, "purge_course", flaky)
    purged = courses_repo.purge_due(now=deleted_at + timedelta(days=31))
    assert purged == [second]
    assert courses_repo.get_any_course(first) is not None


# --- course memory (decision 007) ----------------------------------------------


def test_purge_preserves_course_memory_keepsake() -> None:
    course_id = _course("Keepsake")
    _source(course_id, "syllabus.pdf")
    courses_repo.move_to_trash(course_id)
    courses_repo.purge_course(course_id)
    with connection() as conn:
        memory = conn.execute(
            "SELECT name, summary FROM course_memories WHERE course_id = ?",
            (course_id,),
        ).fetchone()
    assert memory is not None
    assert memory["name"] == "Keepsake"
    assert "syllabus.pdf" in memory["summary"]


def test_memory_budget_scales_sublinearly_and_caps() -> None:
    assert course_memory.target_tokens(1) == 800
    ten = course_memory.target_tokens(10)
    twenty = course_memory.target_tokens(20)
    assert ten < twenty < ten * 2
    assert course_memory.target_tokens(1000) == 5000


def test_memory_summary_keeps_evidence_within_tight_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verbose concepts must never truncate the evidence index away. The
    summary stays within its budget, at least one evidence entry (with an
    uncut sha256) survives, and concept names survive in key_concepts."""
    monkeypatch.setattr(course_memory, "target_tokens", lambda count: 1000)
    course_id = _course("Verbose")
    source_ids = [
        _source(course_id, f"notes-{i:02}.txt", file_hash=f"{i:064x}") for i in range(3)
    ]
    long_definition = "a very long course-specific definition " * 30
    with connection() as conn:
        for source_id in source_ids:
            locator_id = uuid4()
            conn.execute(
                "INSERT INTO locators (locator_id, source_id, locator_type, start,"
                " label) VALUES (?, ?, 'page', '1', 'page 1')",
                (locator_id, source_id),
            )
            conn.execute(
                "INSERT INTO chunks (chunk_id, source_id, locator_id, chunk_index,"
                " text) VALUES (?, ?, ?, 0, 'representative excerpt text')",
                (uuid4(), source_id, locator_id),
            )
        for i in range(40):
            conn.execute(
                "INSERT INTO concepts (concept_id, course_id, name, definition)"
                " VALUES (?, ?, ?, ?)",
                (uuid4(), course_id, f"Concept {i}", long_definition),
            )
        conn.commit()

    courses_repo.move_to_trash(course_id)

    with connection() as conn:
        memory = conn.execute(
            "SELECT summary, key_concepts, token_budget FROM course_memories"
            " WHERE course_id = ?",
            (course_id,),
        ).fetchone()
    summary = memory["summary"]
    assert len(summary) <= memory["token_budget"] * 4
    evidence = summary.split("Evidence snapshot:", 1)[1]
    assert "notes-00.txt" in evidence and "sha256=" in evidence
    for piece in evidence.split("- ")[1:]:
        assert not piece.rstrip().endswith("sha256=")
    assert "Concept 0" in memory["key_concepts"]


def test_course_memory_refresh_updates_updated_at_not_created_at() -> None:
    course_id = _course("Timestamps")
    with connection() as conn:
        first = conn.execute(
            "SELECT created_at, updated_at FROM course_memories WHERE course_id = ?",
            (course_id,),
        ).fetchone()
    courses_repo.rename_course(course_id, "Timestamps v2")
    with connection() as conn:
        second = conn.execute(
            "SELECT created_at, updated_at, name FROM course_memories"
            " WHERE course_id = ?",
            (course_id,),
        ).fetchone()
    assert second["created_at"] == first["created_at"]
    assert second["updated_at"] > first["updated_at"]
    assert second["name"] == "Timestamps v2"


# --- orphan sweep ---------------------------------------------------------------


def test_sweep_removes_orphan_course_directories_only() -> None:
    orphan = uuid4()
    survivor = _course("Sweep Survivor")
    keep_dir = storage.storage_root() / str(survivor)
    keep_dir.mkdir(parents=True, exist_ok=True)
    orphan_dir = storage.storage_root() / str(orphan)
    orphan_dir.mkdir(parents=True, exist_ok=True)
    stale = orphan_dir / f"{uuid4()}.bin"
    stale.write_bytes(b"old orphan")
    _age(stale)
    fresh = orphan_dir / f"{uuid4()}.bin"
    fresh.write_bytes(b"fresh orphan")
    foreign = storage.storage_root() / "operator-staging"
    foreign.mkdir(parents=True, exist_ok=True)

    assert orphan not in courses_repo.sweep_storage_orphans(min_age=timedelta(hours=1))
    assert orphan_dir.exists()
    _age(fresh)
    _age(orphan_dir)
    swept = courses_repo.sweep_storage_orphans(min_age=timedelta(hours=1))
    assert orphan in swept and survivor not in swept
    assert not orphan_dir.exists()
    assert keep_dir.exists() and foreign.exists()
    shutil.rmtree(foreign)


def test_sweep_removes_uncommitted_source_file_in_live_course_dir() -> None:
    """The crash-between-file-write-and-commit orphan: the course row
    exists, only the source row died with the transaction."""
    course_id = _course("Orphan Files")
    live = _source(course_id)
    ghost_path = storage.write_stored(course_id, uuid4(), b"orphan")

    courses_repo.sweep_storage_orphans(min_age=timedelta(hours=1))
    assert ghost_path.exists()

    _age(ghost_path)
    _age(storage.source_disk_path(course_id, live))
    courses_repo.sweep_storage_orphans(min_age=timedelta(hours=1))
    assert not ghost_path.exists()
    assert storage.source_disk_path(course_id, live).exists()


def test_sweep_leaves_fresh_orphan_dir_alone() -> None:
    """An in-flight upload writes its file BEFORE the row commits; the
    grace must protect a directory the database doesn't know yet."""
    target = uuid4()
    target_dir = storage.storage_root() / str(target)
    target_dir.mkdir(parents=True)
    fresh = target_dir / f"{uuid4()}.bin"
    fresh.write_bytes(b"upload in flight")
    assert target not in courses_repo.sweep_storage_orphans(min_age=timedelta(hours=1))
    assert fresh.exists()
    _age(fresh)
    _age(target_dir)
    courses_repo.sweep_storage_orphans(min_age=timedelta(hours=1))
    assert not target_dir.exists()


def test_sweep_removes_interrupted_staging_files_but_keeps_fresh_ones() -> None:
    course_id = _course("Staging Sweep")
    live = _source(course_id)
    course_dir = storage.storage_root() / str(course_id)
    stale = course_dir / f".{uuid4()}-ab12cd3e.tmp"
    stale.write_bytes(b"interrupted staging write")
    _age(stale)
    fresh = course_dir / f".{uuid4()}-ff00ff00.tmp"
    fresh.write_bytes(b"write in progress")

    courses_repo.sweep_storage_orphans(min_age=timedelta(hours=1))
    assert not stale.exists()
    assert fresh.exists()
    assert storage.source_disk_path(course_id, live).exists()


# --- maintenance loop -------------------------------------------------------------


def test_maintenance_pass_purges_due_trash_and_sweeps() -> None:
    course_id = _course("Old")
    courses_repo.move_to_trash(course_id, now=datetime(2020, 1, 1, tzinfo=UTC))
    aged_orphan = storage.storage_root() / str(uuid4())
    aged_orphan.mkdir(parents=True)
    _age(aged_orphan)

    purged, swept = maintenance.run_once()
    assert (purged, swept) == (1, 1)
    assert courses_repo.get_any_course(course_id) is None


def test_app_lifespan_migrates_and_serves_api() -> None:
    from src.backend.main import create_app

    with TestClient(create_app()) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/api/courses").json() == []
