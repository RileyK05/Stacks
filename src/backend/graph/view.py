from __future__ import annotations

from collections.abc import Collection
from uuid import UUID

from pydantic import BaseModel, Field
from src.backend.common.db import connection, json_ids
from src.backend.common.embeddings_config import load_embedding_policy
from src.backend.common.queries import get


class GraphNodeOut(BaseModel):
    id: UUID
    kind: str
    origin: str = "source"
    source_id: UUID
    label: str
    parent_id: UUID | None = None
    chunk_index: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    unit_kind: str | None = None


class GraphEdgeOut(BaseModel):
    source: UUID
    target: UUID
    kind: str
    weight: float | None = None
    origin: str = "source"


class CourseGraphOut(BaseModel):
    course_id: UUID
    model: str
    nodes: list[GraphNodeOut] = Field(default_factory=list)
    edges: list[GraphEdgeOut] = Field(default_factory=list)


def course_graph(
    course_id: UUID, source_ids: Collection[UUID] | None = None
) -> CourseGraphOut:
    model = load_embedding_policy().model
    params = {
        "course_id": course_id,
        "source_ids": json_ids(source_ids) if source_ids is not None else None,
    }
    with connection() as conn:
        containers = conn.execute(
            get("passages", "course_containers"), params
        ).fetchall()
        passages = conn.execute(get("passages", "course_passages"), params).fetchall()
        similarities = conn.execute(
            get("graph", "course_graph_edges"), {"course_id": course_id, "model": model}
        ).fetchall()
    nodes = [
        GraphNodeOut(
            id=row["container_id"],
            kind="source" if row["level"] == 0 else "container",
            source_id=row["source_id"],
            label=row["title"],
            origin=row["origin"],
            parent_id=row["parent_id"],
            char_start=row["char_start"],
            char_end=row["char_end"],
        )
        for row in containers
    ]
    nodes.extend(
        GraphNodeOut(
            id=row["chunk_id"],
            kind="passage",
            source_id=row["source_id"],
            label=" ".join(row["text"].split())[:120],
            parent_id=row["container_id"],
            chunk_index=row["chunk_index"],
            char_start=row["char_start"],
            char_end=row["char_end"],
            unit_kind=row["unit_kind"],
        )
        for row in passages
    )
    edges = [
        GraphEdgeOut(source=node.parent_id, target=node.id, kind="contains")
        for node in nodes
        if node.parent_id is not None
    ]
    previous: dict[UUID | None, UUID] = {}
    for row in passages:
        parent = row["container_id"]
        if parent is not None and parent in previous:
            edges.append(
                GraphEdgeOut(
                    source=previous[parent], target=row["chunk_id"], kind="next"
                )
            )
        previous[parent] = row["chunk_id"]
    eligible = {node.id for node in nodes}
    edges.extend(
        GraphEdgeOut(
            source=row["chunk_a"],
            target=row["chunk_b"],
            kind="similar",
            weight=row["weight"],
            origin="inference",
        )
        for row in similarities
        if row["chunk_a"] in eligible and row["chunk_b"] in eligible
    )
    return CourseGraphOut(course_id=course_id, model=model, nodes=nodes, edges=edges)
