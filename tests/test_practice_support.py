from __future__ import annotations

import json
from uuid import uuid4

import pytest
from src.backend.common import conversations_repo, provider
from src.backend.common.db import connection
from src.backend.student_model import learning, practice_support
from src.backend.student_model.archive import export_learning, import_learning
from tests.factories import add_chunk, make_course
from tests.test_learning import _submit, _suite, _target


@pytest.fixture
def quiz():
    course = make_course()
    chunk = add_chunk(
        course.course_id, "Linear maps preserve addition and scaling.", label="page 8"
    )
    suite = _suite(course.course_id, chunk, method="worked_example")
    return course.course_id, suite, chunk


def stub(
    monkeypatch,
    text="Consider what happens when two inputs are combined. [1]",
    sources=None,
):
    calls = []

    def generate(task, prompt, **kwargs):
        calls.append((task, prompt, kwargs))
        return provider.GenerationResult(
            json.dumps({"text": text, "sources": sources or [1]}), "fixture", 10, 10
        )

    monkeypatch.setattr(provider, "generate", generate)
    return calls


def help_url(course, suite, index=0):
    return f"/courses/{course}/practice/{suite}/questions/{index}/help"


def rating_url(course, suite, index=0):
    return f"/courses/{course}/practice/{suite}/questions/{index}/feedback"


def test_hint_is_grounded_cached_and_reload_cannot_hide_assistance(
    client, quiz, monkeypatch
):
    course, suite, _ = quiz
    calls = stub(monkeypatch)
    run = uuid4()
    request = {"run_id": str(run), "kind": "hint"}
    first = client.post(help_url(course, suite), json=request)
    assert first.status_code == 200, first.text
    assert client.post(help_url(course, suite), json=request).json() == first.json()
    assert len(calls) == 1
    prompt = calls[0][1]
    assert "<<<UNTRUSTED_COURSE_MATERIAL begin>>>" in prompt
    assert "preserve addition and scaling" in prompt
    assert "Preserves lengths" not in prompt and "current_key" not in prompt
    assert "question" in prompt
    before = client.get(f"/courses/{course}/learning").json()
    assert before["runs"] == []
    assert all(t["proficiency"] is None for t in before["targets"])
    # A reloaded client uses a different attempt ID and falsely claims no help.
    saved = _submit(client, course, suite, [0, 1], helped=[False, False]).json()
    assert saved["helped"] == [True, False]
    assert _target(client, course, "recognition")["independent_items"] == 0
    assert _target(client, course, "recognition")["proficiency"] == 40
    assert _target(client, course, "application")["independent_items"] == 1


def test_quiz_help_respects_its_saved_chat_model_choice(client, quiz, monkeypatch):
    course, suite, _ = quiz
    chat = conversations_repo.create(course, "Pinned model")
    with connection() as conn:
        conversations_repo.add_turn(
            conn,
            chat.conversation_id,
            question="Quiz me",
            answer="Quiz ready",
            trace_id=None,
            payload={},
        )
        message = conn.execute(
            "SELECT message_id FROM messages "
            "WHERE conversation_id=? AND role='assistant'",
            (chat.conversation_id,),
        ).fetchone()["message_id"]
        conn.execute(
            "UPDATE practice_suites SET origin=? WHERE suite_id=?",
            (json.dumps({"message_id": str(message)}), suite),
        )
        conn.execute(
            "UPDATE conversations SET model_choice=? WHERE conversation_id=?",
            ('{"connection":"chosen","model":"chosen-model"}', chat.conversation_id),
        )
        conn.commit()
    calls = stub(monkeypatch)
    response = client.post(
        help_url(course, suite), json={"run_id": str(uuid4()), "kind": "hint"}
    )
    assert response.status_code == 200, response.text
    assert calls[0][2]["choice"].connection == "chosen"
    assert calls[0][2]["choice"].model == "chosen-model"


def test_explain_requires_submission_and_tracks_corrected_or_flagged_key(
    client, quiz, monkeypatch
):
    course, suite, _ = quiz
    calls = stub(
        monkeypatch, "The source describes the defining properties of a linear map. [1]"
    )
    run = uuid4()
    request = {"run_id": str(run), "kind": "explain"}
    assert client.post(help_url(course, suite), json=request).status_code == 422
    _submit(client, course, suite, [1, 0], run_id=run)
    first = client.post(help_url(course, suite), json=request)
    assert first.status_code == 200, first.text
    assert '"student_answer": "Preserves lengths"' in calls[-1][1]
    assert '"current_key": "Preserves addition and scaling"' in calls[-1][1]
    patch = f"/courses/{course}/practice/{suite}/questions/0"
    assert (
        client.patch(patch, json={"answer": None, "reason": "ambiguous"}).status_code
        == 200
    )
    second = client.post(help_url(course, suite), json=request)
    assert second.status_code == 200, second.text
    assert second.json()["help_id"] != first.json()["help_id"]
    assert "Excluded; key withheld pending review" in calls[-1][1]
    assert "current_key" not in calls[-1][1]
    assert _target(client, course, "recognition")["proficiency"] is None


@pytest.mark.parametrize(
    "text,sources",
    [
        ("Use the answer. [7]", [7]),
        ("Preserves addition and scaling is the answer. [1]", [1]),
    ],
)
def test_invalid_or_leaking_hint_is_withheld_and_does_not_mark_assistance(
    client, quiz, monkeypatch, text, sources
):
    course, suite, _ = quiz
    stub(monkeypatch, text, sources)
    assert (
        client.post(
            help_url(course, suite), json={"run_id": str(uuid4()), "kind": "hint"}
        ).status_code
        == 422
    )
    assert _submit(client, course, suite, [0, 1]).json()["helped"] == [False, False]


