from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from psycopg import Cursor, sql
from psycopg.rows import dict_row
from src.backend.common import budget, courses_repo, memory_bank, storage
from src.backend.common.db import connection
from src.backend.common.lifecycle_config import load_lifecycle_policy
from src.backend.common.queries import get
from src.backend.common.schemas.base import CourseVisibility, UserTier
from src.backend.common.schemas.identity import Course, StorageCleanupJob
from src.backend.common.tiers import TierPolicy

_ARCHIVE_FILE = "course_archives"
_DELETION_FILE = "course_deletion"
logger = logging.getLogger(__name__)


class UnknownCourseError(RuntimeError):
    def __init__(self, course_id: UUID) -> None:
        super().__init__(f"course not found: {course_id}")


class ArchiveAccessError(RuntimeError):
    pass


class CourseTransitionError(RuntimeError):
    pass


class UncopyableCourseError(RuntimeError):
    """The archived course contains course objects whose only payload is a
    content_uri into the old course's storage; copying would strand them."""


def _archive_locked_course(
    cur: Cursor[Any],
    course: dict[str, Any],
    archived_at: datetime,
    purge_after: datetime,
) -> None:
    course_id = course["course_id"]
    participants = cur.execute(
        get(_ARCHIVE_FILE, "archive_participants"), {"course_id": course_id}
    ).fetchall()
    participant_ids = [participant["user_id"] for participant in participants]
    memory_bank.upsert_for_users(cur, course_id, participant_ids)
    for user_id in participant_ids:
        cur.execute(
            get(_ARCHIVE_FILE, "grant_archive_access"),
            {
                "course_id": course_id,
                "user_id": user_id,
                "expires_at": purge_after,
            },
        )
    cur.execute(
        get(_ARCHIVE_FILE, "mark_archived"),
        {
            "course_id": course_id,
            "archived_at": archived_at,
            "purge_after": purge_after,
        },
    )


def _copy_course_contents(
    cur: Cursor[Any],
    source_course_id: UUID,
    target_course_id: UUID,
    target_owner_id: UUID,
) -> None:
    uncopyable_row = cur.execute(
        get(_ARCHIVE_FILE, "uncopyable_object_count"),
        {"course_id": source_course_id},
    ).fetchone()
    assert uncopyable_row is not None
    if int(uncopyable_row["uncopyable"]) > 0:
        raise UncopyableCourseError(
            "course contains file-backed objects that cannot be copied"
        )
    cur.execute(
        get(_ARCHIVE_FILE, "copy_study_periods"),
        {
            "source_course_id": source_course_id,
            "target_course_id": target_course_id,
        },
    )
    source_rows = cur.execute(
        get(_ARCHIVE_FILE, "source_rows"), {"course_id": source_course_id}
    ).fetchall()
    for source_row in source_rows:
        target_object_id = uuid4()
        target_source_id = uuid4()
        target_path = storage.copy_stored(
            source_course_id,
            source_row["source_id"],
            target_course_id,
            target_source_id,
        )
        cur.execute(
            get(_ARCHIVE_FILE, "insert_copied_source_object"),
            {
                "object_id": target_object_id,
                "course_id": target_course_id,
                "owner_user_id": target_owner_id,
                "content_type": source_row["mime_type"],
                "content": json.dumps({"source_id": str(target_source_id)}),
                "origin": f"copied_from_archive:{source_course_id}",
            },
        )
        cur.execute(
            get(_ARCHIVE_FILE, "insert_copied_source"),
            {
                "source_id": target_source_id,
                "object_id": target_object_id,
                "owner_user_id": target_owner_id,
                "course_id": target_course_id,
                "filename": source_row["filename"],
                "mime_type": source_row["mime_type"],
                "source_type": source_row["source_type"],
                "version": source_row["version"],
                "uri": str(target_path),
                "file_hash": source_row["file_hash"],
                "size_bytes": source_row["size_bytes"],
                "stored_encoding": source_row["stored_encoding"],
            },
        )
    other_objects = cur.execute(
        get(_ARCHIVE_FILE, "non_source_object_rows"),
        {"course_id": source_course_id},
    ).fetchall()
    for object_row in other_objects:
        cur.execute(
            get(_ARCHIVE_FILE, "insert_copied_object"),
            {
                "course_id": target_course_id,
                "owner_user_id": target_owner_id,
                "kind": object_row["kind"],
                "content_type": object_row["content_type"],
                "content": json.dumps(object_row["content"]),
                "origin": f"copied_from_archive:{source_course_id}",
                "status": object_row["status"],
                "access_scope": object_row["access_scope"],
            },
        )
    concept_map: dict[UUID, UUID] = {}
    concept_rows = cur.execute(
        get(_ARCHIVE_FILE, "concept_rows"), {"course_id": source_course_id}
    ).fetchall()
    for concept_row in concept_rows:
        target_concept_id = uuid4()
        concept_map[concept_row["concept_id"]] = target_concept_id
        cur.execute(
            get(_ARCHIVE_FILE, "insert_copied_concept"),
            {
                "concept_id": target_concept_id,
                "course_id": target_course_id,
                "name": concept_row["name"],
                "definition": concept_row["definition"],
                "synonyms": json.dumps(concept_row["synonyms"]),
                "evidence_level": concept_row["evidence_level"],
            },
        )
    dependency_rows = cur.execute(
        get(_ARCHIVE_FILE, "dependency_rows"), {"course_id": source_course_id}
    ).fetchall()
    for dependency_row in dependency_rows:
        cur.execute(
            get(_ARCHIVE_FILE, "insert_copied_dependency"),
            {
                "prereq_id": concept_map.get(dependency_row["prereq_id"]),
                "dependent_id": concept_map[dependency_row["dependent_id"]],
                "prereq_kind": dependency_row["prereq_kind"],
                "external_ref": dependency_row["external_ref"],
            },
        )


