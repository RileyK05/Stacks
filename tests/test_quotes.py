"""Quote-anchored answers (tutor/quotes.py + compose's quotes mode)."""

import json
from typing import Any
from uuid import uuid4

import pytest
from src.backend.retrieval.funnel import Candidate
from src.backend.tutor import quotes
from src.backend.tutor.compose import AnswerMode, Intent, compose_answer

SYLLABUS = (
    "Grading: The first exam is worth 25% of your final grade, and the\n"
    "second exam is worth 30%. Attendance counts for 10%; you may miss\n"
    "three lectures without penalty. Office hours are Tuesdays 2–4 pm in\n"
    "Smith Hall 204, or by appointment."
)
READING = "Pan-\nethnic identity among Latinos is shaped by the Spanish language."


@pytest.mark.parametrize(
    "quote",
    [
        "you may miss three lectures without penalty",
        "You may MISS three lectures   without penalty.",
        "The first exam is worth 25% of your final grade",
        "Office hours are Tuesdays 2-4 pm in Smith Hall 204",  # dash differs
        "the first exam is worth 25% ... you may miss three lectures",  # elision
        "Attendance counts for 10%[...] three lectures without penalty",
    ],
)
def test_real_quotes_match(quote: str) -> None:
    assert quotes.quote_matches(quote, SYLLABUS)


def test_line_broken_hyphenation_matches() -> None:
    assert quotes.quote_matches("pan-ethnic identity among Latinos", READING)


@pytest.mark.parametrize(
    "quote",
    [
        "you may miss five lectures without penalty",  # changed a fact word
        "the second exam is worth 30% of the grade",  # words added
        "you may miss three lectures ... the first exam",  # elision out of order
        "The final exam is worth 50% of your grade",
        "office hours",  # too short to anchor anything
        "Students should park in Lot C near the building",
    ],
)
def test_invented_or_altered_quotes_do_not_match(quote: str) -> None:
    assert not quotes.quote_matches(quote, SYLLABUS)


def test_verify_checks_the_named_chunk_and_range() -> None:
    chunks = (SYLLABUS, READING)
    good = quotes.Quote(1, "you may miss three lectures without penalty")
    wrong_chunk = quotes.Quote(2, "you may miss three lectures without penalty")
    out_of_range = quotes.Quote(3, "Pan-ethnic identity among Latinos")
    verified, rejected = quotes.verify([good, wrong_chunk, out_of_range], chunks)
    assert verified == [good]
    assert rejected == [wrong_chunk, out_of_range]


def test_anchor_citations_only_fills_missing_markers() -> None:
    verified = [quotes.Quote(2, "x y z"), quotes.Quote(1, "a b c")]
    assert (
        quotes.anchor_citations("Three lectures.", verified) == "Three lectures. [1][2]"
    )
    assert quotes.anchor_citations("Three [1].", verified) == "Three [1]."
    assert quotes.anchor_citations("No evidence.", []) == "No evidence."


def _candidates(*texts: str) -> tuple[Candidate, ...]:
    return tuple(
        Candidate(
            chunk_id=uuid4(),
            source_id=uuid4(),
            locator_id=uuid4(),
            chunk_index=index,
            text=text,
            layers=frozenset({"keyword"}),
            rank=1.0,
        )
        for index, text in enumerate(texts)
    )


def test_quotes_mode_generates_evidence_first_and_drops_fakes() -> None:
    calls: list[dict[str, Any]] = []
    reply = {
        "quotes": [
            {"source": 1, "quote": "you may miss three lectures without penalty"},
            {"source": 1, "quote": "you may miss ten lectures and still pass"},
        ],
        "answer": "You can miss three lectures without penalty.",
    }

    def generate(task: str, prompt: str, *, response_schema: Any = None) -> str:
        calls.append({"task": task, "prompt": prompt, "schema": response_schema})
        return json.dumps(reply)

    composed = compose_answer(
        "How many lectures can I miss?",
        _candidates(SYLLABUS, READING),
        generate,
        answer_mode=AnswerMode.QUOTES,
    )
    schema = calls[0]["schema"]
    assert list(schema["properties"]) == ["quotes", "answer"]
    assert (
        schema["properties"]["quotes"]["items"]["properties"]["source"]["maximum"] == 2
    )
    assert "word-for-word" in calls[0]["prompt"]
    assert composed.intent is Intent.ANSWER and composed.structured
    assert composed.text == "You can miss three lectures without penalty. [1]"
    assert len(composed.quotes) == 1 and len(composed.rejected_quotes) == 1


def test_quotes_mode_falls_back_to_plain_on_unusable_reply() -> None:
    replies = iter(["not json at all", "Plain answer [1]."])
    prompts: list[str] = []

    def generate(task: str, prompt: str, *, response_schema: Any = None) -> str:
        prompts.append(prompt)
        return next(replies)

    composed = compose_answer(
        "How many lectures can I miss?",
        _candidates(SYLLABUS),
        generate,
        answer_mode=AnswerMode.QUOTES,
    )
    assert composed.text == "Plain answer [1]." and not composed.structured
    assert len(prompts) == 2 and "word-for-word" not in prompts[1]


def test_quotes_mode_leaves_graded_work_and_workspace_alone() -> None:
    seen: list[Any] = []

    def generate(task: str, prompt: str, *, response_schema: Any = None) -> str:
        seen.append(response_schema)
        return "I can't write work you will submit."

    compose_answer(
        "Write my essay so I can submit it",
        _candidates(SYLLABUS),
        generate,
        answer_mode=AnswerMode.QUOTES,
    )
    assert seen == [None], "the steer prompt is unconstrained prose"
