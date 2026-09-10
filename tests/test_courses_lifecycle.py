import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from psycopg import errors as psycopg_errors
from psycopg.rows import dict_row
from src.backend.common import (
    archive_maintenance,
    course_memory,
    courses_lifecycle,
    courses_repo,
    enrollments_repo,
    storage,
    users_repo,
)
from src.backend.common.auth import hash_password
from src.backend.common.db import connection
from src.backend.common.schemas.base import CourseVisibility, UserTier
from src.backend.common.tiers import load_tier_policies


def _user(name: str):
    return users_repo.create(
        name, f"{uuid4().hex}@test.invalid", hash_password("long-password")
    )


def _course(owner_id: UUID, name: str, visibility: str = "private"):
    return courses_repo.create_course(owner_id, name, CourseVisibility(visibility))


@pytest.fixture(autouse=True)
def _sandbox(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(
        "src.backend.common.storage.get_settings",
        lambda: type("S", (), {"storage_root": str(tmp_path)})(),
    )
    return tmp_path


def _source_object(course_id: UUID, owner_id: UUID) -> UUID:
    with connection() as conn:
        object_id = conn.execute(
            "INSERT INTO course_objects "
            "(course_id, created_by_user_id, kind, content_type, content, "
            "access_scope) VALUES (%s, %s, 'source', 'text/plain', '{}', "
            "'enrolled') RETURNING object_id",
            (course_id, owner_id),
        ).fetchone()[0]
        conn.commit()
    return object_id


def _source(
    course_id: UUID,
    owner_id: UUID,
    filename: str = "f.txt",
    *,
    file_hash: str | None = None,
) -> UUID:
    object_id = _source_object(course_id, owner_id)
    with connection() as conn:
        source_id = conn.execute(
            "INSERT INTO sources "
            "(object_id, uploaded_by_user_id, course_id, filename, mime_type, "
            "source_type, size_bytes, file_hash) "
            "VALUES (%s, %s, %s, %s, 'text/plain', 'notes', 7, %s) "
            "RETURNING source_id",
            (object_id, owner_id, course_id, filename, file_hash),
        ).fetchone()[0]
        conn.commit()
    storage.write_stored(course_id, source_id, b"content")
    return source_id


def test_delete_archives_for_90_days_then_purges_full_course() -> None:
    owner = _user("Deleter")
    learner = _user("Learner")
    course = _course(owner.user_id, "Deletion Test")
    source_id = _source(course.course_id, owner.user_id)
    with connection() as conn:
        conn.execute(
            "INSERT INTO study_periods (course_id, label, start_date, end_date) "
            "VALUES (%s, 'Week 1', CURRENT_DATE, CURRENT_DATE)",
            (course.course_id,),
        )
        conn.execute(
            "INSERT INTO course_enrollments "
            "(course_id, user_id, enrollment_source, invited_by_user_id) "
            "VALUES (%s, %s, 'invitation', %s)",
            (course.course_id, learner.user_id, owner.user_id),
        )
        conn.execute(
            "INSERT INTO citation_snapshots "
            "(user_id, course_id, source_id, source_name) "
            "VALUES (%s, %s, %s, 'f.txt')",
            (learner.user_id, course.course_id, source_id),
        )
        conn.execute(
            "INSERT INTO user_artifacts "
            "(user_id, source_course_id, source_course_label, kind, "
            "content_type, content) "
            "VALUES (%s, %s, 'Deletion Test', 'guide', "
            "'application/json', '{}')",
            (learner.user_id, course.course_id),
        )
        conn.commit()

    archived_at = datetime(2030, 1, 1, tzinfo=UTC)
    purge_after = courses_lifecycle.delete_course(
        course.course_id, now=archived_at
    )

    assert purge_after == archived_at + timedelta(days=90)
    assert storage.source_disk_path(course.course_id, source_id).exists()
    with connection() as conn:
        state = conn.execute(
            "SELECT lifecycle_status, purge_after FROM courses WHERE course_id = %s",
            (course.course_id,),
        ).fetchone()
        assert state == ("archived", purge_after)
        assert conn.execute(
            "SELECT COUNT(*) FROM sources WHERE course_id = %s",
            (course.course_id,),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM course_archive_access WHERE course_id = %s",
            (course.course_id,),
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM citation_snapshots WHERE course_id = %s",
            (course.course_id,),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM user_artifacts WHERE source_course_id = %s",
            (course.course_id,),
        ).fetchone()[0] == 1
        memories = conn.execute(
            "SELECT user_id, course_ref, summary FROM course_memories "
            "WHERE course_id = %s ORDER BY user_id",
            (course.course_id,),
        ).fetchall()
        # Course memory is owner-only (ruling 2026-09-10): the learner gets
        # archive access, but no distilled course-memory record.
        assert {row[0] for row in memories} == {owner.user_id}
        assert all(row[1] == str(course.course_id) for row in memories)
        assert all("f.txt" in row[2] for row in memories)

    assert courses_lifecycle.purge_expired_archives(now=purge_after) == [
        course.course_id
    ]
    with connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM courses WHERE course_id = %s",
            (course.course_id,),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM sources WHERE course_id = %s",
            (course.course_id,),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM course_memories WHERE course_id = %s",
            (course.course_id,),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM citation_snapshots WHERE course_id = %s",
            (course.course_id,),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM user_artifacts WHERE source_course_id = %s",
            (course.course_id,),
        ).fetchone()[0] == 0
    assert storage.source_disk_path(course.course_id, source_id).exists()
    assert courses_lifecycle.process_cleanup_jobs() == 1
    assert not storage.source_disk_path(course.course_id, source_id).exists()


