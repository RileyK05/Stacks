"""Mechanical checks for practice answers.

Multiple choice is an index match. A short answer is correct only when
every required point appears in the student's words. Points are short
claims the generator copied from the cited passage, so the check does
not call a model and does not treat a paraphrase that drops those
claims as complete.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    (
        "a",
        "an",
        "the",
        "of",
        "to",
        "and",
        "or",
        "in",
        "on",
        "for",
        "with",
        "from",
        "by",
        "that",
        "this",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "as",
        "at",
        "it",
        "its",
        "their",
        "his",
        "her",
        "they",
        "them",
        "than",
        "then",
        "not",
        "no",
    )
)


def _words(text: str) -> list[str]:
    return _WORD.findall(text.casefold())


def content_words(text: str) -> list[str]:
    return [word for word in _words(text) if word not in _STOP and len(word) > 2]


def point_covered(answer: str, point: str) -> bool:
    answer_words = _words(answer)
    point_words = _words(point)
    if not point_words:
        return False
    if " ".join(point_words) in " ".join(answer_words):
        return True
    needed = content_words(point)
    if not needed:
        return False
    have = set(content_words(answer))
    return all(word in have for word in needed)


def missed_points(answer: str, points: list[str]) -> list[str]:
    return [point for point in points if not point_covered(answer, point)]


def short_answer_correct(answer: str, points: list[str]) -> bool:
    if not isinstance(answer, str) or not answer.strip() or not points:
        return False
    return not missed_points(answer, points)
