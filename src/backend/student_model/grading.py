"""Mechanical checks for practice answers.

Multiple choice is an index match. A short answer is correct only when
every required point appears in the student's words. Points are short
claims the generator copied from the cited passage, so the check does
not call a model and does not treat a paraphrase that drops those claims
as complete.

Claims keep their roles: the point's words must appear in order, because
"Mexico paid the United States" is not "the United States paid Mexico".
Numbers are canonicalized ("fifteen million", "$15M", "15,000,000" all
read as 15000000) and a capitalised acronym may stand for the words it
abbreviates ("US" covers "United States"), so a correct paraphrase is
not failed for spelling (R4-NEW-c).
"""

from __future__ import annotations

import re
from typing import NamedTuple

_TOKEN = re.compile(r"[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")
_DIGITS = re.compile(r"^(\d+)([kmb])?$", re.IGNORECASE)
_DOTTED = re.compile(r"^(?:[a-z]\.)+[a-z]$", re.IGNORECASE)

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
_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fourty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 10**6, "billion": 10**9}
_SUFFIX_SCALES = {"k": 1000, "m": 10**6, "b": 10**9}


def _words(text: str) -> list[str]:
    return [match.group().casefold() for match in _TOKEN.finditer(text)]


class _Token(NamedTuple):
    word: str
    acronym: bool = False
    new_clause: bool = False


def content_words(text: str) -> list[str]:
    """Words that carry the claim. Stopwords are dropped, but a number is
    kept even when it is only one or two digits."""
    return [
        word
        for word in _words(_THOUSANDS.sub("", text))
        if word not in _STOP and (len(word) > 2 or word.isdigit())
    ]


def _number_at(words: list[str], index: int) -> tuple[str, int] | None:
    """One canonical digit string for the number written at `index`, and how
    many words it used. "fifteen million" and "15M" both read as 15000000."""
    total = 0
    current = 0
    used = False
    cursor = index
    while cursor < len(words):
        word = words[cursor]
        if word == "and" and used:
            following = words[cursor + 1] if cursor + 1 < len(words) else ""
            if following in _NUMBER_WORDS or _DIGITS.match(following):
                cursor += 1
                continue
            break
        digits = _DIGITS.match(word)
        if digits:
            current += int(digits.group(1)) * _SUFFIX_SCALES.get(
                digits.group(2) or "", 1
            )
            used = True
            cursor += 1
            if digits.group(2):
                break
            continue
        value = _NUMBER_WORDS.get(word)
        if value is not None:
            current += value
            used = True
            cursor += 1
            continue
        scale = _SCALES.get(word)
        if scale is None or not used:
            break
        if scale == 100:
            current = (current or 1) * 100
        else:
            total += (current or 1) * scale
            current = 0
        cursor += 1
    if not used:
        return None
    return str(total + current), cursor - index


def _is_acronym(raw: str) -> bool:
    return bool(_DOTTED.fullmatch(raw) or (raw.isalpha() and raw.isupper()))


_CLAUSE_END = re.compile(r"[.!?;:]")
_CLAUSE_BARRIER = frozenset(
    {
        "and",
        "but",
        "or",
        "nor",
        "so",
        "yet",
        "while",
        "whereas",
        "although",
        "though",
        "however",
        "because",
        "unless",
        "until",
        "except",
    }
)


def _tokens(text: str) -> list[_Token]:
    """Word tokens with acronym flags and clause starts, numbers folded."""
    cleaned = _THOUSANDS.sub("", text)
    matches = list(_TOKEN.finditer(cleaned))
    raw = [match.group() for match in matches]
    words = [word.casefold() for word in raw]
    out: list[_Token] = []
    index = 0
    previous_end = 0
    while index < len(words):
        number = _number_at(words, index)
        gap = cleaned[previous_end : matches[index].start()]
        new_clause = bool(_CLAUSE_END.search(gap))
        if number is not None:
            value, used = number
            out.append(_Token(value, False, new_clause))
            previous_end = matches[index + used - 1].end()
            index += used
            continue
        word = words[index]
        letters = "".join(character for character in raw[index] if character.isalpha())
        acronym = 2 <= len(letters) <= 5 and _is_acronym(raw[index])
        out.append(_Token(letters.casefold() if acronym else word, acronym, new_clause))
        previous_end = matches[index].end()
        index += 1
    return out


