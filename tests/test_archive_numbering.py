from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from src.backend.common import conversations_repo
from src.backend.common.db import connection
from src.backend.retrieval.funnel import Candidate, RetrievalResult
from src.backend.retrieval.trace import record_trace
from tests.test_course_archive import _course_with_sources, _import


def _add_candidate(course_id: UUID, source_id: UUID, text: str) -> UUID:
    locator_id, chunk_id = uuid4(), uuid4()
    with connection() as conn:
        conn.execute(
            "INSERT INTO locators (locator_id, source_id, locator_type, start, label) "
            "VALUES (?, ?, 'line_range', '0', 'line 1')",
            (locator_id, source_id),
        )
        conn.execute(
            "INSERT INTO chunks (chunk_id, source_id, locator_id, chunk_index, text) "
            "VALUES (?, ?, ?, 0, ?)",
            (chunk_id, source_id, locator_id, text),
        )
        conn.commit()
    return chunk_id


def test_sparse_workspace_numbering_and_empty_trace_survive_course_round_trip(
    client: TestClient, monkeypatch
) -> None:
    from src.backend.common import provider

    course_id = UUID(_course_with_sources(client))
    sources = client.get(f"/courses/{course_id}/sources").json()
    by_name = {source["filename"]: UUID(source["source_id"]) for source in sources}
    first = _add_candidate(course_id, by_name["notes.md"], "First candidate.")
    second = _add_candidate(course_id, by_name["week 2.txt"], "Second candidate.")
    chat = conversations_repo.create(course_id, "Sparse source numbering")
    with connection() as conn:
        _, message = conversations_repo.add_turn(
            conn,
            chat.conversation_id,
            question="Make a map",
            answer="Map ready, with no prose citations.",
            trace_id=None,
            payload={
                "chunk_ids": [],
                "material_chunk_ids": [str(first), str(second)],
                "trace_id": "",
                "model": "test-model",
                "workspace": [
                    {
                        "type": "mind_map",
                        "title": "Topics",
                        "nodes": [
                            {
                                "id": "space",
                                "label": "Space",
                                "summary": "Geometry studies space.",
                                "sources": [2],
                            },
                            {
                                "id": "geometry",
                                "label": "Geometry",
                                "summary": "Studies lengths and shapes.",
                                "sources": [2],
                            },
                        ],
                        "edges": [
                            {
                                "source": "space",
                                "target": "geometry",
                                "kind": "branch",
                                "label": "example",
                                "explanation": "Geometry studies space.",
                                "sources": [2],
                            }
                        ],
                    }
                ],
            },
        )
        trace = record_trace(
            conn,
            course_id,
            "uncited retrieval",
            RetrievalResult(
                (
                    Candidate(
                        first,
                        by_name["notes.md"],
                        None,
                        0,
                        "First candidate.",
                        frozenset({"keyword"}),
                        1.0,
                    ),
                    Candidate(
                        second,
                        by_name["week 2.txt"],
                        None,
                        0,
                        "Second candidate.",
                        frozenset({"keyword"}),
                        0.5,
                    ),
                )
            ),
            cited=(),
        )
        conversations_repo.add_turn(
            conn,
            chat.conversation_id,
            question="Another retrieval",
            answer="No cited evidence.",
            trace_id=trace.trace_id,
            payload={
                "chunk_ids": [],
                "material_chunk_ids": [],
                "trace_id": str(trace.trace_id),
                "model": "test-model",
            },
        )
        conn.commit()

    saved = client.post(
        f"/courses/{course_id}/artifacts/from-message",
        json={"message_id": str(message.message_id), "item_index": 0},
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["sources"] == [str(second)]

    path = Path(client.post(f"/courses/{course_id}/export").json()["path"])
    new_id = _import(client, path).json()["course"]["course_id"]
    imported_chunks = {}
    with connection() as conn:
        rows = conn.execute(
            "SELECT chunk_id, source_id, text FROM citation_snapshots "
            "WHERE course_id = ?",
            (UUID(new_id),),
        ).fetchall()
        imported_chunks = {row["text"]: row["chunk_id"] for row in rows}
        persisted = conn.execute(
            "SELECT retrieved_chunk_ids FROM retrieval_traces "
            "WHERE course_id = ? AND query = 'uncited retrieval'",
            (UUID(new_id),),
        ).fetchone()
    assert persisted["retrieved_chunk_ids"]["cited_chunk_ids"] == []
    assert imported_chunks["Second candidate."] != second

    chats = client.get(f"/courses/{new_id}/conversations").json()
    thread = client.get(
        f"/courses/{new_id}/conversations/{chats[0]['conversation_id']}"
    ).json()
    imported_message = thread["messages"][1]
    assert imported_message["answer"]["chunk_ids"] == []
    assert imported_message["answer"]["material_chunk_ids"] == [
        str(next(row["chunk_id"] for row in rows if row["text"] == "First candidate.")),
        str(imported_chunks["Second candidate."]),
    ]

    imported_artifacts = client.get(f"/courses/{new_id}/artifacts").json()
    assert len(imported_artifacts) == 1
    imported_artifact_id = imported_artifacts[0]["artifact_id"]
    artifact = client.get(f"/courses/{new_id}/artifacts/{imported_artifact_id}")
    assert artifact.status_code == 200
    artifact_citations = client.get(
        f"/courses/{new_id}/artifacts/{imported_artifact_id}/citations"
    ).json()
    assert artifact_citations[0]["citation"]["chunk_id"] == str(
        imported_chunks["Second candidate."]
    )

    def fake_generate(task, prompt, **kwargs):
        return provider.GenerationResult(
            json.dumps({"text": "Geometry studies shape [1].", "sources": [1]}),
            "test-model",
            10,
            10,
        )

    monkeypatch.setattr(provider, "generate", fake_generate)
    mapped = client.post(
        f"/courses/{new_id}/mind-map/study",
        json={
            "origin": {"message_id": imported_message["message_id"]},
            "node_id": "geometry",
            "action": "explain",
            "request_id": str(uuid4()),
        },
    )
    assert mapped.status_code == 200, mapped.text
    assert mapped.json()["citations"][0]["chunk_id"] == str(
        imported_chunks["Second candidate."]
    )

    def fake_quiz(task, prompt, **kwargs):
        return provider.GenerationResult(
            json.dumps(
                {
                    "reply": "Practice",
                    "item": {
                        "type": "quiz",
                        "title": "Geometry",
                        "questions": [
                            {
                                "prompt": "What does geometry study?",
                                "options": ["Lengths and shapes", "Only numbers"],
                                "answer": 0,
                                "explanation": (
                                    "Geometry studies lengths and shapes [1]."
                                ),
                                "sources": [1],
                                "topic": "Geometry",
                                "capability": "recognition",
                            }
                        ],
                    },
                }
            ),
            "test-model",
            10,
            10,
        )

    monkeypatch.setattr(provider, "generate", fake_quiz)
    quiz = client.post(
        f"/courses/{new_id}/mind-map/study",
        json={
            "origin": {"message_id": imported_message["message_id"]},
            "node_id": "geometry",
            "action": "quiz",
            "request_id": str(uuid4()),
        },
    )
    assert quiz.status_code == 200, quiz.text
    assert quiz.json()["citations"][0]["chunk_id"] == str(
        imported_chunks["Second candidate."]
    )
    quiz_citations = client.get(
        f"/courses/{new_id}/artifacts/{quiz.json()['quiz_id']}/citations"
    ).json()
    assert quiz_citations[0]["citation"]["chunk_id"] == str(
        imported_chunks["Second candidate."]
    )
