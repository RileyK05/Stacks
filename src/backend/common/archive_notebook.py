"""Portable chat and artifact history for .course format v2.

Only evidence actually cited by the saved notebook travels in the archive.
On import it becomes a source-scoped snapshot, so subsequent ingestion can
rebuild chunks without changing what an old citation meant.
"""

from __future__ import annotations

import json
from contextlib import suppress
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from src.backend.common.db import Connection, connection, json_ids
from src.backend.common.queries import get


class ArchiveModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Citation(ArchiveModel):
    chunk_id: UUID
    source_id: UUID
    chunk_index: int
    text: str
    locator_type: str
    label: str
    description: str | None = None


class Trace(ArchiveModel):
    trace_id: UUID
    query: str
    chunk_ids: list[UUID]
    model: str | None = None


class Message(ArchiveModel):
    seq: int = Field(ge=1)
    role: Literal["user", "assistant"]
    text: str
    trace_id: UUID | None = None
    payload: dict[str, Any]
    created_at: datetime


class Conversation(ArchiveModel):
    conversation_id: UUID
    title: str
    model_choice: dict[str, Any] | None = None
    source_ids: list[UUID] | None = None
    summary: str = ""
    summary_through: int = 0
    created_at: datetime
    updated_at: datetime
    messages: list[Message]


class Version(ArchiveModel):
    version: int = Field(ge=1)
    title: str
    content: dict[str, Any]
    sources: list[UUID]
    author: Literal["you", "model"]
    note: str
    created_at: datetime


class Artifact(ArchiveModel):
    artifact_id: UUID
    kind: Literal["doc", "sheet", "slides", "quiz", "flashcards", "code", "chart"]
    title: str
    content: dict[str, Any]
    sources: list[UUID]
    origin: dict[str, Any]
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    versions: list[Version]


class Notebook(ArchiveModel):
    conversations: list[Conversation]
    traces: list[Trace]
    citations: list[Citation]
    artifacts: list[Artifact]


