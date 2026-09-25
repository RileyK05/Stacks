"""Row factories for tests that need derived rows (sources, chunks,
concepts, TOC entries) without running ingestion. Ingestion tests cover
how those rows are produced; these build them directly."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import numpy as np
from src.backend.common import courses_repo
from src.backend.common.db import connection
from src.backend.common.schemas.identity import Course


def make_course(name: str = "Course") -> Course:
    return courses_repo.create_course(name)


def rename_course(course_id: UUID, name: str) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE courses SET name = ? WHERE course_id = ?", (name, course_id)
        )
        conn.commit()


def insert_source(
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


def insert_chunk(
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
            add_embedding_on(conn, chunk_id, embedding, embedding_model)
        conn.commit()
    return chunk_id


def add_embedding_on(
    conn, chunk_id: UUID, embedding: list[float], model: str = "test-embed"
) -> None:
    conn.execute(
        "INSERT INTO chunk_embeddings (chunk_id, model, dimension, embedding)"
        " VALUES (?, ?, ?, ?)",
        (
            chunk_id,
            model,
            len(embedding),
            np.asarray(embedding, dtype="<f4").tobytes(),
        ),
    )


def insert_chunks(source_id: UUID, count: int, text: str = "linearity mention") -> None:
    """`count` chunks, each under its own page locator so labels stay
    per-chunk."""
    for i in range(count):
        insert_chunk(source_id, f"{text} {i}", chunk_index=i, label=f"page {i + 1}")


def add_chunk(
    course_id: UUID,
    text: str,
    *,
    label: str = "page 1",
    embedding: list[float] | None = None,
    embedding_model: str = "test-embed",
) -> UUID:
    """One source + locator + chunk; each chunk gets its own source so
    per-source allocation can be tested precisely."""
    source_id = insert_source(course_id)
    return insert_chunk(
        source_id,
        text,
        label=label,
        embedding=embedding,
        embedding_model=embedding_model,
    )


def chunk_source_locator(chunk_id: UUID) -> tuple[UUID, UUID]:
    with connection() as conn:
        row = conn.execute(
            "SELECT source_id, locator_id FROM chunks WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()
    return row["source_id"], row["locator_id"]


def add_toc_entry(
    course_id: UUID, chunk_id: UUID, title: str, description: str, position: int = 0
) -> UUID:
    source_id, locator_id = chunk_source_locator(chunk_id)
    with connection() as conn:
        toc = conn.execute(
            "SELECT toc_id FROM tables_of_contents WHERE course_id = ?"
            " ORDER BY version DESC LIMIT 1",
            (course_id,),
        ).fetchone()
        toc_id = toc["toc_id"] if toc else uuid4()
        if toc is None:
            conn.execute(
                "INSERT INTO tables_of_contents (toc_id, course_id, version)"
                " VALUES (?, ?, 1)",
                (toc_id, course_id),
            )
        entry_id = uuid4()
        conn.execute(
            "INSERT INTO toc_entries (entry_id, toc_id, source_id, locator_id, title,"
            " description, concepts, position) VALUES (?, ?, ?, ?, ?, ?, '[]', ?)",
            (entry_id, toc_id, source_id, locator_id, title, description, position),
        )
        conn.commit()
    return entry_id


def add_concept(
    course_id: UUID,
    name: str,
    synonyms: list[str],
    *,
    depends_on: list[UUID] | None = None,
) -> UUID:
    concept_id = uuid4()
    with connection() as conn:
        conn.execute(
            "INSERT INTO concepts (concept_id, course_id, name, definition, synonyms)"
            " VALUES (?, ?, ?, 'def', ?)",
            (concept_id, course_id, name, json.dumps(synonyms)),
        )
        for prereq_id in depends_on or []:
            conn.execute(
                "INSERT INTO dependencies (dep_id, prereq_id, dependent_id)"
                " VALUES (?, ?, ?)",
                (uuid4(), prereq_id, concept_id),
            )
        conn.commit()
    return concept_id


def add_memory_object(concept_id: UUID, source_id: UUID, content: str) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO memory_objects (memory_id, concept_id, source_id, kind,"
            " content) VALUES (?, ?, ?, 'concept', ?)",
            (uuid4(), concept_id, source_id, content),
        )
        conn.commit()


def set_source_status(source_id: UUID, status: str) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE sources SET status = ? WHERE source_id = ?", (status, source_id)
        )
        conn.commit()
