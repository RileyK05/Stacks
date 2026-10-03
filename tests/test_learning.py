from __future__ import annotations

import json
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from src.backend.common import course_memory_repo, courses_repo, provider
from src.backend.common.db import connection, utc_now
from src.backend.common.schemas.learning import PracticeQuestion
from src.backend.student_model import inspection, learning, research
from tests.conftest import configure_test_provider
from tests.factories import add_chunk, make_course


def _suite(course_id: UUID, chunk: UUID, *, suffix: str = "", method=None):
    with connection() as conn:
        suite_id = learning.create_suite(
            conn,
            course_id,
            "Whole test",
            [
                PracticeQuestion(
                    prompt=f"Which property defines linearity? {suffix}",
                    options=["Preserves addition and scaling", "Preserves lengths"],
                    answer=0,
                    sources=[1],
                    topic="Linearity",
                    capability="recognition",
                ),
                PracticeQuestion(
                    prompt=f"Which map preserves addition? {suffix}",
                    options=["x squared", "Twice x"],
                    answer=1,
                    sources=[1],
                    topic="Linearity",
                    capability="application",
                ),
            ],
            (chunk,),
            {"by": "test", "batch": str(uuid4())},
            method,
        )
        conn.commit()
    return suite_id


def _submit(client, course_id, suite_id, answers, *, run_id=None, helped=None):
    body = {"run_id": str(run_id or uuid4()), "answers": answers}
    if helped is not None:
        body["helped"] = helped
    return client.post(f"/courses/{course_id}/practice/{suite_id}/runs", json=body)


def _target(client, course_id, capability):
    view = client.get(f"/courses/{course_id}/learning").json()
    return next(
        t
        for t in view["targets"]
        if t["topic"] == "Linearity" and t["capability"] == capability
    )


def test_complete_suite_survives_reload_and_preserves_each_answer(client):
    course = make_course()
    chunk = add_chunk(course.course_id, "Linear maps preserve addition and scaling.")
    test = _suite(course.course_id, chunk)
    before = client.get(f"/courses/{course.course_id}/learning").json()
    assert len(before["targets"]) == 5
    assert all(t["proficiency"] is None for t in before["targets"])
    run = _submit(client, course.course_id, test, [0, 0])
    assert run.status_code == 200, run.text
    reopened = client.get(f"/courses/{course.course_id}/practice/{test}").json()
    assert reopened["latest_run"]["answers"] == [0, 0]
    assert reopened["latest_run"]["results"] == [True, False]
    assert len(reopened["suite"]["questions"]) == 2
    assert reopened["suite"]["evidence"][0]["chunk_id"] == str(chunk)
    assert _target(client, course.course_id, "recognition")["proficiency"] == 60
    assert _target(client, course.course_id, "application")["proficiency"] == 0
    assert _target(client, course.course_id, "transfer")["proficiency"] is None


def test_revealed_retake_is_not_independent_even_if_browser_reloads(client):
    course = make_course()
    chunk = add_chunk(course.course_id, "Linearity preserves addition and scaling.")
    test = _suite(course.course_id, chunk)
    assert _submit(client, course.course_id, test, [1, 0]).status_code == 200
    retake = _submit(client, course.course_id, test, [0, 1]).json()
    assert retake["results"] == [True, True]
    assert retake["helped"] == [True, True]
    assert _target(client, course.course_id, "application")["proficiency"] == 0
    assert _target(client, course.course_id, "application")["independent_items"] == 1
    fresh = _suite(course.course_id, chunk, suffix="Fresh example")
    assert _submit(client, course.course_id, fresh, [0, 1]).status_code == 200
    assert _target(client, course.course_id, "application")["proficiency"] == 50


