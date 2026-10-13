"""Explicit-address routing (plan-score-retrieval.md Phase 1): labels, weeks,
source-week inference, the funnel filters, follow-up scoping and rerank pins.
"""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from src.backend.common import provider
from src.backend.common.db import connection
from src.backend.retrieval import funnel, route
from src.backend.retrieval.config import (
    RoutePolicy,
    load_rerank_policy,
    load_retrieval_policy,
)
from src.backend.retrieval.funnel import LABEL, Candidate
from src.backend.retrieval.rerank import select_for_generation
from src.backend.tutor.chat import ChatContext, retrieval_query
from tests.factories import insert_chunk, insert_source, make_course

POLICY = RoutePolicy(
    enabled=True,
    label_kinds=("table", "figure", "fig", "equation", "eq", "chapter"),
    label_limit=5,
)


@pytest.mark.parametrize(
    ("text", "labels", "weeks"),
    [
        ("Reproduce Table 2.2", ("table 2.2",), ()),
        ("Show me Fig. 3 please", ("figure 3",), ()),
        ("What does Table 2.2a report?", ("table 2.2a",), ()),
        ("Make a quiz on Week 3", (), (3,)),
        ("weeks 1-5 study guide", (), (1, 2, 3, 4, 5)),
        ("weeks 1 to 5", (), (1, 2, 3, 4, 5)),
        ("weeks 1\u20135", (), (1, 2, 3, 4, 5)),
        ("week 99 is out of range", (), ()),
        ("hello world", (), ()),
    ],
)
def test_parse_addresses(
    text: str, labels: tuple[str, ...], weeks: tuple[int, ...]
) -> None:
    addresses = route.parse_addresses(text, POLICY)
    assert addresses.labels == labels
    assert addresses.weeks == weeks
    assert addresses.empty() == (not labels and not weeks)


def test_label_phrase_keeps_single_characters() -> None:
    assert route.label_phrase("table 2.2") == '"table 2 2"'
    assert route.label_phrase("figure 3a") == '"figure 3a"'


def test_label_phrase_does_not_match_a_longer_number() -> None:
    course = make_course("Route Course")
    source = insert_source(course.course_id, filename="Week1 notes.pdf")
    exact = insert_chunk(
        source,
        "TABLE 2.2 Race of Major Hispanic Ancestries",
        chunk_index=0,
        label="page 14",
    )
    longer = insert_chunk(
        source, "Table 2.20 Other Ancestry Data", chunk_index=1, label="page 15"
    )
    with connection() as conn:
        found = funnel.label_seam(conn, course.course_id, "table 2.2", 10)
    assert exact in found
    assert longer not in found
    assert found[exact].layers == frozenset({LABEL})


def test_source_weeks_infers_from_filenames() -> None:
    course = make_course("Week Course")
    week1 = insert_source(course.course_id, filename="Week1.pdf")
    week10 = insert_source(course.course_id, filename="Week 10 notes")
    wk03 = insert_source(course.course_id, filename="wk_03 slides")
    weeks4 = insert_source(course.course_id, filename="Weeks 4 notes.pdf")
    none = insert_source(course.course_id, filename="syllabus.pdf")
    weekend = insert_source(course.course_id, filename="weekend notes.pdf")
    with connection() as conn:
        weeks = route.source_weeks(conn, course.course_id)
    assert weeks == {
        week1: 1,
        week10: 10,
        wk03: 3,
        weeks4: 4,
        none: None,
        weekend: None,
    }


def _week_course() -> tuple[object, UUID, UUID]:
    course = make_course("Week Filter Course")
    week1 = insert_source(course.course_id, filename="Week1 notes.pdf")
    week3 = insert_source(course.course_id, filename="Week3 notes.pdf")
    insert_chunk(
        week1,
        "quiz week one covers the assigned readings and the lecture material "
        "for the first week of the course",
        label="page 1",
    )
    insert_chunk(
        week3,
        "quiz week three covers the assigned readings and the lecture material "
        "for the third week of the course",
        label="page 1",
    )
    return course, week1, week3


def test_week_address_filters_to_that_source() -> None:
    course, _week1, week3 = _week_course()
    with connection() as conn:
        result = funnel.retrieve(
            conn, course.course_id, "Make a quiz on Week 3", load_retrieval_policy()
        )
    assert result.route["week_filter"] == "matched"
    assert result.candidates
    assert {candidate.source_id for candidate in result.candidates} == {week3}


def test_a_week_with_no_source_fails_open() -> None:
    course, week1, week3 = _week_course()
    with connection() as conn:
        result = funnel.retrieve(
            conn, course.course_id, "Make a quiz on Week 9", load_retrieval_policy()
        )
    assert result.route["week_filter"] == "no_match"
    found = {candidate.source_id for candidate in result.candidates}
    assert found & {week1, week3}


def test_a_label_is_pinned_ahead_of_generic_table_matches() -> None:
    course = make_course("Table Pin Course")
    source = insert_source(course.course_id, filename="Week1 notes.pdf")
    for index in range(10):
        insert_chunk(
            source,
            f"table of contents entry {index} lists the assigned readings "
            "and the lecture topics for this part of the course",
            chunk_index=index,
            label=f"page {index + 1}",
        )
    table = insert_chunk(
        source,
        "TABLE 2.2 Race of Major Hispanic Ancestries in the assigned readings "
        "for the first week of the course",
        chunk_index=10,
        label="page 20",
    )
    with connection() as conn:
        result = funnel.retrieve(
            conn, course.course_id, "Reproduce Table 2.2", load_retrieval_policy()
        )
    assert result.route["labels"] == ["table 2.2"]
    assert result.candidates[0].chunk_id == table
    assert LABEL in result.candidates[0].layers


# --- follow-up scoping (R5-NEW-p) -----------------------------------------


def test_a_follow_up_naming_an_address_drops_previous_questions() -> None:
    context = ChatContext(
        summary="",
        recent=(),
        previous_questions=("what does Resendez argue", "and the encomienda"),
    )
    addressed = retrieval_query("Reproduce Table 2.2", context)
    assert "Resendez" not in addressed
    assert "Table 2.2" in addressed
    unaddressed = retrieval_query("what about that", context)
    assert "and the encomienda" in unaddressed


# --- rerank pins ----------------------------------------------------------


def _candidate(text: str, index: int) -> Candidate:
    return Candidate(
        chunk_id=uuid4(),
        source_id=uuid4(),
        locator_id=uuid4(),
        chunk_index=index,
        text=text,
        layers=frozenset({"keyword"}),
        rank=1.0,
    )


def test_a_pinned_candidate_survives_the_reranker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin = replace(
        _candidate("TABLE 2.2 Race of Major Hispanic Ancestries", 0),
        layers=frozenset({LABEL}),
    )
    others = tuple(
        _candidate(text, index + 1)
        for index, text in enumerate(
            ("office hours", "the exam is worth forty percent")
        )
    )

    def scores(model: str, question: str, texts: list[str]) -> list[float]:
        return [10.0 for _ in texts]

    monkeypatch.setattr(provider, "rerank_scores", scores)
    policy = load_rerank_policy().model_copy(update={"generation_k": 1})
    chosen = select_for_generation("reproduce table 2.2", (pin, *others), policy)
    assert chosen[0].chunk_id == pin.chunk_id
