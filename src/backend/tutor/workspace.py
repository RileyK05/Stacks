"""Workspace items: interactive blocks a tutor answer can carry.

The tutor may embed fenced ```workspace JSON blocks in an answer (a
multiple-choice quiz, an editable study document). They are lifted out
of the chat text and rendered in the workspace pane beside the chat.

Decision 009's hard gate lives here, in code rather than in the prompt:
every element must cite the numbered material the answer was grounded
on. A block with a missing or out-of-range citation is withheld and the
reason is surfaced (golden rule 2), never rendered uncited.

Not to be confused with `user_artifacts` (decision 003): workspace
items are ephemeral per-answer views, not persisted learner artifacts.
Saving one as a personal artifact is the M5 path.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError, model_validator

WORKSPACE_BLOCK_RE = re.compile(r"```workspace[ \t]*\r?\n(.*?)```", re.DOTALL)
INLINE_CITATION_RE = re.compile(r"\[(\d+)\]")


class QuizQuestion(BaseModel):
    prompt: str = Field(min_length=1)
    options: list[str] = Field(min_length=2, max_length=8)
    answer: int
    explanation: str | None = None
    sources: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def _answer_is_an_option(self) -> QuizQuestion:
        if not 0 <= self.answer < len(self.options):
            raise ValueError(
                f"answer index {self.answer} is not one of the "
                f"{len(self.options)} options"
            )
        return self


class WorkspaceQuiz(BaseModel):
    type: Literal["quiz"]
    title: str | None = None
    questions: list[QuizQuestion] = Field(min_length=1, max_length=20)


class WorkspaceDocument(BaseModel):
    type: Literal["document"]
    title: str | None = None
    content: str = Field(min_length=1)
    sources: list[int] = Field(min_length=1)


WorkspaceItem = Annotated[
    WorkspaceQuiz | WorkspaceDocument, Field(discriminator="type")
]

_ITEM_ADAPTER: TypeAdapter[WorkspaceQuiz | WorkspaceDocument] = TypeAdapter(
    WorkspaceItem
)


@dataclass(frozen=True)
class ExtractedAnswer:
    """The chat-facing body, the items that passed the gate, and a
    human-readable reason for every block that was withheld."""

    body: str
    items: tuple[WorkspaceQuiz | WorkspaceDocument, ...]
    withheld: tuple[str, ...]


def extract_workspace_items(text: str, material_count: int) -> ExtractedAnswer:
    """Split an answer into chat body + gated workspace items.

    `material_count` is how many numbered chunks the prompt carried; a
    citation [n] is valid only for 1 <= n <= material_count. Every block
    is removed from the body whether it passes or not: a withheld quiz
    must not leak its answer key into the chat as raw JSON."""
    items: list[WorkspaceQuiz | WorkspaceDocument] = []
    withheld: list[str] = []

    def lift(match: re.Match[str]) -> str:
        item, reason = _parse_block(match.group(1), material_count)
        if item is not None:
            items.append(item)
        else:
            withheld.append(reason)
        return ""

    body = WORKSPACE_BLOCK_RE.sub(lift, text)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return ExtractedAnswer(body=body, items=tuple(items), withheld=tuple(withheld))


def _parse_block(
    raw: str, material_count: int
) -> tuple[WorkspaceQuiz | WorkspaceDocument | None, str]:
    try:
        item = _ITEM_ADAPTER.validate_python(json.loads(raw))
    except json.JSONDecodeError:
        return None, "workspace block is not valid JSON"
    except ValidationError as err:
        first = err.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        return None, f"workspace block is malformed ({where}: {first['msg']})"
    problem = _citation_problem(item, material_count)
    if problem is not None:
        return None, f"withheld {item.type}: {problem}"
    return item, ""


def _citation_problem(
    item: WorkspaceQuiz | WorkspaceDocument, material_count: int
) -> str | None:
    if isinstance(item, WorkspaceDocument):
        cited = [*item.sources, *_inline_citations(item.content)]
        return _out_of_range(cited, material_count, "document")
    for number, question in enumerate(item.questions, start=1):
        cited = [
            *question.sources,
            *_inline_citations(question.prompt),
            *_inline_citations(question.explanation or ""),
        ]
        problem = _out_of_range(cited, material_count, f"question {number}")
        if problem is not None:
            return problem
    return None


def _inline_citations(text: str) -> list[int]:
    return [int(n) for n in INLINE_CITATION_RE.findall(text)]


def _out_of_range(cited: list[int], material_count: int, where: str) -> str | None:
    bad = sorted({n for n in cited if n < 1 or n > material_count})
    if bad:
        return (
            f"{where} cites {bad}, but only material "
            f"[1]..[{material_count}] was provided"
        )
    return None