def test_submission_retry_is_idempotent_and_conflicting_answers_are_rejected(client):
    course = make_course()
    chunk = add_chunk(course.course_id, "Course evidence.")
    test = _suite(course.course_id, chunk)
    run_id = uuid4()
    first = _submit(client, course.course_id, test, [0, 1], run_id=run_id)
    again = _submit(client, course.course_id, test, [0, 1], run_id=run_id)
    assert first.json() == again.json()
    assert len(client.get(f"/courses/{course.course_id}/learning").json()["runs"]) == 1
    assert (
        _submit(client, course.course_id, test, [1, 0], run_id=run_id).status_code
        == 422
    )
    assert (
        _submit(
            client, course.course_id, test, [0, 1], run_id=run_id, helped=[True, True]
        ).status_code
        == 422
    )
    assert _target(client, course.course_id, "application")["observations"] == 1


@pytest.mark.parametrize(
    "answers,helped", [([0], None), ([0, 9], None), ([0, 1], [True])]
)
def test_invalid_or_partial_test_does_not_create_memory(client, answers, helped):
    course = make_course()
    chunk = add_chunk(course.course_id, "Course evidence.")
    test = _suite(course.course_id, chunk)
    assert (
        _submit(client, course.course_id, test, answers, helped=helped).status_code
        == 422
    )
    view = client.get(f"/courses/{course.course_id}/learning").json()
    assert view["runs"] == []
    assert all(t["observations"] == 0 for t in view["targets"])


def test_deleting_session_keeps_memory_and_evidence(client):
    course = make_course()
    chunk = add_chunk(course.course_id, "Linear maps preserve addition.")
    test = _suite(course.course_id, chunk)
    run = _submit(client, course.course_id, test, [0, 0]).json()
    target = _target(client, course.course_id, "application")
    assert (
        client.delete(
            f"/courses/{course.course_id}/practice/runs/{run['run_id']}"
        ).status_code
        == 204
    )
    assert (
        client.get(
            f"/courses/{course.course_id}/practice/runs/{run['run_id']}"
        ).status_code
        == 404
    )
    assert _target(client, course.course_id, "application") == target
    assert any(
        "Linearity / application" in m.summary
        for m in course_memory_repo.list_memories()
    )


def test_bad_key_can_be_excluded_and_corrected_without_rewriting_history(client):
    course = make_course()
    chunk = add_chunk(course.course_id, "Linear maps preserve addition.")
    test = _suite(course.course_id, chunk, method="worked_example")
    run = _submit(client, course.course_id, test, [0, 0]).json()
    endpoint = f"/courses/{course.course_id}/practice/{test}/questions/1"
    excluded = client.patch(
        endpoint, json={"answer": None, "reason": "Question is wrong"}
    )
    assert excluded.status_code == 200
    assert excluded.json()["latest_run"]["results"] == [True, None]
    assert _target(client, course.course_id, "application")["proficiency"] is None
    corrected = client.patch(
        endpoint, json={"answer": 0, "reason": "Reviewed source"}
    ).json()
    assert corrected["suite"]["questions"][1]["answer"] == 1
    assert corrected["latest_run"]["answers"] == run["answers"]
    assert corrected["latest_run"]["results"] == [True, True]
    root = client.get("/learning/core").json()
    assert root["methods"][0]["successes"] == 2


def test_core_methods_cross_courses_but_course_capabilities_do_not(client):
    first, second = make_course("Math"), make_course("History")
    chunk = add_chunk(first.course_id, "Linearity preserves addition.")
    test = _suite(first.course_id, chunk, method="visual_structure")
    _submit(client, first.course_id, test, [0, 1])
    view = client.get(f"/courses/{second.course_id}/learning").json()
    assert view["targets"] == []
    assert view["core"]["methods"][0]["method"] == "visual_structure"
    assert client.get(f"/courses/{second.course_id}/practice/{test}").status_code == 404
    assert _submit(client, second.course_id, test, [0, 1]).status_code == 404
    courses_repo.move_to_trash(first.course_id)
    assert courses_repo.purge_course(first.course_id)
    assert client.get("/learning/core").json()["methods"][0]["successes"] == 2
    assert "Linearity / application" in course_memory_repo.list_memories()[0].summary


