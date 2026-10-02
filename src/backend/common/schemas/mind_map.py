from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MapNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    label: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=1200)
    sources: list[int] = Field(min_length=1, max_length=8)


class MapEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=40)
    target: str = Field(min_length=1, max_length=40)
    kind: Literal["branch", "similarity"]
    label: str = Field(min_length=1, max_length=100)
    explanation: str = Field(min_length=1, max_length=1200)
    sources: list[int] = Field(min_length=1, max_length=8)


class MindMapContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[MapNode] = Field(default_factory=list, max_length=24)
    edges: list[MapEdge] = Field(default_factory=list, max_length=36)

    @model_validator(mode="after")
    def _forest(self) -> MindMapContent:
        if not self.nodes and not self.edges:
            return self
        if len(self.nodes) < 2 or not self.edges:
            raise ValueError("a map needs at least two connected nodes")
        ids = {node.id for node in self.nodes}
        labels = {" ".join(node.label.casefold().split()) for node in self.nodes}
        if len(ids) != len(self.nodes) or len(labels) != len(self.nodes):
            raise ValueError("map nodes need unique IDs and labels")
        parents: dict[str, str] = {}
        seen: set[tuple[str, ...]] = set()
        touched: set[str] = set()
        for edge in self.edges:
            if edge.source not in ids or edge.target not in ids:
                raise ValueError("a connection names a missing node")
            if edge.source == edge.target:
                raise ValueError("a node cannot connect to itself")
            pair = tuple(sorted((edge.source, edge.target)))
            if pair in seen:
                raise ValueError("a pair of nodes can have only one connection")
            seen.add(pair)
            touched.update(pair)
            if edge.kind == "branch":
                if edge.target in parents:
                    raise ValueError("a topic branch can have only one parent")
                parents[edge.target] = edge.source
        if touched != ids:
            raise ValueError("every node must have a connection")
        for node_id in ids:
            path: set[str] = set()
            while node_id in parents:
                if node_id in path:
                    raise ValueError("topic branches cannot form a cycle")
                path.add(node_id)
                node_id = parents[node_id]
        for node in self.nodes:
            if not node.label.strip() or not node.summary.strip():
                raise ValueError("nodes need a meaningful label and summary")
            if re.fullmatch(
                r"(?:broad|main|central|root)?\s*(?:topic|concept|node)\s*\d*"
                r"|course material(?:s)?|overview|introduction",
                node.label.strip(),
                re.IGNORECASE,
            ):
                raise ValueError("use actual course subjects, not placeholder topics")
        for edge in self.edges:
            if not edge.label.strip() or not edge.explanation.strip():
                raise ValueError("connections need a label and explanation")
        return self


def check_map_evidence(mapped: MindMapContent, passages: list[str]) -> None:
    def flat(text: str) -> str:
        return " ".join(text.casefold().split())

    def supports(text: str, numbers: list[int], labels: list[str]) -> bool:
        return any(
            1 <= number <= len(passages)
            and flat(text) in flat(passages[number - 1])
            and all(flat(label) in flat(text) for label in labels)
            for number in numbers
        )

    nodes = {node.id: node for node in mapped.nodes}
    for node in mapped.nodes:
        if not supports(node.summary, node.sources, [node.label]):
            raise ValueError("a map description must quote evidence naming its topic")
    for edge in mapped.edges:
        labels = [nodes[edge.source].label, nodes[edge.target].label]
        if not supports(edge.explanation, edge.sources, labels):
            raise ValueError("a map connection must quote evidence naming both topics")


def anchor_map_evidence(mapped: MindMapContent, passages: list[str]) -> MindMapContent:
    def excerpt(numbers: list[int], labels: list[str]) -> tuple[str, list[int]]:
        for number in numbers:
            if not 1 <= number <= len(passages):
                continue
            text = " ".join(passages[number - 1].split())
            matches = [
                re.search(re.escape(label), text, re.IGNORECASE) for label in labels
            ]
            if not all(matches):
                continue
            start = min(m.start() for m in matches if m)
            end = max(m.end() for m in matches if m)
            boundary = text.rfind(". ", 0, start)
            start = boundary + 2 if boundary >= 0 else 0
            stop = text.find(". ", end)
            stop = len(text) if stop < 0 else stop + 1
            quote = text[start:stop]
            if len(quote) <= 1200:
                return quote, [number]
        raise ValueError("no bounded source excerpt supports this map connection")

    nodes = {node.id: node for node in mapped.nodes}
    copied_nodes = []
    for node in mapped.nodes:
        summary, sources = excerpt(node.sources, [node.label])
        copied_nodes.append(
            node.model_copy(update={"summary": summary, "sources": sources})
        )
    copied_edges = []
    for edge in mapped.edges:
        quote, sources = excerpt(
            edge.sources, [nodes[edge.source].label, nodes[edge.target].label]
        )
        copied_edges.append(
            edge.model_copy(
                update={
                    "explanation": quote,
                    "sources": sources,
                    "label": "Topic connection"
                    if edge.kind == "branch"
                    else "Comparison in the reading",
                }
            )
        )
    result = MindMapContent(nodes=copied_nodes, edges=copied_edges)
    check_map_evidence(result, passages)
    return result
