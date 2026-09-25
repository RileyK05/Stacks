"""What each kind of artifact holds, and its citations.

An artifact's content is typed JSON validated here. Citations are the same
everywhere: an inline "[n]" (or "[n, m]") in any text field, plus the
`sources` number lists some items carry (quiz questions, flashcards). The
number n always means the artifact's n-th source chunk — so saving,
editing and exporting only ever need two operations on content: find the
numbers it cites, and renumber them.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from src.backend.tutor.workspace import (
    WorkspaceCode,
    WorkspaceDocument,
    WorkspaceHtml,
    WorkspaceItem,
    WorkspaceQuiz,
    WorkspaceSheet,
    WorkspaceSlides,
)

ArtifactKind = Literal["doc", "sheet", "slides", "quiz", "flashcards", "code", "chart"]
KINDS: tuple[ArtifactKind, ...] = (
    "doc",
    "sheet",
    "slides",
    "quiz",
    "flashcards",
    "code",
    "chart",
)
MAX_TEXT = 200_000
MAX_CELL = 5_000

CITATION_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_ESCAPED_CITATION = re.compile(r"\\\[(\d+(?:\s*,\s*\d+)*)\\\]")


class DocContent(BaseModel):
    """A document as Markdown (headings, lists, tables, math, code)."""

    markdown: str = Field(default="", max_length=MAX_TEXT)

    @model_validator(mode="after")
    def _citations_unescaped(self) -> DocContent:
        # Markdown writers escape "[" ("\[1\]"); a citation stays "[1]".
        self.markdown = _ESCAPED_CITATION.sub(r"[\1]", self.markdown)
        return self


class SheetContent(BaseModel):
    columns: list[str] = Field(default_factory=lambda: ["A", "B", "C"], max_length=50)
    rows: list[list[str]] = Field(default_factory=list, max_length=5000)

    @model_validator(mode="after")
    def _rectangular(self) -> SheetContent:
        width = len(self.columns)
        for number, row in enumerate(self.rows, start=1):
            if len(row) != width:
                raise ValueError(
                    f"row {number} has {len(row)} cells but there are {width} columns"
                )
            if any(len(cell) > MAX_CELL for cell in row):
                raise ValueError(f"a cell in row {number} is too long")
        return self


class Slide(BaseModel):
    title: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=20_000)
    notes: str = Field(default="", max_length=20_000)


class SlidesContent(BaseModel):
    slides: list[Slide] = Field(default_factory=lambda: [Slide()], max_length=200)


class QuizQuestion(BaseModel):
    prompt: str = Field(min_length=1, max_length=5_000)
    options: list[str] = Field(min_length=2, max_length=8)
    answer: int
    explanation: str = Field(default="", max_length=5_000)
    sources: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def _answer_is_an_option(self) -> QuizQuestion:
        if not 0 <= self.answer < len(self.options):
            raise ValueError(
                f"answer {self.answer} is not one of the {len(self.options)} options"
            )
        return self


class QuizContent(BaseModel):
    questions: list[QuizQuestion] = Field(default_factory=list, max_length=100)


class Flashcard(BaseModel):
    front: str = Field(min_length=1, max_length=5_000)
    back: str = Field(min_length=1, max_length=5_000)
    sources: list[int] = Field(default_factory=list)


class FlashcardsContent(BaseModel):
    cards: list[Flashcard] = Field(default_factory=list, max_length=1000)


class CodeContent(BaseModel):
    language: str = Field(default="", max_length=40)
    code: str = Field(default="", max_length=MAX_TEXT)


class ChartContent(BaseModel):
    """Sanitized HTML/SVG rendered by the frontend; never executed."""

    html: str = Field(default="", max_length=MAX_TEXT)


CONTENT_MODELS: dict[str, type[BaseModel]] = {
    "doc": DocContent,
    "sheet": SheetContent,
    "slides": SlidesContent,
    "quiz": QuizContent,
    "flashcards": FlashcardsContent,
    "code": CodeContent,
    "chart": ChartContent,
}

DEFAULT_TITLES: dict[str, str] = {
    "doc": "Untitled doc",
    "sheet": "Untitled sheet",
    "slides": "Untitled deck",
    "quiz": "Untitled quiz",
    "flashcards": "Untitled flashcards",
    "code": "Untitled code",
    "chart": "Untitled chart",
}


def validate_content(kind: str, raw: Any) -> dict[str, Any]:
    """Validated, normalised content for a kind (raises ValueError)."""
    model = CONTENT_MODELS.get(kind)
    if model is None:
        raise ValueError(f"unknown artifact kind: {kind}")
    return model.model_validate(raw).model_dump()


def blank(kind: str) -> dict[str, Any]:
    return validate_content(kind, {})


# --- citations ---------------------------------------------------------


def _walk(
    value: Any,
    on_text: Callable[[str], str],
    on_numbers: Callable[[list[int]], list[int]],
) -> Any:
    if isinstance(value, str):
        return on_text(value)
    if isinstance(value, list):
        return [_walk(item, on_text, on_numbers) for item in value]
    if isinstance(value, dict):
        walked: dict[str, Any] = {}
        for key, item in value.items():
            if key == "sources" and isinstance(item, list):
                walked[key] = on_numbers([int(n) for n in item])
            else:
                walked[key] = _walk(item, on_text, on_numbers)
        return walked
    return value


def cited_numbers(content: Any) -> set[int]:
    found: set[int] = set()

    def text(value: str) -> str:
        for match in CITATION_RE.finditer(value):
            found.update(int(n) for n in re.split(r"\s*,\s*", match.group(1)))
        return value

    def numbers(values: list[int]) -> list[int]:
        found.update(values)
        return values

    _walk(content, text, numbers)
    return found


class UnknownCitationError(ValueError):
    """Content cites a number that has no source."""


def renumber(content: Any, mapping: Mapping[int, int]) -> Any:
    """Rewrite every citation number through `mapping`; a number it does
    not cover raises UnknownCitationError (never silently kept)."""

    def lookup(number: int) -> int:
        if number not in mapping:
            raise UnknownCitationError(f"citation [{number}] has no source")
        return mapping[number]

    def text(value: str) -> str:
        def replace(match: re.Match[str]) -> str:
            numbers = [lookup(int(n)) for n in re.split(r"\s*,\s*", match.group(1))]
            return "[" + ", ".join(str(n) for n in dict.fromkeys(numbers)) + "]"

        return CITATION_RE.sub(replace, value)

    def numbers(values: list[int]) -> list[int]:
        return list(dict.fromkeys(lookup(n) for n in values))

    return _walk(content, text, numbers)


def compact(
    content: Any, numbered: Sequence[UUID], also: Sequence[int] = ()
) -> tuple[Any, list[UUID]]:
    """Keep only the chunks the content cites (plus `also`: numbers the
    item cited as a whole), in number order, and renumber to match.
    `numbered[n-1]` is what [n] means on the way in."""
    wanted = cited_numbers(content) | set(also)
    used = sorted(n for n in wanted if 1 <= n <= len(numbered))
    unknown = wanted - set(used)
    if unknown:
        raise UnknownCitationError(
            f"citation [{min(unknown)}] is outside the {len(numbered)} sources"
        )
    sources: list[UUID] = []
    mapping: dict[int, int] = {}
    for number in used:
        chunk_id = numbered[number - 1]
        if chunk_id not in sources:
            sources.append(chunk_id)
        mapping[number] = sources.index(chunk_id) + 1
    return renumber(content, mapping), sources


def merge(
    content: Any, numbered: Sequence[UUID], existing: Sequence[UUID]
) -> tuple[Any, list[UUID]]:
    """Content whose [n] refer to `numbered` (e.g. a model edit's material),
    renumbered onto the artifact's `existing` sources: chunks already there
    keep their number, new ones are appended. Unused existing sources stay
    (other parts of the artifact may cite them)."""
    sources = list(existing)
    mapping: dict[int, int] = {}
    for number in sorted(cited_numbers(content)):
        if not 1 <= number <= len(numbered):
            raise UnknownCitationError(
                f"citation [{number}] is outside the {len(numbered)} sources"
            )
        chunk_id = numbered[number - 1]
        if chunk_id not in sources:
            sources.append(chunk_id)
        mapping[number] = sources.index(chunk_id) + 1
    return renumber(content, mapping), sources


# --- from a chat's workspace item ------------------------------------------


def _deck_slides(deck: str) -> list[dict[str, str]]:
    slides: list[dict[str, str]] = []
    for part in re.split(r"^\s*---\s*$", deck, flags=re.MULTILINE):
        text = part.strip()
        if not text:
            continue
        lines = text.splitlines()
        title = ""
        if lines and lines[0].lstrip().startswith("#"):
            title = lines[0].lstrip("# ").strip()
            lines = lines[1:]
        slides.append({"title": title, "body": "\n".join(lines).strip(), "notes": ""})
    return slides or [{"title": "", "body": deck.strip(), "notes": ""}]


def from_workspace_item(
    item: WorkspaceItem,
) -> tuple[str, str, dict[str, Any], list[int]]:
    """(kind, title, content, item-level citations) for a chat workspace
    item. Citations keep the item's numbering; the caller compacts them
    onto chunk ids, so what the item as a whole cited stays in the
    artifact's sources even where no line cites it inline."""
    title = item.title or ""
    if isinstance(item, WorkspaceDocument):
        return "doc", title or "Study notes", {"markdown": item.content}, item.sources
    if isinstance(item, WorkspaceSheet):
        return (
            "sheet",
            title or "Table",
            {"columns": item.columns, "rows": item.rows},
            item.sources,
        )
    if isinstance(item, WorkspaceSlides):
        return (
            "slides",
            title or "Slides",
            {"slides": _deck_slides(item.deck)},
            item.sources,
        )
    if isinstance(item, WorkspaceQuiz):
        return (
            "quiz",
            title or "Practice quiz",
            {
                "questions": [
                    {
                        "prompt": q.prompt,
                        "options": q.options,
                        "answer": q.answer,
                        "explanation": q.explanation or "",
                        "sources": q.sources,
                    }
                    for q in item.questions
                ]
            },
            [],
        )
    if isinstance(item, WorkspaceCode):
        return (
            "code",
            title or "Code",
            {"language": item.language or "", "code": item.code},
            item.sources,
        )
    if isinstance(item, WorkspaceHtml):
        return "chart", title or "Chart", {"html": item.html}, item.sources
    raise ValueError("unsupported workspace item")
