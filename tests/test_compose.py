"""Task framing (tutor/compose.py): intent routing, the constrained
workspace path, and its fallbacks."""

import json
from uuid import uuid4

import pytest
from src.backend.retrieval.funnel import Candidate
from src.backend.tutor.compose import (
    Intent,
    classify_intent,
    compose_answer,
    numbered_passages,
    parse_json_object,
    workspace_schema,
)
from src.backend.tutor.workspace import extract_workspace_items


def _candidates(count: int = 2) -> tuple[Candidate, ...]:
    return tuple(
        Candidate(
            chunk_id=uuid4(),
            source_id=uuid4(),
            locator_id=uuid4(),
            chunk_index=index,
            text=f"material {index}",
            layers=frozenset({"keyword"}),
            rank=1.0,
        )
        for index in range(count)
    )


@pytest.mark.parametrize(
    ("question", "intent"),
    [
        ("What does linearity mean?", Intent.ANSWER),
        ("Quiz me on chapter 2", Intent.QUIZ),
        ("Make a practice test", Intent.QUIZ),
        ("Prepare a full practice test suite on chapter 2", Intent.QUIZ),
        ("Turn this into flashcards", Intent.QUIZ),
        ("Make slides about eigenvalues", Intent.SLIDES),
        ("Give me a table of the key dates", Intent.SHEET),
        ("Write a Python function for the dot product", Intent.CODE),
        ("Make me a study guide for the midterm", Intent.DOCUMENT),
        ("Make me a cheat sheet", Intent.DOCUMENT),
        ("Make me a study sheet", Intent.DOCUMENT),
        ("Write a 300-word essay about the groups in your table", Intent.DOCUMENT),
        ("Could you draft a sample paper about the lecture slides?", Intent.DOCUMENT),
        ("Create an editable document comparing spreadsheet methods", Intent.DOCUMENT),
        ("Create a table of essay arguments", Intent.SHEET),
        ("Make slides from these study notes", Intent.SLIDES),
        # Course vocabulary must not trigger a shape.
        ("What notation does the textbook use?", Intent.ANSWER),
        ("Explain the codomain", Intent.ANSWER),
        ("Explain the code in my notes", Intent.ANSWER),
        ("What do the slides say about linearity?", Intent.ANSWER),
        ("Can you explain the table on page 2?", Intent.ANSWER),
        ("When is the quiz due?", Intent.ANSWER),
        ("Summarize my lecture notes", Intent.ANSWER),
        ("Could you please create a table of dates?", Intent.SHEET),
        # Graded work never gets a workspace item, whatever shape it names.
        ("Give me the filled-in answer sheet to submit", Intent.GRADED),
        ("Take this quiz for me", Intent.GRADED),
        ("Write my essay as notes so I can submit it", Intent.GRADED),
    ],
)
def test_classify_intent(question: str, intent: Intent) -> None:
    assert classify_intent(question) == intent


def test_requested_ten_question_quiz_is_not_capped_at_six() -> None:
    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        assert (
            response_schema["properties"]["item"]["properties"]["questions"]["maxItems"]
            == 10
        )
        return json.dumps(
            {
                "reply": "Practice test",
                "item": {
                    "type": "quiz",
                    "title": "Organizing",
                    "questions": [
                        {
                            "prompt": f"Which group organized event {index}?",
                            "options": [f"Group {index}", "Another group"],
                            "answer": 0,
                            "explanation": f"Group {index} organized the event.",
                            "sources": [1],
                        }
                        for index in range(10)
                    ],
                },
            }
        )

    result = compose_answer("Create a ten-question quiz", _candidates(), generate)
    assert result.structured
    assert (
        len(extract_workspace_items(result.text, material_count=2).items[0].questions)
        == 10
    )


def test_out_of_range_quiz_count_returns_explanation_without_generation() -> None:
    calls = []

    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        calls.append(prompt)
        raise AssertionError("an unsupported count must not call the model")

    result = compose_answer("Make a 50-question quiz", _candidates(), generate)
    assert "1–20" in result.text
    assert calls == []


def test_quiz_repair_propagates_non_schema_provider_errors() -> None:
    calls = 0

    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            return '{"item":{"type":"quiz","questions":[]}}'
        raise RuntimeError("provider budget exceeded")

    with pytest.raises(RuntimeError, match="provider budget exceeded"):
        compose_answer("Make a quiz", _candidates(), generate)