def _initials_cover(tokens: list[_Token], start: int, letters: str) -> int:
    """Consecutive tokens at `start` whose initials spell `letters`."""
    spelled = ""
    for offset in range(start, min(start + len(letters), len(tokens))):
        spelled += tokens[offset].word[:1]
        if spelled == letters:
            return offset - start + 1
        if not letters.startswith(spelled):
            return 0
    return 0


def _advance(
    answer: list[_Token], a: int, point: list[_Token], p: int
) -> tuple[int, int]:
    """Tokens covered on each side when the two words at these positions
    meet: identical words, or an acronym for the words it abbreviates."""
    word, acronym = answer[a].word, answer[a].acronym
    target, target_acronym = point[p].word, point[p].acronym
    if word == target:
        return 1, 1
    if acronym:
        used = _initials_cover(point, p, word)
        if used:
            return 1, used
    if target_acronym:
        used = _initials_cover(answer, a, target)
        if used:
            return used, 1
    return 0, 0


def _negated_before(tokens: list[_Token], index: int) -> bool:
    """Whether the clause holding `index` denies it. A negation reaches as
    far as its clause does ("there is no evidence that they preserve
    addition"), and no further than a conjunction or a new sentence (CR-25)."""
    cursor = index
    while cursor > 0:
        if tokens[cursor].new_clause or tokens[cursor - 1].word in _CLAUSE_BARRIER:
            break
        cursor -= 1
    return any(token.word in _NEGATION for token in tokens[cursor:index])


def _phrase_without_negation(answer: list[_Token], point: list[_Token]) -> bool:
    """The point's words as one run. A positive point is not covered when
    its clause denies it."""
    if any(token.word in _NEGATION for token in point):
        return " ".join(token.word for token in point) in " ".join(
            token.word for token in answer
        )
    size = len(point)
    for start in range(len(answer) - size + 1):
        if [token.word for token in answer[start : start + size]] != [
            token.word for token in point
        ]:
            continue
        if _negated_before(answer, start):
            continue
        return True
    return False


def _claims_in_order(answer: list[_Token], point: list[_Token]) -> bool:
    """Every needed word of the point, in order. Words the answer may drop
    (articles, auxiliaries) are skipped; a reversed or scattered claim is
    not covered."""
    needed = [
        token for token in point if token.word in _NEGATION or token.word not in _STOP
    ]
    if not needed:
        return False
    negated_point = any(token.word in _NEGATION for token in needed)
    answer_words = [token.word for token in answer]
    matched: list[int] = []
    cursor = 0
    wanted = 0
    while cursor < len(answer) and wanted < len(needed):
        used_answer, used_point = _advance(answer, cursor, needed, wanted)
        if used_point:
            matched.append(cursor)
            wanted += used_point
            cursor += used_answer
        else:
            cursor += 1
    if wanted != len(needed):
        return False
    if negated_point:
        return all(
            word in set(answer_words)
            for word in (token.word for token in needed)
            if word in _NEGATION
        )
    return not any(_negated_before(answer, at) for at in matched)


def point_covered(answer: str, point: str) -> bool:
    answer_tokens = _tokens(answer)
    point_tokens = _tokens(point)
    if not point_tokens:
        return False
    if _phrase_without_negation(answer_tokens, point_tokens):
        return True
    return _claims_in_order(answer_tokens, point_tokens)


def missed_points(answer: str, points: list[str]) -> list[str]:
    return [point for point in points if not point_covered(answer, point)]


def short_answer_correct(answer: str, points: list[str]) -> bool:
    if not isinstance(answer, str) or not answer.strip() or not points:
        return False
    return not missed_points(answer, points)