def test_focus_is_bounded_scoped_and_cooled_down(client):
    course = make_course()
    chunk = add_chunk(course.course_id, "Linearity preserves addition.")
    test = _suite(course.course_id, chunk)
    _submit(client, course.course_id, test, [1, 0])
    with connection() as conn:
        now = utc_now()
        assert (
            "Linearity"
            not in learning.adaptation(conn, course.course_id, "quiz me", now=now)[0]
        )
        assert (
            "Linearity"
            in learning.adaptation(
                conn, course.course_id, "quiz me", now=now + timedelta(days=2)
            )[0]
        )
        assert (
            "Linearity"
            not in learning.adaptation(
                conn,
                course.course_id,
                "quiz me",
                source_ids=[uuid4()],
                now=now + timedelta(days=2),
            )[0]
        )


def test_strong_memory_is_checked_occasionally_not_every_time(client):
    course = make_course()
    chunk = add_chunk(course.course_id, "Linearity preserves addition.")
    for index in range(8):
        test = _suite(course.course_id, chunk, suffix=f"Independent problem {index}")
        assert _submit(client, course.course_id, test, [0, 1]).status_code == 200
    assert _target(client, course.course_id, "application")["proficiency"] == 100
    with connection() as conn:
        assert (
            "maintenance"
            not in learning.adaptation(conn, course.course_id, "quiz me")[0]
        )
        assert (
            "maintenance"
            in learning.adaptation(
                conn, course.course_id, "quiz me", now=utc_now() + timedelta(days=15)
            )[0]
        )


def test_chat_research_is_tentative_and_requires_actual_student_quote(
    client, monkeypatch
):
    course = make_course()
    chunk = add_chunk(course.course_id, "A linear map preserves addition and scaling.")
    configure_test_provider(monkeypatch)
    proposals = [
        {
            "topic": "Linearity",
            "capability": "application",
            "hypothesis": "May struggle applying the definition",
            "proposed_check": "Try a fresh map",
            "student_quote": "I cannot connect the definition to this example",
            "sources": [1],
        }
    ]
    monkeypatch.setattr(
        provider,
        "_call_provider",
        lambda *args, **kwargs: (json.dumps({"experiments": proposals}), 10, 5),
    )
    research.inspect_exchange(
        course.course_id,
        uuid4(),
        "I cannot connect the definition to this example",
        "Explanation [1]",
        (chunk,),
        None,
    )
    view = client.get(f"/courses/{course.course_id}/learning").json()
    assert len(view["experiments"]) == 1
    assert view["targets"] == []
    assert view["experiments"][0]["status"] == "proposed"
    assert view["core"]["methods"] == []
    proposals[0]["topic"] = "Invented topic"
    proposals[0]["student_quote"] = "Words the student never said"
    research.inspect_exchange(
        course.course_id,
        uuid4(),
        "I cannot connect the definition to this example",
        "Explanation [1]",
        (chunk,),
        None,
    )
    assert (
        len(client.get(f"/courses/{course.course_id}/learning").json()["experiments"])
        == 1
    )
    test = _suite(course.course_id, chunk)
    _submit(client, course.course_id, test, [0, 1])
    assert (
        client.get(f"/courses/{course.course_id}/learning").json()["experiments"][0][
            "status"
        ]
        == "resolved"
    )
    correction = client.patch(
        f"/courses/{course.course_id}/practice/{test}/questions/1",
        json={"answer": None, "reason": "The source does not support this check"},
    )
    assert correction.status_code == 200
    reopened = client.get(f"/courses/{course.course_id}/learning").json()[
        "experiments"
    ][0]
    assert reopened["status"] == "proposed"
    assert reopened["checks"] == 0


def test_preference_changes_cached_presentation_and_research_failure_keeps_answer(
    client, monkeypatch
):
    course = make_course()
    add_chunk(course.course_id, "Linearity preserves addition.")
    calls = configure_test_provider(monkeypatch, "Preserves addition [1].")
    first = client.post(
        f"/courses/{course.course_id}/ask", json={"question": "What is linearity?"}
    ).json()
    assert not first["cached"]
    assert (
        client.put(
            "/learning/core", json={"preferred_method": "visual_structure"}
        ).status_code
        == 200
    )
    second = client.post(
        f"/courses/{course.course_id}/ask", json={"question": "What is linearity?"}
    ).json()
    assert not second["cached"]
    assert "compact diagram" in calls[-1]["prompt"]
    chat = client.post(f"/courses/{course.course_id}/conversations", json={}).json()[
        "conversation_id"
    ]
    response = client.post(
        f"/courses/{course.course_id}/conversations/{chat}/messages",
        json={"question": "I am confused about linearity"},
    )
    assert response.status_code == 200
    assert response.json()["reply"]["text"] == "Preserves addition [1]."
    assert (
        client.get(f"/courses/{course.course_id}/learning").json()["experiments"] == []
    )