def delete_course(course_id: UUID, *, now: datetime | None = None) -> datetime:
    """Archive a course for the configured grace period and write a permanent
    memory into every current participant's memory bank."""
    archived_at = now or datetime.now(UTC)
    purge_after = archived_at + timedelta(
        days=load_lifecycle_policy().archive_grace_days
    )
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        course = cur.execute(
            get(_ARCHIVE_FILE, "lock_active_course"), {"course_id": course_id}
        ).fetchone()
        if course is None:
            raise UnknownCourseError(course_id)
        _archive_locked_course(cur, course, archived_at, purge_after)
        conn.commit()
    return purge_after


def _delete_subtree(cur: Cursor[Any], course_id: UUID) -> None:
    block = get(_DELETION_FILE, "delete_course_subtree")
    # The extended query protocol forbids multiple statements in one prepared
    # statement, so the block runs via the simple protocol. That protocol has
    # no parameter binding, so the block's only placeholder (%(course_id)s) is
    # rendered first — via psycopg's UUID adapter, which safely quotes the
    # literal exactly as any parameterized query would.
    statement = block.replace("%(course_id)s", sql.Literal(course_id).as_string(None))
    cur.execute(statement)


def purge_expired_archives(
    *, now: datetime | None = None, limit: int = 100
) -> list[UUID]:
    """Purge each due archive in its own transaction: one course's failure
    (an unexpected FK edge, a storage error) rolls back only that course and
    leaves the rest of the queue purgeable. Failed courses are logged and
    skipped — they stay archived with purge_after in the past, so the next
    sweep retries them; a persistently failing purge needs operator
    attention, which the repeated log line provides."""
    reference = now or datetime.now(UTC)
    purged: list[UUID] = []
    for row in _due_archives(reference, limit):
        course_id = row["course_id"]
        try:
            purged.append(_purge_one(course_id))
        except Exception:
            logger.exception("purge failed for course %s; skipped", course_id)
    return purged


def _due_archives(
    reference: datetime, limit: int
) -> list[dict[str, Any]]:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        return (
            cur.execute(
                get(_ARCHIVE_FILE, "due_archives"),
                {"now": reference, "limit": limit},
            ).fetchall()
        )


