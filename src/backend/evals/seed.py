"""Direct seeding for the evaluation harness (T-15).

The bake-off and eval scripts need a course with known chunks without
running ingestion. Constructing those stored rows is production
evaluation tooling, not test behavior, so it lives here rather than in
`tests/factories.py`; the tests import these same helpers.

These insert stored results directly. They do not write raw files or run
the pipeline — ingestion tests cover publication separately.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import numpy as np
from src.backend.common import courses_repo
from src.backend.common.db import Connection, connection
from src.backend.common.schemas.identity import Course


def seed_course(name: str = "Course") -> Course:
    """One course, no sources."""
    return courses_repo.create_course(name)


def seed_source(
    course_id: UUID,
    *,
    filename: str = "notes.txt",
    status: str = "indexed",
    mime_type: str = "text/plain",
) -> UUID:
    """One source row with a unique hash (no stored file)."""
    source_id = uuid4()
    with connection() as conn:
        conn.execute(
            "INSERT INTO sources (source_id, course_id, filename, mime_type,"
            " source_type, uri, status, file_hash, size_bytes, stored_encoding)"
            " VALUES (?, ?, ?, ?, 'notes', 'disk://x', ?, ?, 10, 'identity')",
            (source_id, course_id, filename, mime_type, status, uuid4().hex),
        )
        conn.commit()
    return source_id


def seed_chunk(
    source_id: UUID,
    text: str,
    *,
    chunk_index: int = 0,
    label: str = "page 1",
    embedding: list[float] | None = None,
    embedding_model: str = "test-embed",
) -> UUID:
    """One locator + chunk (+ citation-map row, + optional embedding)."""
    locator_id, chunk_id = uuid4(), uuid4()
    with connection() as conn:
        conn.execute(
            "INSERT INTO locators (locator_id, source_id, locator_type, start,"
            " end_value, label) VALUES (?, ?, 'page', '0', '100', ?)",
            (locator_id, source_id, label),
        )
        conn.execute(
            "INSERT INTO chunks (chunk_id, source_id, locator_id, chunk_index, text)"
            " VALUES (?, ?, ?, ?, ?)",
            (chunk_id, source_id, locator_id, chunk_index, text),
        )
        conn.execute(
            "INSERT INTO chunk_locators (chunk_id, locator_id) VALUES (?, ?)",
            (chunk_id, locator_id),
        )
        if embedding is not None:
            add_embedding(conn, chunk_id, embedding, embedding_model)
        conn.commit()
    return chunk_id


def add_embedding(
    conn: Connection,
    chunk_id: UUID,
    embedding: list[float] | np.ndarray,
    model: str = "test-embed",
) -> None:
    vector = np.asarray(embedding, dtype="<f4")
    conn.execute(
        "INSERT INTO chunk_embeddings (chunk_id, model, dimension, embedding)"
        " VALUES (?, ?, ?, ?)",
        (chunk_id, model, len(vector), vector.tobytes()),
    )


def seed_chunks(source_id: UUID, count: int, text: str = "linearity mention") -> None:
    """`count` chunks, each under its own page locator so labels stay
    per-chunk."""
    for i in range(count):
        seed_chunk(source_id, f"{text} {i}", chunk_index=i, label=f"page {i + 1}")


def seed_chunked_source(
    course_id: UUID,
    text: str,
    *,
    label: str = "page 1",
    embedding: list[float] | None = None,
    embedding_model: str = "test-embed",
) -> UUID:
    """One source + locator + chunk; each chunk gets its own source so
    per-source allocation can be tested precisely."""
    source_id = seed_source(course_id)
    return seed_chunk(
        source_id,
        text,
        label=label,
        embedding=embedding,
        embedding_model=embedding_model,
    )


def set_source_status(source_id: UUID, status: str) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE sources SET status = ? WHERE source_id = ?", (status, source_id)
        )
        conn.commit()


def seed_harness_course() -> Course:
    """The `harness-course` that `data/eval/answer/cases.json` resolves:
    one linearly-independent chunk (page 1) and one worked linearity
    passage (page 2). Shared by `run_answer_eval` fixtures and the
    bake-off so the prompt the model sees is identical in tests and runs."""
    course = seed_course("harness-course")
    seed_chunked_source(
        course.course_id,
        "A linear transformation preserves addition and scalar multiplication.",
        label="page 1",
    )
    seed_chunked_source(
        course.course_id,
        "Scalar multiplication multiplies each vector coordinate by a scalar: "
        "2(1, 3) = (2, 6). Vector addition adds corresponding coordinates. "
        "For linearity, check T(u+v)=T(u)+T(v) and T(cu)=cT(u). "
        "Practice idea: compute 3(2, -1), then check both properties for T(x)=2x. "
        "Use a fresh vector to check your work independently.",
        label="page 2",
    )
    return course
