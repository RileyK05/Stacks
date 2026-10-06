from __future__ import annotations

import copy
import json
from dataclasses import replace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from src.backend.artifacts import content, export
from src.backend.common import (
    archive_notebook,
    artifacts_repo,
    conversations_repo,
    provider,
)
from src.backend.common.db import connect, connection
from src.backend.common.schemas.mind_map import MindMapContent
from src.backend.tutor.compose import (
    Intent,
    classify_intent,
    compose_answer,
    retrieval_topic,
)
from src.backend.tutor.workspace import extract_workspace_items
from tests.factories import add_chunk, chunk_source_locator, make_course
from tests.test_compose import _candidates


def sample_map():
    return {
        "nodes": [
            {
                "id": "algebra",
                "label": "Linearity",
                "summary": "Preserves addition and scaling.",
                "sources": [1],
            },
            {
                "id": "scaling",
                "label": "Scaling",
                "summary": "T(cx) = cT(x).",
                "sources": [1],
            },
            {
                "id": "geometry",
                "label": "Geometry",
                "summary": "Studies lengths and shapes.",
                "sources": [2],
            },
            {
                "id": "length",
                "label": "Lengths",
                "summary": "Lengths measure size.",
                "sources": [2],
            },
        ],
        "edges": [
            {
                "source": "algebra",
                "target": "scaling",
                "kind": "branch",
                "label": "defining property",
                "explanation": "Linearity preserves scalar multiplication.",
                "sources": [1],
            },
            {
                "source": "geometry",
                "target": "length",
                "kind": "branch",
                "label": "measurement",
                "explanation": "Geometry studies lengths.",
                "sources": [2],
            },
            {
                "source": "algebra",
                "target": "geometry",
                "kind": "similarity",
                "label": "contrasting transformations",
                "explanation": "Linearity need not preserve lengths.",
                "sources": [2],
            },
        ],
    }


@pytest.fixture
def mapped():
    course = make_course("Map study")
    chunks = [
        add_chunk(course.course_id, text)
        for text in (
            "A linear map preserves addition and scalar multiplication: T(cx) = cT(x).",
            "Geometry studies lengths and shapes. "
            "Linear maps need not preserve lengths.",
        )
    ]
    chat = conversations_repo.create(course.course_id, "Map chat")
    with connection() as conn:
        _, message = conversations_repo.add_turn(
            conn,
            chat.conversation_id,
            question="Make a mind map",
            answer="Map ready",
            trace_id=None,
            payload={
                "chunk_ids": [str(cid) for cid in chunks],
                "workspace": [{"type": "mind_map", "title": "Topics", **sample_map()}],
            },
        )
        conn.commit()
    return course.course_id, chunks, chat.conversation_id, message.message_id


def stub(monkeypatch, *, quiz=False, before=None):
    calls = []

    def generate(task, prompt, **kwargs):
        calls.append((task, prompt, kwargs))
        if before:
            before()
        result = {"text": "You can test scaling with T(cx)=cT(x). [1]", "sources": [1]}
        if quiz:
            result = {
                "reply": "Practice",
                "item": {
                    "type": "quiz",
                    "title": "Linearity",
                    "questions": [
                        {
                            "prompt": "Which property does a linear map preserve?",
                            "options": ["Addition and scaling", "Lengths"],
                            "answer": 0,
                            "explanation": "Preserves addition and scaling [1].",
                            "sources": [1],
                            "topic": "Linearity",
                            "capability": "recognition",
                        }
                    ],
                },
            }
        return provider.GenerationResult(json.dumps(result), "test-model", 10, 10)

    monkeypatch.setattr(provider, "generate", generate)
    return calls


def request(client, mapped, action="explain", **overrides):
    course, _, _, message = mapped
    body = {
        "origin": {"message_id": str(message)},
        "node_id": "algebra",
        "action": action,
        "request_id": str(uuid4()),
        **overrides,
    }
    return client.post(f"/courses/{course}/mind-map/study", json=body)