def test_empty_learner_scaffolds_practice_only(client):
    course = make_course()
    with connection() as conn:
        assert (
            learning.adaptation(conn, course.course_id, "What is linearity?")[2]
            != "step_by_step"
        )
        assert (
            learning.adaptation(conn, course.course_id, "quiz me on linearity")[2]
            == "step_by_step"
        )
    assert (
        client.put(
            "/learning/core", json={"preferred_method": "visual_structure"}
        ).status_code
        == 200
    )
    with connection() as conn:
        assert (
            learning.adaptation(conn, course.course_id, "What is linearity?")[2]
            == "visual_structure"
        )


def test_assisted_new_answers_remain_tentative_for_course_and_core(client):
    course = make_course()
    chunk = add_chunk(course.course_id, "Linearity preserves addition and scaling.")
    test = _suite(course.course_id, chunk, method="analogy")
    run = _submit(client, course.course_id, test, [0, 1], helped=[True, True])
    assert run.status_code == 200
    target = _target(client, course.course_id, "application")
    assert target["proficiency"] == 40
    assert target["independent_items"] == 0
    method = client.get("/learning/core").json()["methods"][0]
    assert method["checks"] == method["successes"] == 0
    assert method["evidence"][0]["helped"] is True


@pytest.mark.parametrize("same_chat", [False, True])
def test_upgrade_keeps_capability_history_and_only_valid_method_associations(
    tmp_path, monkeypatch, client, same_chat
):
    from src.backend.common import conversations_repo
    from src.backend.common import migrate as migrations
    from src.backend.common.queries import get

    path = tmp_path / "old-learning.db"
    pending = migrations._pending_migrations
    with monkeypatch.context() as scope:
        scope.setattr(
            migrations,
            "_pending_migrations",
            lambda: [
                (version, file) for version, file in pending() if int(version) <= 20
            ],
        )
        migrations.migrate(path)
    monkeypatch.setenv("DATABASE_PATH", str(path))
    course = make_course()
    chunk = add_chunk(course.course_id, "Linearity preserves addition and scaling.")
    suite_id = _suite(course.course_id, chunk, method="analogy")
    conversation = conversations_repo.create(course.course_id)
    teaching_trace, quiz_trace = uuid4(), uuid4()
    with connection() as conn:
        origin = {
            "trace_id": str(quiz_trace),
            "teaching_context": {"trace_ref": str(teaching_trace), "method": "analogy"},
        }
        if same_chat:
            for trace_id in (teaching_trace, quiz_trace):
                conn.execute(
                    get("retrieval_traces", "insert_trace"),
                    {
                        "trace_id": trace_id,
                        "course_id": course.course_id,
                        "query": "Practice",
                        "chunk_ids": json.dumps({"chunk_ids": [str(chunk)]}),
                        "model": "test",
                    },
                )
                conversations_repo.add_turn(
                    conn,
                    conversation.conversation_id,
                    question="Practice",
                    answer="Practice [1]",
                    trace_id=trace_id,
                    payload={},
                )
        conn.execute(
            "UPDATE practice_suites SET origin=? WHERE suite_id=?",
            (json.dumps(origin), suite_id),
        )
        conn.commit()
    assert _submit(client, course.course_id, suite_id, [0, 1]).status_code == 200
    with connection() as conn:
        assert len(inspection.rows(conn, "core_observations")) == 2
    assert migrations.migrate(path) == ["021"]
    with connection() as conn:
        observations = inspection.rows(conn, "observations", course_id=course.course_id)
        assert len(observations) == 2 and all(row["correct"] for row in observations)
        assert all(
            row["method"] == ("analogy" if same_chat else None) for row in observations
        )
        assert len(inspection.rows(conn, "core_observations")) == (
            2 if same_chat else 0
        )
        test = learning.suite(conn, course.course_id, suite_id)
        if not same_chat:
            assert (
                test.origin["discarded_teaching_context"] == origin["teaching_context"]
            )
        assert test.method == ("analogy" if same_chat else None)


