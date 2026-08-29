from __future__ import annotations

from uuid import UUID

from psycopg.rows import dict_row
from src.backend.common.db import connection
from src.backend.common.queries import get
from src.backend.common.schemas.base import CourseVisibility
from src.backend.common.schemas.identity import Course

_FILE = "courses"


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


def create_course(
    owner_user_id: UUID, code: str, name: str,
    visibility: CourseVisibility = CourseVisibility.PRIVATE,
) -> Course:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "insert_course"),
            {
                "owner_user_id": owner_user_id,
                "code": code,
                "name": name,
                "visibility": visibility.value,
            },
        ).fetchone()
        conn.commit()
    assert row is not None
    return Course(
        course_id=row["course_id"],
        owner_user_id=row["owner_user_id"],
        code=row["code"],
        name=row["name"],
        visibility=row["visibility"],
    )