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
        first = int(bounds[0])
        last = int(bounds[-1])
        if len(bounds) == 1:
            numbers.append(first)
        elif first <= last and last - first <= 1000:
            numbers.extend(range(first, last + 1))
        else:
            numbers.extend((0, first, last))
    return numbers


def cited_numbers(text: str) -> set[int]:
    found: set[int] = set()

    def scan(prose: str) -> str:
        for match in CITATION_RE.finditer(prose):
            found.update(marker_numbers(match.group(1)))
        return prose

    prose_transform(text, scan)
    return found
