from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from src.backend.common import codes, memory_bank
from src.backend.common.db import connection
from src.backend.common.queries import get
from src.backend.common.schemas.base import CourseVisibility
from src.backend.common.schemas.identity import Course

_FILE = "courses"


class CourseLimitReachedError(RuntimeError):
    def __init__(self, owned: int, limit: int) -> None:
        self.owned = owned
        self.limit = limit
        super().__init__(f"course limit reached: {owned}/{limit}")


class RestrictedTransitionError(RuntimeError):
    """A public course may not become restricted via a plain UPDATE; that
    transition is versioned and must go through courses_lifecycle so
    existing learners receive the promised archive/copy grace period."""


def generate_join_code() -> str:
    return codes.generate_code()


def _to_course(row: dict[str, Any]) -> Course:
    return Course(
        course_id=row["course_id"],
        owner_user_id=row["owner_user_id"],
        join_code=row["code"],
        name=row["name"],
        visibility=row["visibility"],
        lifecycle_status=row["lifecycle_status"],
        archived_at=row["archived_at"],
        purge_after=row["purge_after"],
    )


def get_course(course_id: UUID) -> Course | None:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(get(_FILE, "get_by_id"), {"course_id": course_id}).fetchone()
    return _to_course(row) if row else None


def get_any_course(course_id: UUID) -> Course | None:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "get_any_by_id"), {"course_id": course_id}
        ).fetchone()
    return _to_course(row) if row else None


def get_by_join_code(join_code: str) -> Course | None:
    normalized = codes.normalize_code(join_code)
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "get_by_join_code"),
            {"code": normalized},
        ).fetchone()
    return _to_course(row) if row else None


def create_course(
    owner_user_id: UUID,
    name: str,
    visibility: CourseVisibility = CourseVisibility.PRIVATE,
    *,
    max_owned_courses: int | None = None,
) -> Course:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        if max_owned_courses is not None:
            conn.execute(
                "SELECT user_id FROM users WHERE user_id = %s FOR UPDATE",
                (owner_user_id,),
            ).fetchone()
            count_row = cur.execute(
                get(_FILE, "count_owned_courses"),
                {"owner_user_id": owner_user_id},
            ).fetchone()
            assert count_row is not None
            owned = int(count_row["owned"])
            if owned >= max_owned_courses:
                raise CourseLimitReachedError(owned, max_owned_courses)
        row = cur.execute(
            get(_FILE, "insert_course"),
            {
                "owner_user_id": owner_user_id,
                # generate_join_code() is canonical payload form; the DB CHECK
                # expects it without dashes. Grouping is display-only.
                "code": generate_join_code(),
                "name": name,
                "visibility": visibility.value,
            },
        ).fetchone()
        assert row is not None
        memory_bank.upsert_for_users(cur, row["course_id"], [owner_user_id])
        conn.commit()
    return _to_course(row)


def update_course(
    course_id: UUID,
    *,
    name: str | None = None,
    visibility: CourseVisibility | None = None,
) -> Course | None:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        existing = cur.execute(
            get(_FILE, "get_any_by_id"), {"course_id": course_id}
        ).fetchone()
        if (
            existing is not None
            and existing["lifecycle_status"] == "active"
            and visibility is not None
            and existing["visibility"] == CourseVisibility.PUBLIC.value
            and visibility != CourseVisibility.PUBLIC
        ):
            raise RestrictedTransitionError(
                "restricting a public course requires the versioned "
                "lifecycle path so existing learners receive the archive "
                "grace period"
            )
        row = cur.execute(
            get(_FILE, "update_course"),
            {
                "course_id": course_id,
                "name": name,
                "visibility": visibility.value if visibility else None,
            },
        ).fetchone()
        if row is not None:
            memory_bank.upsert_for_current_participants(cur, course_id)
        conn.commit()
    return _to_course(row) if row else None


def rotate_join_code(course_id: UUID) -> Course | None:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "rotate_join_code"),
            {"course_id": course_id, "code": generate_join_code()},
        ).fetchone()
        conn.commit()
    return _to_course(row) if row else None


def delete_course_row(course_id: UUID) -> None:
    with connection() as conn:
        conn.execute(get(_FILE, "delete_course_row"), {"course_id": course_id})
        conn.commit()


def list_owned(owner_user_id: UUID) -> list[Course]:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            get(_FILE, "list_owned"), {"owner_user_id": owner_user_id}
        ).fetchall()
    return [_to_course(row) for row in rows]


def list_enrolled(user_id: UUID) -> list[Course]:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(get(_FILE, "list_enrolled"), {"user_id": user_id}).fetchall()
    return [_to_course(row) for row in rows]


def list_public(limit: int = 100) -> list[Course]:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(get(_FILE, "list_public"), {"limit": limit}).fetchall()
    return [_to_course(row) for row in rows]


def source_stats(course_ids: list[UUID]) -> dict[UUID, tuple[int, int]]:
    """Map course_id -> (source_count, stored_bytes)."""
    if not course_ids:
        return {}
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            get(_FILE, "course_source_stats"), {"course_ids": list(course_ids)}
        ).fetchall()
    return {
        row["course_id"]: (int(row["source_count"]), int(row["stored"]))
        for row in rows
    }


def count_owned_courses(owner_user_id: UUID) -> int:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "count_owned_courses"), {"owner_user_id": owner_user_id}
        ).fetchone()
    assert row is not None
    return int(row["owned"])


def course_storage_bytes(course_id: UUID) -> int:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "course_storage_bytes"), {"course_id": course_id}
        ).fetchone()
    assert row is not None
    return int(row["stored"])


def total_storage_bytes(owner_user_id: UUID) -> int:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "total_storage_bytes"), {"owner_user_id": owner_user_id}
        ).fetchone()
    assert row is not None
    return int(row["stored"])
