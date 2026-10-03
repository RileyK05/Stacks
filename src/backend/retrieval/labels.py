"""Page labels for the slice of a passage a reader or the model sees."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace
from typing import Any
from uuid import UUID

from src.backend.common.db import Connection, json_ids
from src.backend.common.queries import get
from src.backend.retrieval.funnel import Candidate

_PAGE = re.compile(r"page (\d+)", re.IGNORECASE)


def format_span_label(labels: Sequence[str]) -> str:
    """One page stays `page 3`. Several consecutive pages become `pages 3–6`."""
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    numbers: list[int] = []
    for label in labels:
        match = _PAGE.fullmatch(label.strip())
        if match is None:
            return f"{labels[0]}–{labels[-1]}"
        numbers.append(int(match.group(1)))
    if numbers[0] == numbers[-1]:
        return labels[0]
    return f"pages {numbers[0]}–{numbers[-1]}"


def _overlaps(
    spans: Sequence[tuple[int, int, str]], abs_start: int, abs_end: int
) -> list[str]:
    return [label for start, end, label in spans if start < abs_end and end > abs_start]


def label_for_window(
    spans: Sequence[tuple[int, int, str]],
    *,
    chunk_start: int | None,
    chunk_end: int | None,
    window_start: int,
    window_end: int | None,
    partial: bool,
    fallback: str,
) -> str:
    """The locator label covering the absolute character window."""
    if chunk_start is None or not spans:
        return fallback
    if partial and window_end is not None:
        abs_start = chunk_start + window_start
        abs_end = chunk_start + window_end
    else:
        abs_start = chunk_start
        abs_end = chunk_end if chunk_end is not None else chunk_start
    chosen = _overlaps(spans, abs_start, abs_end)
    if not chosen:
        return fallback
    return format_span_label(chosen)


def candidate_label(candidate: Candidate, fallback: str = "") -> str:
    return label_for_window(
        candidate.locators,
        chunk_start=candidate.chunk_char_start,
        chunk_end=candidate.chunk_char_end,
        window_start=candidate.window_start,
        window_end=candidate.window_end,
        partial=candidate.partial,
        fallback=fallback,
    )


def parse_locator_span(row: Any) -> tuple[int, int, str] | None:
    try:
        start = int(row["start"])
        end = int(row["end_value"]) if row["end_value"] is not None else start
    except (TypeError, ValueError):
        return None
    return start, end, str(row["label"])


def attach_passage_context(
    conn: Connection, candidates: tuple[Candidate, ...]
) -> tuple[Candidate, ...]:
    """Add filename, source type, container title, and page spans.

    Called before a passage is windowed. `dataclasses.replace` keeps the
    spans, so the label can be computed for the window the model reads.
    """
    if not candidates:
        return candidates
    chunk_ids = [candidate.chunk_id for candidate in candidates]
    rows = conn.execute(
        get("retrieval_traces", "chunks_with_locators_by_ids"),
        {"chunk_ids": json_ids(chunk_ids)},
    ).fetchall()
    by_id = {row["chunk_id"]: row for row in rows}
    spans: dict[UUID, list[tuple[int, int, str]]] = {}
    for row in conn.execute(
        get("retrieval_traces", "chunk_locator_spans"),
        {"chunk_ids": json_ids(chunk_ids)},
    ).fetchall():
        parsed = parse_locator_span(row)
        if parsed is not None:
            spans.setdefault(row["chunk_id"], []).append(parsed)
    attached: list[Candidate] = []
    for candidate in candidates:
        row = by_id.get(candidate.chunk_id)
        if row is None:
            attached.append(candidate)
            continue
        title = row["container_title"] or ""
        attached.append(
            replace(
                candidate,
                chunk_char_start=row["char_start"],
                chunk_char_end=row["char_end"],
                source_filename=row["filename"] or "",
                source_type=row["source_type"] or "",
                container_title="" if title == "Document" else title,
                locators=tuple(spans.get(candidate.chunk_id, ())),
            )
        )
    return tuple(attached)
