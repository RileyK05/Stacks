"""Recover document structure for passage parents, without a separate TOC store."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any

from src.backend.ingest.extract import ExtractedSource
from src.backend.rag.segment import ContainerSpan, containers

HEADING_SIZE_RATIO = 1.12
MAX_HEADING_WORDS = 14
# A title repeated on this share of pages is a running head, not a section.
_RUNNING_HEAD_SHARE = 0.30
_LETTERS = re.compile(r"[A-Za-z].*[A-Za-z]")


@dataclass(frozen=True)
class _Heading:
    page: int  # 0-based
    title: str
    level: int = 1


def _clean(text: str) -> str:
    return " ".join(text.split())


def _outline_headings(reader: Any) -> list[_Heading]:
    headings: list[_Heading] = []

    def walk(items: list[Any], level: int = 1) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item, level + 1)
                continue
            try:
                page = reader.get_destination_page_number(item)
            except Exception:
                continue
            title = _clean(str(getattr(item, "title", "")))
            if title and page is not None and page >= 0:
                headings.append(_Heading(page=page, title=title, level=level))

    walk(list(reader.outline or []))
    return headings


def _baseline(tm: Any) -> float:
    try:
        return round(float(tm[5]), 1)
    except (TypeError, IndexError, ValueError):
        return 0.0


def _text_runs(page: Any) -> list[tuple[float, str, float]]:
    """(effective font size, text, baseline) for every text run on a page."""
    runs: list[tuple[float, str, float]] = []

    def visit(text: str, cm: Any, tm: Any, font: Any, size: float) -> None:
        if not text.strip():
            return
        scale = abs(tm[3]) if tm and tm[3] else 1.0
        outer = abs(cm[3]) if cm and cm[3] else 1.0
        runs.append(
            (round(float(size) * scale * outer, 1), text.strip(), _baseline(tm))
        )

    try:
        page.extract_text(visitor_text=visit)
    except Exception:
        return []
    return runs


def _merge_baseline_runs(
    runs: list[tuple[float, str, float]],
) -> list[tuple[float, str]]:
    """Join fragments that sit on one baseline.

    Small-caps headings arrive as separate runs (`C`, `OMMUNITY B`). They
    are one title; joining them with a space would search for that space
    inside a word. A new baseline starts a new run.
    """
    merged: list[tuple[float, str]] = []
    last_baseline: float | None = None
    for size, text, baseline in runs:
        if (
            merged
            and last_baseline is not None
            and abs(baseline - last_baseline) <= 0.5
            and abs(size - merged[-1][0]) <= 0.3
        ):
            merged[-1] = (merged[-1][0], merged[-1][1] + text)
            continue
        merged.append((size, text))
        last_baseline = baseline
    return merged


def _is_title(title: str) -> bool:
    letters = sum(char.isalpha() for char in title)
    return (
        letters >= 3
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


def _drop_running_heads(headings: list[_Heading], page_count: int) -> list[_Heading]:
    """A title on one page is a heading. The same title on most pages is
    the running head."""
    if page_count <= 0:
        return headings
    counts: dict[str, int] = {}
    for heading in headings:
        key = heading.title.casefold()
        counts[key] = counts.get(key, 0) + 1
    return [
        heading
        for heading in headings
        if counts[heading.title.casefold()] < 2
        or counts[heading.title.casefold()] / page_count < _RUNNING_HEAD_SHARE
    ]


def _typographic_headings(reader: Any) -> list[_Heading]:
    found = [
        _Heading(page=page_index, title=title)
        for page_index, page in enumerate(reader.pages)
        for title in _page_headings(_merge_baseline_runs(_text_runs(page)))
    ]
    return _drop_running_heads(found, len(reader.pages))


def _heading_start(
    text: str, page_start: int, page_end: int, title: str, *, allow_page_start: bool
) -> int | None:
    """Where `title` begins a line inside the page. A miss does not invent
    a container at the page start unless the title came from the outline."""
    page_text = text[page_start:page_end]
    boundary = r"\b" if title[-1:].isalnum() else ""
    match = re.search(rf"(?m)^\s*{re.escape(title)}{boundary}", page_text)
    if match is not None:
        return page_start + match.start()
    if allow_page_start:
        return page_start
    return None


def pdf_containers(
    extracted: ExtractedSource, pdf_bytes: bytes
) -> tuple[ContainerSpan, ...]:
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    headings = _outline_headings(reader)
    origin = "source"
    allow_page_start = True
    if not headings:
        headings = _typographic_headings(reader)
        origin = "inference"
        allow_page_start = False
    pages = [loc for loc in extracted.locators if loc.locator_type == "page"]
    positioned = []
    seen = set()
    for heading in headings:
        if heading.page >= len(pages) or not heading.title:
            continue
        page = pages[heading.page]
        start = _heading_start(
            extracted.text,
            page.start,
            page.end,
            heading.title,
            allow_page_start=allow_page_start,
        )
        if start is None:
            continue
        key = (start, heading.level)
        if key not in seen:
            positioned.append((start, heading.level, heading.title))
            seen.add(key)
    positioned.sort()
    if not positioned:
        return containers(extracted.text)
    result: list[ContainerSpan] = []
    stack: list[int] = []
    for i, (start, level, title) in enumerate(positioned):
        while stack and result[stack[-1]].level >= level:
            stack.pop()
        end = next(
            (a for a, depth, _ in positioned[i + 1 :] if depth <= level),
            len(extracted.text),
        )
        if end <= start:
            continue
        result.append(
            ContainerSpan(
                start, end, title, level, stack[-1] if stack else None, origin
            )
        )
        stack.append(len(result) - 1)
    return tuple(result)


def office_containers(extracted: ExtractedSource) -> tuple[ContainerSpan, ...] | None:
    located = [
        span
        for span in extracted.locators
        if span.locator_type in ("slide", "sheet") and span.end > span.start
    ]
    if not located:
        return None
    return tuple(
        ContainerSpan(span.start, span.end, span.label, 1, None) for span in located
    )
