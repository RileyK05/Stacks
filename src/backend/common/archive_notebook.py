"""Portable chat and artifact history for .course format v2.

Evidence cited by the saved notebook and candidate passages needed to preserve
workspace numbering travel in the archive. On import each becomes a
source-scoped snapshot, so subsequent ingestion cannot change old references.
"""

from __future__ import annotations

import json
from contextlib import suppress
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from src.backend.common.db import Connection, connection, json_ids
from src.backend.common.queries import get
from src.backend.common.schemas.work import ArchivedWork
from src.backend.common.work_archive import export_work, import_work
from src.backend.student_model.archive import (
    LearningArchive,
    export_learning,
    import_learning,
)


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
    # None means an archive written before citation attribution was retained;
    # [] is an explicit record that no retrieved passage was cited.
    cited_chunk_ids: list[UUID] | None = None
    citation_markers: list[int] | None = None
    model: str | None = None

    @model_validator(mode="after")
    def validate_citation_mapping(self) -> Trace:
        if (self.cited_chunk_ids is None) != (self.citation_markers is None):
            raise ValueError("trace citation IDs and markers must be stored together")
        if self.cited_chunk_ids is not None and self.citation_markers is not None:
            if len(self.cited_chunk_ids) != len(self.citation_markers):
                raise ValueError("trace citation IDs and markers must align")
            if any(
                marker < 1
                or marker > len(self.chunk_ids)
                or self.chunk_ids[marker - 1] != chunk_id
                for chunk_id, marker in zip(
                    self.cited_chunk_ids, self.citation_markers, strict=True
                )
            ):
                raise ValueError("trace citation marker does not match its candidate")
        return self


def _payload_uuid_list(payload: Any, key: str) -> list[UUID]:
    """Return valid UUIDs from a supported chunk-ID array, ignoring bad values."""
    if not isinstance(payload, dict):
        return []
    raw = payload.get(key)
    if not isinstance(raw, list):
        return []
    result: list[UUID] = []
    for value in raw:
        if isinstance(value, str):
            with suppress(ValueError):
                result.append(UUID(value))
    return result


class Message(ArchiveModel):
    message_id: UUID | None = None
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
    kind: Literal[
        "doc", "sheet", "slides", "quiz", "flashcards", "code", "chart", "mind_map"
    ]
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
    learning: LearningArchive | None = None
    work_sessions: list[ArchivedWork] = Field(default_factory=list)


def export_notebook(course_id: UUID) -> Notebook:
    with connection() as conn:
        study = export_learning(conn, course_id)
        work_sessions = export_work(conn, course_id)
        conversations: list[Conversation] = []
        cited_ids: set[UUID] = set()
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
            for message in messages:
                cited_ids.update(_payload_uuid_list(message.payload, "chunk_ids"))
                cited_ids.update(
                    _payload_uuid_list(message.payload, "material_chunk_ids")
                )
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
        for work in work_sessions:
            for turn in work.turns:
                if turn.reply.trace_id:
                    with suppress(ValueError):
                        trace_ids.add(UUID(str(turn.reply.trace_id)))
                for citation in turn.reply.citations:
                    with suppress(ValueError):
                        cited_ids.add(UUID(str(citation.chunk_id)))
        traces: list[Trace] = []
        for trace_id in sorted(trace_ids, key=str):
            row = conn.execute(
                get("archive_notebook", "trace"),
                {"trace_id": trace_id, "course_id": course_id},
            ).fetchone()
            if row is None:
                continue
            payload = row["retrieved_chunk_ids"]
            chunk_ids = _payload_uuid_list(payload, "chunk_ids")
            has_citation_mapping = (
                isinstance(payload, dict) and "cited_chunk_ids" in payload
            )
            cited_chunk_ids = (
                _payload_uuid_list(payload, "cited_chunk_ids")
                if has_citation_mapping
                else None
            )
            citation_markers = (
                payload.get("citation_markers")
                if has_citation_mapping and isinstance(payload, dict)
                else None
            )
            traces.append(
                Trace(
                    trace_id=trace_id,
                    query=row["query"],
                    chunk_ids=chunk_ids,
                    cited_chunk_ids=cited_chunk_ids,
                    citation_markers=citation_markers,
                    model=row["model"],
                )
            )
            cited_ids.update(chunk_ids)
            cited_ids.update(cited_chunk_ids or [])
        for suite in study.suites:
            cited_ids.update(
                UUID(source["chunk_id"])
                for source in suite.evidence
                if "chunk_id" in source
            )
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
        learning=study,
        work_sessions=work_sessions,
    )


