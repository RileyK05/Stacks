"""Model draft structure, assembled into the existing Markdown workspace format.

Section/slide boundaries live in arrays, so constrained string generation cannot
erase them. These are transient response contracts, not another material store.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_MATERIAL_CHARS = 200_000
_TITLE_MAX = 120
_LINE_BREAK = re.compile(r"<br\s*/?>|\r\n|\r|\n", re.IGNORECASE)
_NEWLINE = re.compile(r"\r\n|\r|\n")
# splitlines() would also split U+2028/U+2029/U+0085 (and \x1c–\x1e), which
# some models emit inside a JSON string. Those are line breaks for rendering,
# not structure (R5-NEW-l).
_UNICODE_BREAK = re.compile(r"[\u2028\u2029\u0085\x1c-\x1e]")
_TABLE_ROW = re.compile(r"^\s*\|.+\|\s*$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")
_FENCE = re.compile(r"^\s*(?:```|~~~)")
# A bullet glued to the sentence before it with no newline: "…[10].- **Term**"
# (R5-NEW-k). Only split when the bullet is bold, so prose em-dashes survive.
_GLUED_BULLET = re.compile(r"(?<=[.!?\]\)])\s*-\s+(?=\*\*)")
# Short structural headings, not content: a vocabulary slide of bare terms
# ("Manifest Destiny") is body, a bare "Exam Essentials" heading is not
# (R5-NEW-f, keeping R4-NEW-i).
_STRUCTURAL_HEADS = frozenset(
    {
        "overview",
        "introduction",
        "summary",
        "conclusion",
        "contents",
        "outline",
        "agenda",
        "objectives",
        "key terms",
        "key concepts",
        "exam essentials",
        "review",
        "references",
    }
)


def _starts_new_table(rows: Sequence[str]) -> bool:
    return (
        len(rows) >= 2
        and not _TABLE_SEPARATOR.match(rows[0])
        and bool(_TABLE_SEPARATOR.match(rows[1]))
    )


def _split_tables(rows: Sequence[str]) -> list[list[str]]:
    """A run of pipe rows may hold two adjacent tables (R5-NEW-u): a new
    header row followed by a separator starts another one."""
    tables: list[list[str]] = []
    current: list[str] = []
    for index, row in enumerate(rows):
        if current and _starts_new_table(rows[index:]):
            tables.append(current)
            current = []
        current.append(row)
    if current:
        tables.append(current)
    return tables


def _content_lines(text: str) -> list[str]:
    """Paragraph text as lines, preserving indentation inside a fenced code
    block (R5-NEW-e) and splitting glued bullets (R5-NEW-k)."""
    glued = _GLUED_BULLET.sub("\n- ", text)
    lines: list[str] = []
    in_fence = False
    for raw in _LINE_BREAK.split(glued):
        stripped = raw.strip()
        if _FENCE.match(stripped):
            in_fence = not in_fence
            if stripped:
                lines.append(stripped)
            continue
        if in_fence:
            # A blank line inside a fence is part of the code. Collapsing it
            # (the way prose drops empty lines) changes the program.
            lines.append(raw.rstrip())
            continue
        if stripped:
            lines.append(stripped)
    return lines


def _reflowed(paragraphs: Sequence[str]) -> list[str]:
    """Undo what a strict-JSON string does to line structure: the model
    joins lines with <br> instead of escaping newlines, and drops a table
    into one paragraph per row, which renders as literal pipes rather than
    a table (R3-NEW-2)."""
    out: list[str] = []
    table: list[str] = []

    def flush() -> None:
        if table:
            out.extend("\n".join(rows) for rows in _split_tables(table))
            table.clear()

    for paragraph in paragraphs:
        text = _UNICODE_BREAK.sub("\n", str(paragraph))
        rows = [line.strip() for line in _NEWLINE.split(text) if line.strip()]
        if rows and all(_TABLE_ROW.match(row) for row in rows):
            # <br> inside a cell is one row, not a table break (R5-NEW-t).
            table.extend(rows)
            continue
        flush()
        lines = _content_lines(text)
        if lines:
            out.append("\n".join(lines))
    flush()
    return out or list(paragraphs)


def has_body(markdown: str, title: str = "") -> bool:
    lines: list[str] = []
    labels = {"content", "deck", "markdown", "body", title.strip().casefold()}
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        heading = bool(re.match(r"^\s*#{1,6}\s+", stripped))
        content = re.sub(r"^\s*#{1,6}\s+", "", stripped)
        content = content.strip(" *_`").strip()
        if not content or re.match(r"^[-*_]{3,}$", content):
            continue
        folded = content.casefold()
        if folded in labels or folded in _STRUCTURAL_HEADS:
            continue
        # A bare short line is only a heading when it wears a heading marker;
        # otherwise it may be a key term in a vocabulary slide (R5-NEW-f).
        if heading and len(content.split()) < 3 and not re.search(r"[^\w\s]", content):
            continue
        lines.append(content)
    return bool(lines)


class _Draft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Section(_Draft):
    heading: str = Field(max_length=500)
    paragraphs: list[str] = Field(min_length=1, max_length=64)

    @field_validator("paragraphs", mode="before")
    @classmethod
    def _lines(cls, value: object) -> object:
        return _reflowed(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def _usable(self) -> Section:
        if "\n" in self.heading or "\r" in self.heading:
            raise ValueError("a section heading must be a single line")
        if any(
            not paragraph.strip() or len(paragraph) > 20_000
            for paragraph in self.paragraphs
        ):
            raise ValueError("section paragraphs must contain bounded text")
        if not has_body("\n\n".join(self.paragraphs), self.heading):
            raise ValueError("a section must contain more than headings")
        return self

    def markdown(self) -> str:
        body = "\n\n".join(paragraph.strip() for paragraph in self.paragraphs)
        heading = re.sub(r"^#{1,6}\s+", "", self.heading.strip())
        return f"## {heading}\n\n{body}" if heading else body


class DocumentDraft(_Draft):
    type: Literal["document"]
    title: str = Field(max_length=_TITLE_MAX)
    sections: list[Section] = Field(min_length=1, max_length=64)
    sources: list[int] = Field(min_length=1)

    @field_validator("title", mode="before")
    @classmethod
    def _truncate_title(cls, value: object) -> object:
        if isinstance(value, str) and len(value) > _TITLE_MAX:
            return value[:_TITLE_MAX]
        return value

    def workspace(self) -> dict[str, object]:
        content = "\n\n".join(section.markdown() for section in self.sections)
        if len(content) > MAX_MATERIAL_CHARS:
            raise ValueError("document content is too long")
        return {
            "type": self.type,
            "title": self.title,
            "content": content,
            "sources": self.sources,
        }


class Slide(_Draft):
    title: str = Field(max_length=500)
    paragraphs: list[str] = Field(min_length=1, max_length=32)

    @field_validator("paragraphs", mode="before")
    @classmethod
    def _lines(cls, value: object) -> object:
        return _reflowed(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def _usable(self) -> Slide:
        if not self.title.strip("# \t") or "\n" in self.title or "\r" in self.title:
            raise ValueError("a slide title must be a nonempty single line")
        if any(
            not paragraph.strip() or len(paragraph) > 20_000
            for paragraph in self.paragraphs
        ):
            raise ValueError("slide paragraphs must contain bounded text")
        body = "\n\n".join(self.paragraphs)
        if re.search(r"^\s*---\s*$", body, re.MULTILINE):
            raise ValueError("slide content cannot introduce another slide")
        if not has_body(body, self.title):
            raise ValueError("a slide must contain more than its title")
        return self

    def markdown(self) -> str:
        body = "\n\n".join(paragraph.strip() for paragraph in self.paragraphs)
        title = re.sub(r"^#{1,6}\s+", "", self.title.strip())
        return f"# {title}\n\n{body}"


class DeckDraft(_Draft):
    type: Literal["slides"]
    title: str = Field(max_length=_TITLE_MAX)
    slides: list[Slide] = Field(min_length=1, max_length=200)
    sources: list[int] = Field(min_length=1)

    @field_validator("title", mode="before")
    @classmethod
    def _truncate_title(cls, value: object) -> object:
        if isinstance(value, str) and len(value) > _TITLE_MAX:
            return value[:_TITLE_MAX]
        return value

    def workspace(self) -> dict[str, object]:
        deck = "\n\n---\n\n".join(slide.markdown() for slide in self.slides)
        if len(deck) > MAX_MATERIAL_CHARS:
            raise ValueError("deck content is too long")
        return {
            "type": self.type,
            "title": self.title,
            "deck": deck,
            "sources": self.sources,
        }
