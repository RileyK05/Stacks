"""Workspace-item citation gate (decision 009 hard gate).

A tutor answer's ```workspace blocks are lifted out of the chat body;
only blocks whose every element cites provided material survive, and
every withheld block is named with a reason.
"""

from __future__ import annotations

import json

from src.backend.tutor.workspace import (
    WorkspaceDocument,
    WorkspaceQuiz,
    extract_workspace_items,
)


def _block(payload: dict) -> str:
    return f"```workspace\n{json.dumps(payload)}\n```"


def _quiz(**question_overrides) -> dict:
    question = {
        "prompt": "What does a linear map preserve?",
        "options": ["Addition and scaling", "Only zero"],
        "answer": 0,
        "explanation": "It preserves both operations [1].",
        "sources": [1],
    }
    question.update(question_overrides)
    return {"type": "quiz", "title": "Linearity", "questions": [question]}


def test_valid_quiz_is_lifted_out_of_the_body() -> None:
    text = f"Here is a quick check [1].\n\n{_block(_quiz())}\n\nGood luck!"
    extracted = extract_workspace_items(text, material_count=1)
    assert extracted.withheld == ()
    assert len(extracted.items) == 1
    quiz = extracted.items[0]
    assert isinstance(quiz, WorkspaceQuiz)
    assert quiz.questions[0].answer == 0
    assert "```" not in extracted.body
    assert extracted.body == "Here is a quick check [1].\n\nGood luck!"


def test_valid_document_is_lifted() -> None:
    doc = {
        "type": "document",
        "title": "Notes",
        "content": "# Linearity\nPreserves addition [1] and scaling [2].",
        "sources": [1, 2],
    }
    extracted = extract_workspace_items(_block(doc), material_count=2)
    assert extracted.withheld == ()
    assert isinstance(extracted.items[0], WorkspaceDocument)
    assert extracted.body == ""


def test_uncited_question_is_withheld_not_rendered() -> None:
    extracted = extract_workspace_items(
        _block(_quiz(sources=[])), material_count=1
    )
    assert extracted.items == ()
    assert len(extracted.withheld) == 1
    assert "sources" in extracted.withheld[0]


def test_out_of_range_source_is_withheld_with_reason() -> None:
    extracted = extract_workspace_items(
        _block(_quiz(sources=[3])), material_count=2
    )
    assert extracted.items == ()
    assert "question 1 cites [3]" in extracted.withheld[0]


def test_out_of_range_inline_citation_in_explanation_is_withheld() -> None:
    extracted = extract_workspace_items(
        _block(_quiz(explanation="See [4].")), material_count=1
    )
    assert extracted.items == ()
    assert "[4]" in extracted.withheld[0]


def test_document_inline_citation_out_of_range_is_withheld() -> None:
    doc = {"type": "document", "content": "Claim [9].", "sources": [1]}
    extracted = extract_workspace_items(_block(doc), material_count=1)
    assert extracted.items == ()
    assert "document cites [9]" in extracted.withheld[0]


def test_answer_index_must_be_an_option() -> None:
    extracted = extract_workspace_items(
        _block(_quiz(answer=5)), material_count=1
    )
    assert extracted.items == ()
    assert "malformed" in extracted.withheld[0]


def test_withheld_block_never_leaks_its_answer_key_into_chat() -> None:
    """A rejected quiz must not fall back into the chat as raw JSON:
    that would show the answer key while claiming it was withheld."""
    text = f"Try these.\n{_block(_quiz(sources=[7]))}"
    extracted = extract_workspace_items(text, material_count=1)
    assert extracted.body == "Try these."
    assert "Addition and scaling" not in extracted.body


def test_invalid_json_and_unknown_type_are_withheld() -> None:
    bad_json = "```workspace\n{not json}\n```"
    unknown = _block({"type": "flashcards", "cards": []})
    extracted = extract_workspace_items(
        f"{bad_json}\n{unknown}", material_count=1
    )
    assert extracted.items == ()
    assert len(extracted.withheld) == 2
    assert "not valid JSON" in extracted.withheld[0]
    assert "malformed" in extracted.withheld[1]


def test_answer_without_blocks_is_untouched() -> None:
    text = "Linearity preserves structure [1]."
    extracted = extract_workspace_items(text, material_count=1)
    assert extracted.body == text
    assert extracted.items == ()
    assert extracted.withheld == ()


def test_ordinary_code_fences_are_not_workspace_blocks() -> None:
    text = "Example:\n```python\nprint(1)\n```"
    extracted = extract_workspace_items(text, material_count=1)
    assert extracted.body == text
    assert extracted.items == ()
