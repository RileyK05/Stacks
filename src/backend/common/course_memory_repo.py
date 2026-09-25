from __future__ import annotations

from typing import Any

from src.backend.common.db import connection
from src.backend.common.queries import get
from src.backend.common.schemas.identity import CourseMemory

_FILE = "course_memory"


def _to_memory(row: dict[str, Any]) -> CourseMemory:
    return CourseMemory(**row)


def list_memories() -> list[CourseMemory]:
    """Every course-memory node, including keepsakes of purged courses."""
    with connection() as conn:
        rows = conn.execute(get(_FILE, "list_memories")).fetchall()
    return [_to_memory(row) for row in rows]