def test_short_quiz_cannot_be_published_as_requested_full_suite() -> None:
    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        return json.dumps(
            {
                "reply": "Here is your full test",
                "item": {
                    "type": "quiz",
                    "title": "Organizing",
                    "questions": [
                        {
                            "prompt": "Which group was organized?",
                            "options": ["Farm workers", "Railroad workers"],
                            "answer": 0,
                            "explanation": "Farm workers were organized.",
                            "sources": [1],
                        }
                    ],
                },
            }
        )

    result = compose_answer("Create a quiz with 10 questions", _candidates(), generate)
    assert not result.structured
    assert "only 1 of the 10" in result.text
    assert "workspace" not in result.text


@pytest.mark.parametrize("kind,key", [("document", "content"), ("slides", "deck")])
def test_title_only_study_material_is_withheld(kind: str, key: str) -> None:
    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        return json.dumps(
            {
                "reply": "Done",
                "item": {
                    "type": kind,
                    "title": "Organizing",
                    key: "# Organizing",
                    "sources": [1],
                },
            }
        )

    result = compose_answer(
        "Make notes" if kind == "document" else "Make slides", _candidates(), generate
    )
    assert not result.structured


def test_passage_header_names_the_source_type_and_container() -> None:
    candidate = Candidate(
        chunk_id=uuid4(),
        source_id=uuid4(),
        locator_id=uuid4(),
        chunk_index=0,
        text="Sánchez wrote this.",
        layers=frozenset({"keyword"}),
        rank=1.0,
        source_filename="Week2.pdf",
        source_type="lecture_slides",
        container_title="Sep 21 lecture",
    )
    header = numbered_passages((candidate,)).splitlines()[0]
    assert f"chunk {candidate.chunk_id}" in header
    assert "Week2.pdf" in header
    assert "lecture slides" in header
    assert "Sep 21 lecture" in header


def test_schema_bounds_citations_to_the_provided_material() -> None:
    schema = workspace_schema(Intent.DOCUMENT, material_count=3)
    sources = schema["properties"]["item"]["properties"]["sources"]
    assert sources["items"] == {"type": "integer", "minimum": 1, "maximum": 3}
    assert sources["minItems"] == 1
    # Strict-mode shape: every object lists all its properties as required.
    item = schema["properties"]["item"]
    assert set(item["required"]) == set(item["properties"])
    assert item["additionalProperties"] is False


def test_document_boundaries_survive_flattened_json_strings() -> None:
    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        assert "sections" in response_schema["properties"]["item"]["properties"]
        return json.dumps(
            {
                "reply": "Study notes",
                "item": {
                    "type": "document",
                    "title": "Linearity",
                    "sections": [
                        {
                            "heading": "Addition",
                            "paragraphs": [
                                "Preserves addition [1].",
                                "Compare both sides [1].",
                            ],
                        },
                        {
                            "heading": "Scaling",
                            "paragraphs": ["Preserves scaling [2]."],
                        },
                    ],
                    "sources": [1, 2],
                },
            },
            separators=(",", ":"),
        )

    composed = compose_answer("Create a study guide", _candidates(), generate)
    assert composed.structured
    item = extract_workspace_items(composed.text, 2).items[0]
    assert item.content == (
        "## Addition\n\nPreserves addition [1].\n\nCompare both sides [1]."
        "\n\n## Scaling\n\nPreserves scaling [2]."
    )
    assert "sections" not in item.model_dump()


def test_slide_boundaries_and_count_survive_flattened_json_strings() -> None:
    from src.backend.artifacts.content import from_workspace_item

    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        slides = response_schema["properties"]["item"]["properties"]["slides"]
        assert slides["minItems"] == slides["maxItems"] == 8
        return json.dumps(
            {
                "reply": "A deck",
                "item": {
                    "type": "slides",
                    "title": "Linearity",
                    "slides": [
                        {
                            "title": f"Example {index}",
                            "paragraphs": [
                                f"- Check addition in example {index} [2].",
                                "- Then check scaling [1].",
                            ],
                        }
                        for index in range(8)
                    ],
                    "sources": [1, 2],
                },
            },
            separators=(",", ":"),
        )

    composed = compose_answer("Create an eight-slide deck", _candidates(), generate)
    assert composed.structured
    workspace = extract_workspace_items(composed.text, 2).items[0]
    kind, _, content, sources = from_workspace_item(workspace)
    assert kind == "slides" and sources == [1, 2]
    assert len(content["slides"]) == 8
    assert content["slides"][7]["title"] == "Example 7"
    assert (
        content["slides"][7]["body"]
        == "- Check addition in example 7 [2].\n\n- Then check scaling [1]."
    )