def test_model_failure_can_be_retried_without_creating_learning_evidence(
    client, quiz, monkeypatch
):
    course, suite, _ = quiz
    run = uuid4()

    def offline(*args, **kwargs):
        raise provider.ProviderUnavailableError("offline")

    monkeypatch.setattr(provider, "generate", offline)
    request = {"run_id": str(run), "kind": "hint"}
    assert client.post(help_url(course, suite), json=request).status_code == 503
    assert _target(client, course, "recognition")["observations"] == 0
    stub(monkeypatch)
    assert client.post(help_url(course, suite), json=request).status_code == 200
    assert _submit(client, course, suite, [0, 1], run_id=run).json()["helped"] == [
        True,
        False,
    ]


def test_valid_declared_sources_get_visible_citations(client, quiz, monkeypatch):
    course, suite, _ = quiz
    stub(monkeypatch, "What properties could you check?")
    result = client.post(
        help_url(course, suite), json={"run_id": str(uuid4()), "kind": "hint"}
    )
    assert result.status_code == 200, result.text
    assert result.json()["content"]["text"].endswith("[1]")


def test_explanation_is_withheld_if_assessment_changes_during_generation(
    client, quiz, monkeypatch
):
    course, suite, _ = quiz
    run = uuid4()
    _submit(client, course, suite, [0, 1], run_id=run)

    def generate(*args, **kwargs):
        with connection() as conn:
            learning.revise(conn, course, suite, 0, None, "Concurrent review")
            conn.commit()
        return provider.GenerationResult(
            '{"text":"The stored key fits. [1]","sources":[1]}', "fixture", 1, 1
        )

    monkeypatch.setattr(provider, "generate", generate)
    response = client.post(
        help_url(course, suite), json={"run_id": str(run), "kind": "explain"}
    )
    assert response.status_code == 422
    assert "answer key changed" in response.json()["detail"]


def test_submission_during_hint_is_blocked_without_holding_model_transaction(
    client, quiz, monkeypatch
):
    course, suite, _ = quiz
    run = uuid4()

    def generate(*args, **kwargs):
        with connection() as other:
            assert not other.in_transaction
            other.execute("BEGIN IMMEDIATE")
        attempt = _submit(client, course, suite, [0, 1], run_id=run)
        assert attempt.status_code == 422
        assert "wait for the hint" in attempt.json()["detail"]
        return provider.GenerationResult(
            '{"text":"Consider the two defining operations. [1]","sources":[1]}',
            "fixture",
            1,
            1,
        )

    monkeypatch.setattr(provider, "generate", generate)
    assert (
        client.post(
            help_url(course, suite), json={"run_id": str(run), "kind": "hint"}
        ).status_code
        == 200
    )
    assert _submit(client, course, suite, [0, 1], run_id=run).json()["helped"] == [
        True,
        False,
    ]


def test_feedback_is_editable_scoped_and_has_no_mastery_or_core_effect(client, quiz):
    course, suite, chunk = quiz
    _submit(client, course, suite, [0, 1])
    before = client.get(f"/courses/{course}/learning").json()
    request = {
        "target": "question",
        "rating": "bad",
        "reason": "Distractor is unclear.",
    }
    for _ in range(3):
        response = client.put(rating_url(course, suite), json=request)
        assert response.status_code == 200, response.text
        assert len(response.json()) == 1
    assert client.get(f"/courses/{course}/learning").json() == before
    with connection() as conn:
        context = practice_support.feedback_context(conn, course, None)
        assert "Distractor is unclear." in context
        assert not practice_support.feedback_context(conn, course, [])
    other = make_course()
    assert (
        client.put(rating_url(other.course_id, suite), json=request).status_code == 404
    )
    assert (
        client.get(f"/courses/{course}/practice/{suite}").json()["feedback"][0][
            "rating"
        ]
        == "bad"
    )
    request["rating"] = "good"
    assert (
        client.put(rating_url(course, suite), json=request).json()[0]["rating"]
        == "good"
    )
    request["rating"] = None
    assert client.put(rating_url(course, suite), json=request).json() == []


def test_help_feedback_targets_exact_output_and_portable_archive(
    client, quiz, monkeypatch
):
    course, suite, chunk = quiz
    stub(monkeypatch)
    hint = client.post(
        help_url(course, suite), json={"run_id": str(uuid4()), "kind": "hint"}
    ).json()
    body = {
        "target": "hint",
        "help_id": hint["help_id"],
        "rating": "good",
        "reason": "Useful nudge.",
    }
    assert client.put(rating_url(course, suite, 1), json=body).status_code == 404
    assert client.put(rating_url(course, suite), json=body).status_code == 200
    other = make_course()
    with connection() as conn:
        archive = export_learning(conn, course)
        assert len(archive.help) == len(archive.feedback) == 1
        mapped = import_learning(conn, other.course_id, archive, {}, {})
        conn.commit()
        imported = export_learning(conn, other.course_id)
        assert imported.help[0].help_id != archive.help[0].help_id
        assert imported.feedback[0].help_id == imported.help[0].help_id
        assert imported.help[0].suite_id == mapped[suite]
    # Imported hint exposure also prevents claiming independence.
    assert _submit(client, other.course_id, mapped[suite], [0, 1]).json()["helped"] == [
        True,
        False,
    ]
