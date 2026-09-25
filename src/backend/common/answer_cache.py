"""Answer cache (migration 002; docs/plan-local-first.md §6 item 11).

Only plain answers are cached — never workspace items (a second "quiz me"
should bring new questions) and never an answer a rate-limited cloud
model handed to the local one. The key covers everything that shapes an
answer: the question (normalised), the course's content fingerprint, the
endpoint and model, and the versions of the prompts, retrieval settings
and answer mode. Change any of them and the old entry simply stops
matching.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from uuid import UUID

from src.backend.common.db import Connection
from src.backend.common.providers import ResolvedProvider
from src.backend.common.queries import get

_FILE = "answer_cache"
_TRAILING_PUNCTUATION = re.compile(r"[\s?!.]+$")


@dataclass(frozen=True)
class CachedAnswer:
    trace_id: UUID
    text: str
    chunk_ids: tuple[UUID, ...]
    model: str


def normalise_question(question: str) -> str:
    """Treat "What is X?" and "what is  x" as the same question."""
    return _TRAILING_PUNCTUATION.sub("", " ".join(question.split()).casefold())


def course_fingerprint(conn: Connection, course_id: UUID) -> str:
    row = conn.execute(
        get(_FILE, "course_fingerprint"), {"course_id": course_id}
    ).fetchone()
    return str(row["fingerprint"]) if row else ""


def cache_key(
    *,
    course_id: UUID,
    fingerprint: str,
    question: str,
    endpoint: ResolvedProvider,
    versions: dict[str, str],
) -> str:
    parts = {
        "course": str(course_id),
        "fingerprint": fingerprint,
        "question": normalise_question(question),
        "endpoint": [endpoint.name, endpoint.base_url, endpoint.model],
        "versions": versions,
    }
    encoded = json.dumps(parts, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def lookup(conn: Connection, key: str) -> CachedAnswer | None:
    row = conn.execute(get(_FILE, "lookup"), {"cache_key": key}).fetchone()
    if row is None:
        return None
    ids = row["chunk_ids"] if isinstance(row["chunk_ids"], list) else []
    return CachedAnswer(
        trace_id=row["trace_id"],
        text=row["answer_text"],
        chunk_ids=tuple(UUID(str(value)) for value in ids),
        model=row["model"],
    )


def store(
    conn: Connection,
    *,
    key: str,
    course_id: UUID,
    fingerprint: str,
    trace_id: UUID,
    text: str,
    chunk_ids: tuple[UUID, ...],
    model: str,
) -> None:
    """Store one answer and drop the course's entries for older content.
    Part of the caller's transaction (it commits with the trace)."""
    conn.execute(
        get(_FILE, "drop_stale"), {"course_id": course_id, "fingerprint": fingerprint}
    )
    conn.execute(
        get(_FILE, "store"),
        {
            "cache_key": key,
            "course_id": course_id,
            "fingerprint": fingerprint,
            "trace_id": trace_id,
            "answer_text": text,
            "chunk_ids": json.dumps([str(chunk_id) for chunk_id in chunk_ids]),
            "model": model,
        },
    )
