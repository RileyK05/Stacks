from dataclasses import replace
from uuid import uuid4

import numpy as np
import pytest
from src.backend.common import provider
from src.backend.common.db import connection
from src.backend.graph.view import course_graph
from src.backend.ingest.extract import ExtractedSource, LocatorSpan
from src.backend.rag import store
from src.backend.rag.config import load_policy
from src.backend.rag.segment import segment, windows
from src.backend.retrieval.funnel import keyword_seam
from tests.factories import insert_source, make_course


def _extracted(text: str) -> ExtractedSource:
    return ExtractedSource(
        text, (LocatorSpan(uuid4(), "section", 0, len(text), "Notes"),)
    )


def _publish(text: str):
    course = make_course("Passages")
    source = insert_source(course.course_id)
    with connection() as conn:
        prepared = store.prepare(conn, source, _extracted(text), load_policy())
        store.publish(conn, prepared)
        conn.commit()
    return course, source, prepared


def test_proof_is_one_passage_with_bounded_windows() -> None:
    text = (
        "# Chapter 1\n\nTheorem. This sequence converges.\n\n"
        "Proof. Assume convergence.\n\n"
    )
    text += "\n\n".join(
        f"Step {i}: choose epsilon and the next bound." for i in range(90)
    )
    text += "\n\nTherefore it converges. QED\n\nA separate remark."
    result = segment(text, load_policy(), token_count=len)
    proof = [span for span in result.passages if span.kind == "proof"]
    assert len(proof) == 1
    value = text[proof[0].start : proof[0].end]
    assert value.startswith("Theorem.") and "Step 89" in value and "QED" in value
    assert "separate remark" not in value
    bounded = windows(value, 128, 16, token_count=len)
    assert len(bounded) > 1
    assert all(len(value[a:b]) <= 128 for a, b in bounded)
    covered = set().union(*(set(range(a, b)) for a, b in bounded))
    assert covered == set(range(len(value)))
    assert "".join(text[p.start : p.end] for p in result.passages) == text


def test_semantic_change_splits_short_unrelated_paragraphs() -> None:
    text = "Limits describe nearby behavior.\n\nA grape boycott is collective activism."

    def encode(values):
        return [[1, 0] if "Limits" in value else [0, 1] for value in values]

    result = segment(text, load_policy(), encode=encode, token_count=len)
    assert len(result.passages) == 2 and result.semantic_used
    assert result.passages[1].boundary == "semantic"


def test_boundary_failure_preserves_all_source_text() -> None:
    text = "An introduction.\n\nThis assumes independence.\n\nThen apply the argument."

    def broken(values):
        raise RuntimeError("encoder unavailable")

    result = segment(text, load_policy(), encode=broken, token_count=len)
    assert not result.semantic_used and result.warning
    assert "".join(text[p.start : p.end] for p in result.passages) == text


def test_five_chapters_have_real_parent_nodes_and_no_prerequisite_edges() -> None:
    text = "\n\n".join(
        f"# Chapter {i}\n\nContent for chapter {i}." for i in range(1, 6)
    )
    course, _, prepared = _publish(text)
    graph = course_graph(course.course_id)
    chapters = {node.id for node in graph.nodes if node.kind == "container"}
    assert len(chapters) == 5
    assert all(p["container_id"] in chapters for p in prepared.passages)
    assert {edge.kind for edge in graph.edges} == {"contains"}


def test_retry_keeps_passage_identities() -> None:
    text = "# Chapter 1\n\nThe derivative measures change."
    _, source, before = _publish(text)
    with connection() as conn:
        after = store.prepare(conn, source, _extracted(text), load_policy())
        store.publish(conn, after)
        conn.commit()
    assert [p["chunk_id"] for p in before.passages] == [
        p["chunk_id"] for p in after.passages
    ]


def test_unchanged_text_does_not_let_an_older_preparation_overwrite_publication():
    text = "Limits describe nearby behavior."
    _, source, _ = _publish(text)
    with connection() as conn:
        first = store.prepare(conn, source, _extracted(text), load_policy())
        stale = store.prepare(conn, source, _extracted(text), load_policy())
        assert first.revision != stale.revision
        store.publish(conn, first)
        conn.commit()
        with pytest.raises(ValueError, match="source changed"):
            store.publish(conn, stale)
        conn.rollback()
        active = conn.execute(
            "SELECT revision FROM source_indexes WHERE source_id = ?", (source,)
        ).fetchone()
        assert active["revision"] == first.revision


def test_failed_encoding_keeps_the_previous_index(monkeypatch) -> None:
    course, source, before = _publish("Derivatives measure change.")
    monkeypatch.setattr(provider, "embed_chunks", lambda texts: [[float("nan")]])
    with connection() as conn:
        with pytest.raises(ValueError, match="invalid search-window"):
            store.prepare(conn, source, _extracted("A replacement."), load_policy())
        hits = keyword_seam(conn, course.course_id, "derivatives", 10)
    assert set(hits) == {p["chunk_id"] for p in before.passages}


def test_failed_publication_rolls_back_every_index_row() -> None:
    course, source, before = _publish("Derivatives measure change.")
    with connection() as conn:
        prepared = store.prepare(
            conn, source, _extracted("A replacement."), load_policy()
        )
        bad_windows = tuple(
            {**row, "embedding": b"bad"} for row in prepared.search_windows
        )
        with pytest.raises(Exception, match="CHECK constraint"):
            store.publish(conn, replace(prepared, search_windows=bad_windows))
        conn.rollback()
        hits = keyword_seam(conn, course.course_id, "derivatives", 10)
        index = conn.execute(
            "SELECT revision FROM source_indexes WHERE source_id = ?", (source,)
        ).fetchone()
    assert set(hits) == {p["chunk_id"] for p in before.passages}
    assert index["revision"] == before.revision


def test_deleted_course_cannot_publish_a_prepared_index() -> None:
    course, source, _ = _publish("Limits describe nearby behavior.")
    with connection() as conn:
        prepared = store.prepare(
            conn, source, _extracted("A replacement."), load_policy()
        )
        conn.execute(
            "UPDATE courses SET deleted_at = now_utc(), purge_after = now_utc()"
            " WHERE course_id = ?",
            (course.course_id,),
        )
        conn.commit()
        with pytest.raises(ValueError, match="source changed"):
            store.publish(conn, prepared)
        conn.rollback()


def test_window_embeddings_are_normalized_and_graph_selection_is_scoped() -> None:
    course, source, prepared = _publish("Limits describe nearby behavior.")
    assert course_graph(course.course_id, []).nodes == []
    assert course_graph(course.course_id, [source]).nodes
    for row in prepared.search_windows:
        vector = np.frombuffer(row["embedding"], dtype="<f4")
        assert np.linalg.norm(vector) == pytest.approx(1.0)
