"""Stage 3 handler: token-bounded retrieval chunks.

Chunks are sized to fit the model context window (never arbitrary lines)
and each points back to the locator it spans. The estimate is deliberately
the same characters-per-token approximation used elsewhere in the project;
exact tokenization is a versioned-config concern if it ever matters.
Boundaries prefer paragraph breaks, then sentence breaks, then hard cuts —
a chunk should never split mid-word.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from src.backend.ingest.extract import LocatorSpan

CHARS_PER_TOKEN = 4
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
PARAGRAPH_RE = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class ChunkSpan:
    """One retrieval slice: text plus the locators it spans."""

    chunk_index: int
    text: str
    start: int
    end: int
    locator_ids: tuple[UUID, ...]


def chunk_text(
    text: str,
    locators: tuple[LocatorSpan, ...],
    *,
    max_tokens: int,
) -> tuple[ChunkSpan, ...]:
    """Split text into token-bounded chunks and map each to the locators
    its character range overlaps. Locator ranges are character offsets into
    `text`, matching `extract.ExtractedSource`."""
    if max_tokens < 1:
        raise ValueError("max_tokens must be at least 1")
    max_chars = max_tokens * CHARS_PER_TOKEN
    spans: list[ChunkSpan] = []
    position = 0
    while position < len(text):
        boundary = _boundary(text, position, max_chars)
        raw = text[position:boundary]
        stripped = raw.strip()
        if stripped:
            start = position + (len(raw) - len(raw.lstrip()))
            end = start + len(stripped)
            spans.append(
                ChunkSpan(
                    chunk_index=len(spans),
                    text=stripped,
                    start=start,
                    end=end,
                    locator_ids=tuple(
                        locator.locator_id
                        for locator in locators
                        if locator.start < end and locator.end > start
                    ),
                )
            )
        position = boundary
        while position < len(text) and text[position].isspace():
            position += 1
    return tuple(spans)


def _boundary(text: str, position: int, max_chars: int) -> int:
    """End offset for one chunk: last paragraph break within the window,
    else last sentence break, else last whitespace, else the hard edge.
    Paragraph/sentence boundaries only count when they leave a
    meaningfully sized chunk (>= half the window)."""
    window_end = min(position + max_chars, len(text))
    if window_end == len(text):
        return window_end
    window = text[position:window_end]
    paragraph = max(
        (match.end() for match in PARAGRAPH_RE.finditer(window)), default=0
    )
    if paragraph > max_chars // 2:
        return position + paragraph
    sentence = max(
        (match.end() for match in SENTENCE_RE.finditer(window)), default=0
    )
    if sentence > max_chars // 2:
        return position + sentence
    space = window.rfind(" ")
    if space > 0:
        return position + space + 1
    return window_end