def export_notebook(course_id: UUID) -> Notebook:
    with connection() as conn:
        conversations: list[Conversation] = []
        trace_ids: set[UUID] = set()
        for row in conn.execute(
            get("archive_notebook", "conversations"), {"course_id": course_id}
        ).fetchall():
            messages = [
                Message.model_validate(message)
                for message in conn.execute(
                    get("archive_notebook", "messages"),
                    {"conversation_id": row["conversation_id"]},
                ).fetchall()
            ]
            trace_ids.update(m.trace_id for m in messages if m.trace_id is not None)
            conversations.append(
                Conversation(
                    conversation_id=row["conversation_id"],
                    title=row["title"],
                    model_choice=row["model_choice"],
                    source_ids=row["source_ids"],
                    summary=row["summary"],
                    summary_through=row["summary_through"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    messages=messages,
                )
            )
        artifacts: list[Artifact] = []
        cited_ids: set[UUID] = set()
        for row in conn.execute(
            get("archive_notebook", "artifacts"), {"course_id": course_id}
        ).fetchall():
            versions = [
                Version.model_validate(version)
                for version in conn.execute(
                    get("archive_notebook", "versions"),
                    {"artifact_id": row["artifact_id"]},
                ).fetchall()
            ]
            artifact = Artifact(
                artifact_id=row["artifact_id"],
                kind=row["kind"],
                title=row["title"],
                content=row["content"],
                sources=row["sources"],
                origin=row["origin"],
                version=row["version"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                versions=versions,
            )
            artifacts.append(artifact)
            cited_ids.update(artifact.sources)
            for version in versions:
                cited_ids.update(version.sources)
        traces: list[Trace] = []
        for trace_id in trace_ids:
            row = conn.execute(
                get("archive_notebook", "trace"),
                {"trace_id": trace_id, "course_id": course_id},
            ).fetchone()
            if row is None:
                continue
            payload = row["retrieved_chunk_ids"]
            chunk_ids = (
                [UUID(cid) for cid in payload.get("chunk_ids", [])]
                if isinstance(payload, dict)
                else []
            )
            traces.append(
                Trace(
                    trace_id=trace_id,
                    query=row["query"],
                    chunk_ids=chunk_ids,
                    model=row["model"],
                )
            )
            cited_ids.update(chunk_ids)
        citations: list[Citation] = []
        if cited_ids:
            rows = conn.execute(
                get("retrieval_traces", "chunks_with_locators_by_ids"),
                {"chunk_ids": json_ids(sorted(cited_ids, key=str))},
            ).fetchall()
            citations = [
                Citation.model_validate(
                    {key: row[key] for key in Citation.model_fields}
                )
                for row in rows
            ]
    return Notebook(
        conversations=conversations,
        traces=traces,
        citations=citations,
        artifacts=artifacts,
    )


def _remap_payload(
    payload: dict[str, Any], chunk_map: dict[UUID, UUID], trace_map: dict[UUID, UUID]
) -> dict[str, Any]:
    result = dict(payload)
    for key, mapping in (("trace_id", trace_map),):
        raw = result.get(key)
        if isinstance(raw, str):
            with suppress(ValueError):
                result[key] = str(mapping.get(UUID(raw), raw))
    raw_chunks = result.get("chunk_ids")
    if isinstance(raw_chunks, list):
        mapped: list[Any] = []
        for value in raw_chunks:
            if isinstance(value, str):
                with suppress(ValueError):
                    value = str(chunk_map.get(UUID(value), UUID(value)))
            mapped.append(value)
        result["chunk_ids"] = mapped
    return result


def import_notebook(
    conn: Connection,
    course_id: UUID,
    notebook: Notebook,
    source_map: dict[UUID, UUID],
) -> None:
    cited_ids = {citation.chunk_id for citation in notebook.citations}
    for trace in notebook.traces:
        cited_ids.update(trace.chunk_ids)
    for artifact in notebook.artifacts:
        cited_ids.update(artifact.sources)
        for version in artifact.versions:
            cited_ids.update(version.sources)
    for conversation in notebook.conversations:
        for message in conversation.messages:
            raw_chunks = message.payload.get("chunk_ids")
            for raw in raw_chunks if isinstance(raw_chunks, list) else []:
                if isinstance(raw, str):
                    with suppress(ValueError):
                        cited_ids.add(UUID(raw))
    chunk_map = {old: uuid4() for old in cited_ids}
    trace_map = {trace.trace_id: uuid4() for trace in notebook.traces}
    for citation in notebook.citations:
        source_id = source_map.get(citation.source_id)
        if source_id is None:
            continue
        conn.execute(
            get("archive_notebook", "insert_snapshot"),
            {
                "chunk_id": chunk_map[citation.chunk_id],
                "course_id": course_id,
                "source_id": source_id,
                "chunk_index": citation.chunk_index,
                "text": citation.text,
                "locator_type": citation.locator_type,
                "label": citation.label,
                "description": citation.description,
            },
        )
    for trace in notebook.traces:
        conn.execute(
            get("archive_notebook", "insert_trace"),
            {
                "trace_id": trace_map[trace.trace_id],
                "course_id": course_id,
                "query": trace.query,
                "chunk_ids": json.dumps(
                    {"chunk_ids": [str(chunk_map[c]) for c in trace.chunk_ids]}
                ),
                "model": trace.model,
            },
        )
    for conversation in notebook.conversations:
        conversation_id = uuid4()
        selected = (
            [str(source_map[s]) for s in conversation.source_ids if s in source_map]
            if conversation.source_ids is not None
            else None
        )
        conn.execute(
            get("archive_notebook", "insert_conversation"),
            {
                "conversation_id": conversation_id,
                "course_id": course_id,
                "title": conversation.title,
                "model_choice": (
                    json.dumps(conversation.model_choice)
                    if conversation.model_choice is not None
                    else None
                ),
                "source_ids": json.dumps(selected) if selected is not None else None,
                "summary": conversation.summary,
                "summary_through": conversation.summary_through,
                "created_at": conversation.created_at,
                "updated_at": conversation.updated_at,
            },
        )
        for message in conversation.messages:
            conn.execute(
                get("archive_notebook", "insert_message"),
                {
                    "message_id": uuid4(),
                    "conversation_id": conversation_id,
                    "seq": message.seq,
                    "role": message.role,
                    "text": message.text,
                    "trace_id": (
                        trace_map.get(message.trace_id) if message.trace_id else None
                    ),
                    "payload": json.dumps(
                        _remap_payload(message.payload, chunk_map, trace_map)
                    ),
                    "created_at": message.created_at,
                },
            )
    for artifact in notebook.artifacts:
        artifact_id = uuid4()
        mapped = [str(chunk_map[chunk]) for chunk in artifact.sources]
        conn.execute(
            get("archive_notebook", "insert_artifact"),
            {
                "artifact_id": artifact_id,
                "course_id": course_id,
                "kind": artifact.kind,
                "title": artifact.title,
                "content": json.dumps(artifact.content),
                "sources": json.dumps(mapped),
                "origin": json.dumps(artifact.origin),
                "version": artifact.version,
                "created_at": artifact.created_at,
                "updated_at": artifact.updated_at,
            },
        )
        for version in artifact.versions:
            conn.execute(
                get("archive_notebook", "insert_version"),
                {
                    "artifact_id": artifact_id,
                    "version": version.version,
                    "title": version.title,
                    "content": json.dumps(version.content),
                    "sources": json.dumps([str(chunk_map[c]) for c in version.sources]),
                    "author": version.author,
                    "note": version.note,
                    "created_at": version.created_at,
                },
            )
