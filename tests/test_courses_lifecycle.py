import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from src.backend.common import (
    courses_lifecycle,
    courses_repo,
    memory_bank,
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


def _source(course_id: UUID, owner_id: UUID, filename: str = "f.txt") -> UUID:
    object_id = _source_object(course_id, owner_id)
    with connection() as conn:
        source_id = conn.execute(
            "INSERT INTO sources "
            "(object_id, uploaded_by_user_id, course_id, filename, mime_type, "
            "source_type, size_bytes) "
            "VALUES (%s, %s, %s, %s, 'text/plain', 'notes', 7) "
            "RETURNING source_id",
            (object_id, owner_id, course_id, filename),
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
        assert {row[0] for row in memories} == {owner.user_id, learner.user_id}
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
        ).fetchone()[0] == 0
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
    assert memory_bank.target_tokens(1, UserTier.FREE) == 800
    assert memory_bank.target_tokens(10, UserTier.FREE) == 1000
    ten_paid = memory_bank.target_tokens(10, UserTier.PAID)
    twenty_paid = memory_bank.target_tokens(20, UserTier.PAID)
    assert ten_paid < twenty_paid < ten_paid * 2
    assert memory_bank.target_tokens(100, UserTier.PAID) == 5000


def test_expired_running_cleanup_lease_is_reclaimed() -> None:
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

    assert courses_lifecycle.process_cleanup_jobs() == 1
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


def test_copy_drops_cross_course_dependencies() -> None:
    owner = _user("Dep Owner")
    course = _course(owner.user_id, "Dependencies")
    other = _course(owner.user_id, "Other Course")
    with connection() as conn:
        dep_id = conn.execute(
            "INSERT INTO concepts (course_id, name, definition) "
            "VALUES (%s, 'In-course', 'kept') RETURNING concept_id",
            (course.course_id,),
        ).fetchone()[0]
        foreign_id = conn.execute(
            "INSERT INTO concepts (course_id, name, definition) "
            "VALUES (%s, 'Foreign', 'another course') RETURNING concept_id",
            (other.course_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO dependencies (prereq_id, dependent_id, prereq_kind, "
            "external_ref) VALUES (%s, %s, 'in_course', NULL)",
            (foreign_id, dep_id),
        )
        conn.execute(
            "INSERT INTO dependencies (prereq_id, dependent_id) "
            "VALUES (NULL, %s)",
            (dep_id,),
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
        copied_deps = conn.execute(
            "SELECT COUNT(*) FROM dependencies AS d "
            "JOIN concepts AS c ON c.concept_id = d.dependent_id "
            "WHERE c.course_id = %s",
            (copied.course_id,),
        ).fetchone()[0]
        assert copied_deps == 1
        null_prereq = conn.execute(
            "SELECT COUNT(*) FROM dependencies AS d "
            "JOIN concepts AS c ON c.concept_id = d.dependent_id "
            "WHERE c.course_id = %s AND d.prereq_id IS NULL",
            (copied.course_id,),
        ).fetchone()[0]
        assert null_prereq == 1


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


def test_purge_removes_distilled_memory_bank_entries() -> None:
    """Nothing survives purge: the memory bank is written at archive time but
    destroyed when the archive expires."""
    owner = _user("Memory Purge")
    course = _course(owner.user_id, "Purged Memory")
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
        assert post == 0


def test_purge_block_covers_every_fk_referencing_table() -> None:
    """Mechanical guard for the hand-ordered purge block: derive, from the
    live schema, every table whose rows can reference the course subtree via
    a foreign key, and require the purge block to mention it. A future
    migration that adds a referencing table without a purge statement fails
    here instead of wedging production purges."""
    from src.backend.common.queries import get as get_query

    block = get_query("course_deletion", "delete_course_subtree")

    with connection() as conn:
        referencing = {
            row[0]
            for row in conn.execute(
                """
                SELECT DISTINCT conrelid::regclass::text
                FROM pg_constraint
                WHERE contype = 'f'
                  AND conrelid::regclass::text LIKE 'public.%'
                  AND confrelid::regclass::text LIKE 'public.%'
                  AND connamespace = 'public'::regnamespace
                """
            ).fetchall()
        }

    block_tables = {
        word.lower()
        for word in block.replace("\n", " ").split()
        if word.lower().startswith("delete from")
    }
    block_tables = {
        name.split(" AS ")[0].split(" as ")[0]
        for name in (
            line.split("DELETE FROM", 1)[1].strip()
            for line in block.splitlines()
            if "DELETE FROM" in line
        )
    }

    # Tables the purge deliberately does NOT touch, with the reason:
    # course_memories is deleted via the block; course_archive_access rows
    # cascade from courses; storage_cleanup_jobs is keyed by enqueue, not FK.
    excluded = {
        "course_archive_access",
        "course_memories",
        "storage_cleanup_jobs",
        "course_memories_user_course",
    }

    missing = sorted(
        table
        for table in referencing
        if table.startswith("public.")
        and table.replace("public.", "") not in excluded
        and table.replace("public.", "") not in block_tables
    )
    assert missing == [], (
        "purge block does not mention tables that can reference the "
        f"course subtree via FK: {missing}"
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