@pytest.mark.parametrize(
    "issue", ["cycle", "missing", "parents", "duplicate", "uncited"]
)
def test_bad_graph_is_withheld(issue):
    mapped = sample_map()
    edge = copy.deepcopy(mapped["edges"][0])
    if issue == "cycle":
        edge.update(source="scaling", target="algebra")
        mapped["edges"][0] = edge
        mapped["edges"].append(
            {**edge, "source": "algebra", "target": "geometry", "kind": "branch"}
        )
        mapped["edges"].append(
            {**edge, "source": "geometry", "target": "scaling", "kind": "branch"}
        )
    elif issue == "missing":
        mapped["edges"][0]["target"] = "missing"
    elif issue == "parents":
        mapped["edges"].append({**edge, "source": "geometry"})
    elif issue == "duplicate":
        mapped["nodes"][1]["id"] = "algebra"
    else:
        mapped["edges"][0]["sources"] = []
    with pytest.raises(ValidationError):
        MindMapContent.model_validate(mapped)
    lifted = extract_workspace_items(
        "```workspace\n" + json.dumps({"type": "mind_map", **mapped}) + "\n```", 2
    )
    assert not lifted.items and lifted.withheld


def test_map_generation_gates_edges_and_preserves_citation_numbers():
    assert classify_intent("Make a mind map of transformations") == Intent.MIND_MAP
    assert classify_intent("Quiz me on concept maps") == Intent.QUIZ
    assert classify_intent("Explain a concept map") == Intent.ANSWER
    assert retrieval_topic("Make a mind map of the course") == ""
    raw = {"reply": "Topics", "item": {"type": "mind_map", **sample_map()}}
    passages = [
        "Linearity preserves addition and Scaling. Scaling uses T(cx) = cT(x).",
        "Geometry studies Lengths. Linearity and Geometry involve transformations.",
    ]
    for node in raw["item"]["nodes"]:
        node["summary"] = passages[node["sources"][0] - 1]
    for edge in raw["item"]["edges"]:
        edge["explanation"] = passages[edge["sources"][0] - 1]
    candidates = tuple(
        replace(c, text=t) for c, t in zip(_candidates(), passages, strict=True)
    )
    composed = compose_answer(
        "Make a mind map", candidates, lambda *a, **kw: json.dumps(raw)
    )
    lifted = extract_workspace_items(composed.text, 2)
    assert len(lifted.items) == 1
    kind, _, mapped, _ = content.from_workspace_item(lifted.items[0])
    assert kind == "mind_map" and content.cited_numbers(mapped) == {1, 2}
    renumbered = content.renumber(mapped, {1: 2, 2: 1})
    assert renumbered["edges"][2]["sources"] == [1]
    raw["item"]["edges"][2]["sources"] = [3]
    rejected = compose_answer(
        "Make a mind map", candidates, lambda *a, **kw: json.dumps(raw)
    )
    assert not extract_workspace_items(rejected.text, 2).items
    raw["item"]["edges"][2]["sources"] = [2]
    raw["item"]["nodes"][0]["label"] = "Invented concept absent from the source"
    rejected = compose_answer(
        "Make a mind map", candidates, lambda *a, **kw: json.dumps(raw)
    )
    assert not extract_workspace_items(rejected.text, 2).items


@pytest.mark.parametrize(
    "options,prompt",
    [
        (
            ["Gonzales, walkouts, and boycott", "Boycott, Gonzales, and walkouts"],
            "Which examples appear in the reading?",
        ),
        (
            ["The labor campaign", "The LA walkouts"],
            "Which concept is identified as a labor campaign?",
        ),
    ],
)
def test_duplicate_lists_and_tautological_quiz_answers_are_withheld(options, prompt):
    raw = {
        "reply": "Quiz",
        "item": {
            "type": "quiz",
            "title": "Practice",
            "questions": [
                {
                    "prompt": prompt,
                    "options": options,
                    "answer": 0,
                    "explanation": "The source supports the answer [1].",
                    "sources": [1],
                    "topic": "Movement",
                    "capability": "recognition",
                }
            ],
        },
    }
    result = compose_answer("Quiz me", _candidates(), lambda *a, **kw: json.dumps(raw))
    assert not extract_workspace_items(result.text, 2).items


def test_explain_is_scoped_and_does_not_write_learning(client, mapped, monkeypatch):
    calls = stub(monkeypatch, before=lambda: make_course("Another writer"))
    course, _, chat, _ = mapped
    with connection() as conn:
        conn.execute(
            "UPDATE conversations SET model_choice=? WHERE conversation_id=?",
            ('{"connection":"chosen","model":"chosen-model"}', chat),
        )
        conn.commit()
    response = request(client, mapped)
    assert response.status_code == 200, response.text
    assert len(response.json()["citations"]) == 1
    assert "Geometry studies" not in calls[0][1]
    assert "UNTRUSTED_COURSE_MATERIAL" in calls[0][1]
    assert calls[0][2]["choice"].model == "chosen-model"
    learning = client.get(f"/courses/{course}/learning").json()
    assert learning["runs"] == [] and learning["experiments"] == []
    with connection() as conn:
        for table in [
            "learning_observations",
            "learning_teaching_events",
            "core_method_observations",
        ]:
            assert (
                conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] == 0
            )


