"""Model draft structure, assembled into the existing Markdown workspace format.

Section/slide boundaries live in arrays, so constrained string generation cannot
erase them. These are transient response contracts, not another material store.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_MATERIAL_CHARS = 200_000


def has_body(markdown: str, title: str = "") -> bool:
    lines = [
        line.strip()
        for line in markdown.splitlines()
        if line.strip() and not re.match(r"^\s*(?:#{1,6}\s|[-*_]{3,}\s*$)", line)
    ]
    return bool(lines) and any(
        line.strip(" *_`").casefold()
        not in {"content", "deck", "markdown", "body", title.strip().casefold()}
        for line in lines
    )


class _Draft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Section(_Draft):
    heading: str = Field(max_length=500)
    paragraphs: list[str] = Field(min_length=1, max_length=64)

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
        heading = self.heading.strip().lstrip("# ")
        return f"## {heading}\n\n{body}" if heading else body


class DocumentDraft(_Draft):
    type: Literal["document"]
    title: str = Field(max_length=120)
    sections: list[Section] = Field(min_length=1, max_length=64)
    sources: list[int] = Field(min_length=1)

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
        return f"# {self.title.strip().lstrip('# ')}\n\n{body}"


class DeckDraft(_Draft):
    type: Literal["slides"]
    title: str = Field(max_length=120)
    slides: list[Slide] = Field(min_length=1, max_length=200)
    sources: list[int] = Field(min_length=1)

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