@pytest.mark.parametrize(
    "item",
    [
        {
            "type": "document",
            "title": "Notes",
            "sections": [{"heading": "Notes", "paragraphs": ["# Notes"]}],
            "sources": [1],
        },
        {
            "type": "document",
            "title": "Notes",
            "sections": [{"heading": "Facts", "paragraphs": ["A fact [99]."]}],
            "sources": [1],
        },
        {
            "type": "slides",
            "title": "Deck",
            "slides": [{"title": "Topic", "paragraphs": ["Topic"]}],
            "sources": [1],
        },
        {
            "type": "slides",
            "title": "Deck",
            "slides": [
                {"title": "Topic", "paragraphs": ["First [1].\n---\nSecond [1]."]}
            ],
            "sources": [1],
        },
    ],
)
def test_invalid_structured_units_are_not_published(item: dict) -> None:
    calls = []

    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        calls.append(prompt)
        return json.dumps({"reply": "Done", "item": item})

    question = "Make slides" if item["type"] == "slides" else "Make notes"
    composed = compose_answer(question, _candidates(), generate)
    assert not composed.structured
    assert "Done" not in composed.text
    assert len(calls) == 2


def test_incomplete_deck_is_repaired_instead_of_claiming_requested_count() -> None:
    calls = []

    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        calls.append(prompt)
        return json.dumps(
            {
                "reply": "Done",
                "item": {
                    "type": "slides",
                    "title": "Deck",
                    "sources": [1],
                    "slides": [
                        {
                            "title": f"Example {index}",
                            "paragraphs": [f"Example {index} preserves addition [1]."],
                        }
                        for index in range(2 if len(calls) == 1 else 3)
                    ],
                },
            }
        )

    composed = compose_answer("Create 3 slides", _candidates(), generate)
    assert composed.structured
    assert len(calls) == 2
    assert extract_workspace_items(composed.text, 2).items[0].deck.count("\n---\n") == 2


def test_persistent_incomplete_deck_is_not_presented_as_complete() -> None:
    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        return json.dumps(
            {
                "reply": "Here are all eight slides",
                "item": {
                    "type": "slides",
                    "title": "Deck",
                    "sources": [1],
                    "slides": [
                        {"title": "Addition", "paragraphs": ["Preserves addition [1]."]}
                    ],
                },
            }
        )

    composed = compose_answer("Create 8 slides", _candidates(), generate)
    assert not composed.structured
    assert "all eight" not in composed.text


def test_duplicate_slides_cannot_pad_the_requested_count() -> None:
    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        return json.dumps(
            {
                "reply": "Done",
                "item": {
                    "type": "slides",
                    "title": "Deck",
                    "sources": [1],
                    "slides": [
                        {"title": "Addition", "paragraphs": ["Preserves addition [1]."]}
                    ]
                    * 3,
                },
            }
        )

    composed = compose_answer("Create 3 slides", _candidates(), generate)
    assert not composed.structured
    assert "Done" not in composed.text


def test_valid_material_does_not_hide_invalid_citations_in_its_intro() -> None:
    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        return json.dumps(
            {
                "reply": "Done [99]",
                "item": {
                    "type": "document",
                    "title": "Notes",
                    "sources": [1],
                    "sections": [
                        {
                            "heading": "Addition",
                            "paragraphs": ["Preserves addition [1]."],
                        }
                    ],
                },
            }
        )

    composed = compose_answer("Create notes", _candidates(), generate)
    assert not composed.structured
    assert "[99]" not in composed.text


def test_plain_question_uses_the_lean_prompt_without_a_schema() -> None:
    calls: list[tuple[str, dict | None]] = []

    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        calls.append((task, response_schema))
        return "Linearity preserves sums [1]."

    composed = compose_answer("What is linearity?", _candidates(), generate)
    assert calls == [("tutor_answer", None)]
    assert composed.text == "Linearity preserves sums [1]."
    assert composed.intent is Intent.ANSWER