def test_excluded_removed_foreign_and_stale_origins_are_rejected(
    client, mapped, monkeypatch
):
    calls = stub(monkeypatch)
    course, chunks, chat, message = mapped
    other = make_course()
    foreign = client.post(
        f"/courses/{other.course_id}/mind-map/study",
        json={
            "origin": {"message_id": str(message)},
            "node_id": "algebra",
            "action": "explain",
            "request_id": str(uuid4()),
        },
    )
    assert foreign.status_code == 404
    with connection() as conn:
        conn.execute(
            "UPDATE conversations SET source_ids='[]' WHERE conversation_id=?", (chat,)
        )
        conn.commit()
    assert request(client, mapped).status_code == 422
    saved = artifacts_repo.create(
        course, kind="mind_map", title="Map", content=sample_map(), sources=chunks
    )
    assert (
        request(
            client,
            mapped,
            origin={"artifact_id": str(saved.artifact_id), "artifact_version": 2},
        ).status_code
        == 409
    )
    with connection() as conn:
        conn.execute(
            "DELETE FROM sources WHERE source_id=?",
            (chunk_source_locator(chunks[0])[0],),
        )
        conn.commit()
    assert (
        request(
            client,
            mapped,
            origin={"artifact_id": str(saved.artifact_id), "artifact_version": 1},
        ).status_code
        == 422
    )
    assert not calls


def test_changed_map_during_generation_is_not_delivered(client, mapped, monkeypatch):
    course, chunks, _, _ = mapped
    saved = artifacts_repo.create(
        course, kind="mind_map", title="Map", content=sample_map(), sources=chunks
    )
    stub(
        monkeypatch,
        before=lambda: artifacts_repo.save(
            course,
            saved.artifact_id,
            expected_version=1,
            title="Changed",
            content=sample_map(),
            sources=chunks,
            author="you",
        ),
    )
    assert (
        request(
            client,
            mapped,
            origin={"artifact_id": str(saved.artifact_id), "artifact_version": 1},
        ).status_code
        == 409
    )


def test_quiz_is_saved_idempotent_and_only_submission_changes_memory(
    client, mapped, monkeypatch
):
    calls = stub(monkeypatch, quiz=True)
    course, _, _, _ = mapped
    identity = str(uuid4())
    first = request(client, mapped, "quiz", request_id=identity)
    assert first.status_code == 200, first.text
    second = request(client, mapped, "quiz", request_id=identity)
    assert second.json() == first.json() and len(calls) == 1
    assert "Geometry" not in calls[0][1]
    quiz_id = first.json()["quiz_id"]
    assert client.get(f"/courses/{course}/artifacts/{quiz_id}").json()["kind"] == "quiz"
    before = client.get(f"/courses/{course}/learning").json()
    assert before["runs"] == []
    suite = client.post(
        f"/courses/{course}/practice",
        json={"artifact_id": quiz_id, "artifact_version": 1},
    ).json()["suite"]
    score = client.post(
        f"/courses/{course}/practice/{suite['suite_id']}/runs",
        json={"run_id": str(uuid4()), "answers": [suite["questions"][0]["answer"]]},
    )
    assert score.status_code == 200 and score.json()["results"] == [True]
    assert client.get(f"/courses/{course}/learning").json()["runs"]
    assert (
        request(
            client, mapped, "quiz", node_id="scaling", request_id=identity
        ).status_code
        == 422
    )