def _remap_payload(
    payload: dict[str, Any],
    chunk_map: dict[UUID, UUID],
    trace_map: dict[UUID, UUID],
    suite_map: dict[UUID, UUID],
) -> dict[str, Any]:
    result = dict(payload)
    for key, mapping in (("trace_id", trace_map),):
        raw = result.get(key)
        if isinstance(raw, str):
            with suppress(ValueError):
                result[key] = str(mapping.get(UUID(raw), raw))
    for chunk_key in ("chunk_ids", "material_chunk_ids"):
        raw_chunks = result.get(chunk_key)
        if isinstance(raw_chunks, list):
            mapped: list[Any] = []
            for value in raw_chunks:
                if isinstance(value, str):
                    with suppress(ValueError):
                        value = str(chunk_map.get(UUID(value), UUID(value)))
                mapped.append(value)
            result[chunk_key] = mapped
    if isinstance(result.get("workspace"), list):
        items = []
        for item in result["workspace"]:
            if isinstance(item, dict) and item.get("type") == "quiz":
                item = dict(item)
                raw = item.pop("practice_id", None)
                if raw:
                    with suppress(ValueError):
                        mapped_suite = suite_map.get(UUID(raw))
                        if mapped_suite:
                            item["practice_id"] = str(mapped_suite)
            items.append(item)
        result["workspace"] = items
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
        cited_ids.update(trace.cited_chunk_ids or [])
    for artifact in notebook.artifacts:
        cited_ids.update(artifact.sources)
        for version in artifact.versions:
            cited_ids.update(version.sources)
    for conversation in notebook.conversations:
        for message in conversation.messages:
            for field in ("chunk_ids", "material_chunk_ids"):
                cited_ids.update(_payload_uuid_list(message.payload, field))
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
                    {
                        "chunk_ids": [str(chunk_map[c]) for c in trace.chunk_ids],
                        **(
                            {
                                "cited_chunk_ids": [
                                    str(chunk_map[c]) for c in trace.cited_chunk_ids
                                ],
                                "citation_markers": trace.citation_markers,
                            }
                            if trace.cited_chunk_ids is not None
                            else {}
                        ),
                    }
                ),
                "model": trace.model,
            },
        )
    suite_map = (
        import_learning(conn, course_id, notebook.learning, source_map, chunk_map)
        if notebook.learning
        else {}
    )
    conversation_map: dict[str, str] = {}
    message_map: dict[str, str] = {}
    for conversation in notebook.conversations:
        conversation_id = uuid4()
        conversation_map[str(conversation.conversation_id)] = str(conversation_id)
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
            message_id = uuid4()
            if message.message_id is not None:
                message_map[str(message.message_id)] = str(message_id)
            conn.execute(
                get("archive_notebook", "insert_message"),
                {
                    "message_id": message_id,
                    "conversation_id": conversation_id,
                    "seq": message.seq,
                    "role": message.role,
                    "text": message.text,
                    "trace_id": (
                        trace_map.get(message.trace_id) if message.trace_id else None
                    ),
                    "payload": json.dumps(
                        _remap_payload(message.payload, chunk_map, trace_map, suite_map)
                    ),
                    "created_at": message.created_at,
                },
            )
    artifact_map = {str(a.artifact_id): str(uuid4()) for a in notebook.artifacts}
    for artifact in notebook.artifacts:
        artifact_id = UUID(artifact_map[str(artifact.artifact_id)])
        mapped = [str(chunk_map[chunk]) for chunk in artifact.sources]
        origin = dict(artifact.origin)
        if isinstance(origin.get("map_origin"), dict):
            map_origin = dict(origin["map_origin"])
            if map_origin.get("artifact_id"):
                mapped_id = artifact_map.get(str(map_origin["artifact_id"]))
                if mapped_id:
                    map_origin["artifact_id"] = mapped_id
                else:
                    map_origin = {}
            elif map_origin.get("message_id"):
                mapped_id = message_map.get(str(map_origin["message_id"]))
                if mapped_id:
                    map_origin["message_id"] = mapped_id
                else:
                    map_origin = {}
            origin["map_origin"] = map_origin
            origin["map_request_id"] = str(uuid4())
            if origin.get("message_id"):
                origin["message_id"] = message_map.get(str(origin["message_id"]))
        if origin.get("by") == "chat":
            prior_message = str(origin.get("message_id", ""))
            if prior_message in message_map:
                origin["message_id"] = message_map[prior_message]
                origin["conversation_id"] = conversation_map.get(
                    str(origin.get("conversation_id", "")), ""
                )
            else:
                origin["adopted"] = False
        conn.execute(
            get("archive_notebook", "insert_artifact"),
            {
                "artifact_id": artifact_id,
                "course_id": course_id,
                "kind": artifact.kind,
                "title": artifact.title,
                "content": json.dumps(artifact.content),
                "sources": json.dumps(mapped),
                "origin": json.dumps(origin),
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

    import_work(
        conn, course_id, notebook.work_sessions, chunk_map, source_map, trace_map
    )

    from src.backend.common import course_memory

    course_memory.refresh(conn, course_id)
