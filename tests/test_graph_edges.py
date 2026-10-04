from __future__ import annotations

from uuid import UUID, uuid4

import numpy as np
from src.backend.common.db import connection
from src.backend.common.embeddings_config import load_embedding_policy
from src.backend.common.queries import get
from src.backend.graph import edges, vectors
from src.backend.graph.view import course_graph
from src.backend.rag.config import load_policy
from src.backend.retrieval import funnel
from src.backend.retrieval.funnel import Candidate
from tests.factories import add_chunk, chunk_source_locator, make_course


def _chunks(count: int = 3) -> tuple[UUID, list[UUID], list[UUID]]:
    course_id = make_course("Graph rebuild").course_id
    chunk_ids = [
        add_chunk(course_id, f"Substantive graph passage number {index}.")
        for index in range(count)
    ]
    source_ids = [chunk_source_locator(chunk_id)[0] for chunk_id in chunk_ids]
    return course_id, chunk_ids, source_ids


def _policy(*, neighbors: int = 1):
    return load_policy().model_copy(
        update={
            "similarity_floor": 0.7,
            "similarity_neighbors": neighbors,
            "similarity_block_rows": 1,
        }
    )


def _edge_pairs(course_id: UUID, model: str) -> set[frozenset[UUID]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT chunk_a, chunk_b FROM graph_edges WHERE course_id=? AND model=?",
            (course_id, model),
        ).fetchall()
    return {frozenset((row["chunk_a"], row["chunk_b"])) for row in rows}


def test_source_refresh_rebuilds_asymmetric_course_neighbor_union(monkeypatch):
    course_id, chunk_ids, source_ids = _chunks()
    theta_b, theta_c = np.deg2rad(30), np.deg2rad(50)
    matrix = np.asarray(
        [
            [1.0, 0.0],
            [np.cos(theta_b), np.sin(theta_b)],
            [np.cos(theta_c), np.sin(theta_c)],
        ],
        dtype=np.float32,
    )
    monkeypatch.setattr(
        edges,
        "load_course_vectors",
        lambda conn, course, model: (chunk_ids, matrix, []),
    )
    policy = _policy()
    with connection() as conn:
        edges.build_course_edges(conn, course_id, policy=policy, model="test")
        conn.commit()
    before = _edge_pairs(course_id, "test")
    assert frozenset((chunk_ids[0], chunk_ids[1])) in before
    assert frozenset((chunk_ids[1], chunk_ids[2])) in before

    edges.build_source_edges(source_ids[1], policy=policy, model="test")
    assert _edge_pairs(course_id, "test") == before


def test_empty_vector_refresh_clears_all_stale_course_edges(monkeypatch):
    course_id, chunk_ids, source_ids = _chunks(2)
    matrix = np.asarray([[1.0, 0.0], [0.9, 0.1]], dtype=np.float32)
    monkeypatch.setattr(
        edges,
        "load_course_vectors",
        lambda conn, course, model: (chunk_ids, matrix, []),
    )
    policy = _policy()
    with connection() as conn:
        edges.build_course_edges(conn, course_id, policy=policy, model="test")
        conn.commit()
    assert _edge_pairs(course_id, "test")

    monkeypatch.setattr(
        edges,
        "load_course_vectors",
        lambda conn, course, model: ([], np.zeros((0, 0), np.float32), []),
    )
    assert edges.build_source_edges(source_ids[0], policy=policy, model="test") == 0
    assert _edge_pairs(course_id, "test") == set()


def test_valid_vectors_uses_expected_dimension_not_first_row(monkeypatch):
    rows = [
        {"dimension": 3, "embedding": np.asarray([1, 0, 0], dtype="<f4").tobytes()},
        {"dimension": 2, "embedding": np.asarray([0, 1], dtype="<f4").tobytes()},
        {"dimension": 2, "embedding": np.asarray([np.nan, 1], dtype="<f4").tobytes()},
    ]
    monkeypatch.setattr(
        vectors,
        "load_embedding_policy",
        lambda: load_embedding_policy().model_copy(update={"dimension": 2}),
    )
    kept, matrix = vectors.valid_vectors(rows)
    assert [row["dimension"] for row in kept] == [2]
    assert matrix.shape == (1, 2)
    assert np.allclose(matrix, [[0.0, 1.0]])


def test_graph_seam_and_view_hide_edges_with_stale_endpoint_vectors():
    course_id, chunk_ids, source_ids = _chunks(2)
    model = load_embedding_policy().model
    with connection() as conn:
        conn.execute(
            get("graph", "insert_graph_edge"),
            {
                "edge_id": uuid4(),
                "course_id": course_id,
                "model": model,
                "chunk_a": chunk_ids[0],
                "chunk_b": chunk_ids[1],
                "weight": 0.95,
                "algorithm_version": "test",
            },
        )
        for chunk_id, dimension in zip(chunk_ids, (2, 3), strict=True):
            vector = np.zeros(dimension, dtype="<f4")
            vector[0] = 1.0
            conn.execute(
                "INSERT INTO chunk_embeddings(chunk_id, model, dimension, embedding) "
                "VALUES (?, ?, ?, ?)",
                (chunk_id, model, dimension, vector.tobytes()),
            )
        hit = Candidate(
            chunk_id=chunk_ids[0],
            source_id=source_ids[0],
            locator_id=None,
            chunk_index=0,
            text="Substantive graph passage number 0.",
            layers=frozenset({"keyword"}),
            rank=1.0,
        )
        assert not funnel.graph_seam(
            conn, course_id, {chunk_ids[0]: hit}, 5, model, dimension=2
        )
        conn.commit()

    graph = course_graph(course_id)
    assert not any(edge.kind == "similar" for edge in graph.edges)
