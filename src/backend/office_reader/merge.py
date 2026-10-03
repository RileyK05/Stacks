"""Merge several readings of one document into one consensus, and score
how much the methods agree.

Redundancy is only useful if you can see it: the merge keeps the *union* of
what every method read, in document order, and reports per-method agreement
so the pane can show "the OOXML read and the screenshot read agree on 12 of
14 units" instead of a single opaque string.

Matching is deliberately forgiving: OCR text differs from source text by
whitespace, punctuation, and case, so units are compared on a normalized
form (lowercased, non-alphanumerics collapsed). Exact duplicates collapse;
near-duplicates from different methods are treated as the same passage.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from src.backend.office_reader.models import (
    Agreement,
    DocumentRead,
    MergedRead,
    TextUnit,
)

_NORMALIZE = re.compile(r"[^a-z0-9]+")
# A containment match is accepted only when the shorter unit is a large
# fraction of the longer one: OCR trims a paragraph lightly, so a heading
# ("chapter 1") must not be treated as the same passage as the paragraph
# that quotes it.
_MATCH_RATIO = 0.5
_MIN_MATCH_WORDS = 2


def normalize(text: str) -> str:
    return _NORMALIZE.sub(" ", text.lower()).strip()


def _similar(left: str, right: str) -> bool:
    """Whether two normalized units are the same passage. Exact matches
    always count; a containment match (OCR often trims or pads a
    paragraph) counts only when the shorter unit is at least half the
    longer one's words."""
    if not left or not right:
        return False
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    if shorter not in longer:
        return False
    short_words = len(shorter.split())
    return short_words >= _MIN_MATCH_WORDS and short_words >= _MATCH_RATIO * len(
        longer.split()
    )


def _distinct(read: DocumentRead) -> list[tuple[str, TextUnit]]:
    return [(normalize(unit.text), unit) for unit in read.units if not unit.empty]


def merge_reads(reads: Iterable[DocumentRead]) -> MergedRead:
    """Union of several methods' readings, with per-method agreement.

    Order follows the methods in the order given; within a method, document
    order. A unit already claimed by an earlier method is not added twice,
    but it still counts as *matched* for the later method."""
    reads = tuple(reads)
    if not reads:
        return MergedRead(host="", units=(), reads=(), agreement=())

    merged: list[TextUnit] = []
    merged_keys: list[str] = []
    agreement: list[Agreement] = []
    warnings: list[str] = []
    seen_warning: set[str] = set()

    for read in reads:
        matched = unique = 0
        for key, unit in _distinct(read):
            same = None
            for index, existing in enumerate(merged_keys):
                if _similar(key, existing):
                    same = index
                    break
            if same is not None:
                matched += 1
                # Prefer the fuller reading by word count: OCR may truncate,
                # but a punctuation-only difference must not flip the text
                # back and forth between methods.
                if len(unit.text.split()) > len(merged[same].text.split()):
                    merged[same] = unit
            else:
                merged.append(unit)
                merged_keys.append(key)
                unique += 1
        agreement.append(
            Agreement(
                method=read.method,
                matched=matched,
                unique=unique,
                total=matched + unique,
            )
        )
        for warning in read.warnings:
            if warning not in seen_warning:
                seen_warning.add(warning)
                warnings.append(f"{read.method}: {warning}")

    host = next((read.host for read in reads if read.host), "")
    return MergedRead(
        host=host,
        units=tuple(merged),
        reads=reads,
        agreement=tuple(agreement),
        warnings=tuple(warnings),
    )
