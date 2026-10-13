"""Explicit-address routing for retrieval (plan-score-retrieval.md Phase 1).

A question that names a numbered thing in the material ("Table 2.2") or a
week ("Week 3", "Weeks 1-5") can be routed: the label becomes an FTS phrase
that pins the exact passage, and a week becomes a source filter. This is the
fix for STK-025/044, STK-039 and R5-NEW-p. Pure functions except
`source_weeks`, which reads source filenames.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from src.backend.common.db import Connection
from src.backend.common.queries import get
from src.backend.retrieval.config import RoutePolicy, load_route_policy

_KIND_ALIASES = {"fig": "figure", "eq": "equation"}
_LABEL = re.compile(r"\b([A-Za-z]+)\.?\s+(\d+(?:\.\d+)*[a-z]?)\b")
_WEEK_RANGE = re.compile(
    r"\b(?:weeks?|wk)\s*\.?\s*(\d{1,2})"
    r"(?:\s*(?:-|–|—|to|through|thru)\s*(\d{1,2}))?\b",
    re.IGNORECASE,
)
_FILENAME_WEEK = re.compile(r"(?i)(?<![a-z])(?:weeks?|wk)[\s_-]*0?(\d{1,2})(?!\d)")
_PHRASE_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Addresses:
    labels: tuple[str, ...]
    weeks: tuple[int, ...]

    def empty(self) -> bool:
        return not self.labels and not self.weeks


def parse_addresses(text: str, policy: RoutePolicy | None = None) -> Addresses:
    """Explicit references in a question: normalized labels ("table 2.2")
    and week numbers (a range expands). Nothing found gives an empty result."""
    policy = policy or load_route_policy()
    kinds = {kind.casefold() for kind in policy.label_kinds}
    labels: list[str] = []
    for match in _LABEL.finditer(text):
        kind = _KIND_ALIASES.get(match.group(1).casefold(), match.group(1).casefold())
        if kind not in kinds:
            continue
        label = f"{kind} {match.group(2).casefold()}"
        if label not in labels:
            labels.append(label)
    weeks: list[int] = []
    for match in _WEEK_RANGE.finditer(text):
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        low, high = sorted((start, end))
        for week in range(low, high + 1):
            if 1 <= week <= 52 and week not in weeks:
                weeks.append(week)
    return Addresses(tuple(labels), tuple(sorted(weeks)))


def label_phrase(label: str) -> str:
    """One FTS5 phrase for a label, tokenized the way the index is: single
    characters are kept and the tokens stay adjacent ("Table 2.2" ->
    '"table 2 2"'), and the phrase does not match "Table 2.20"."""
    tokens = _PHRASE_TOKEN.findall(label.casefold())
    return '"' + " ".join(tokens) + '"' if tokens else ""


def source_weeks(conn: Connection, course_id: UUID) -> dict[UUID, int | None]:
    """Each live source's week, inferred from its filename. None when the
    filename names no week."""
    rows = conn.execute(
        get("retrieval", "course_source_filenames"), {"course_id": course_id}
    ).fetchall()
    weeks: dict[UUID, int | None] = {}
    for row in rows:
        match = _FILENAME_WEEK.search(row["filename"] or "")
        weeks[row["source_id"]] = int(match.group(1)) if match else None
    return weeks
