"""Persist passage identities and retrieval-layer attribution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from src.backend.common.db import Connection
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
    course_id: UUID,
    query: str,
    result: RetrievalResult,
    *,
    embedding_model: str | None = None,
    cited: tuple[tuple[UUID, int], ...] | None = None,
) -> StoredTrace:
    """Retain the retrieval path, related context and exact coverage read."""
    per_chunk = [
        {
            "chunk_id": str(candidate.chunk_id),
            "layers": sorted(candidate.layers),
            "partial": candidate.partial,
            "char_start": candidate.window_start if candidate.partial else None,
            "char_end": candidate.window_end if candidate.partial else None,
            "text_length": candidate.text_length,
            "context_for": sorted(str(identity) for identity in candidate.context_for),
            "generated_materials": [
                {"artifact_id": identity, "title": title, "version": version}
                for identity, title, version in candidate.generated_materials
            ],
        }
        for candidate in result.candidates
    ]
    contribution: dict[str, int] = {}
    for candidate in result.candidates:
        for layer in candidate.layers:
            contribution[layer] = contribution.get(layer, 0) + 1
    chunk_payload: dict[str, object] = {
        "chunk_ids": [entry["chunk_id"] for entry in per_chunk],
        "per_chunk_layers": per_chunk,
        "layer_contribution": contribution,
    }
    if cited is not None:
        # The full candidate list stays above. These are the markers the
        # answer actually printed, in marker order, so the sources list
        # does not renumber them.
        chunk_payload["cited_chunk_ids"] = [str(chunk_id) for chunk_id, _ in cited]
        chunk_payload["citation_markers"] = [marker for _, marker in cited]
    row = conn.execute(
        get(_FILE, "insert_trace"),
        {
            "trace_id": uuid4(),
            "course_id": course_id,
            "query": query,
            "chunk_ids": json.dumps(chunk_payload),
            "model": embedding_model,
        },
    ).fetchone()
    assert row is not None
    chunk_uuids: list[UUID] = []
    for entry in per_chunk:
        try:
            chunk_uuids.append(UUID(str(entry["chunk_id"])))
        except ValueError:
            continue
    return StoredTrace(
        trace_id=row["trace_id"],
        query=query,
        chunk_ids=tuple(chunk_uuids),
        layer_contribution=contribution,
        created_at=row["created_at"],
    )
