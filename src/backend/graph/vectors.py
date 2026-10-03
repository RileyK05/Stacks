"""Loading a course's chunk vectors for the graph.

One place decides which vectors count: dimension-consistent with the
configured model and finite. Mismatched vector spaces (a model swap under
the same name) are excluded, never scored — the retrieval seam's guard.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import numpy as np
from src.backend.common.db import Connection
from src.backend.common.queries import get

_FILE = "graph"


def valid_vectors(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], np.ndarray]:
    """Drop rows whose stored dimension or byte length disagrees with the
    batch, and any non-finite vector. Returns (kept rows, matrix)."""
    if not rows:
        return [], np.zeros((0, 0), np.float32)
    dimension = int(rows[0]["dimension"])
    rows = [
        row
        for row in rows
        if int(row["dimension"]) == dimension
        and len(row["embedding"]) == dimension * np.dtype("<f4").itemsize
    ]
    if not rows:
        return [], np.zeros((0, 0), np.float32)
    matrix = (
        np.frombuffer(b"".join(row["embedding"] for row in rows), dtype="<f4")
        .reshape(len(rows), dimension)
        .astype(np.float32)
    )
    norms = np.linalg.norm(matrix, axis=1)
    valid = np.isfinite(matrix).all(axis=1) & np.isfinite(norms) & (norms > 0)
    kept = [row for row, keep in zip(rows, valid, strict=True) if keep]
    return kept, matrix[valid] / norms[valid, None]


def load_course_vectors(
    conn: Connection, course_id: UUID, model: str
) -> tuple[list[UUID], np.ndarray, list[dict[str, Any]]]:
    """(chunk ids, matrix, kept rows) for one course and model. Rows keep
    their source/locator/text metadata so callers can render without a
    second query."""
    rows = conn.execute(
        get(_FILE, "course_chunk_vectors"),
        {"course_id": course_id, "model": model},
    ).fetchall()
    kept, matrix = valid_vectors(list(rows))
    ids = [UUID(str(row["chunk_id"])) for row in kept]
    return ids, matrix, kept
