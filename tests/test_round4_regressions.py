"""Round-4 retest regressions (docs/RETEST-round4.md): the R4-NEW-* bugs and
the code-review findings they turned up. Each test is the report's repro,
without a model."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from src.backend.artifacts import exam_style
from src.backend.common import migrate, provider
from src.backend.common.prompt_registry import load_prompt_policy
from src.backend.common.schemas.work import WorkCitation
from src.backend.ingest.extract import (
    ExtractedSource,
    _join_pages,
    _pdf_locators,
    assess_pages,
    clean_text,
    page_quality,
)
from src.backend.ingest.ocr_pages import split_ocr_pages
from src.backend.student_model.grading import (
    missed_points,
    point_covered,
    short_answer_correct,
)
from src.backend.tutor.compose import (
    Intent,
    _shuffle_quiz_options,
    classify_intent,
    retrieval_topic,
)
from src.backend.tutor.critique import (
    _names_fallacy,
    refuses_rewrite,
    validate_findings,
)
from src.backend.tutor.materials import has_body
from src.backend.tutor.work import document_context
from tests.test_exam_style import EXEMPLAR, PASSAGE, PROFILE, _candidate
from tests.test_providers import REAL_CALL, _capture_post, _endpoint, _Response


def _completion(text: str, finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": text}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 8},
    }


def _finding(original: str, feedback: str, **extra: Any) -> dict[str, Any]:
    return {
        "original": original,
        "feedback": feedback,
        "dimension": "reasoning",
        "grounding": "craft",
        "fallacy": "none",
        **extra,
    }


# --- R4-NEW-a: a refusal is a canned reply, not any prose that says "rejected"


def test_prose_about_a_rejected_request_is_an_answer_not_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reply = "The 1836 request was rejected by the Mexican Congress."
    _capture_post(monkeypatch, _Response(200, _completion(reply)))
    assert REAL_CALL("tutor_answer", _endpoint(), "prompt")[0] == reply
    insurers = "Some rates were considered high risk by insurers."
    _capture_post(monkeypatch, _Response(200, _completion(insurers)))
    assert REAL_CALL("tutor_answer", _endpoint(), "prompt")[0] == insurers


@pytest.mark.parametrize(
    "reply",
    [
        "The request was rejected because it was considered high risk",
        "Your request was rejected because it was considered unsafe.",
        "the request was rejected.",
    ],
)
def test_a_whole_canned_refusal_still_stops_the_answer(
    monkeypatch: pytest.MonkeyPatch, reply: str
) -> None:
    _capture_post(monkeypatch, _Response(200, _completion(reply)))
    with pytest.raises(provider.ModelRefusalError, match="refused to answer"):
        REAL_CALL("tutor_answer", _endpoint(), "prompt")


def test_content_filter_finish_reason_is_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _completion("Harmless text.", finish_reason="content_filter")
    _capture_post(monkeypatch, _Response(200, body))
    with pytest.raises(provider.ModelRefusalError, match="refused to answer"):
        REAL_CALL("tutor_answer", _endpoint(), "prompt")


# --- R4-NEW-f: a malformed reply is not retried as if the network failed


def test_a_shape_error_is_not_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_post(monkeypatch, _Response(200, {"choices": []}))
    with pytest.raises(provider.ProviderUnavailableError) as raised:
        REAL_CALL("tutor_answer", _endpoint(), "prompt")
    assert not raised.value.transient


# --- R4-NEW-d: one page is the whole reply, separators or not


def test_single_page_ocr_keeps_a_markdown_rule_inside_the_page() -> None:
    assert split_ocr_pages("Title\n\n---\n\nBody", 1) == ["Title\n\n---\n\nBody"]
    assert split_ocr_pages("[blank]", 1) == [""]


def test_a_leading_separator_is_not_an_extra_page() -> None:
    assert split_ocr_pages("---\nA\n---\nB\n---\nC\n---\nD", 4) == ["A", "B", "C", "D"]


# --- R4-NEW-b: shuffling must not break options that name each other


def _quiz(options: list[str], answer: int, explanation: str) -> dict[str, Any]:
    return {
        "type": "quiz",
        "questions": [
            {
                "prompt": "Which treaties shaped the border?",
                "options": options,
                "answer": answer,
                "explanation": explanation,
            }
        ],
    }


def test_shuffle_rewrites_positional_options_and_letter_explanations() -> None:
    item = _quiz(
        ["Guadalupe Hidalgo", "Adams-Onís", "Both A and B", "None of the above"],
        0,
        "Option A is correct. Option B is a definition.",
    )
    question = _shuffle_quiz_options(item)["questions"][0]
    options = question["options"]
    assert question["answer"] == options.index("Guadalupe Hidalgo")
    assert "None of these choices" in options
    moved = chr(ord("A") + question["answer"])
    assert question["explanation"].startswith(f"Option {moved} is correct")
    second = chr(ord("A") + options.index("Adams-Onís"))
    assert f"Option {second} is a definition" in question["explanation"]


def test_an_unrewritable_positional_option_pins_the_question() -> None:
    item = _quiz(["First", "Second", "See option A above", "Fourth"], 1, "")
    question = _shuffle_quiz_options(item)["questions"][0]
    assert question["options"] == ["First", "Second", "See option A above", "Fourth"]
    assert question["answer"] == 1


# --- R4-NEW-c: claims keep their roles, numbers and acronyms normalize


def test_short_answers_reject_a_reversed_claim_and_accept_a_paraphrase() -> None:
    point = "The United States paid Mexico $15 million"
    assert not point_covered("Mexico paid the United States 15 million", point)
    assert not point_covered("united states mexico paid 15 million", point)
    assert point_covered("The U.S. paid Mexico fifteen million dollars", point)
    assert point_covered("The US paid Mexico $15M", point)
    assert point_covered("The United States paid Mexico 15,000,000 dollars", point)


def test_negation_reaches_its_clause_and_no_further() -> None:
    assert not point_covered(
        "There is no evidence that they preserve addition", "preserve addition"
    )
    assert point_covered(
        "The evidence is not absent. They preserve addition.", "preserve addition"
    )
    assert point_covered(
        "They did not reject it, and preserve addition", "preserve addition"
    )
    assert missed_points("They preserve addition only.", ["preserve scaling"]) == [
        "preserve scaling"
    ]
    assert short_answer_correct("It works.", ["It works."])


# --- R4-NEW-g: the topic keeps what names the material


@pytest.mark.parametrize(
    ("question", "topic", "intent"),
    [
        ("Make a quiz on week 3", "week 3", Intent.QUIZ),
        ("Make a quiz about the 1848 treaty", "1848 treaty", Intent.QUIZ),
        ("Make a table reproducing Table 2.2", "reproducing Table 2.2", Intent.SHEET),
        ("Make an 8-slide deck on Week 2", "Week 2", Intent.SLIDES),
        ("Quiz me with 10 questions on Week 3", "Week 3", Intent.QUIZ),
    ],
)
def test_retrieval_topic_keeps_numbered_subjects(
    question: str, topic: str, intent: Intent
) -> None:
    assert retrieval_topic(question) == topic
    assert classify_intent(question) == intent


def test_a_deck_is_an_artifact_even_when_it_comes_from_notes() -> None:
    assert classify_intent("Make a deck from my notes") == Intent.SLIDES
    assert classify_intent("give me the notes") == Intent.ANSWER


# --- R4-NEW-h: asking how to write is advice, not a rewrite demand


def test_advice_seeking_is_not_a_rewrite_request() -> None:
    assert not refuses_rewrite("How should I write my conclusion section?")
    assert not refuses_rewrite("What would make it better?")
    assert not refuses_rewrite(
        "Can you help me write a stronger thesis for this paper?"
    )
    assert refuses_rewrite("Rewrite this paragraph")
    assert refuses_rewrite("write the essay")
    assert refuses_rewrite("make it better")


# --- R4-NEW-i: a bare label is still only a heading


def test_a_heading_label_is_not_body() -> None:
    assert not has_body("## Overview", "Deck")
    assert not has_body("Exam Essentials", "Deck")
    assert has_body("### Key term – definition [1]")
    assert has_body("The land was the key issue [1].")


# --- R4-NEW-k: lone returns and C0 controls are cleaned


def test_clean_text_removes_controls_and_normalizes_returns() -> None:
    assert clean_text("a\rb\x0bc\x10d") == "a\nbcd"
    assert clean_text("one\r\ntwo") == "one\ntwo"
    assert "\t" in clean_text("a\tb")


# --- R4-NEW-n: one bad finding costs that finding, not the review


def test_a_fallacy_can_be_explained_without_the_label_verbatim() -> None:
    assert _names_fallacy(
        "This claim is not supported by any cited evidence.", "unsupported_claim"
    )
    assert _names_fallacy(
        "…and it never addresses a counterargument.", "missing_counterargument"
    )
    assert _names_fallacy("This is a post-hoc inference.", "post_hoc")
    assert _names_fallacy("You generalize hastily here.", "hasty_generalization")
    assert not _names_fallacy("The warrant is thin.", "straw_man")


def test_one_unusable_finding_is_dropped_not_the_whole_critique() -> None:
    draft = "First sentence here. Second sentence here. Third sentence here."
    findings = [
        _finding("First sentence here.", "The warrant is thin."),
        _finding("Not in this draft at all.", "Invented quote."),
        _finding("Second sentence here.", "The motive is unearned."),
    ]
    kept, _ = validate_findings(
        {"findings": findings},
        document_text=draft,
        scope=draft,
        genre="argumentative",
        cap=5,
        citations=[],
        open_quotes=set(),
    )
    assert [finding.original for finding in kept] == [
        "First sentence here.",
        "Second sentence here.",
    ]


def test_a_critique_whose_findings_all_fail_is_still_rejected() -> None:
    with pytest.raises(ValueError, match="outside the reviewed draft"):
        validate_findings(
            {"findings": [_finding("Not in this draft.", "Thin.")]},
            document_text="Only this sentence.",
            scope="Only this sentence.",
            genre="argumentative",
            cap=5,
            citations=[],
            open_quotes=set(),
        )


def test_only_the_citations_of_kept_findings_are_reported() -> None:
    citations = [
        WorkCitation(
            number=1,
            chunk_id=str(_candidate("x").chunk_id),
            source_id=str(_candidate("x").source_id),
            filename="Week1",
            label="p. 1",
            text="x",
        )
    ]
    draft = "One. Two."
    kept, used = validate_findings(
        {
            "findings": [
                _finding("One.", "Thin. [1]"),
                _finding("Two.", "Invented. [9]"),
            ]
        },
        document_text=draft,
        scope=draft,
        genre="argumentative",
        cap=5,
        citations=citations,
        open_quotes=set(),
    )
    assert [finding.original for finding in kept] == ["One."]
    assert [citation.number for citation in used] == [1]


# --- R4-NEW-o: the question text may arrive as "stem"


def test_exam_style_reads_the_question_text_from_stem() -> None:
    profile = exam_style.profile_from_model(PROFILE)
    question = {
        "format": "short_answer",
        "stem": "Which property do linear maps preserve?",
        "expected": "Linear maps preserve addition.",
        "points": ["preserve addition"],
        "sources": [1],
    }
    accepted = exam_style.accept_questions(
        [question], profile, (_candidate(PASSAGE),), EXEMPLAR
    )
    assert accepted[0]["prompt"] == "Which property do linear maps preserve?"


# --- R4-NEW-p: a request about "the introduction" reaches that section


def test_document_context_finds_the_named_section() -> None:
    units = []
    for index in range(20):
        if index == 1:
            body = "The team collected survey evidence. " * 40
            units.append(f"paragraph {index + 1}\nIntroduction\n{body}")
        else:
            body = "The corpus overview lists cohort numbers. " * 40
            units.append(f"paragraph {index + 1}\nSection body\n{body}")
    context, _ = document_context(
        "\n\n".join(units),
        "Rewrite the introduction paragraph so it is clearer and more formal.",
    )
    assert "Introduction" in context


# --- R4-NEW-q: interactive answers may think longer than a summary


def test_reasoning_allowance_is_per_task(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.backend.common.generation import plan_call
    from src.backend.common.generation_config import load_generation_policy

    class _Profile:
        reasoning = True
        max_output_tokens = 16_384
        output_token_limit = None
        context_window_tokens = None

    monkeypatch.setattr(
        "src.backend.common.model_profiles.profile_for", lambda _m: _Profile()
    )
    answer = plan_call("tutor_answer", _endpoint(model="mimo-v2.6-flash"), "prompt")
    summary = plan_call(
        "conversation_summary", _endpoint(model="mimo-v2.6-flash"), "prompt"
    )
    policy = load_generation_policy()
    assert answer.output_tokens == min(
        16_384,
        policy.tasks["tutor_answer"].desired_output_tokens
        * policy.tasks["tutor_answer"].reasoning_multiplier,
    )
    assert summary.output_tokens < answer.output_tokens


# --- R4-NEW-l / R4-NEW-e: a refusal is retried, then pages go one at a time


def _ocr_handlers(pages: list[str]) -> Any:
    from src.backend.ingest import orchestrator

    report = assess_pages(pages, min_page_chars=20, quality_floor=0.35)
    extracted = ExtractedSource(
        _join_pages(pages), _pdf_locators(pages), tuple(pages), report
    )
    source = orchestrator.SourceRow(*_source_row_args())
    handlers = orchestrator.IngestionHandlers(
        None, source, ocr_max_pages=4, ocr_scale=1, ocr_batch_pages=4
    )
    handlers.extracted = extracted
    handlers.needs_ocr = True
    return handlers


def test_a_refused_ocr_batch_is_retried_then_read_page_by_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.backend.common import generation
    from src.backend.common.provider import GenerationResult
    from src.backend.ingest import extract, orchestrator

    handlers = _ocr_handlers(["", "", "", ""])
    calls: list[Any] = []

    def render(*args, pages, **kwargs):
        return [extract.RasterizedPage(index, b"png") for index in pages]

    def generate(*args, **kwargs):
        images = kwargs.get("images") or []
        calls.append((len(images), generation._OPERATION.get()))
        if len(calls) <= 2:
            raise provider.ModelRefusalError("the request was rejected")
        text = f"page words clearly recognized {len(calls)}"
        return GenerationResult(text, "m", 1, 1)

    monkeypatch.setattr(extract, "rasterize_pages_with_ids", render)
    monkeypatch.setattr(orchestrator.provider, "generate", generate)
    with generation.operation():
        handlers.ocr()
    assert [size for size, _ in calls] == [4, 4, 1, 1, 1, 1]
    assert all(page.strip() for page in handlers.extracted.page_texts)
    # The per-page retries must not spend the batch's budget (R4-NEW-e).
    assert calls[0][1] is calls[1][1]
    assert calls[2][1] is not calls[0][1]


def test_ocr_warning_lists_pages_in_order_and_without_developer_text() -> None:
    from src.backend.ingest import orchestrator
    from src.backend.ingest.pipeline import StageWarning

    pages = ["readable page", "", "readable page"]
    report = assess_pages(pages, min_page_chars=20, quality_floor=0.35)
    extracted = ExtractedSource(
        _join_pages(pages), _pdf_locators(pages), tuple(pages), report
    )
    source = orchestrator.SourceRow(*_source_row_args())
    handlers = orchestrator.IngestionHandlers(
        None, source, ocr_max_pages=10, ocr_scale=1
    )
    handlers.extracted = extracted
    with pytest.raises(StageWarning) as raised:
        handlers._warn_if_incomplete(
            [1, 0],
            ["pages 5, 2 were declined by the reading model"],
            cap_exceeded=False,
        )
    message = str(raised.value)
    assert "unresolved pages 2" in message
    assert "pages 1 have only a little text" in message
    assert "declined by the reading model" in message
    assert "warning:" not in message
    assert "pick another model" not in message


def _source_row_args() -> tuple[Any, ...]:
    from uuid import uuid4

    return uuid4(), uuid4(), "text/plain", "identity"


def test_migration_versions_cannot_be_interpolated() -> None:
    with pytest.raises(ValueError, match="unrecognized migration version"):
        migrate._migration_script("CREATE TABLE t (a);", "001'); DROP TABLE t; --")


def test_an_overlong_content_length_is_rejected_before_int() -> None:
    from src.backend.common.body_limits import BodyLimitMiddleware

    async def _app(scope, receive, send):  # pragma: no cover - never reached
        raise AssertionError("the body must be refused first")

    async def _run() -> list[dict[str, Any]]:
        sent: list[dict[str, Any]] = []

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b""}

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/companion/courses/x/work/y/file",
            "headers": [
                (b"content-type", b"multipart/form-data; boundary=x"),
                (b"content-length", b"9" * 5000),
            ],
        }
        await BodyLimitMiddleware(_app)(scope, receive, send)
        return sent

    sent = asyncio.run(_run())
    assert sent[0]["status"] == 413


def test_a_prompt_section_without_text_is_a_configuration_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "prompts.toml"
    path.write_text(
        '[version]\nprompts_config_version = "1"\n\n[prompt.broken]\nnope = 1\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must define a text body"):
        load_prompt_policy(path)


def test_backup_ids_are_lowercase_hex() -> None:
    from src.backend.common import backups

    with pytest.raises(ValueError, match="invalid backup id"):
        backups.recover_backup("Z" * 32)
    with pytest.raises(ValueError, match="invalid backup id"):
        backups.recover_backup("notes.md")


def test_page_quality_stays_in_range() -> None:
    noisy = "/" + ".o" * 200
    assert 0.0 <= page_quality(noisy) <= 1.0