def _purge_one(course_id: UUID) -> UUID:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(get(_ARCHIVE_FILE, "enqueue_cleanup"), {"course_id": course_id})
        _delete_subtree(cur, course_id)
        conn.commit()
    return course_id


def restrict_public_course(
    course_id: UUID,
    owner_user_id: UUID,
    tier: UserTier,
    tier_policy: TierPolicy,
    visibility: CourseVisibility,
    *,
    name: str | None = None,
    now: datetime | None = None,
) -> Course:
    """Archive the exact public version and atomically create its restricted
    successor. Existing learners retain only archive/copy access to the old
    version; the active successor starts with no enrollments."""
    if visibility == CourseVisibility.PUBLIC:
        raise ValueError("restricted successor must not be public")
    archived_at = now or datetime.now(UTC)
    purge_after = archived_at + timedelta(
        days=load_lifecycle_policy().archive_grace_days
    )
    copied_course_id: UUID | None = None
    try:
        with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            owner = cur.execute(
                "SELECT user_id FROM users WHERE user_id = %s FOR UPDATE",
                (owner_user_id,),
            ).fetchone()
            if owner is None:
                raise UnknownCourseError(course_id)
            course = cur.execute(
                get(_ARCHIVE_FILE, "lock_active_course"), {"course_id": course_id}
            ).fetchone()
            if course is None or course["owner_user_id"] != owner_user_id:
                raise UnknownCourseError(course_id)
            if course["visibility"] != CourseVisibility.PUBLIC.value:
                raise CourseTransitionError("course is not public")
            source_size_row = cur.execute(
                "SELECT COALESCE(SUM(size_bytes), 0) AS stored "
                "FROM sources WHERE course_id = %s",
                (course_id,),
            ).fetchone()
            owner_size_row = cur.execute(
                """
                SELECT COALESCE(SUM(source.size_bytes), 0) AS stored
                FROM sources AS source
                JOIN courses AS course ON course.course_id = source.course_id
                WHERE course.owner_user_id = %s
                """,
                (owner_user_id,),
            ).fetchone()
            assert source_size_row is not None and owner_size_row is not None
            source_size = int(source_size_row["stored"])
            owner_size = int(owner_size_row["stored"])
            if source_size > tier_policy.max_course_storage_bytes:
                raise budget.StorageLimitExceededError(
                    tier,
                    0,
                    source_size,
                    tier_policy.max_course_storage_bytes,
                    "per course",
                )
            if owner_size + source_size > tier_policy.max_total_storage_bytes:
                raise budget.StorageLimitExceededError(
                    tier,
                    owner_size,
                    source_size,
                    tier_policy.max_total_storage_bytes,
                    "total",
                )
            course_row = cur.execute(
                get(_ARCHIVE_FILE, "insert_course_copy"),
                {
                    "owner_user_id": owner_user_id,
                    "code": courses_repo.generate_join_code(),
                    "name": name or course["name"],
                    "visibility": visibility.value,
                },
            ).fetchone()
            assert course_row is not None
            copied_course_id = course_row["course_id"]
            _copy_course_contents(
                cur, course_id, copied_course_id, owner_user_id
            )
            memory_bank.upsert_for_users(
                cur, copied_course_id, [owner_user_id]
            )
            _archive_locked_course(cur, course, archived_at, purge_after)
            conn.commit()
            return Course(
                course_id=course_row["course_id"],
                owner_user_id=course_row["owner_user_id"],
                join_code=course_row["code"],
                name=course_row["name"],
                visibility=course_row["visibility"],
                lifecycle_status=course_row["lifecycle_status"],
                archived_at=course_row["archived_at"],
                purge_after=course_row["purge_after"],
            )
    except BaseException:
        if copied_course_id is not None:
            try:
                storage.remove_course_directory(copied_course_id)
            except OSError:
                logger.exception(
                    "could not remove failed visibility copy %s", copied_course_id
                )
        raise


