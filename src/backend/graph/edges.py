"""Bounded nearest-neighbor similarity edges over source passages."""

from __future__ import annotations

from uuid import UUID, uuid4

import numpy as np
from src.backend.common.db import Connection
from src.backend.common.db import connection as db_connection
from src.backend.common.embeddings_config import load_embedding_policy
from src.backend.common.queries import get
from src.backend.graph.vectors import load_course_vectors
from src.backend.rag.config import PassagePolicy, load_policy

_FILE = "graph"


def _similarity_pairs(
    ids: list[UUID],
    matrix: np.ndarray,
    *,
    floor: float,
    block_rows: int,
    neighbors: int,
    positions: list[int] | None = None,
) -> list[tuple[UUID, UUID, float]]:
    """Keep bounded nearest neighbors above the cosine floor per selected row.

    Return canonical unordered pairs without self-pairs or duplicates.
    """
    seen: set[tuple[UUID, UUID]] = set()
    pairs: list[tuple[UUID, UUID, float]] = []
    total = matrix.shape[0]
    positions = positions if positions is not None else list(range(total))
    for start in range(0, len(positions), block_rows):
        batch = positions[start : start + block_rows]
        block = matrix[batch]
        scores = block @ matrix.T
        for offset in range(block.shape[0]):
            i = batch[offset]
            row = scores[offset]
            ordered_hits = np.argsort(-row, kind="stable")
            hits = [j for j in ordered_hits if j != i and row[j] >= floor][:neighbors]
            for j in hits:
                j = int(j)
                if i == j:
                    continue
                a, b = (
                    (ids[i], ids[j]) if str(ids[i]) < str(ids[j]) else (ids[j], ids[i])
                )
                key = (a, b)
                if key in seen:
                    continue
                seen.add(key)
                pairs.append((a, b, min(1.0, float(row[j]))))
    return pairs


def _insert_edges(
    conn: Connection,
    course_id: UUID,
    model: str,
    pairs: list[tuple[UUID, UUID, float]],
    version: str,
) -> int:
    conn.executemany(
        get(_FILE, "insert_graph_edge"),
        [
            {
                "edge_id": uuid4(),
                "course_id": course_id,
                "model": model,
                "chunk_a": a,
                "chunk_b": b,
                "weight": weight,
                "algorithm_version": version,
            }
            for a, b, weight in pairs
        ],
    )
    return len(pairs)


def build_course_edges(
    conn: Connection,
    course_id: UUID,
    *,
    policy: PassagePolicy | None = None,
    model: str | None = None,
) -> int:
    """Rebuild every similarity edge for a course. Returns the edge count."""
    policy = policy or load_policy()
    model = model or load_embedding_policy().model
    ids, matrix, _rows = load_course_vectors(conn, course_id, model)
    pairs = _similarity_pairs(
        ids,
        matrix,
        floor=policy.similarity_floor,
        block_rows=policy.similarity_block_rows,
        neighbors=policy.similarity_neighbors,
    )
    conn.execute(
        get(_FILE, "delete_course_edges"),
        {"course_id": course_id, "model": model},
    )
    return _insert_edges(conn, course_id, model, pairs, policy.version)


def build_source_edges(
    source_id: UUID,
    *,
    policy: PassagePolicy | None = None,
    model: str | None = None,
) -> int:
    """Rebuild all course edges after a source refresh and commit.

    An undirected union of per-row nearest neighbors can change edges between
    two other sources when one source changes, so a source-only rebuild cannot
    preserve the course graph. Scoring uses bounded row blocks; returns the
    course's new edge count.
    """
    with db_connection() as conn:
        row = conn.execute(
            get("ingestion", "source_row"), {"source_id": source_id}
        ).fetchone()
        if row is None:
            return 0
        course_id = row["course_id"]
        count = build_course_edges(conn, course_id, policy=policy, model=model)
        conn.commit()
        return count