def test_graded_work_gets_the_steer_prompt() -> None:
    prompts: list[str] = []

    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        assert task == "tutor_answer" and response_schema is None
        prompts.append(prompt)
        return "I can't write work you'll submit, but let's walk through it [1]."

    composed = compose_answer(
        "Write my exam essay so I can submit it", _candidates(), generate
    )
    assert composed.intent is Intent.GRADED
    assert "graded work" in prompts[0]
    assert composed.text.startswith("I can't write")


def test_quiz_schema_rejects_letter_only_options() -> None:
    schema = workspace_schema(Intent.QUIZ, material_count=2)
    question = schema["properties"]["item"]["properties"]["questions"]["items"]
    assert question["properties"]["options"]["items"]["minLength"] == 2


def test_workspace_request_becomes_a_gated_block() -> None:
    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        assert task == "artifact_generation" and response_schema is not None
        assert "multiple-choice quiz" in prompt
        return json.dumps(
            {
                "reply": "A quick check [1].",
                "item": {
                    "type": "quiz",
                    "title": "Check",
                    "questions": [
                        {
                            "prompt": "Which property is being checked?",
                            "options": [
                                "The distributive property",
                                "The identity property",
                            ],
                            "answer": 1,
                            "explanation": "Because [2].",
                            "sources": [2],
                        }
                    ],
                },
            }
        )

    composed = compose_answer("Quiz me", _candidates(), generate)
    assert composed.structured
    extracted = extract_workspace_items(composed.text, material_count=2)
    assert extracted.body == "A quick check [1]."
    assert [item.type for item in extracted.items] == ["quiz"]
    assert extracted.withheld == ()


def test_unusable_structured_quiz_fails_closed() -> None:
    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        return "I can make a quiz if you ask."

    composed = compose_answer("Quiz me", _candidates(), generate)
    assert not composed.structured
    assert "couldn't create a trustworthy quiz" in composed.text
    extracted = extract_workspace_items(composed.text, material_count=2)
    assert extracted.items == ()


def test_placeholder_quiz_is_retried_and_never_returned_as_workspace() -> None:
    calls = 0

    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            item = {
                "type": "quiz",
                "title": "Quiz",
                "questions": [
                    {
                        "prompt": "Question about the topic?",
                        "options": ["option1", "option2", "option3"],
                        "answer": 0,
                        "explanation": "",
                        "sources": [1],
                    }
                ],
            }
        else:
            assert "previous quiz was unusable" in prompt
            item = {
                "type": "quiz",
                "title": "César Chávez",
                "questions": [
                    {
                        "prompt": "What did Chávez organize?",
                        "options": ["Farm workers", "Railroad workers"],
                        "answer": 0,
                        "explanation": "The material describes his organizing work.",
                        "sources": [1],
                    }
                ],
            }
        return json.dumps({"reply": "Try this quiz.", "item": item})

    composed = compose_answer("Create a quiz on César Chávez", _candidates(), generate)
    assert calls == 3
    assert composed.structured
    assert "option1" not in composed.text
    assert extract_workspace_items(composed.text, material_count=2).items


def test_persistently_placeholder_quiz_fails_closed() -> None:
    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        return json.dumps(
            {
                "reply": "Try this.",
                "item": {
                    "type": "quiz",
                    "title": "Quiz",
                    "questions": [
                        {
                            "prompt": "Question about the topic?",
                            "options": ["option1", "option2"],
                            "answer": 0,
                            "explanation": "",
                            "sources": [1],
                        }
                    ],
                },
            }
        )

    composed = compose_answer("Create a quiz", _candidates(), generate)
    assert not composed.structured
    assert "couldn't create a trustworthy quiz" in composed.text
    assert "option1" not in composed.text


