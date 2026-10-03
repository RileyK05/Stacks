"""Source containment and bounded passage similarity; no prerequisite graph."""

from __future__ import annotations

from src.backend.graph.edges import build_course_edges, build_source_edges
from src.backend.graph.view import course_graph

__all__ = [
    "build_course_edges",
    "build_source_edges",
    "course_graph",
]
