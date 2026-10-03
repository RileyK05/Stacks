"""Test-facing aliases for the evaluation seeding helpers.

The row-construction logic lives in `src.backend.evals.seed` so the
production bake-off and the tests share one implementation (T-15). This
module keeps the historical test names and adds the test-only helpers
(`rename_course`, `chunk_source_locator`).
"""

from __future__ import annotations

from uuid import UUID

from src.backend.common.db import connection
from src.backend.evals.seed import (
    add_embedding as add_embedding_on,
)
from src.backend.evals.seed import (
    seed_chunk as insert_chunk,
)
from src.backend.evals.seed import (
    seed_chunked_source as add_chunk,
)
from src.backend.evals.seed import (
    seed_chunks as insert_chunks,
)
from src.backend.evals.seed import (
    seed_course as make_course,
)
from src.backend.evals.seed import (
    seed_source as insert_source,
)
from src.backend.evals.seed import (
    set_source_status,
)


def rename_course(course_id: UUID, name: str) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE courses SET name = ? WHERE course_id = ?", (name, course_id)
        )
        conn.commit()


def chunk_source_locator(chunk_id: UUID) -> tuple[UUID, UUID]:
    with connection() as conn:
        row = conn.execute(
            "SELECT source_id, locator_id FROM chunks WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()
    return row["source_id"], row["locator_id"]


__all__ = [
    "add_chunk",
    "add_embedding_on",
    "chunk_source_locator",
    "insert_chunk",
    "insert_chunks",
    "insert_source",
    "make_course",
    "rename_course",
    "set_source_status",
]
