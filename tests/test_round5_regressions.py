"""Round-5 retest regressions (docs/RETEST-round5.md, docs/STATUS-round5.md):
the R5-NEW-* bugs. Each test is the report's repro, without a model."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from src.backend.common import provider, storage
from src.backend.common.prompt_registry import strip_fence_echo
from src.backend.ingest.extract import (
    ExtractedSource,
    _join_pages,
    _pdf_locators,
    assess_pages,
)
from src.backend.ingest.ocr_pages import split_ocr_pages
from src.backend.ingest.pipeline import StageWarning
from src.backend.student_model.grading import point_covered
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
from src.backend.tutor.materials import _reflowed, has_body
from src.backend.tutor.workspace import extract_workspace_items
from tests.test_providers import REAL_CALL, _capture_post, _endpoint, _Response


def _completion(text: str, finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": text}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 8},
    }


# --- R5-NEW-l: U+2028 inside a JSON string must not invalidate the block


def test_unicode_line_separator_keeps_the_workspace_block_valid() -> None:
    payload = json.dumps(
        {
            "type": "document",
            "title": "T",
            "content": "- a\u2028- b",
            "sources": [1],
        },
        ensure_ascii=False,
    )
    extracted = extract_workspace_items(
        strip_fence_echo(f"```workspace\n{payload}\n```"), 3
    )
    assert extracted.withheld == ()
    assert extracted.items and extracted.items[0].type == "document"


# --- R5-NEW-c: a hyphenated numeric range names the material


@pytest.mark.parametrize(
    ("question", "fragment"),
    [
        ("Create a study guide for the first exam covering Weeks 1-5", "1-5"),
        ("Make a quiz on pages 40-45", "40-45"),
        ("Make a study guide on 1846-1848", "1846-1848"),
    ],
)
def test_retrieval_topic_keeps_number_ranges(question: str, fragment: str) -> None:
    topic = retrieval_topic(question)
    assert fragment in topic
    assert classify_intent(question) in (Intent.DOCUMENT, Intent.QUIZ)


def test_a_hyphenated_size_count_is_still_dropped() -> None:
    assert "10-question" not in retrieval_topic("Make a 10-question quiz on Week 3")
    assert "8-slide" not in retrieval_topic("Make an 8-slide deck on Week 2")


# --- R5-NEW-d: options that name each other by position still pin the question


def _quiz(options: list[str], answer: int, explanation: str) -> dict[str, Any]:
    return {
        "type": "quiz",
        "questions": [
            {
                "prompt": "Which is correct?",
                "options": options,
                "answer": answer,
                "explanation": explanation,
            }
        ],
    }


@pytest.mark.parametrize(
    "options",
    [
        ["First", "Second", "Both of the above", "Fourth"],
        ["First", "Second", "Neither A nor B", "Fourth"],
        ["First", "Second", "A and B only", "Fourth"],
    ],
)
def test_a_positional_option_pins_the_question(options: list[str]) -> None:
    question = _shuffle_quiz_options(_quiz(options, 1, ""))["questions"][0]
    assert question["options"] == options
    assert question["answer"] == 1


def test_a_parenthesised_letter_in_the_explanation_follows_the_shuffle() -> None:
    options = ["Guadalupe Hidalgo", "Adams-Onís", "Third option", "Fourth option"]
    question = _shuffle_quiz_options(_quiz(options, 0, "(A) is correct."))["questions"][
        0
    ]
    moved = chr(ord("A") + question["answer"])
    assert question["explanation"] == f"({moved}) is correct."


# --- R5-NEW-k / -e / -t / -u: reflow keeps bullets, indentation and tables


def test_a_glued_bullet_list_splits_into_separate_lines() -> None:
    glued = (
        "…manifest destiny [10].- **Annexation of Texas** — a [5].- **Rio Grande** — b"
    )
    paragraphs = _reflowed([glued])
    assert len(paragraphs) == 1
    lines = paragraphs[0].splitlines()
    assert sum(line.startswith("- **") for line in lines) == 2


def test_code_block_indentation_is_preserved() -> None:
    paragraphs = _reflowed(["```\ndef f(x):\n    if x:\n        return 1\n```"])
    assert "    if x:" in paragraphs[0]
    assert "        return 1" in paragraphs[0]


def test_code_block_blank_lines_are_preserved() -> None:
    paragraphs = _reflowed(["```\ndef f(x):\n\n    return 1\n```"])
    assert "def f(x):\n\n    return 1" in paragraphs[0]


def test_br_inside_a_table_cell_does_not_split_the_table() -> None:
    paragraphs = _reflowed(
        [
            "| Date | Event |",
            "|---|---|",
            "| 1846 | War begins<br>Thornton Affair |",
            "| 1848 | Treaty |",
        ]
    )
    assert len(paragraphs) == 1
    assert "<br>" in paragraphs[0]


def test_two_adjacent_tables_are_kept_separate() -> None:
    paragraphs = _reflowed(
        [
            "| A | B |",
            "|---|---|",
            "| 1 | 2 |",
            "| C | D | E |",
            "|---|---|---|",
            "| 3 | 4 | 5 |",
        ]
    )
    assert len(paragraphs) == 2


# --- R5-NEW-f: a key term is body, a structural heading is not


def test_a_bare_key_term_is_body_but_a_heading_is_not() -> None:
    assert has_body("Manifest Destiny")
    assert has_body("Encomienda")
    assert not has_body("## Overview", "Deck")
    assert not has_body("Exam Essentials", "Deck")
    assert has_body("### Key term – definition [1]")


# --- R5-NEW-g: a leading and trailing OCR separator both strip


def test_leading_and_trailing_ocr_separators_both_strip() -> None:
    assert split_ocr_pages("---\nA\n---\nB\n---\n", 2) == ["A", "B"]
    assert split_ocr_pages("---\nA\n---\nB", 2) == ["A", "B"]


# --- R5-NEW-a: the fallacy matcher needs more than a 4-character overlap


def test_fallacy_matching_rejects_coincidental_substrings() -> None:
    assert not _names_fallacy(
        "You need to determine your thesis more clearly.", "ad_hominem"
    )
    assert not _names_fallacy("This strategy section is vague.", "straw_man")
    assert _names_fallacy(
        "This claim is not supported by any cited evidence.", "unsupported_claim"
    )
    assert _names_fallacy("You generalize hastily here.", "hasty_generalization")


# --- R5-NEW-i: a question-phrased rewrite demand is still a rewrite


def test_a_question_phrased_rewrite_is_refused_but_advice_is_not() -> None:
    assert refuses_rewrite("Can you help me rewrite this paragraph?")
    assert refuses_rewrite("Why don't you just rewrite my essay for me?")
    assert refuses_rewrite("Could you help me finish my essay?")
    assert not refuses_rewrite("How should I write my conclusion section?")
    assert not refuses_rewrite("What would make it better?")


# --- R5-NEW-n: a raw snake_case label is stripped from feedback


def test_a_leading_snake_case_label_is_stripped_from_feedback() -> None:
    draft = "First sentence here. Second sentence here."
    kept, _ = validate_findings(
        {
            "findings": [
                {
                    "original": "First sentence here.",
                    "feedback": "unsupported_claim: this sentence asserts too much.",
                    "dimension": "reasoning",
                    "grounding": "craft",
                    "fallacy": "none",
                }
            ]
        },
        document_text=draft,
        scope=draft,
        genre="argumentative",
        cap=5,
        citations=[],
        open_quotes=set(),
    )
    assert kept[0].feedback == "this sentence asserts too much."


# --- R5-NEW-b: passive / reordered answers and "not … until" are correct


def test_correct_passive_and_reordered_answers_are_accepted() -> None:
    money = "The United States paid Mexico $15 million"
    assert point_covered("Mexico was paid 15 million by the United States", money)
    assert not point_covered("Mexico paid the United States 15 million", money)
    assert not point_covered("The United States did not pay Mexico $15 million", money)
    annexation = "Texas was annexed in 1845"
    assert point_covered("In 1845 Texas was annexed", annexation)
    assert point_covered("Texas was not annexed until 1845", annexation)
    assert point_covered("Texas joined the US in 1845 when it was annexed", annexation)
    # A synonym verb still needs a model; recorded as a known limitation.
    assert not point_covered(
        "Mexico received $15 million from the United States", money
    )


# --- R5-NEW-h: short canned refusals are still recognized


@pytest.mark.parametrize(
    "reply",
    [
        "Request rejected.",
        "Your request was rejected as it may contain sensitive content.",
        "the request was rejected.",
        "请求被拒绝",
    ],
)
def test_short_canned_refusals_are_detected(
    monkeypatch: pytest.MonkeyPatch, reply: str
) -> None:
    _capture_post(monkeypatch, _Response(200, _completion(reply)))
    with pytest.raises(provider.ModelRefusalError, match="refused to answer"):
        REAL_CALL("tutor_answer", _endpoint(), "prompt")


def test_prose_about_a_rejected_request_is_still_an_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reply = "The 1836 request was rejected by the Mexican Congress."
    _capture_post(monkeypatch, _Response(200, _completion(reply)))
    assert REAL_CALL("tutor_answer", _endpoint(), "prompt")[0] == reply


# --- R5-NEW-o / R5-NEW-r: a transient batch failure falls back per page and
# the raw provider text never reaches the student


def _ocr_handlers(pages: list[str]) -> Any:
    from src.backend.ingest import orchestrator

    report = assess_pages(pages, min_page_chars=20, quality_floor=0.35)
    extracted = ExtractedSource(
        _join_pages(pages), _pdf_locators(pages), tuple(pages), report
    )
    handlers = orchestrator.IngestionHandlers(
        None,
        orchestrator.SourceRow(uuid4(), uuid4(), "text/plain", "identity"),
        ocr_max_pages=4,
        ocr_scale=1,
        ocr_batch_pages=4,
    )
    handlers.extracted = extracted
    handlers.needs_ocr = True
    return handlers


def test_a_transient_ocr_batch_failure_reads_page_by_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.backend.common import generation
    from src.backend.common.provider import GenerationResult
    from src.backend.ingest import extract, orchestrator

    handlers = _ocr_handlers(["", "", "", ""])
    calls: list[int] = []

    def render(*args, pages, **kwargs):
        return [extract.RasterizedPage(index, b"png") for index in pages]

    def generate(*args, **kwargs):
        images = kwargs.get("images") or []
        calls.append(len(images))
        if len(images) > 1:
            # A dropped connection, not a refusal (R5-NEW-o).
            raise provider.ProviderUnavailableError(
                "peer closed connection", transient=True
            )
        return GenerationResult(f"page {len(calls)} clearly recognized", "m", 1, 1)

    monkeypatch.setattr(extract, "rasterize_pages_with_ids", render)
    monkeypatch.setattr(orchestrator.provider, "generate", generate)
    with generation.operation():
        handlers.ocr()
    assert calls == [4, 4, 1, 1, 1, 1]


def test_a_truncated_ocr_batch_reads_page_by_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Four dense pages can outgrow a model's output limit where one fits:
    seen with a profile-less model at the 2048-token default."""
    from src.backend.common import generation
    from src.backend.common.provider import GenerationResult
    from src.backend.ingest import extract, orchestrator

    handlers = _ocr_handlers(["", "", "", ""])
    calls: list[int] = []

    def render(*args: Any, pages: list[int], **kwargs: Any) -> list[Any]:
        return [extract.RasterizedPage(index, b"png") for index in pages]

    def generate(*args: Any, **kwargs: Any) -> Any:
        images = kwargs.get("images") or []
        calls.append(len(images))
        if len(images) > 1:
            raise provider.ModelOutputTruncatedError("hit its output limit")
        return GenerationResult(f"page {len(calls)} clearly recognized", "m", 1, 1)

    monkeypatch.setattr(extract, "rasterize_pages_with_ids", render)
    monkeypatch.setattr(orchestrator.provider, "generate", generate)
    with generation.operation():
        handlers.ocr()
    assert calls == [4, 1, 1, 1, 1]
    assert handlers.extracted is not None
    assert all(page.strip() for page in handlers.extracted.page_texts)