def test_delete_missing_course_raises() -> None:
    with pytest.raises(courses_lifecycle.UnknownCourseError):
        courses_lifecycle.delete_course(uuid4())


def test_archived_memory_records_concepts_and_tier_budget() -> None:
    owner = _user("Concept Owner")
    course = _course(owner.user_id, "Concepts")
    with connection() as conn:
        conn.execute(
            "INSERT INTO concepts (course_id, name, definition) "
            "VALUES (%s, 'Factorization', 'the lemma')",
            (course.course_id,),
        )
        conn.commit()
    courses_lifecycle.delete_course(course.course_id)
    with connection() as conn:
        memory = conn.execute(
            "SELECT key_concepts, token_budget, summary_version "
            "FROM course_memories WHERE course_id = %s",
            (course.course_id,),
        ).fetchone()
    assert memory is not None
    assert "Factorization" in memory[0]
    assert memory[1] <= 1000
    assert memory[2] == "deterministic-v1"


def test_purge_handles_grounded_responses_and_mastery() -> None:
    owner = _user("Grounded Owner")
    course = _course(owner.user_id, "Grounded")
    with connection() as conn:
        concept_id = conn.execute(
            "INSERT INTO concepts (course_id, name, definition) "
            "VALUES (%s, 'Evidence', 'grounded support') RETURNING concept_id",
            (course.course_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO concept_mastery (user_id, concept_id) VALUES (%s, %s)",
            (owner.user_id, concept_id),
        )
        conversation_id = conn.execute(
            "INSERT INTO conversations (user_id, course_id, title) "
            "VALUES (%s, %s, 'Grounded') RETURNING conversation_id",
            (owner.user_id, course.course_id),
        ).fetchone()[0]
        trace_id = conn.execute(
            "INSERT INTO retrieval_traces "
            "(user_id, course_id, conversation_id, query) "
            "VALUES (%s, %s, %s, 'why') RETURNING trace_id",
            (owner.user_id, course.course_id, conversation_id),
        ).fetchone()[0]
        response_id = conn.execute(
            "INSERT INTO responses (conversation_id, trace_id, content) "
            "VALUES (%s, %s, 'because') RETURNING response_id",
            (conversation_id, trace_id),
        ).fetchone()[0]
        claim_id = conn.execute(
            "INSERT INTO claims (response_id, claim_type, text) "
            "VALUES (%s, 'factual', 'claim') RETURNING claim_id",
            (response_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO citations (claim_id, target_type, target_id, trace_id) "
            "VALUES (%s, 'concept', %s, %s)",
            (claim_id, concept_id, trace_id),
        )
        conn.commit()

    archived_at = datetime(2030, 1, 1, tzinfo=UTC)
    purge_after = courses_lifecycle.delete_course(
        course.course_id, now=archived_at
    )
    courses_lifecycle.purge_expired_archives(now=purge_after)

    with connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM courses WHERE course_id = %s",
            (course.course_id,),
        ).fetchone()[0] == 0


def test_purge_rolls_back_archive_and_cleanup_job_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _user("Rollback Owner")
    course = _course(owner.user_id, "Rollback")
    purge_after = courses_lifecycle.delete_course(
        course.course_id, now=datetime(2030, 1, 1, tzinfo=UTC)
    )

    def fail_delete(*args: object, **kwargs: object) -> None:
        raise RuntimeError("delete failed")

    monkeypatch.setattr(courses_lifecycle, "_delete_subtree", fail_delete)
    assert courses_lifecycle.purge_expired_archives(now=purge_after) == []

    with connection() as conn:
        assert conn.execute(
            "SELECT lifecycle_status FROM courses WHERE course_id = %s",
            (course.course_id,),
        ).fetchone()[0] == "archived"
        assert conn.execute(
            "SELECT COUNT(*) FROM storage_cleanup_jobs WHERE course_id = %s",
            (course.course_id,),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM course_memories WHERE course_id = %s",
            (course.course_id,),
        ).fetchone()[0] == 1


def test_memory_budget_scales_sublinearly_and_caps_by_tier() -> None:
    assert course_memory.target_tokens(1, UserTier.FREE) == 800
    assert course_memory.target_tokens(10, UserTier.FREE) == 1000
    ten_paid = course_memory.target_tokens(10, UserTier.PAID)
    twenty_paid = course_memory.target_tokens(20, UserTier.PAID)
    assert ten_paid < twenty_paid < ten_paid * 2
    assert course_memory.target_tokens(100, UserTier.PAID) == 5000


def test_memory_summary_keeps_evidence_within_tight_budget() -> None:
    """Plan phase 1.4: verbose concepts must never truncate the evidence
    index away. The summary stays within its budget, at least one evidence
    entry (with an uncut sha256) survives, and concept information survives
    in the bounded key_concepts record."""
    owner = _user("Verbose Owner")
    course = _course(owner.user_id, "Verbose")
    source_ids = [
        _source(
            course.course_id,
            owner.user_id,
            f"notes-{i:02}.txt",
            file_hash=f"{i:064x}",
        )
        for i in range(3)
    ]
    long_definition = "a very long course-specific definition " * 30
    concept_names = [f"Concept {i}" for i in range(40)]
    with connection() as conn:
        for source_id in source_ids:
            locator_id = conn.execute(
                "INSERT INTO locators (source_id, locator_type, start, label) "
                "VALUES (%s, 'page', '1', 'page 1') RETURNING locator_id",
                (source_id,),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO chunks (source_id, locator_id, chunk_index, text) "
                "VALUES (%s, %s, 0, %s)",
                (source_id, locator_id, "representative excerpt text"),
            )
        for name in concept_names:
            conn.execute(
                "INSERT INTO concepts (course_id, name, definition) "
                "VALUES (%s, %s, %s)",
                (course.course_id, name, long_definition),
            )
        conn.commit()

    archived_at = datetime(2030, 1, 1, tzinfo=UTC)
    courses_lifecycle.delete_course(course.course_id, now=archived_at)

    with connection() as conn:
        memory = conn.execute(
            "SELECT summary, key_concepts, token_budget "
            "FROM course_memories WHERE course_id = %s",
            (course.course_id,),
        ).fetchone()
    assert memory is not None
    summary: str = memory[0]
    key_concepts: list[str] = memory[1]
    token_budget: int = memory[2]

    budget_chars = token_budget * 4
    assert len(summary) <= budget_chars, (
        f"summary {len(summary)} exceeds token budget {budget_chars}"
    )
    assert "Evidence snapshot:" in summary
    evidence_section = summary.split("Evidence snapshot:", 1)[1]
    assert "notes-00.txt" in evidence_section
    assert "sha256=" in evidence_section
    for piece in evidence_section.split("- ")[1:]:
        assert not piece.rstrip().endswith("sha256=")
        assert "sha256=" not in piece or piece.count("sha256=") == 1
    assert key_concepts, "concept information must survive the budget"
    assert "Concept 0" in key_concepts


def test_expired_running_cleanup_lease_is_reclaimed() -> None:
    """Reclaim ownership lives in run_once()/the maintenance loop; the
    processing loop itself never reclaims (double reclaim in one pass could
    dead-end a job on stale attempt counts)."""
    course_id = uuid4()
    with connection() as conn:
        job_id = conn.execute(
            "INSERT INTO storage_cleanup_jobs "
            "(course_id, status, attempt_count, next_attempt_at) "
            "VALUES (%s, 'running', 2, now() - interval '1 minute') "
            "RETURNING job_id",
            (course_id,),
        ).fetchone()[0]
        conn.commit()

    assert courses_lifecycle.process_cleanup_jobs() == 0
    assert archive_maintenance.run_once()[0] == 1
    with connection() as conn:
        state = conn.execute(
            "SELECT status, attempt_count, completed_at "
            "FROM storage_cleanup_jobs WHERE job_id = %s",
            (job_id,),
        ).fetchone()
    assert state[0] == "succeeded"
    assert state[1] == 3
    assert state[2] is not None


def test_expired_lease_past_max_attempts_goes_dead_and_is_not_retried() -> None:
    course_id = uuid4()
    with connection() as conn:
        job_id = conn.execute(
            "INSERT INTO storage_cleanup_jobs "
            "(course_id, status, attempt_count, next_attempt_at) "
            "VALUES (%s, 'running', 5, now() - interval '1 minute') "
            "RETURNING job_id",
            (course_id,),
        ).fetchone()[0]
        conn.commit()

    reclaimed = courses_lifecycle.reclaim_expired_cleanup_leases()
    assert reclaimed == 1
    with connection() as conn:
        state = conn.execute(
            "SELECT status, attempt_count, error_message "
            "FROM storage_cleanup_jobs WHERE job_id = %s",
            (job_id,),
        ).fetchone()
    assert state[0] == "dead"
    assert state[1] == 5
    assert state[2] is not None
    assert courses_lifecycle.process_cleanup_jobs() == 0


def test_failed_cleanup_marks_dead_after_max_attempts() -> None:
    course_id = uuid4()
    with connection() as conn:
        job_id = conn.execute(
            "INSERT INTO storage_cleanup_jobs "
            "(course_id, status, attempt_count, next_attempt_at) "
            "VALUES (%s, 'failed', 4, now()) RETURNING job_id",
            (course_id,),
        ).fetchone()[0]
        conn.commit()

    original = courses_lifecycle.storage.remove_course_directory

    def fail_remove(course: object) -> None:
        raise OSError("directory wedged")

    import src.backend.common.courses_lifecycle as lifecycle_module

    lifecycle_module.storage.remove_course_directory = fail_remove
    try:
        assert courses_lifecycle.process_cleanup_jobs() == 0
    finally:
        lifecycle_module.storage.remove_course_directory = original
    with connection() as conn:
        state = conn.execute(
            "SELECT status, attempt_count, error_message "
            "FROM storage_cleanup_jobs WHERE job_id = %s",
            (job_id,),
        ).fetchone()
    assert state[0] == "dead"
    assert state[1] == 5
    assert "wedged" in state[2]


def test_dead_cleanup_job_logs_operator_signal(caplog) -> None:
    """Plan phase 1.2: a job that becomes dead must emit an error log with
    job_id, course_id, attempt count, and the final error — never silently
    abandon data."""
    import logging

    course_id = uuid4()
    with connection() as conn:
        job_id = conn.execute(
            "INSERT INTO storage_cleanup_jobs "
            "(course_id, status, attempt_count, next_attempt_at) "
            "VALUES (%s, 'failed', 5, now()) RETURNING job_id",
            (course_id,),
        ).fetchone()[0]
        conn.commit()

    original = courses_lifecycle.storage.remove_course_directory

    def fail_remove(course: object) -> None:
        raise OSError("disk unmounted")

    import src.backend.common.courses_lifecycle as lifecycle_module

    lifecycle_module.storage.remove_course_directory = fail_remove
    try:
        with caplog.at_level(
            logging.ERROR,
            logger="src.backend.common.courses_lifecycle",
        ):
            assert courses_lifecycle.process_cleanup_jobs() == 0
    finally:
        lifecycle_module.storage.remove_course_directory = original

    dead_logs = [r for r in caplog.records if "is now dead" in r.message]
    assert dead_logs, "a dead transition must log an operator signal"
    message = dead_logs[0].getMessage()
    assert str(job_id) in message
    assert str(course_id) in message
    assert "disk unmounted" in message
    assert dead_logs[0].levelno == logging.ERROR


def test_memory_bank_refresh_updates_updated_at_not_created_at() -> None:
    owner = _user("Timestamp Owner")
    course = _course(owner.user_id, "Timestamps")
    with connection() as conn:
        first = conn.execute(
            "SELECT created_at, updated_at FROM course_memories "
            "WHERE user_id = %s AND course_id = %s",
            (owner.user_id, course.course_id),
        ).fetchone()
    courses_repo.update_course(course.course_id, name="Timestamps v2")
    with connection() as conn:
        second = conn.execute(
            "SELECT created_at, updated_at FROM course_memories "
            "WHERE user_id = %s AND course_id = %s",
            (owner.user_id, course.course_id),
        ).fetchone()
    assert second[0] == first[0]
    assert second[1] > first[1]


def test_sweep_removes_orphan_course_directories_only() -> None:
    orphan = uuid4()
    survivor_owner = _user("Sweep Owner")
    survivor = _course(survivor_owner.user_id, "Sweep Survivor")
    keep_dir = storage.storage_root() / str(survivor.course_id)
    keep_dir.mkdir(parents=True, exist_ok=True)
    orphan_dir = storage.storage_root() / str(orphan)
    orphan_dir.mkdir(parents=True, exist_ok=True)
    stale = orphan_dir / f"{uuid4()}.bin"
    stale.write_bytes(b"old orphan")
    import os

    os.utime(stale, (0, 0))
    fresh = orphan_dir / f"{uuid4()}.bin"
    fresh.write_bytes(b"fresh orphan")
    foreign = storage.storage_root() / "operator-staging"
    foreign.mkdir(parents=True, exist_ok=True)

    swept = courses_lifecycle.sweep_storage_orphans(
        min_age=timedelta(hours=1)
    )
    assert orphan not in swept
    assert orphan_dir.exists()
    os.utime(fresh, (0, 0))
    os.utime(orphan_dir, (0, 0))
    swept = courses_lifecycle.sweep_storage_orphans(min_age=timedelta(hours=1))
    assert orphan in swept
    assert survivor.course_id not in swept
    assert not orphan_dir.exists()
    assert keep_dir.exists()
    assert foreign.exists()
    shutil.rmtree(foreign)


def test_sweep_removes_uncommitted_source_file_in_live_course_dir() -> None:
    """The crash-between-file-write-and-commit orphan: the course row EXISTS,
    only the source row died with the transaction. The directory-level sweep
    alone would never touch it."""
    owner = _user("Orphan File Owner")
    course = _course(owner.user_id, "Orphan Files")
    live = _source(course.course_id, owner.user_id)
    ghost = uuid4()
    ghost_path = storage.write_stored(course.course_id, ghost, b"orphan")

    courses_lifecycle.sweep_storage_orphans(
        min_age=timedelta(hours=1)
    )
    assert ghost_path.exists()
    assert storage.source_disk_path(course.course_id, live).exists()

    import os

    os.utime(ghost_path, (0, 0))
    os.utime(storage.source_disk_path(course.course_id, live), (0, 0))
    courses_lifecycle.sweep_storage_orphans(min_age=timedelta(hours=1))
    assert not ghost_path.exists()
    assert storage.source_disk_path(course.course_id, live).exists()


def test_sweep_leaves_fresh_orphan_dir_of_in_flight_copy_alone() -> None:
    """An in-flight restrict_public_course / copy_archived_course writes its
    target files BEFORE the course row commits. The dir-level sweep sees a
    directory with no courses row — the grace must protect it wholesale."""
    target = uuid4()
    target_dir = storage.storage_root() / str(target)
    target_dir.mkdir(parents=True)
    fresh = target_dir / f"{uuid4()}.bin"
    fresh.write_bytes(b"copy in flight")
    swept = courses_lifecycle.sweep_storage_orphans(
        min_age=timedelta(hours=1)
    )
    assert target not in swept
    assert fresh.exists()
    import os

    os.utime(fresh, (0, 0))
    os.utime(target_dir, (0, 0))
    swept = courses_lifecycle.sweep_storage_orphans(min_age=timedelta(hours=1))
    assert not target_dir.exists()


def test_sweep_removes_interrupted_staging_files() -> None:
    """Crash mid-atomic-write leaves .{source_id}-{rand}.tmp staging debris
    in a live course directory; the sweep clears it once it ages past grace."""
    owner = _user("Staging Sweep Owner")
    course = _course(owner.user_id, "Staging Sweep")
    live = _source(course.course_id, owner.user_id)
    staging = (
        storage.storage_root()
        / str(course.course_id)
        / f".{uuid4()}-ab12cd3e.tmp"
    )
    staging.write_bytes(b"interrupted staging write")
    import os

    os.utime(staging, (0, 0))

    courses_lifecycle.sweep_storage_orphans(min_age=timedelta(hours=1))
    assert not staging.exists()
    assert storage.source_disk_path(course.course_id, live).exists()


def test_sweep_keeps_fresh_staging_file_in_course_dir() -> None:
    owner = _user("Fresh Staging Owner")
    course = _course(owner.user_id, "Fresh Staging")
    _source(course.course_id, owner.user_id)
    staging = (
        storage.storage_root()
        / str(course.course_id)
        / f".{uuid4()}-ff00ff00.tmp"
    )
    staging.write_bytes(b"write in progress")
    courses_lifecycle.sweep_storage_orphans(min_age=timedelta(hours=1))
    assert staging.exists()


def test_copy_refuses_courses_with_uncopyable_file_backed_objects() -> None:
    owner = _user("File Owner")
    course = _course(owner.user_id, "File-backed")
    with connection() as conn:
        conn.execute(
            "INSERT INTO course_objects "
            "(course_id, created_by_user_id, kind, content_type, content_uri, "
            "access_scope) VALUES (%s, %s, 'artifact', 'application/pdf', "
            "'file://legacy/thing.pdf', 'enrolled')",
            (course.course_id, owner.user_id),
        )
        conn.commit()
    archived_at = datetime(2030, 1, 1, tzinfo=UTC)
    courses_lifecycle.delete_course(course.course_id, now=archived_at)

    with pytest.raises(courses_lifecycle.UncopyableCourseError):
        courses_lifecycle.copy_archived_course(
            course.course_id,
            owner.user_id,
            UserTier.FREE,
            load_tier_policies().policy_for(UserTier.FREE),
            now=archived_at + timedelta(days=1),
        )
    with connection() as conn:
        copies = conn.execute(
            "SELECT COUNT(*) FROM courses WHERE owner_user_id = %s "
            "AND lifecycle_status = 'active'",
            (owner.user_id,),
        ).fetchone()[0]
        assert copies == 0
        access = conn.execute(
            "SELECT 1 FROM course_archive_access "
            "WHERE course_id = %s AND user_id = %s",
            (course.course_id, owner.user_id),
        ).fetchone()
        assert access is not None


def test_copy_requeues_ingestion_and_skips_derived_memory() -> None:
    """Recommended copy strategy: raw sources are copied and enqueued for
    fresh ingestion; derived concepts/dependencies are not copied, so the
    copy never carries stale, ungrounded derived memory."""
    owner = _user("Reingest Owner")
    course = _course(owner.user_id, "Reingest")
    _source(course.course_id, owner.user_id, "keep.txt")
    with connection() as conn:
        concept_id = conn.execute(
            "INSERT INTO concepts (course_id, name, definition) "
            "VALUES (%s, 'Derived', 'from ingestion') RETURNING concept_id",
            (course.course_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO dependencies (prereq_id, dependent_id) "
            "VALUES (NULL, %s)",
            (concept_id,),
        )
        conn.commit()

    archived_at = datetime(2030, 1, 1, tzinfo=UTC)
    courses_lifecycle.delete_course(course.course_id, now=archived_at)
    copied = courses_lifecycle.copy_archived_course(
        course.course_id,
        owner.user_id,
        UserTier.FREE,
        load_tier_policies().policy_for(UserTier.FREE),
        now=archived_at + timedelta(days=1),
    )
    with connection() as conn:
        copied_sources = conn.execute(
            "SELECT source_id, status FROM sources WHERE course_id = %s",
            (copied.course_id,),
        ).fetchall()
        assert len(copied_sources) == 1
        assert copied_sources[0][1] == "uploaded"
        pending = conn.execute(
            "SELECT reason FROM pending_ingestion WHERE course_id = %s",
            (copied.course_id,),
        ).fetchall()
        assert len(pending) == 1
        assert pending[0][0] == f"copied_from_archive:{course.course_id}"
        copied_concepts = conn.execute(
            "SELECT COUNT(*) FROM concepts WHERE course_id = %s",
            (copied.course_id,),
        ).fetchone()[0]
        assert copied_concepts == 0
        copied_deps = conn.execute(
            "SELECT COUNT(*) FROM dependencies AS d "
            "JOIN concepts AS c ON c.concept_id = d.dependent_id "
            "WHERE c.course_id = %s",
            (copied.course_id,),
        ).fetchone()[0]
        assert copied_deps == 0
        # The archived original keeps its derived memory for the grace window
        original_concepts = conn.execute(
            "SELECT COUNT(*) FROM concepts WHERE course_id = %s",
            (course.course_id,),
        ).fetchone()[0]
        assert original_concepts == 1
        assert storage.source_disk_path(
            copied.course_id, copied_sources[0][0]
        ).exists()


def test_archive_can_be_copied_repeatedly_during_grace() -> None:
    """Copy-any-time policy: the grace window grants unlimited copies; no
    copy-once bookkeeping exists."""
    owner = _user("Repeat Copier")
    course = _course(owner.user_id, "Repeatable")
    archived_at = datetime(2030, 1, 1, tzinfo=UTC)
    courses_lifecycle.delete_course(course.course_id, now=archived_at)
    policy = load_tier_policies().policy_for(UserTier.FREE)

    first = courses_lifecycle.copy_archived_course(
        course.course_id,
        owner.user_id,
        UserTier.FREE,
        policy,
        now=archived_at + timedelta(days=1),
    )
    second = courses_lifecycle.copy_archived_course(
        course.course_id,
        owner.user_id,
        UserTier.FREE,
        policy,
        now=archived_at + timedelta(days=2),
        name="Second copy",
    )
    assert first.course_id != second.course_id
    with connection() as conn:
        copies = conn.execute(
            "SELECT COUNT(*) FROM courses WHERE owner_user_id = %s "
            "AND lifecycle_status = 'active'",
            (owner.user_id,),
        ).fetchone()[0]
        assert copies == 2


def test_copy_names_are_bounded_and_disambiguated() -> None:
    """Default copy names respect the 200-char create bound and never
    collide with a course the copier already owns."""
    owner = _user("Copy Namer")
    course = _course(owner.user_id, "x" * 250)
    archived_at = datetime(2030, 1, 1, tzinfo=UTC)
    courses_lifecycle.delete_course(course.course_id, now=archived_at)
    policy = load_tier_policies().policy_for(UserTier.PAID)

    first = courses_lifecycle.copy_archived_course(
        course.course_id, owner.user_id, UserTier.PAID, policy,
        now=archived_at + timedelta(days=1),
    )
    second = courses_lifecycle.copy_archived_course(
        course.course_id, owner.user_id, UserTier.PAID, policy,
        now=archived_at + timedelta(days=2),
    )
    third = courses_lifecycle.copy_archived_course(
        course.course_id, owner.user_id, UserTier.PAID, policy,
        now=archived_at + timedelta(days=3),
    )
    assert len(first.name) <= 200
    assert first.name.endswith(" (copy)")
    assert second.name.endswith(" (copy 2)")
    assert third.name.endswith(" (copy 3)")
    assert len({first.name, second.name, third.name}) == 3
    assert len(second.name) <= 200
    assert len(third.name) <= 200


def test_purge_preserves_memory_bank_entries() -> None:
    """Memory is user-owned: purge destroys the course's materials and
    archive, but the distilled memory written at archive time survives —
    the memory bank is the retention that outlives the course."""
    owner = _user("Memory Keeper")
    course = _course(owner.user_id, "Remembered")
    archived_at = datetime(2030, 1, 1, tzinfo=UTC)
    courses_lifecycle.delete_course(course.course_id, now=archived_at)
    with connection() as conn:
        pre = conn.execute(
            "SELECT COUNT(*) FROM course_memories WHERE course_id = %s",
            (course.course_id,),
        ).fetchone()[0]
        assert pre == 1
    courses_lifecycle.purge_expired_archives(
        now=archived_at + timedelta(days=91)
    )
    with connection() as conn:
        post = conn.execute(
            "SELECT COUNT(*) FROM course_memories WHERE course_id = %s",
            (course.course_id,),
        ).fetchone()[0]
        assert post == 1


def test_purge_block_covers_every_fk_referencing_table() -> None:
    """Mechanical guard for the hand-ordered purge block: derive the tables
    transitively entangled with a course row through NO ACTION foreign keys
    (the edges that would wedge a purge), and require the block to mention
    each one. Cascade/set-null edges and documented exclusions are fine —
    a NO ACTION edge is not. A future migration that adds one without a
    purge statement fails here instead of wedging production purges."""
    from src.backend.common.queries import get as get_query

    block = get_query("course_deletion", "delete_course_subtree")

    with connection() as conn:
        referencing = {
            row[0]
            for row in conn.execute(
                """
                WITH RECURSIVE subtree(tab) AS (
                    SELECT 'courses'::regclass
                    UNION
                    SELECT con.conrelid
                    FROM pg_constraint AS con
                    JOIN subtree ON con.confrelid = subtree.tab
                    WHERE con.contype = 'f'
                      AND con.confdeltype IN ('a', 'r')
                )
                SELECT DISTINCT con.conrelid::regclass::text
                FROM pg_constraint AS con
                JOIN subtree ON con.confrelid = subtree.tab
                WHERE con.contype = 'f'
                  AND con.confdeltype IN ('a', 'r')
                """
            ).fetchall()
        }

    block_tables = {
        line.split("DELETE FROM", 1)[1].strip().split()[0].strip(",;()")
        for line in block.splitlines()
        if "DELETE FROM" in line
    }

    # Tables the purge deliberately does NOT touch, with the reason:
    # course_memories is user-owned retention that outlives the course
    # (documented decision 2026-09-05). Everything else in the closure
    # either cascades from a row the block deletes or is deleted directly.
    excluded = {"course_memories", "course_memories_user_course"}

    missing = sorted(
        table
        for table in referencing
        if table not in excluded
        and table not in block_tables
    )
    assert missing == [], (
        "purge block does not mention tables that reference the course "
        f"subtree through a NO ACTION foreign key: {missing}"
    )


def test_failed_archive_copy_cleans_files_and_allows_retry(monkeypatch) -> None:
    """Mid-copy failure: the successor course row rolls back, its partially
    written directory is removed, and the archive stays copyable."""
    owner = _user("Retry Copier")
    course = _course(owner.user_id, "Retryable Copy")
    _source(course.course_id, owner.user_id)
    archived_at = datetime(2030, 1, 1, tzinfo=UTC)
    courses_lifecycle.delete_course(course.course_id, now=archived_at)

    dirs_before = {p.name for p in storage.storage_root().iterdir()}

    def explode(*args: object, **kwargs: object) -> Path:
        raise OSError("disk hiccup")

    real_copy_stored = storage.copy_stored
    monkeypatch.setattr(storage, "copy_stored", explode)
    with pytest.raises(OSError):
        courses_lifecycle.copy_archived_course(
            course.course_id,
            owner.user_id,
            UserTier.FREE,
            load_tier_policies().policy_for(UserTier.FREE),
            now=archived_at + timedelta(days=1),
        )
    assert {p.name for p in storage.storage_root().iterdir()} == dirs_before

    with connection() as conn:
        partial = conn.execute(
            "SELECT COUNT(*) FROM courses WHERE owner_user_id = %s "
            "AND lifecycle_status = 'active'",
            (owner.user_id,),
        ).fetchone()[0]
        assert partial == 0

    monkeypatch.setattr(storage, "copy_stored", real_copy_stored)
    copy = courses_lifecycle.copy_archived_course(
        course.course_id,
        owner.user_id,
        UserTier.FREE,
        load_tier_policies().policy_for(UserTier.FREE),
        now=archived_at + timedelta(days=2),
    )
    assert copy.lifecycle_status == "active"


def test_failed_restrict_cleans_files_and_leaves_course_public(monkeypatch) -> None:
    """A failed public->private restriction leaves the original public and
    active, removes the successor's partial directory, and the owner can
    retry the restriction afterwards."""
    owner = _user("Restrict Owner")
    course = _course(owner.user_id, "Restrictable", visibility="public")
    _source(course.course_id, owner.user_id)
    dirs_before = {p.name for p in storage.storage_root().iterdir()}

    def explode(*args: object, **kwargs: object) -> Path:
        raise OSError("disk hiccup")

    real_copy_stored = storage.copy_stored
    monkeypatch.setattr(storage, "copy_stored", explode)
    with pytest.raises(OSError):
        courses_lifecycle.restrict_public_course(
            course.course_id,
            owner.user_id,
            UserTier.FREE,
            load_tier_policies().policy_for(UserTier.FREE),
            CourseVisibility.PRIVATE,
        )
    assert {p.name for p in storage.storage_root().iterdir()} == dirs_before
    with connection() as conn:
        row = conn.execute(
            "SELECT lifecycle_status, visibility FROM courses "
            "WHERE course_id = %s",
            (course.course_id,),
        ).fetchone()
        assert row == ("active", "public")

    monkeypatch.setattr(storage, "copy_stored", real_copy_stored)
    courses_lifecycle.restrict_public_course(
        course.course_id,
        owner.user_id,
        UserTier.FREE,
        load_tier_policies().policy_for(UserTier.FREE),
        CourseVisibility.PRIVATE,
    )
    with connection() as conn:
        row = conn.execute(
            "SELECT lifecycle_status FROM courses WHERE course_id = %s",
            (course.course_id,),
        ).fetchone()
        assert row == ("archived",)


def test_purge_failure_is_isolated_per_course(monkeypatch) -> None:
    """One wedged purge rolls back only that course; the rest of the queue
    still purges, and the failed course remains archived for the next sweep."""
    blocker_owner = _user("Purge Blocker")
    blocker = _course(blocker_owner.user_id, "Blocked Purge")
    healthy_owner = _user("Purge Survivor")
    healthy = _course(healthy_owner.user_id, "Healthy Purge")
    archived_at = datetime(2030, 1, 1, tzinfo=UTC)
    courses_lifecycle.delete_course(blocker.course_id, now=archived_at)
    courses_lifecycle.delete_course(healthy.course_id, now=archived_at)

    real_delete = courses_lifecycle._delete_subtree

    def selective(cur, course_id, *args, **kwargs):
        if course_id == blocker.course_id:
            raise RuntimeError("simulated FK edge")
        real_delete(cur, course_id)

    monkeypatch.setattr(courses_lifecycle, "_delete_subtree", selective)
    purged = courses_lifecycle.purge_expired_archives(
        now=archived_at + timedelta(days=91)
    )
    monkeypatch.undo()
    assert purged == [healthy.course_id]

    with connection() as conn:
        assert conn.execute(
            "SELECT lifecycle_status FROM courses WHERE course_id = %s",
            (blocker.course_id,),
        ).fetchone()[0] == "archived"
        assert conn.execute(
            "SELECT COUNT(*) FROM courses WHERE course_id = %s",
            (healthy.course_id,),
        ).fetchone()[0] == 0

    assert courses_lifecycle.purge_expired_archives(
        now=archived_at + timedelta(days=91)
    ) == [blocker.course_id]


def test_restrict_refuses_uncopyable_course_and_stays_public() -> None:
    """A public course with file-backed non-source objects cannot be copied
    into a restricted successor; the guard fires before any mutation, so the
    original stays public and active."""
    owner = _user("Uncopyable Public")
    course = _course(owner.user_id, "Stuck Public", visibility="public")
    with connection() as conn:
        conn.execute(
            "INSERT INTO course_objects "
            "(course_id, created_by_user_id, kind, content_type, content_uri, "
            "access_scope) VALUES (%s, %s, 'artifact', 'application/pdf', "
            "'file://legacy/thing.pdf', 'enrolled')",
            (course.course_id, owner.user_id),
        )
        conn.commit()
    with pytest.raises(courses_lifecycle.UncopyableCourseError):
        courses_lifecycle.restrict_public_course(
            course.course_id,
            owner.user_id,
            UserTier.FREE,
            load_tier_policies().policy_for(UserTier.FREE),
            CourseVisibility.PRIVATE,
        )
    with connection() as conn:
        row = conn.execute(
            "SELECT lifecycle_status, visibility FROM courses "
            "WHERE course_id = %s",
            (course.course_id,),
        ).fetchone()
        assert row == ("active", "public")


def test_accept_invitation_cannot_race_course_archival() -> None:
    """Two-connection regression for the accept-vs-archival race. The
    enrollment policy trigger takes FOR SHARE on the courses row, which
    conflicts with delete_course's FOR UPDATE: an in-flight accept blocks
    archival until it commits, and an archival that lands first forces any
    later accept to fail the policy check. Either way, no learner ends up
    'active' on a course archived before they were snapshotted."""
    owner = _user("Race Owner")
    learner = _user("Race Learner")
    course = _course(owner.user_id, "Race Course")
    enrollments_repo.invite(course.course_id, learner.user_id, owner.user_id)

    # Connection A holds an open accept transaction: the trigger has taken
    # FOR SHARE on the course row but the transaction is not yet committed.
    conn_a = courses_lifecycle_db()
    conn_b = courses_lifecycle_db()
    try:
        accept_row = conn_a.cursor(row_factory=dict_row).execute(
            "UPDATE course_enrollments "
            "SET status = 'active', responded_at = now() "
            "WHERE course_id = %s AND user_id = %s AND status = 'invited' "
            "RETURNING enrollment_id",
            (course.course_id, learner.user_id),
        ).fetchone()
        assert accept_row is not None

        # Connection B attempts the same row lock delete_course takes.
        # NOWAIT proves the conflict exists: A's FOR SHARE is held, so B
        # cannot take FOR UPDATE. This is the serialization that makes the
        # trigger's lifecycle check atomic with archival.
        with pytest.raises(psycopg_errors.LockNotAvailable):
            conn_b.execute("SELECT 1").fetchone()
            conn_b.cursor(row_factory=dict_row).execute(
                "SELECT course_id FROM courses WHERE course_id = %s "
                "AND lifecycle_status = 'active' FOR UPDATE NOWAIT",
                (course.course_id,),
            ).fetchone()
        conn_b.rollback()

        # A commits; the archival then proceeds and snapshots the learner
        # as an active participant — they receive the archive access they
        # earned.
        conn_a.commit()
    finally:
        conn_a.close()
        conn_b.close()
    courses_lifecycle.delete_course(course.course_id)

    with connection() as conn:
        enrollment = conn.execute(
            "SELECT status FROM course_enrollments "
            "WHERE course_id = %s AND user_id = %s",
            (course.course_id, learner.user_id),
        ).fetchone()
        access = conn.execute(
            "SELECT 1 FROM course_archive_access "
            "WHERE course_id = %s AND user_id = %s",
            (course.course_id, learner.user_id),
        ).fetchone()
    assert enrollment[0] == "active"
    assert access is not None

    # The complementary interleaving: archival wins the race for a still
    # pending invitation; the later accept must fail the policy trigger.
    owner2 = _user("Race Owner 2")
    learner2 = _user("Race Learner 2")
    course2 = _course(owner2.user_id, "Race Course 2")
    enrollments_repo.invite(course2.course_id, learner2.user_id, owner2.user_id)
    courses_lifecycle.delete_course(course2.course_id)
    with pytest.raises(psycopg_errors.CheckViolation), connection() as conn:
        conn.execute(
            "UPDATE course_enrollments "
            "SET status = 'active', responded_at = now() "
            "WHERE course_id = %s AND user_id = %s AND status = 'invited'",
            (course2.course_id, learner2.user_id),
        )
        conn.commit()


def courses_lifecycle_db():
    from src.backend.common.db import connect

    return connect()