def test_quiz_keeps_verified_questions_from_separate_attempts() -> None:
    calls = 0

    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        nonlocal calls
        calls += 1
        question = (
            {
                "prompt": "Which group was organized?",
                "options": ["Farm workers", "Railroad workers"],
                "answer": 0,
                "explanation": "Farm workers were organized.",
                "sources": [1],
            }
            if calls == 1
            else {
                "prompt": "Which method drew support?",
                "options": ["A boycott", "A court appeal"],
                "answer": 0,
                "explanation": "A boycott drew support.",
                "sources": [2],
            }
        )
        questions = [question]
        if calls == 1:
            questions.append(
                {
                    "prompt": "Question about the topic?",
                    "options": ["option1", "option2"],
                    "answer": 0,
                    "explanation": "",
                    "sources": [1],
                }
            )
        else:
            questions.append(
                {
                    "prompt": "Who benefited from organizing?",
                    "options": ["Farm workers.", "Railroad workers."],
                    "answer": 0,
                    "explanation": "Farm workers benefited.",
                    "sources": [1],
                }
            )
        return json.dumps(
            {
                "reply": "Try this quiz.",
                "item": {"type": "quiz", "title": "Quiz", "questions": questions},
            }
        )

    composed = compose_answer("Quiz me", _candidates(), generate)
    extracted = extract_workspace_items(composed.text, material_count=2)
    assert calls == 2
    assert composed.structured
    assert len(extracted.items[0].questions) == 2


def test_quiz_answer_must_match_the_option_named_in_its_explanation() -> None:
    calls = 0

    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        nonlocal calls
        calls += 1
        return json.dumps(
            {
                "reply": "Try this quiz.",
                "item": {
                    "type": "quiz",
                    "title": "Farm workers",
                    "questions": [
                        {
                            "prompt": "Who led the Delano grape strike?",
                            "options": ["Larry Itliong", "César Chávez"],
                            "answer": 1,
                            "explanation": "Larry Itliong led the strike.",
                            "sources": [1],
                        }
                    ],
                },
            }
        )

    composed = compose_answer("Quiz me on César Chávez", _candidates(), generate)
    assert calls == 3
    assert not composed.structured
    assert "couldn't create a trustworthy quiz" in composed.text


def test_quiz_date_must_support_the_event_the_question_asks_about() -> None:
    source = Candidate(
        chunk_id=uuid4(),
        source_id=uuid4(),
        locator_id=uuid4(),
        chunk_index=0,
        text=(
            "César Chávez co-founded the National Farm Workers Association in "
            "1962. It later became part of the United Farm Workers."
        ),
        layers=frozenset({"keyword"}),
        rank=1.0,
    )

    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        return json.dumps(
            {
                "reply": "Try this quiz.",
                "item": {
                    "type": "quiz",
                    "title": "Farm workers",
                    "questions": [
                        {
                            "prompt": (
                                "When did the association become part of the "
                                "United Farm Workers?"
                            ),
                            "options": ["1962", "1965"],
                            "answer": 0,
                            "explanation": (
                                "It was co-founded in 1962, then joined later."
                            ),
                            "sources": [1],
                        }
                    ],
                },
            }
        )

    composed = compose_answer("Quiz me on César Chávez", (source,), generate)
    assert not composed.structured
    assert "couldn't create a trustworthy quiz" in composed.text


def test_rejected_schema_retries_without_it() -> None:
    class RejectedError(Exception):
        pass

    calls: list[dict | None] = []

    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        calls.append(response_schema)
        if response_schema is not None:
            raise RejectedError("400: response_format unsupported")
        return (
            'Sure:\n```json\n{"reply": "Notes [1].", "item": {"type": "document",'
            ' "title": "N", "content": "Point [1]", "sources": [1]}}\n```'
        )

    composed = compose_answer(
        "Make me a study guide",
        _candidates(),
        generate,
        on_schema_rejected=lambda err: isinstance(err, RejectedError),
    )
    assert calls[0] is not None and calls[1] is None
    assert composed.structured
    assert "```workspace" in composed.text


def test_parse_json_object_handles_fences_and_noise() -> None:
    assert parse_json_object('{"a": 1}') == {"a": 1}
    assert parse_json_object('text ```json\n{"a": 2}\n``` more') == {"a": 2}
    assert parse_json_object('prefix {"a": 3} suffix') == {"a": 3}
    assert parse_json_object("no json here") is None
    assert parse_json_object("[1, 2]") is None


@pytest.mark.parametrize(
    "raw",
    [
        '{"reply":"Done", "item":',
        '{"reply":"Done", "item":{"type":"document","content":"Hi","sources":[99]}}',
        '{"reply":"Done", "item":{"type":"sheet","columns":["A"],'
        '"rows":[["1"]],"sources":[1]}}',
    ],
)
def test_invalid_document_response_does_not_leak_json_or_claim_success(
    raw: str,
) -> None:
    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        return raw

    composed = compose_answer("Create a study guide", _candidates(), generate)
    assert not composed.structured
    assert "couldn't create a usable workspace item" in composed.text
    assert "Done" not in composed.text
    assert '"item"' not in composed.text


