"""Courses and their lifecycle: create, rename, trash, restore, purge.

Deleting a course moves it to the trash (restorable for the configured
retention period); the maintenance loop purges it after that. Purge is
one cascading DELETE plus removal of the course's stored files — the
course-memory keepsake (decision 007) is refreshed just before, and
survives because it has no foreign key to the course.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from src.backend.common import course_memory, storage
from src.backend.common.db import connection, json_ids, utc_now
from src.backend.common.lifecycle_config import load_lifecycle_policy
from src.backend.common.queries import get
from src.backend.common.schemas.identity import Course

_FILE = "courses"
logger = logging.getLogger(__name__)


class UnknownCourseError(RuntimeError):
    def __init__(self, course_id: UUID) -> None:
        super().__init__(f"course not found: {course_id}")


def _to_course(row: dict[str, Any]) -> Course:
    return Course(
        course_id=row["course_id"],
        name=row["name"],
        created_at=row["created_at"],
        deleted_at=row["deleted_at"],
        purge_after=row["purge_after"],
    )


def create_course(name: str) -> Course:
    with connection() as conn:
        row = conn.execute(
            get(_FILE, "insert_course"), {"course_id": uuid4(), "name": name}
        ).fetchone()
        assert row is not None
        course_memory.refresh(conn, row["course_id"])
        conn.commit()
    return _to_course(row)


def get_course(course_id: UUID) -> Course | None:
    """An active (not trashed) course."""
    with connection() as conn:
        row = conn.execute(
            get(_FILE, "get_active"), {"course_id": course_id}
        ).fetchone()
    return _to_course(row) if row else None


def get_any_course(course_id: UUID) -> Course | None:
    with connection() as conn:
        row = conn.execute(get(_FILE, "get_any"), {"course_id": course_id}).fetchone()
    return _to_course(row) if row else None


def list_courses() -> list[Course]:
    with connection() as conn:
        rows = conn.execute(get(_FILE, "list_active")).fetchall()
    return [_to_course(row) for row in rows]


def list_trash() -> list[Course]:
    with connection() as conn:
        rows = conn.execute(get(_FILE, "list_trash")).fetchall()
    return [_to_course(row) for row in rows]


def rename_course(course_id: UUID, name: str) -> Course | None:
    with connection() as conn:
        row = conn.execute(
            get(_FILE, "rename_course"), {"course_id": course_id, "name": name}
        ).fetchone()
        if row is not None:
            course_memory.refresh(conn, course_id)
        conn.commit()
    return _to_course(row) if row else None


def move_to_trash(course_id: UUID, *, now: datetime | None = None) -> Course:
    """Soft-delete: hide the course and schedule its purge. Refreshes the
    course-memory keepsake so it reflects the course as it was deleted."""
    deleted_at = now or utc_now()
    purge_after = deleted_at + timedelta(
        days=load_lifecycle_policy().trash_retention_days
    )
    with connection() as conn:
        row = conn.execute(
            get(_FILE, "move_to_trash"),
            {
                "course_id": course_id,
                "deleted_at": deleted_at,
                "purge_after": purge_after,
            },
        ).fetchone()
        if row is None:
            raise UnknownCourseError(course_id)
        course_memory.refresh(conn, course_id)
        conn.commit()
    return _to_course(row)


def restore_from_trash(course_id: UUID) -> Course:
    with connection() as conn:
        row = conn.execute(
            get(_FILE, "restore_from_trash"), {"course_id": course_id}
        ).fetchone()
        if row is None:
            raise UnknownCourseError(course_id)
        conn.commit()
    return _to_course(row)


def purge_course(course_id: UUID) -> bool:
    """Permanently delete a trashed course: rows (one cascading DELETE),
    then its stored files. Returns False when the course is not in the
    trash. A file-removal failure is logged, not raised — the orphan sweep
    retries leftover directories on the next maintenance pass."""
    with connection() as conn:
        course_memory.refresh(conn, course_id)
        row = conn.execute(
            get(_FILE, "purge_trashed_course"), {"course_id": course_id}
        ).fetchone()
        conn.commit()
    if row is None:
        return False
    try:
        storage.remove_course_directory(course_id)
    except OSError:
        logger.exception(
            "could not remove stored files for purged course %s; "
            "the orphan sweep will retry",
            course_id,
        )
    return True


def purge_due(*, now: datetime | None = None, limit: int = 100) -> list[UUID]:
    """Purge every trashed course whose retention has elapsed. Each course
    purges in its own transaction, so one failure never blocks the rest;
    a failed course stays due and is retried on the next pass."""
    reference = now or utc_now()
    with connection() as conn:
        due = [
            row["course_id"]
            for row in conn.execute(
                get(_FILE, "due_for_purge"), {"now": reference, "limit": limit}
            ).fetchall()
        ]
    purged: list[UUID] = []
    for course_id in due:
        try:
            if purge_course(course_id):
                purged.append(course_id)
        except Exception:
            logger.exception("purge failed for course %s; will retry", course_id)
    return purged


def source_stats(course_ids: list[UUID]) -> dict[UUID, tuple[int, int]]:
    """Map course_id -> (source_count, stored_bytes)."""
    if not course_ids:
        return {}
    with connection() as conn:
        rows = conn.execute(
            get(_FILE, "course_source_stats"), {"course_ids": json_ids(course_ids)}
        ).fetchall()
    return {
        UUID(str(row["course_id"])): (int(row["source_count"]), int(row["stored"]))
        for row in rows
    }


def sweep_storage_orphans(*, limit: int = 100, min_age: timedelta) -> list[UUID]:
    """Remove stored debris whose DB row never committed or was purged:
    - course directories with no courses row,
    - source files whose source row is absent inside live course dirs
      (crash between file write and DB commit),
    - staging files from interrupted atomic writes.
    Every removal is guarded by `min_age`, so an in-flight upload's files
    (written before commit) are never touched. Returns swept course ids."""
    cutoff = (utc_now() - min_age).timestamp()

    def _expired(path: Path) -> bool:
        return path.stat().st_mtime <= cutoff

    with connection() as conn:
        db_course_ids = {
            UUID(str(row["course_id"]))
            for row in conn.execute(get(_FILE, "all_course_ids")).fetchall()
        }
        db_source_ids = {
            UUID(str(row["source_id"]))
            for row in conn.execute(get(_FILE, "all_source_ids")).fetchall()
        }

    swept: list[UUID] = []
    for course_id in storage.course_directories(limit=limit * 10):
        if len(swept) >= limit:
            break
        if course_id in db_course_ids:
            for source_id, path in storage.course_source_files(course_id):
                if source_id in db_source_ids or not _expired(path):
                    continue
                try:
                    path.unlink()
                    logger.warning("swept orphaned stored file %s", path)
                except OSError:
                    logger.exception("orphan sweep could not remove %s", path)
            for path in storage.course_staging_files(course_id):
                if not _expired(path):
                    continue
                try:
                    path.unlink()
                    logger.warning("swept interrupted staging file %s", path)
                except OSError:
                    logger.exception("orphan sweep could not remove %s", path)
            continue
        # Whole directory orphaned: remove only when the directory and every
        # file in it are older than the grace (the directory check covers a
        # freshly created, still-empty upload target).
        dir_path = storage.storage_root() / str(course_id)
        if _expired(dir_path) and all(
            _expired(entry) for entry in dir_path.iterdir() if entry.is_file()
        ):
            try:
                storage.remove_course_directory(course_id)
            except OSError:
                logger.exception("orphan sweep could not remove %s", course_id)
                continue
            swept.append(course_id)
    return swept