def copy_archived_course(
    course_id: UUID,
    user_id: UUID,
    tier: UserTier,
    tier_policy: TierPolicy,
    *,
    name: str | None = None,
    now: datetime | None = None,
) -> Course:
    reference = now or datetime.now(UTC)
    copied_course_id: UUID | None = None
    try:
        with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            archive = cur.execute(
                get(_ARCHIVE_FILE, "get_archive_access"),
                {"course_id": course_id, "user_id": user_id, "now": reference},
            ).fetchone()
            if archive is None:
                raise ArchiveAccessError("archive not found or grace period expired")
            conn.execute(
                "SELECT user_id FROM users WHERE user_id = %s FOR UPDATE", (user_id,)
            ).fetchone()
            count_row = cur.execute(
                """
                SELECT COUNT(*) AS owned FROM courses
                WHERE owner_user_id = %s AND lifecycle_status = 'active'
                """,
                (user_id,),
            ).fetchone()
            assert count_row is not None
            owned = int(count_row["owned"])
            if owned >= tier_policy.max_owned_courses:
                raise budget.CourseLimitExceededError(
                    tier, owned, tier_policy.max_owned_courses
                )
            archive_size_row = cur.execute(
                "SELECT COALESCE(SUM(size_bytes), 0) AS stored "
                "FROM sources WHERE course_id = %s",
                (course_id,),
            ).fetchone()
            owner_size_row = cur.execute(
                """
                SELECT COALESCE(SUM(source.size_bytes), 0) AS stored
                FROM sources AS source
                JOIN courses AS course ON course.course_id = source.course_id
                WHERE course.owner_user_id = %s
                """,
                (user_id,),
            ).fetchone()
            assert archive_size_row is not None and owner_size_row is not None
            archive_size = int(archive_size_row["stored"])
            owner_size = int(owner_size_row["stored"])
            if archive_size > tier_policy.max_course_storage_bytes:
                raise budget.StorageLimitExceededError(
                    tier,
                    0,
                    archive_size,
                    tier_policy.max_course_storage_bytes,
                    "per course",
                )
            if owner_size + archive_size > tier_policy.max_total_storage_bytes:
                raise budget.StorageLimitExceededError(
                    tier,
                    owner_size,
                    archive_size,
                    tier_policy.max_total_storage_bytes,
                    "total",
                )
            course_row = cur.execute(
                get(_ARCHIVE_FILE, "insert_course_copy"),
                {
                    "owner_user_id": user_id,
                    "code": courses_repo.generate_join_code(),
                    "name": name or f"{archive['name']} (copy)",
                    "visibility": CourseVisibility.PRIVATE.value,
                },
            ).fetchone()
            assert course_row is not None
            copied_course_id = course_row["course_id"]
            _copy_course_contents(cur, course_id, copied_course_id, user_id)
            memory_bank.upsert_for_users(cur, copied_course_id, [user_id])
            conn.commit()
        return Course(
            course_id=course_row["course_id"],
            owner_user_id=course_row["owner_user_id"],
            join_code=course_row["code"],
            name=course_row["name"],
            visibility=course_row["visibility"],
            lifecycle_status=course_row["lifecycle_status"],
            archived_at=course_row["archived_at"],
            purge_after=course_row["purge_after"],
        )
    except BaseException:
        if copied_course_id is not None:
            try:
                storage.remove_course_directory(copied_course_id)
            except OSError:
                logger.exception(
                    "could not remove failed archive copy %s", copied_course_id
                )
        raise


def _to_cleanup_job(row: dict[str, Any]) -> StorageCleanupJob:
    return StorageCleanupJob(**row)


def _claim_cleanup(now: datetime) -> StorageCleanupJob | None:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_ARCHIVE_FILE, "claim_cleanup"),
            {"now": now, "lease_until": now + timedelta(minutes=5)},
        ).fetchone()
        conn.commit()
    return _to_cleanup_job(row) if row else None


def _cleanup_policy() -> tuple[int, timedelta]:
    policy = load_lifecycle_policy()
    return policy.cleanup_max_attempts, timedelta(
        seconds=policy.cleanup_retry_delay_seconds
    )


