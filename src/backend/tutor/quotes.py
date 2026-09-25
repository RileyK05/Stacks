"""Quote-anchored answers (docs/plan-local-first.md §6.2).

The model is asked for evidence before it answers: a few short passages
copied word-for-word from the numbered material, each with its number,
then the answer built from them. The JSON schema lists `quotes` before
`answer`, and constrained decoding generates properties in order, so the
evidence exists before the answer does. Each quote is then verified
mechanically against the chunk it names; one that cannot be found there
is dropped, never shown.

Why: a 2B model asked only for `[n]` markers sometimes decides the
material "doesn't say" when it plainly does (Phase 0: over-refusal was the
main failure on real course files). Pulling quotes first makes it look.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

MIN_QUOTE_WORDS = 3
_ELLIPSIS_RE = re.compile(r"\[?(?:\.\s*){3}\]?|…")

_WORD_RE = re.compile(r"\w+(?:['’]\w+)*")


@dataclass(frozen=True)
class Quote:
    source: int  # 1-based material number
    text: str


def _words(text: str) -> list[str]:
    # Words only: punctuation, hyphens and line breaks drop out, so
    # "pan-\nethnic" in PDF text and "pan-ethnic" in a quote compare equal.
    folded = unicodedata.normalize("NFKC", text).casefold()
    return _WORD_RE.findall(folded.replace("’", "'"))


def quote_matches(quote: str, chunk_text: str) -> bool:
    """True when `quote` appears in `chunk_text` word-for-word. Formatting
    may differ (case, whitespace, punctuation, dashes, line breaks) and an
    ellipsis may skip text, but every quoted word must be there, in order:
    a quote with one fact word changed ("five" for "three") is not
    evidence, so there is deliberately no fuzzy ratio."""
    segments = [_words(part) for part in _ELLIPSIS_RE.split(quote)]
    segments = [segment for segment in segments if segment]
    if sum(len(segment) for segment in segments) < MIN_QUOTE_WORDS:
        return False
    haystack = " " + " ".join(_words(chunk_text)) + " "
    position = 0
    for segment in segments:
        found = haystack.find(" " + " ".join(segment) + " ", position)
        if found < 0:
            return False
        position = found + 1
    return True


def verify(
    quotes: list[Quote], chunk_texts: tuple[str, ...]
) -> tuple[list[Quote], list[Quote]]:
    """Split quotes into (verified, rejected) against the numbered chunks."""
    verified: list[Quote] = []
    rejected: list[Quote] = []
    for quote in quotes:
        in_range = 1 <= quote.source <= len(chunk_texts)
        if in_range and quote_matches(quote.text, chunk_texts[quote.source - 1]):
            verified.append(quote)
        else:
            rejected.append(quote)
    return verified, rejected


def answer_schema(material_count: int) -> dict[str, Any]:
    """`quotes` first on purpose: properties are generated in order."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["quotes", "answer"],
        "properties": {
            "quotes": {
                "type": "array",
                # At least one: with an empty list allowed, MiniCPM5-2B took
                # that exit on every question (eval 2026-09-25: 5/13).
                "minItems": 1,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["source", "quote"],
                    "properties": {
                        "source": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": max(material_count, 1),
                        },
                        "quote": {"type": "string", "minLength": 8, "maxLength": 300},
                    },
                },
            },
            "answer": {"type": "string", "minLength": 1, "maxLength": 4000},
        },
    }


def parse_quotes(raw: Any) -> list[Quote]:
    if not isinstance(raw, list):
        return []
    quotes: list[Quote] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        source, text = item.get("source"), item.get("quote")
        if isinstance(source, int) and isinstance(text, str) and text.strip():
            quotes.append(Quote(source=source, text=text.strip()))
    return quotes


_CITATION_RE = re.compile(r"\[(\d+)\]")


def anchor_citations(answer: str, verified: list[Quote]) -> str:
    """An answer built from verified quotes but written without `[n]`
    markers gets them: the evidence is real, only the formatting was
    skipped. Markers the model did write are left alone."""
    if not verified or _CITATION_RE.search(answer):
        return answer
    numbers = sorted({quote.source for quote in verified})
    return answer.rstrip() + " " + "".join(f"[{n}]" for n in numbers)
