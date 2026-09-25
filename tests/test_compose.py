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
        ("Turn this into flashcards", Intent.QUIZ),
        ("Make slides about eigenvalues", Intent.SLIDES),
        ("Give me a table of the key dates", Intent.SHEET),
        ("Write a Python function for the dot product", Intent.CODE),
        ("Make me a study guide for the midterm", Intent.DOCUMENT),
        ("Make me a cheat sheet", Intent.DOCUMENT),
        # Course vocabulary must not trigger a shape.
        ("What notation does the textbook use?", Intent.ANSWER),
        ("Explain the codomain", Intent.ANSWER),
        # Graded work never gets a workspace item, whatever shape it names.
        ("Give me the filled-in answer sheet to submit", Intent.GRADED),
        ("Take this quiz for me", Intent.GRADED),
        ("Write my essay as notes so I can submit it", Intent.GRADED),
    ],
)
def test_classify_intent(question: str, intent: Intent) -> None:
    assert classify_intent(question) == intent


def test_schema_bounds_citations_to_the_provided_material() -> None:
    schema = workspace_schema(Intent.DOCUMENT, material_count=3)
    sources = schema["properties"]["item"]["properties"]["sources"]
    assert sources["items"] == {"type": "integer", "minimum": 1, "maximum": 3}
    assert sources["minItems"] == 1
    # Strict-mode shape: every object lists all its properties as required.
    item = schema["properties"]["item"]
    assert set(item["required"]) == set(item["properties"])
    assert item["additionalProperties"] is False


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
                            "prompt": "Q?",
                            "options": ["A", "B"],
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


def test_unusable_structured_output_falls_back_to_prose_safely() -> None:
    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        return "I can make a quiz if you ask."

    composed = compose_answer("Quiz me", _candidates(), generate)
    assert not composed.structured
    extracted = extract_workspace_items(composed.text, material_count=2)
    assert extracted.items == ()


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
