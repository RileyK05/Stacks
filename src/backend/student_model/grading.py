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
# "no" is shorter than the content-word cutoff and "not" is a stopword, so
# neither survives content_words. A point that differs only by one of them
# would otherwise be marked covered.
_NEGATION = frozenset({"no", "not"})
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
    """Words that carry the claim. Stopwords are dropped, but a number is
    kept even when it is only one or two digits."""
    return [
        word
        for word in _words(text)
        if word not in _STOP and (len(word) > 2 or word.isdigit())
    ]


def _negated_before(words: list[str], index: int) -> bool:
    return any(word in _NEGATION for word in words[max(0, index - 3) : index])


def _phrase_without_negation(answer_words: list[str], point_words: list[str]) -> bool:
    """The point's words in order. A positive point is not covered when
    "no" or "not" sits in the three words before that run."""
    if any(word in _NEGATION for word in point_words):
        return " ".join(point_words) in " ".join(answer_words)
    size = len(point_words)
    for start in range(len(answer_words) - size + 1):
        if answer_words[start : start + size] != point_words:
            continue
        if _negated_before(answer_words, start):
            continue
        return True
    return False


def point_covered(answer: str, point: str) -> bool:
    answer_words = _words(answer)
    point_words = _words(point)
    if not point_words:
        return False
    if _phrase_without_negation(answer_words, point_words):
        return True
    needed = content_words(point)
    negations = [word for word in point_words if word in _NEGATION]
    if not needed and not negations:
        return False
    point_negated = bool(negations)
    for word in needed:
        positions = [i for i, token in enumerate(answer_words) if token == word]
        if not positions:
            return False
        if not point_negated and all(
            _negated_before(answer_words, i) for i in positions
        ):
            return False
    return all(word in set(answer_words) for word in negations)


def missed_points(answer: str, points: list[str]) -> list[str]:
    return [point for point in points if not point_covered(answer, point)]


def short_answer_correct(answer: str, points: list[str]) -> bool:
    if not isinstance(answer, str) or not answer.strip() or not points:
        return False
    return not missed_points(answer, points)
