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
_LINE_BREAK = re.compile(r"(?:<br\s*/?>|\r\n|\r|\n)+", re.IGNORECASE)
_TABLE_ROW = re.compile(r"^\s*\|.+\|\s*$")


def _reflowed(paragraphs: Sequence[str]) -> list[str]:
    """Undo what a strict-JSON string does to line structure: the model
    joins lines with <br> instead of escaping newlines, and drops a table
    into one paragraph per row, which renders as literal pipes rather than
    a table (R3-NEW-2)."""
    out: list[str] = []
    table: list[str] = []

    def flush() -> None:
        if table:
            out.append("\n".join(table))
            table.clear()

    for paragraph in paragraphs:
        lines = [
            line.strip() for line in _LINE_BREAK.split(str(paragraph)) if line.strip()
        ]
        if lines and all(_TABLE_ROW.match(line) for line in lines):
            table.extend(lines)
            continue
        flush()
        if lines:
            out.append("\n".join(lines))
    flush()
    return out or list(paragraphs)


def has_body(markdown: str, title: str = "") -> bool:
    lines: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        content = re.sub(r"^\s*#{1,6}\s+", "", stripped)
        content = content.strip(" *_`").strip()
        if not content or re.match(r"^[-*_]{3,}$", content):
            continue
        labels = {"content", "deck", "markdown", "body", title.strip().casefold()}
        if content.casefold() in labels:
            continue
        # A bare label ("Overview", "Exam Essentials") is still a heading,
        # whatever marker it wears (R4-NEW-i).
        if len(content.split()) < 3 and not re.search(r"[^\w\s]", content):
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