def test_workspace_document_can_contain_markdown_code_fences() -> None:
    content = "Example [1]:\n```python\nprint('hello')\n```"

    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        return json.dumps(
            {
                "reply": "Example",
                "item": {
                    "type": "document",
                    "content": content,
                    "sources": [1],
                },
            }
        )

    composed = compose_answer("Make notes", _candidates(), generate)
    extracted = extract_workspace_items(composed.text, 2)
    assert len(extracted.items) == 1
    assert extracted.items[0].content == content


def test_placeholder_slide_gets_one_repair_using_the_real_material() -> None:
    calls = []

    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        calls.append(prompt)
        deck = "deck" if len(calls) == 1 else "# Linearity\nPreserves addition [1]."
        return json.dumps(
            {
                "reply": "A slide",
                "item": {
                    "type": "slides",
                    "deck": deck,
                    "sources": [1],
                },
            }
        )

    composed = compose_answer("Make slides", _candidates(), generate)
    assert len(calls) == 2
    assert "Previous output to replace" in calls[1]
    assert "Course material:" in calls[1]
    assert composed.structured
    assert "Preserves addition" in composed.text


def test_persistent_placeholder_slide_is_not_presented_as_a_deck() -> None:
    calls = 0

    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        nonlocal calls
        calls += 1
        return json.dumps(
            {
                "reply": "Done",
                "item": {
                    "type": "slides",
                    "deck": "deck",
                    "sources": [1],
                },
            }
        )

    composed = compose_answer("Make slides", _candidates(), generate)
    assert calls == 2
    assert not composed.structured
    assert "couldn't create a usable" in composed.text


def test_generated_python_syntax_is_checked_before_showing_the_artifact() -> None:
    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        return json.dumps(
            {
                "reply": "Done",
                "item": {
                    "type": "code",
                    "language": "python",
                    "sources": [1],
                    "code": "def is_linear(transform, (*samples*,):\n    return True",
                },
            }
        )

    composed = compose_answer("Write a Python function", _candidates(), generate)
    assert not composed.structured
    assert "couldn't create a usable" in composed.text


def test_python_validation_does_not_execute_generated_code() -> None:
    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        return json.dumps(
            {
                "reply": "Example",
                "item": {
                    "type": "code",
                    "language": "python",
                    "sources": [1],
                    "code": "raise RuntimeError('must not execute')",
                },
            }
        )

    composed = compose_answer("Write Python code", _candidates(), generate)
    assert composed.structured


def test_truncated_workspace_block_is_withheld_instead_of_leaking_answer_key() -> None:
    extracted = extract_workspace_items(
        'Try this.\n```workspace\n{"type":"quiz","answer":0', 1
    )
    assert extracted.body == "Try this."
    assert extracted.withheld
    assert not extracted.items


@pytest.mark.parametrize("topic,key", [("Linearity", 1), ("recognition", 0)])
def test_live_quiz_failure_does_not_grade_an_inconsistent_key_or_capability_as_topic(
    topic, key
):
    def generate(task, prompt, *, response_schema=None):
        return json.dumps(
            {
                "reply": "Practice",
                "item": {
                    "type": "quiz",
                    "title": "Linearity",
                    "questions": [
                        {
                            "prompt": (
                                "Which statement correctly describes "
                                "the linearity of f(x)=2x?"
                            ),
                            "topic": topic,
                            "capability": "recognition",
                            "options": [
                                (
                                    "The function f(x)=2x is linear because "
                                    "it preserves "
                                    "addition and scalar multiplication."
                                ),
                                (
                                    "The function f(x)=2x is not linear because it "
                                    "does not preserve addition."
                                ),
                            ],
                            "answer": key,
                            "explanation": (
                                "The correct option states that f(x)=2x "
                                "is linear because it preserves addition "
                                "and scalar multiplication."
                            ),
                            "sources": [1],
                        }
                    ],
                },
            }
        )

    candidates = _candidates(1)
    composed = compose_answer("Make a practice test on Linearity", candidates, generate)
    assert not composed.structured
    assert "trustworthy quiz" in composed.text