def test_automatic_focus_has_cooldown_and_quota_but_explicit_request_overrides(client):
    course = make_course()
    chunk = add_chunk(course.course_id, "Linearity preserves addition and scaling.")
    test = _suite(course.course_id, chunk)
    _submit(client, course.course_id, test, [1, 0])
    fresh = [
        PracticeQuestion(
            prompt=f"Novel check {i}",
            options=["A", "B"],
            answer=0,
            sources=[1],
            topic="Linearity",
            capability="application",
        )
        for i in range(5)
    ]
    with connection() as conn:
        source = conn.execute(
            "SELECT source_id FROM chunks WHERE chunk_id = ?", (chunk,)
        ).fetchone()["source_id"]
        assert (
            learning.allocate_questions(
                conn,
                course.course_id,
                "Make a practice test",
                fresh,
                source_ids=[source],
            )
            == []
        )
        assert (
            len(
                learning.allocate_questions(
                    conn,
                    course.course_id,
                    "Quiz me on Linearity",
                    fresh,
                    source_ids=[source],
                )
            )
            == 5
        )
        conn.execute(
            "UPDATE learning_observations SET created_at = ? WHERE course_id = ?",
            (utc_now() - timedelta(days=2), course.course_id),
        )
        selected = learning.allocate_questions(
            conn, course.course_id, "Make a practice test", fresh, source_ids=[source]
        )
        assert len(selected) == 2
        other = uuid4()
        assert (
            learning.allocate_questions(
                conn,
                course.course_id,
                "Make a practice test",
                fresh,
                source_ids=[other],
            )
            == []
        )


def test_portable_learning_keeps_distilled_deleted_sessions_without_duplicating_core(
    client,
):
    from src.backend.common import archive_notebook
    from src.backend.student_model.archive import export_learning, import_learning

    course = make_course()
    chunk = add_chunk(course.course_id, "Linearity preserves addition.")
    test = _suite(course.course_id, chunk, method="worked_example")
    run = _submit(client, course.course_id, test, [0, 0]).json()
    client.patch(
        f"/courses/{course.course_id}/practice/{test}/questions/1",
        json={"answer": None, "reason": "Insufficient source"},
    )
    client.delete(f"/courses/{course.course_id}/practice/runs/{run['run_id']}")
    other = make_course("Imported course")
    with connection() as conn:
        source = conn.execute(
            "SELECT source_id FROM chunks WHERE chunk_id = ?", (chunk,)
        ).fetchone()["source_id"]
        study = export_learning(conn, course.course_id)
        assert study.runs == [] and len(study.observations) == 2
        root_before = inspection.core(conn).model_dump()
        new_source, new_chunk = uuid4(), uuid4()
        mapping = import_learning(
            conn, other.course_id, study, {source: new_source}, {chunk: new_chunk}
        )
        conn.commit()
        assert mapping[test] != test
        imported = learning.view(conn, other.course_id)
        target = next(t for t in imported.targets if t.capability == "recognition")
        assert target.proficiency == 60
        assert target.evidence[0]["sources"][0]["source_id"] == str(new_source)
        assert target.evidence[0]["suite_id"] == str(mapping[test])
        assert imported.runs == []
        assert inspection.core(conn).model_dump() == root_before
        excluded = next(t for t in imported.targets if t.capability == "application")
        assert excluded.proficiency is None
    notebook = archive_notebook.export_notebook(course.course_id)
    assert notebook.learning and len(notebook.learning.observations) == 2
    assert any(c.chunk_id == chunk for c in notebook.citations)