def test_map_versions_export_import_and_quiz_provenance(client, mapped, monkeypatch):
    course, chunks, _, _ = mapped
    saved = artifacts_repo.create(
        course, kind="mind_map", title="Map", content=sample_map(), sources=chunks
    )
    origin = {"artifact_id": str(saved.artifact_id), "artifact_version": 1}
    stub(monkeypatch, quiz=True)
    response = request(client, mapped, "quiz", origin=origin)
    assert response.status_code == 200
    notebook = archive_notebook.export_notebook(course)
    destination = make_course()
    new_chunks = [
        add_chunk(destination.course_id, "Imported placeholder") for _ in chunks
    ]
    source_map = {
        chunk_source_locator(old)[0]: chunk_source_locator(new)[0]
        for old, new in zip(chunks, new_chunks, strict=True)
    }
    with connection() as conn:
        archive_notebook.import_notebook(
            conn, destination.course_id, notebook, source_map
        )
        conn.commit()
    imported = artifacts_repo.list_artifacts(destination.course_id)
    imported_map = next(a for a in imported if a.kind == "mind_map")
    imported_quiz = next(a for a in imported if a.kind == "quiz")
    assert imported_quiz.origin["map_origin"]["artifact_id"] == str(
        imported_map.artifact_id
    )
    read = artifacts_repo.get_artifact(destination.course_id, imported_map.artifact_id)
    assert read.content == sample_map() and read.sources != tuple(chunks)
    md = export.render(
        "mind_map",
        "md",
        "Topics",
        sample_map(),
        [export.SourceLabel(1, "Lecture", "page 1")],
    ).decode()
    assert (
        "similarity: contrasting transformations" in md and "[1] Lecture, page 1" in md
    )


def test_saved_map_quiz_help_keeps_chat_pin_and_retry_returns_current_version(
    client, mapped, monkeypatch
):
    course, _, chat, message = mapped
    with connection() as conn:
        conn.execute(
            "UPDATE conversations SET model_choice=? WHERE conversation_id=?",
            ('{"connection":"chosen","model":"chosen-model"}', chat),
        )
        conn.commit()
    calls = stub(monkeypatch, quiz=True)
    identity = str(uuid4())
    result = request(client, mapped, "quiz", request_id=identity)
    assert result.status_code == 200, result.text
    quiz_id = result.json()["quiz_id"]
    saved = artifacts_repo.get_artifact(course, quiz_id)
    assert saved.origin["message_id"] == str(message)
    assert calls[0][2]["choice"].model == "chosen-model"
    artifacts_repo.save(
        course,
        saved.artifact_id,
        expected_version=1,
        title="Edited branch quiz",
        content=saved.content,
        sources=saved.sources,
        author="you",
    )
    replay = request(client, mapped, "quiz", request_id=identity)
    assert replay.status_code == 200, replay.text
    assert replay.json()["quiz_version"] == 2
    assert replay.json()["quiz"]["title"] == "Edited branch quiz"
    assert len(calls) == 1
    suite = client.post(
        f"/courses/{course}/practice",
        json={"artifact_id": quiz_id, "artifact_version": 2},
    ).json()["suite"]
    calls = stub(monkeypatch)
    helped = client.post(
        f"/courses/{course}/practice/{suite['suite_id']}/questions/0/help",
        json={"run_id": str(uuid4()), "kind": "hint"},
    )
    assert helped.status_code == 200, helped.text
    assert calls[0][2]["choice"].model == "chosen-model"


def test_migration_preserves_existing_versions_and_adoption_index(
    tmp_path, monkeypatch
):
    from src.backend.common import migrate

    pending = migrate._pending_migrations()
    with monkeypatch.context() as patch:
        patch.setattr(
            migrate,
            "_pending_migrations",
            lambda: [(v, p) for v, p in pending if v != "012"],
        )
        path = tmp_path / "old.db"
        migrate.migrate(path)
    course, artifact = uuid4(), uuid4()
    conn = connect(path)
    try:
        conn.execute("INSERT INTO courses(course_id,name) VALUES(?, 'Old')", (course,))
        conn.execute(
            "INSERT INTO artifacts(artifact_id,course_id,kind,title,content,origin) "
            "VALUES(?,?,'doc','Old','{}',?)",
            (
                artifact,
                course,
                json.dumps(
                    {"adopted": True, "message_id": str(uuid4()), "item_index": 0}
                ),
            ),
        )
        conn.execute(
            "INSERT INTO artifact_versions(artifact_id,version,title,content,"
            "sources,author) VALUES(?,1,'Old','{}','[]','you')",
            (artifact,),
        )
        conn.commit()
    finally:
        conn.close()
    assert migrate.migrate(path) == ["012"]
    conn = connect(path)
    try:
        assert (
            conn.execute("SELECT title FROM artifact_versions").fetchone()["title"]
            == "Old"
        )
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        indexes = {r["name"] for r in conn.execute("PRAGMA index_list(artifacts)")}
        assert {"idx_artifacts_message_item", "idx_artifacts_map_request"} <= indexes
        conn.execute("DELETE FROM artifacts WHERE artifact_id=?", (artifact,))
        assert (
            conn.execute("SELECT COUNT(*) AS n FROM artifact_versions").fetchone()["n"]
            == 0
        )
    finally:
        conn.close()
