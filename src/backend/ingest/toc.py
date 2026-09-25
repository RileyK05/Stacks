"""Table of contents from the author's own structure (plan §10a step 1).

No chat model: a TOC entry is a heading the author wrote, mapped to the
locator it sits in, so every entry is grounded by construction.

- Markdown: each `#` section locator is an entry.
- PDF with bookmarks: each outline item is an entry on its page.
- PDF without bookmarks: headings are detected from typography — text
  runs set noticeably larger than the page's body text (≥ 1.12×; bold at
  body size is inline emphasis, not a heading). A heading that wraps onto
  a second line is merged; drop caps and page furniture are ignored.

Sources with no detectable structure (plain text, flat PDFs) get no
entries; the stage records that as a skip. Encoder-based boundaries for
those (§10a step 2) come later.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from src.backend.ingest.extract import ExtractedSource, LocatorSpan

HEADING_SIZE_RATIO = 1.12
MAX_HEADING_WORDS = 14
DESCRIPTION_CHARS = 240
_LETTERS = re.compile(r"[A-Za-z].*[A-Za-z]")


@dataclass(frozen=True)
class TocDraft:
    title: str
    locator_id: UUID
    description: str


@dataclass(frozen=True)
class _Heading:
    page: int  # 0-based
    title: str


def _clean(text: str) -> str:
    return " ".join(text.split())


def _description(text: str, start: int, end: int, title: str) -> str:
    """The text right after the heading inside its locator — what the TOC
    seam matches on besides the title."""
    body = text[start:end]
    at = body.find(title) if title else -1
    if at >= 0:
        body = body[at + len(title) :]
    return _clean(body)[:DESCRIPTION_CHARS]


def markdown_entries(extracted: ExtractedSource) -> list[TocDraft]:
    drafts: list[TocDraft] = []
    for span in extracted.locators:
        if span.locator_type != "section":
            continue
        title = span.label.removeprefix("§ ").strip()
        drafts.append(
            TocDraft(
                title=title,
                locator_id=span.locator_id,
                description=_description(extracted.text, span.start, span.end, title),
            )
        )
    return drafts


def _outline_headings(reader: Any) -> list[_Heading]:
    headings: list[_Heading] = []

    def walk(items: list[Any]) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item)
                continue
            try:
                page = reader.get_destination_page_number(item)
            except Exception:
                continue
            title = _clean(str(getattr(item, "title", "")))
            if title and page is not None and page >= 0:
                headings.append(_Heading(page=page, title=title))

    walk(list(reader.outline or []))
    return headings


def _text_runs(page: Any) -> list[tuple[float, str]]:
    """(effective font size, text) for every text run on a page."""
    runs: list[tuple[float, str]] = []

    def visit(text: str, cm: Any, tm: Any, font: Any, size: float) -> None:
        if not text.strip():
            return
        scale = abs(tm[3]) if tm and tm[3] else 1.0
        outer = abs(cm[3]) if cm and cm[3] else 1.0
        runs.append((round(float(size) * scale * outer, 1), text.strip()))

    try:
        page.extract_text(visitor_text=visit)
    except Exception:
        return []
    return runs


def _is_title(title: str) -> bool:
    return (
        bool(title)
        and _LETTERS.search(title) is not None
        and len(title.split()) <= MAX_HEADING_WORDS
        and not title.endswith(".")
    )


def _page_headings(runs: list[tuple[float, str]]) -> list[str]:
    """Heading titles on one page: runs clearly larger than the body size
    (the size carrying the most characters), with consecutive same-size
    runs merged into one wrapped heading."""
    if not runs:
        return []
    weight: dict[float, int] = {}
    for size, text in runs:
        weight[size] = weight.get(size, 0) + len(text)
    body = max(weight, key=lambda size: weight[size])
    titles: list[str] = []
    pending: list[str] = []
    pending_size: float | None = None
    for size, text in runs:
        is_heading = size >= body * HEADING_SIZE_RATIO and len(text) > 1
        if is_heading and pending_size is not None and abs(size - pending_size) <= 0.3:
            pending.append(text)
            continue
        if pending:
            titles.append(_clean(" ".join(pending)))
        pending, pending_size = ([text], size) if is_heading else ([], None)
    if pending:
        titles.append(_clean(" ".join(pending)))
    return [title for title in titles if _is_title(title)]


def _typographic_headings(reader: Any) -> list[_Heading]:
    return [
        _Heading(page=page_index, title=title)
        for page_index, page in enumerate(reader.pages)
        for title in _page_headings(_text_runs(page))
    ]


def pdf_entries(extracted: ExtractedSource, pdf_bytes: bytes) -> list[TocDraft]:
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    headings = _outline_headings(reader) or _typographic_headings(reader)
    pages: list[LocatorSpan] = [
        span for span in extracted.locators if span.locator_type == "page"
    ]
    drafts: list[TocDraft] = []
    seen: set[tuple[int, str]] = set()
    for heading in headings:
        if heading.page >= len(pages) or (heading.page, heading.title) in seen:
            continue
        seen.add((heading.page, heading.title))
        span = pages[heading.page]
        drafts.append(
            TocDraft(
                title=heading.title,
                locator_id=span.locator_id,
                description=_description(
                    extracted.text, span.start, span.end, heading.title
                ),
            )
        )
    return drafts
