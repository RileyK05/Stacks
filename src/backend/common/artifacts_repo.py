"""Artifacts and their versions (migration 004; docs/plan-notebook.md §4.3).

Every save is a new version: the artifact row holds the latest content and
`artifact_versions` keeps every one, with who made it (the student, or the
model on the student's acceptance). A save names the version it was based
on and is refused if the artifact moved on — two windows can never
silently overwrite each other.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from src.backend.common.db import Connection, connection
from src.backend.common.queries import get

_FILE = "artifacts"
Author = Literal["you", "model"]
TITLE_MAX_LENGTH = 200


class StaleVersionError(RuntimeError):
    """The artifact changed since the copy being saved was loaded."""


@dataclass(frozen=True)
class ArtifactSummary:
    artifact_id: UUID
    course_id: UUID
    kind: str
    title: str
    version: int
    created_at: datetime
    updated_at: datetime
    origin: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Artifact(ArtifactSummary):
    content: dict[str, Any] = field(default_factory=dict)
    sources: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class ArtifactVersion:
    version: int
    title: str
    author: str
    note: str
    created_at: datetime
    content: dict[str, Any] | None = None
    sources: tuple[UUID, ...] = ()


def _ids(raw: Any) -> tuple[UUID, ...]:
    return tuple(UUID(str(value)) for value in raw) if isinstance(raw, list) else ()


def _summary(row: dict[str, Any]) -> ArtifactSummary:
    return ArtifactSummary(
        artifact_id=row["artifact_id"],
        course_id=row["course_id"],
        kind=row["kind"],
        title=row["title"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        origin=row["origin"] if isinstance(row["origin"], dict) else {},
    )


def _artifact(row: dict[str, Any]) -> Artifact:
    base = _summary(row)
    return Artifact(
        **base.__dict__,
        content=row["content"] if isinstance(row["content"], dict) else {},
        sources=_ids(row["sources"]),
    )


def _json_ids(ids: tuple[UUID, ...] | list[UUID]) -> str:
    return json.dumps([str(value) for value in ids])


def list_artifacts(course_id: UUID) -> list[ArtifactSummary]:
    with connection() as conn:
        rows = conn.execute(
            get(_FILE, "list_for_course"), {"course_id": course_id}
        ).fetchall()
    return [_summary(row) for row in rows]


def load(conn: Connection, course_id: UUID, artifact_id: UUID) -> Artifact | None:
    row = conn.execute(
        get(_FILE, "get"), {"course_id": course_id, "artifact_id": artifact_id}
    ).fetchone()
    return _artifact(row) if row else None


def get_artifact(course_id: UUID, artifact_id: UUID) -> Artifact | None:
    with connection() as conn:
        return load(conn, course_id, artifact_id)


def create(
    course_id: UUID,
    *,
    kind: str,
    title: str,
    content: dict[str, Any],
    sources: list[UUID] | tuple[UUID, ...] = (),
    origin: dict[str, Any] | None = None,
    author: Author = "you",
    note: str = "",
) -> Artifact:
    with connection() as conn:
        created = _create(
            conn,
            course_id,
            kind=kind,
            title=title,
            content=content,
            sources=sources,
            origin=origin,
            author=author,
            note=note,
        )
        conn.commit()
    return created


def _create(
    conn: Connection,
    course_id: UUID,
    *,
    kind: str,
    title: str,
    content: dict[str, Any],
    sources: list[UUID] | tuple[UUID, ...],
    origin: dict[str, Any] | None,
    author: Author,
    note: str,
) -> Artifact:
    artifact_id = uuid4()
    clean_title = title.strip()[:TITLE_MAX_LENGTH]
    conn.execute(
        get(_FILE, "create"),
        {
            "artifact_id": artifact_id,
            "course_id": course_id,
            "kind": kind,
            "title": clean_title,
            "content": json.dumps(content, ensure_ascii=False),
            "sources": _json_ids(tuple(sources)),
            "origin": json.dumps(origin or {}, ensure_ascii=False),
        },
    )
    conn.execute(
        get(_FILE, "add_version"),
        {
            "artifact_id": artifact_id,
            "version": 1,
            "title": clean_title,
            "content": json.dumps(content, ensure_ascii=False),
            "sources": _json_ids(tuple(sources)),
            "author": author,
            "note": note,
        },
    )
    created = load(conn, course_id, artifact_id)
    assert created is not None
    return created


def adopt_message_item(
    course_id: UUID,
    *,
    kind: str,
    title: str,
    content: dict[str, Any],
    sources: list[UUID] | tuple[UUID, ...],
    origin: dict[str, Any],
    author: Author,
    note: str,
    as_copy: bool = False,
) -> Artifact:
    with connection() as conn:
        if (
            conn.execute(get(_FILE, "lock_course"), {"course_id": course_id}).rowcount
            == 0
        ):
            raise LookupError("course not found")
        if not as_copy:
            row = conn.execute(
                get(_FILE, "from_message"),
                {
                    "course_id": course_id,
                    "message_id": origin["message_id"],
                    "item_index": origin["item_index"],
                },
            ).fetchone()
            if row:
                existing = _artifact(row)
                if existing.content != content or existing.sources != tuple(sources):
                    raise StaleVersionError(
                        "this item already has a saved artifact; open it "
                        "to continue editing "
                        "or choose Save a copy to keep this draft separately"
                    )
                return existing
        created = _create(
            conn,
            course_id,
            kind=kind,
            title=title,
            content=content,
            sources=sources,
            origin={**origin, "adopted": not as_copy},
            author=author,
            note=note,
        )
        conn.commit()
    return created


def save(
    course_id: UUID,
    artifact_id: UUID,
    *,
    expected_version: int,
    title: str,
    content: dict[str, Any],
    sources: list[UUID] | tuple[UUID, ...],
    author: Author,
    note: str = "",
) -> Artifact:
    clean_title = title.strip()[:TITLE_MAX_LENGTH]
    with connection() as conn:
        cursor = conn.execute(
            get(_FILE, "save"),
            {
                "artifact_id": artifact_id,
                "course_id": course_id,
                "expected_version": expected_version,
                "title": clean_title,
                "content": json.dumps(content, ensure_ascii=False),
                "sources": _json_ids(tuple(sources)),
            },
        )
        if cursor.rowcount == 0:
            conn.rollback()
            raise StaleVersionError(
                "this artifact changed since it was opened; reload it to see the latest"
            )
        conn.execute(
            get(_FILE, "add_version"),
            {
                "artifact_id": artifact_id,
                "version": expected_version + 1,
                "title": clean_title,
                "content": json.dumps(content, ensure_ascii=False),
                "sources": _json_ids(tuple(sources)),
                "author": author,
                "note": note,
            },
        )
        conn.commit()
        saved = load(conn, course_id, artifact_id)
    assert saved is not None
    return saved


def rename(
    course_id: UUID, artifact_id: UUID, *, expected_version: int, title: str
) -> Artifact:
    """Change only the title: content and sources stay, and the rename is
    a version in the history like any other save."""
    clean_title = title.strip()[:TITLE_MAX_LENGTH]
    with connection() as conn:
        current = load(conn, course_id, artifact_id)
        if current is None:
            raise StaleVersionError("artifact not found")
        cursor = conn.execute(
            get(_FILE, "rename"),
            {
                "artifact_id": artifact_id,
                "course_id": course_id,
                "expected_version": expected_version,
                "title": clean_title,
            },
        )
        if cursor.rowcount == 0:
            conn.rollback()
            raise StaleVersionError(
                "this artifact changed since it was opened; reload it to see the latest"
            )
        conn.execute(
            get(_FILE, "add_version"),
            {
                "artifact_id": artifact_id,
                "version": expected_version + 1,
                "title": clean_title,
                "content": json.dumps(current.content, ensure_ascii=False),
                "sources": _json_ids(current.sources),
                "author": "you",
                "note": "Renamed",
            },
        )
        conn.commit()
        renamed = load(conn, course_id, artifact_id)
    assert renamed is not None
    return renamed


def versions(artifact_id: UUID) -> list[ArtifactVersion]:
    with connection() as conn:
        rows = conn.execute(
            get(_FILE, "versions"), {"artifact_id": artifact_id}
        ).fetchall()
    return [
        ArtifactVersion(
            version=row["version"],
            title=row["title"],
            author=row["author"],
            note=row["note"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


def version(artifact_id: UUID, number: int) -> ArtifactVersion | None:
    with connection() as conn:
        row = conn.execute(
            get(_FILE, "version"), {"artifact_id": artifact_id, "version": number}
        ).fetchone()
    if row is None:
        return None
    return ArtifactVersion(
        version=row["version"],
        title=row["title"],
        author=row["author"],
        note=row["note"],
        created_at=row["created_at"],
        content=row["content"] if isinstance(row["content"], dict) else {},
        sources=_ids(row["sources"]),
    )


def delete(course_id: UUID, artifact_id: UUID) -> bool:
    with connection() as conn:
        cursor = conn.execute(
            get(_FILE, "delete"), {"course_id": course_id, "artifact_id": artifact_id}
        )
        conn.commit()
    return cursor.rowcount > 0


def chunks_in_course(
    course_id: UUID, chunk_ids: list[UUID] | tuple[UUID, ...]
) -> set[UUID]:
    if not chunk_ids:
        return set()
    with connection() as conn:
        rows = conn.execute(
            get(_FILE, "chunks_in_course"),
            {"course_id": course_id, "chunk_ids": _json_ids(tuple(chunk_ids))},
        ).fetchall()
    return {row["chunk_id"] for row in rows}
