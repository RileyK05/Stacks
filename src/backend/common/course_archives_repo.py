from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from src.backend.common.db import connection
from src.backend.common.queries import get
from src.backend.common.schemas.identity import ArchivedCourse, CourseMemory

_FILE = "course_archives"


def list_archives(
    user_id: UUID, *, now: datetime | None = None
) -> list[ArchivedCourse]:
    reference = now or datetime.now(UTC)
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            get(_FILE, "list_user_archives"),
            {"user_id": user_id, "now": reference},
        ).fetchall()
    return [ArchivedCourse(**row) for row in rows]


def list_memories(user_id: UUID) -> list[CourseMemory]:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            get(_FILE, "list_memories"), {"user_id": user_id}
        ).fetchall()
    return [_to_memory(row) for row in rows]


def _to_memory(row: dict[str, Any]) -> CourseMemory:
    return CourseMemory(
        memory_id=row["memory_id"],
        user_id=row["user_id"],
        course_id=row["course_id"],
        course_ref=row["course_ref"],
        name=row["name"],
        summary=row["summary"],
        key_concepts=row["key_concepts"],
        token_budget=row["token_budget"],
        summary_version=row["summary_version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
