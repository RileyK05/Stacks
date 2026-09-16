"""Retrieval trace persistence (golden rule 2: show what was retrieved).

Every retrieval stores one trace row. The `retrieved_chunk_ids` jsonb
holds the full inspectable payload: the ordered cited chunk ids plus the
layer attribution (which seams contributed each chunk) and the matched
concept ids. The `retrieved_toc_entry_ids` jsonb holds the TOC entries
that matched. Auditors can see WHY a chunk was retrieved, not just that
it was.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from src.backend.common.queries import get
from src.backend.retrieval.funnel import RetrievalResult

_FILE = "retrieval_traces"


@dataclass(frozen=True)
class StoredTrace:
    trace_id: UUID
    query: str
    chunk_ids: tuple[UUID, ...]
    layer_contribution: dict[str, int]
    created_at: datetime


def record_trace(
    conn: Connection,
    user_id: UUID,
    course_id: UUID,
    query: str,
    result: RetrievalResult,
    *,
    embedding_model: str | None = None,
    conversation_id: UUID | None = None,
    toc_entry_ids: tuple[UUID, ...] = (),
) -> StoredTrace:
    """The trace stores the WHY, not just the WHAT: per-chunk layer
    attribution (each cited chunk with the seams that surfaced it),
    matched concept ids, and the TOC entries that matched."""
    per_chunk = [
        {
            "chunk_id": str(candidate.chunk_id),
            "layers": sorted(candidate.layers),
        }
        for candidate in result.candidates
    ]
    chunk_payload = {
        "chunk_ids": [entry["chunk_id"] for entry in per_chunk],
        "per_chunk_layers": per_chunk,
        "layer_contribution": result.layer_contribution,
        "matched_concept_ids": [str(cid) for cid in result.matched_concept_ids],
    }
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "insert_trace"),
            {
                "user_id": user_id,
                "course_id": course_id,
                "conversation_id": conversation_id,
                "query": query,
                "chunk_ids": json.dumps(chunk_payload),
                "toc_entry_ids": json.dumps([str(cid) for cid in toc_entry_ids]),
                "model": embedding_model,
            },
        ).fetchone()
    assert row is not None
    chunk_uuids = tuple(UUID(str(entry["chunk_id"])) for entry in per_chunk)
    return StoredTrace(
        trace_id=row["trace_id"],
        query=query,
        chunk_ids=chunk_uuids,
        layer_contribution=result.layer_contribution,
        created_at=row["created_at"],
    )