def test_a_transient_ocr_failure_hides_the_raw_provider_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.backend.common import generation
    from src.backend.ingest import extract, orchestrator

    handlers = _ocr_handlers([""])

    def render(*args: Any, pages: list[int], **kwargs: Any) -> list[Any]:
        return [extract.RasterizedPage(index, b"png") for index in pages]

    def generate(*args: Any, **kwargs: Any) -> Any:
        raise provider.ProviderUnavailableError(
            "peer closed connection", transient=True
        )

    monkeypatch.setattr(extract, "rasterize_pages_with_ids", render)
    monkeypatch.setattr(orchestrator.provider, "generate", generate)
    with generation.operation(), pytest.raises(StageWarning) as raised:
        handlers.ocr()
    message = str(raised.value)
    assert "peer closed connection" not in message
    assert "could not be read after" in message


def test_a_failed_page_is_not_also_listed_as_unresolved() -> None:
    handlers = _ocr_handlers([""])
    with pytest.raises(StageWarning) as raised:
        handlers._warn_if_incomplete(
            [0], ["pages 1 could not be read after 2 attempt(s)"], cap_exceeded=False
        )
    assert "unresolved pages" not in str(raised.value)


# --- R5-NEW-q: a failed upload removes its temp file


def test_stream_to_temp_removes_its_file_on_failure() -> None:
    before = set(Path(tempfile.gettempdir()).glob("upload-*.tmp"))

    class _Stream:
        def __init__(self) -> None:
            self.chunks = [b"x" * 10, b""]

        def read(self, _size: int) -> bytes:
            return self.chunks.pop(0) if self.chunks else b""

    with pytest.raises(storage.RawUploadLimitExceededError):
        storage.stream_to_temp(_Stream(), max_bytes=5)
    after = set(Path(tempfile.gettempdir()).glob("upload-*.tmp"))
    assert after <= before


# --- R5-NEW-s: a transient quiz-image OCR failure is retried once


def test_exam_style_retries_a_transient_ocr_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.backend.artifacts import exam_style
    from src.backend.common.provider import GenerationResult

    calls: list[str] = []

    def generate(task: str, prompt: str, **kwargs: Any) -> GenerationResult:
        calls.append(task)
        if len(calls) == 1:
            raise provider.ProviderUnavailableError(
                "peer closed connection", transient=True
            )
        return GenerationResult("readable quiz text here", "m", 1, 1)

    monkeypatch.setattr(exam_style.provider, "generate", generate)
    assert exam_style._transcribe(uuid4(), [b"png"]) == ["readable quiz text here"]
    assert calls == ["ocr", "ocr"]


def test_exam_style_does_not_retry_a_non_transient_ocr_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.backend.artifacts import exam_style

    calls: list[str] = []

    def generate(task: str, prompt: str, **kwargs: Any) -> Any:
        calls.append(task)
        raise provider.ProviderUnavailableError("hard failure", transient=False)

    monkeypatch.setattr(exam_style.provider, "generate", generate)
    with pytest.raises(provider.ProviderUnavailableError):
        exam_style._transcribe(uuid4(), [b"png"])
    assert calls == ["ocr"]
