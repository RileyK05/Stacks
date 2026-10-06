"""Numbered evidence markers in prose, excluding literal Markdown code."""

from __future__ import annotations

import re
from collections.abc import Callable

CITATION_RE = re.compile(r"\[(\d+(?:\s*[,–-]\s*\d+)*)\]")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_TICKS = re.compile(r"(?<!`)(`+)(?!`)")


def _inline_transform(text: str, transform: Callable[[str], str]) -> str:
    parts: list[str] = []
    start = 0
    markers = list(_TICKS.finditer(text))
    index = 0
    while index < len(markers):
        opening = markers[index]
        closing = next(
            (
                n
                for n in range(index + 1, len(markers))
                if len(markers[n].group()) == len(opening.group())
            ),
            None,
        )
        if closing is None:
            index += 1
            continue
        end = markers[closing].end()
        parts.extend(
            (transform(text[start : opening.start()]), text[opening.start() : end])
        )
        start = end
        index = closing + 1
    parts.append(transform(text[start:]))
    return "".join(parts)


def prose_transform(
    text: str, transform: Callable[[str], str], *, include_inline: bool = True
) -> str:
    parts: list[str] = []
    prose: list[str] = []
    fence = ""
    for line in text.splitlines(keepends=True):
        match = _FENCE.match(line.rstrip("\r\n"))
        if fence:
            parts.append(line)
            if (
                match
                and match[1][0] == fence[0]
                and len(match[1]) >= len(fence)
                and not match[2].strip()
            ):
                fence = ""
        elif match and not (match[1][0] == "`" and "`" in match[2]):
            block = "".join(prose)
            parts.append(
                _inline_transform(block, transform)
                if include_inline
                else transform(block)
            )
            prose.clear()
            parts.append(line)
            fence = match[1]
        else:
            prose.append(line)
    block = "".join(prose)
    parts.append(
        _inline_transform(block, transform) if include_inline else transform(block)
    )
    return "".join(parts)


def marker_numbers(marker: str) -> list[int]:
    numbers: list[int] = []
    for part in marker.split(","):
        bounds = re.split(r"\s*[–-]\s*", part.strip())
        if len(bounds) > 2:
            numbers.append(0)
            continue
        first = int(bounds[0])
        last = int(bounds[-1])
        if len(bounds) == 1:
            numbers.append(first)
        elif first <= last and abs(last - first) <= 1000:
            numbers.extend(range(first, last + 1))
        else:
            # An invalid sentinel fails closed without expanding a hostile range.
            numbers.append(0)
    return numbers


def cited_numbers(text: str) -> set[int]:
    found: set[int] = set()

    def scan(prose: str) -> str:
        for match in CITATION_RE.finditer(prose):
            # A zero index attached to an identifier is ordinary array
            # notation (for example arr[0]); positive markers stay citations
            # even when attached to a word.
            if _is_subscript(prose, match.start(), match.group(1)):
                continue
            found.update(marker_numbers(match.group(1)))
        return prose

    prose_transform(text, scan)
    return found


def _is_subscript(prose: str, marker_start: int, marker: str) -> bool:
    identifier = re.search(r"([A-Za-z_]\w*)$", prose[:marker_start])
    return bool(identifier and marker.strip() == "0")


def strip_citations(text: str) -> str:
    """Remove recognized prose citation markers, preserving code and subscripts."""

    def strip(prose: str) -> str:
        return CITATION_RE.sub(
            lambda match: (
                ""
                if not _is_subscript(prose, match.start(), match.group(1))
                else match[0]
            ),
            prose,
        )

    return prose_transform(text, strip)