def reclaim_expired_cleanup_leases(*, now: datetime | None = None) -> int:
    """Return jobs stuck in 'running' past their lease to a retryable state,
    or 'dead' once attempts are exhausted. A worker that died mid-job can
    no longer wedge a cleanup forever."""
    reference = now or datetime.now(UTC)
    max_attempts, _ = _cleanup_policy()
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            get(_ARCHIVE_FILE, "reclaim_expired_cleanup"),
            {"now": reference, "limit": 100, "max_attempts": max_attempts},
        ).fetchall()
        conn.commit()
    return len(rows)


def process_cleanup_jobs(*, limit: int = 100) -> int:
    completed = 0
    max_attempts, retry_delay = _cleanup_policy()
    reclaim_expired_cleanup_leases()
    for _ in range(limit):
        now = datetime.now(UTC)
        job = _claim_cleanup(now)
        if job is None:
            break
        try:
            storage.remove_course_directory(job.course_id)
        except OSError as err:
            with connection() as conn:
                conn.execute(
                    get(_ARCHIVE_FILE, "cleanup_failed"),
                    {
                        "job_id": job.job_id,
                        "error_message": str(err),
                        "next_attempt_at": now + retry_delay,
                        "max_attempts": max_attempts,
                    },
                )
                conn.commit()
            continue
        with connection() as conn:
            conn.execute(
                get(_ARCHIVE_FILE, "cleanup_succeeded"), {"job_id": job.job_id}
            )
            conn.commit()
        completed += 1
    return completed


def sweep_storage_orphans(
    *, limit: int = 100, min_age: timedelta
) -> list[UUID]:
    """Remove stored debris whose DB row never committed:
    - course directories with no courses row (dir-level orphans),
    - source files whose source row is absent inside live course dirs
      (crash between file write and DB commit),
    - staging files from interrupted atomic writes.
    Every removal is guarded by the mandatory `min_age`: an in-flight
    transaction's files (written before commit) are never touched, so callers
    must pass an explicit conservative age. Returns swept course ids
    (directories)."""
    now = datetime.now(UTC)
    cutoff = now - min_age

    def _expired(path: Path) -> bool:
        return path.stat().st_mtime <= cutoff.timestamp()

    def _sweep_course_dir(course_id: UUID) -> bool:
        """Sweep one course directory. Returns whether it was removed."""
        if course_id in db_course_ids:
            removed_files = 0
            for source_id, path in storage.course_source_files(course_id):
                if source_id in db_source_ids or not _expired(path):
                    continue
                try:
                    path.unlink()
                except OSError:
                    logger.exception("orphan sweep could not remove file %s", path)
                    continue
                logger.warning(
                    "swept orphaned stored file %s (source row absent; "
                    "crash between file write and commit?)",
                    path,
                )
                removed_files += 1
            for path in storage.course_staging_files(course_id):
                if not _expired(path):
                    continue
                try:
                    path.unlink()
                except OSError:
                    logger.exception("orphan sweep could not remove file %s", path)
                else:
                    logger.warning("swept interrupted staging file %s", path)
            if removed_files > 0:
                logger.info(
                    "storage sweep removed %d orphaned file(s) in course %s",
                    removed_files,
                    course_id,
                )
            return False
        # Whole directory orphaned: remove only if nothing inside is young
        # enough to belong to an in-flight transaction.
        dir_path = storage.storage_root() / str(course_id)
        if all(
            _expired(entry)
            for entry in dir_path.iterdir()
            if entry.is_file()
        ):
            try:
                storage.remove_course_directory(course_id)
            except OSError:
                logger.exception("orphan sweep could not remove %s", course_id)
                return False
            return True
        return False

    db_course_ids: set[UUID] = set()
    db_source_ids: set[UUID] = set()
    with connection() as conn:
        db_course_ids = {
            row[0] for row in conn.execute("SELECT course_id FROM courses").fetchall()
        }
        db_source_ids = {
            row[0] for row in conn.execute("SELECT source_id FROM sources").fetchall()
        }
    swept_dirs: list[UUID] = []
    for course_id in storage.course_directories(limit=limit * 10):
        if len(swept_dirs) >= limit:
            break
        if _sweep_course_dir(course_id):
            swept_dirs.append(course_id)
    return swept_dirs
