"""Exam-style practice: style-only uploads, new grounded questions."""

from __future__ import annotations

import io
import json
from uuid import uuid4

import pytest
from src.backend.artifacts import exam_style
from src.backend.common import provider
from src.backend.common.db import connection
from src.backend.common.provider import GenerationResult
from src.backend.common.schemas.learning import PracticeQuestion
from src.backend.retrieval.funnel import Candidate
from src.backend.student_model import inspection, learning
from src.backend.student_model.grading import missed_points, short_answer_correct
from tests.factories import add_chunk, make_course
from tests.test_extract import _pdf_with_pages, _show

PASSAGE = (
    "Linear maps preserve addition and scaling. Scalar multiplication is "
    "preserved together with addition by linear maps."
)
EXEMPLAR = (
    "Uploaded quiz about classroom style only. Students identify a linear "
    "map from a short list and then justify that classification in their "
    "own words."
)
MARK = "classroom style only"
PROFILE = {
    "topics": ["Linear maps"],
    "difficulty": "explanation",
    "style": "Ask for a property and a short justification.",
    "items": [{"format": "multiple_choice"}, {"format": "short_answer"}],
}
QUESTIONS = {
    "title": "ignored",
    "questions": [
        {
            "format": "multiple_choice",
            "prompt": "Which property do linear maps keep along with addition?",
            "options": [
                "Scalar multiplication",
                "Only vector lengths",
                "Only measured angles",
            ],
            "answer": 0,
            "explanation": (
                "The passage says this property is preserved together with addition."
            ),
            "sources": [1],
            "topic": "Linear maps",
            "capability": "explanation",
        },
        {
            "format": "multi_part",
            "stem": "A map sends every vector to twice itself.",
            "parts": [
                {
                    "format": "short_answer",
                    "prompt": "What two operations do linear maps preserve?",
                    "expected": "They preserve addition and scaling.",
                    "points": ["preserve addition", "preserve scaling"],
                    "explanation": "The passage names addition and scaling.",
                    "sources": [1],
                    "topic": "Linear maps",
                    "capability": "explanation",
                }
            ],
        },
    ],
}


def _result(text: str) -> GenerationResult:
    return GenerationResult(
        text=text, model="test", input_tokens=1, output_tokens=1, provider="test"
    )


def _install(monkeypatch: pytest.MonkeyPatch, replies: dict[str, str]) -> list[dict]:
    calls: list[dict] = []

    def fake(task: str, prompt: str, **kwargs: object) -> GenerationResult:
        calls.append({"task": task, "prompt": prompt, "images": kwargs.get("images")})
        if task == "ocr":
            return _result(replies.get("ocr", EXEMPLAR))
        if "STYLE PROFILE" in prompt:
            return _result(replies["quiz"])
        return _result(replies["profile"])

    monkeypatch.setattr(provider, "generate", fake)
    monkeypatch.setattr(exam_style, "embed_search", lambda _text: None)
    return calls


def _course():
    course = make_course()
    add_chunk(course.course_id, PASSAGE)
    return course


def _upload(client, course_id, name: str, raw: bytes, mime: str):
    return client.post(
        f"/courses/{course_id}/artifacts/exam-style",
        files={"file": (name, raw, mime)},
    )


def _png() -> bytes:
    from PIL import Image

    image = Image.new("RGB", (32, 32), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _candidate(text: str) -> Candidate:
    return Candidate(
        chunk_id=uuid4(),
        source_id=uuid4(),
        locator_id=uuid4(),
        chunk_index=0,
        text=text,
        layers=frozenset({"keyword"}),
        rank=1.0,
    )


def test_overlap_detector_ignores_short_topic_names() -> None:
    shared = "students identify a linear map from a short"
    assert exam_style.copies_exemplar(shared, EXEMPLAR)
    long = "Students identify a linear map from a short list and then justify"
    assert exam_style.copies_exemplar(long, EXEMPLAR)
    assert not exam_style.copies_exemplar("Linear maps", EXEMPLAR)
    assert not exam_style.copies_exemplar(
        "Which property do linear maps keep along with addition?", EXEMPLAR
    )


def test_short_answer_grader_requires_every_point() -> None:
    points = ["preserve addition", "preserve scaling"]
    assert short_answer_correct("PRESERVE ADDITION and PRESERVE SCALING", points)
    assert missed_points("They preserve addition only.", points) == ["preserve scaling"]
    assert not short_answer_correct("They keep sums and resized vectors.", points)
    assert not short_answer_correct("   ", points)
    assert not short_answer_correct("preserve addition and scaling", [])


def test_empty_profile_is_not_a_quiz() -> None:
    with pytest.raises(exam_style.ExamStyleError, match="does not look like"):
        exam_style.profile_from_model({"topics": [], "items": [], "stem": "secret"})


def test_copied_questions_are_rejected_before_save() -> None:
    profile = exam_style.profile_from_model(PROFILE)
    copied = "Students identify a linear map from a short list and then justify"
    with pytest.raises(exam_style.ExamStyleError, match="without repeating"):
        exam_style.accept_questions(
            [{"format": "multiple_choice", "prompt": copied, "options": ["A", "B"]}],
            profile,
            (_candidate(PASSAGE),),
            EXEMPLAR,
        )


def test_upload_saves_new_questions_and_leaves_sources_unchanged(
    client, monkeypatch
) -> None:
    course = _course()
    calls = _install(
        monkeypatch,
        {"profile": json.dumps(PROFILE), "quiz": json.dumps(QUESTIONS)},
    )
    before = client.get(f"/courses/{course.course_id}/sources").json()
    pdf = _pdf_with_pages([_show(EXEMPLAR)])
    response = _upload(client, course.course_id, "midterm.pdf", pdf, "application/pdf")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "quiz"
    assert body["title"] == "Exam-style practice: Linear maps"
    assert MARK not in json.dumps(body["origin"])
    assert MARK not in json.dumps(body["content"])
    origin = body["origin"]["exam_style"]
    assert origin["filename"] == "midterm.pdf"
    assert origin["topics"] == ["Linear maps"]
    assert origin["difficulty"] == "explanation"
    assert origin["formats"] == ["multiple_choice", "short_answer"]
    questions = body["content"]["questions"]
    assert len(questions) == 2
    choice = questions[0]
    assert choice["options"][choice["answer"]] == "Scalar multiplication"
    short = questions[1]
    assert short["format"] == "short_answer"
    assert short["stem"] == "A map sends every vector to twice itself."
    assert short["part"] == "a"
    assert short["points"] == ["preserve addition", "preserve scaling"]
    assert client.get(f"/courses/{course.course_id}/sources").json() == before
    versions = client.get(
        f"/courses/{course.course_id}/artifacts/{body['artifact_id']}/versions"
    ).json()
    assert "not added to course sources" in versions[0]["note"]
    quiz_prompts = [
        call["prompt"] for call in calls if "STYLE PROFILE" in call["prompt"]
    ]
    assert quiz_prompts and MARK not in quiz_prompts[0]
    assert PASSAGE[:40] in quiz_prompts[0]
    assert any(MARK in call["prompt"] for call in calls)
    assert all(call["task"] != "ocr" for call in calls)


def test_copied_upload_saves_nothing(client, monkeypatch) -> None:
    course = _course()
    copied = "Students identify a linear map from a short list and then justify"
    _install(
        monkeypatch,
        {
            "profile": json.dumps(PROFILE),
            "quiz": json.dumps(
                {"questions": [{"format": "short_answer", "prompt": copied}]}
            ),
        },
    )
    pdf = _pdf_with_pages([_show(EXEMPLAR)])
    response = _upload(client, course.course_id, "exam.pdf", pdf, "application/pdf")
    assert response.status_code == 422
    assert "without repeating" in response.json()["detail"]
    assert client.get(f"/courses/{course.course_id}/artifacts").json() == []


def test_non_quiz_and_unreadable_files_are_rejected(client, monkeypatch) -> None:
    course = _course()
    calls = _install(
        monkeypatch, {"profile": json.dumps({"topics": [], "items": []}), "quiz": "{}"}
    )
    pdf = _pdf_with_pages([_show(EXEMPLAR)])
    empty = _upload(client, course.course_id, "notes.pdf", pdf, "application/pdf")
    assert empty.status_code == 422
    assert "does not look like" in empty.json()["detail"]
    junk = _upload(
        client, course.course_id, "notes.txt", b"this is not a quiz", "text/plain"
    )
    assert junk.status_code == 422
    assert "PDF, PNG, JPEG, or WebP" in junk.json()["detail"]
    assert client.get(f"/courses/{course.course_id}/artifacts").json() == []
    assert calls and all(call["task"] != "ocr" for call in calls)


def test_photo_uses_ocr_and_a_down_model_is_unavailable(client, monkeypatch) -> None:
    course = _course()
    calls = _install(
        monkeypatch,
        {"profile": json.dumps(PROFILE), "quiz": json.dumps(QUESTIONS)},
    )
    saved = _upload(client, course.course_id, "quiz.png", _png(), "image/png")
    assert saved.status_code == 201, saved.text
    assert calls[0]["task"] == "ocr"
    assert calls[0]["images"]
    assert MARK not in json.dumps(saved.json()["content"])

    def offline(*_args, **_kwargs):
        raise provider.ProviderUnavailableError("model offline")

    monkeypatch.setattr(provider, "generate", offline)
    down = _upload(client, course.course_id, "quiz.png", _png(), "image/png")
    assert down.status_code == 503


def test_short_answer_submit_grades_points_and_a_flag_excludes_it(client) -> None:
    course = make_course()
    chunk = add_chunk(course.course_id, PASSAGE)
    with connection() as conn:
        suite_id = learning.create_suite(
            conn,
            course.course_id,
            "Short answers",
            [
                PracticeQuestion(
                    format="short_answer",
                    prompt="What do linear maps preserve?",
                    expected="They preserve addition and scaling.",
                    points=["preserve addition", "preserve scaling"],
                    sources=[1],
                    topic="Linear maps",
                    capability="explanation",
                )
            ],
            (chunk,),
            {"by": "test", "batch": str(uuid4())},
        )
        conn.commit()

    def submit(answer: str):
        return client.post(
            f"/courses/{course.course_id}/practice/{suite_id}/runs",
            json={"run_id": str(uuid4()), "answers": [answer]},
        )

    correct = submit("PRESERVE ADDITION and PRESERVE SCALING")
    assert correct.status_code == 200, correct.text
    assert correct.json()["results"] == [True]
    assert correct.json()["missed_points"] == [[]]
    assert correct.json()["correct_answers"] == [None]
    with connection() as conn:
        observed = inspection.rows(conn, "observations", course_id=course.course_id)
    evidence = observed[0]["evidence"]
    assert evidence["selected"] == "PRESERVE ADDITION and PRESERVE SCALING"
    assert evidence["selected_index"] is None
    assert evidence["key"] == "They preserve addition and scaling."

    missed = submit("They preserve addition only.")
    assert missed.status_code == 200, missed.text
    assert missed.json()["results"] == [False]
    assert missed.json()["missed_points"] == [["preserve scaling"]]

    flagged = client.patch(
        f"/courses/{course.course_id}/practice/{suite_id}/questions/0",
        json={"answer": None, "reason": "The wording is ambiguous."},
    )
    assert flagged.status_code == 200, flagged.text
    state = client.get(f"/courses/{course.course_id}/practice/{suite_id}").json()
    assert state["latest_run"]["results"] == [None]
    with connection() as conn:
        revised = inspection.rows(conn, "observations", course_id=course.course_id)
    assert all(row["correct"] is None for row in revised)

    remap = client.patch(
        f"/courses/{course.course_id}/practice/{suite_id}/questions/0",
        json={"answer": 0, "reason": "Try to remap a short answer."},
    )
    assert remap.status_code == 422
