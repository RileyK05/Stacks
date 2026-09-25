"""Citations for lines a model wrote but did not cite.

A small model drafting from course material often copies or closely
follows a passage and forgets the "[n]". A new line that takes most of its
meaningful words from one numbered passage gets that passage's number;
anything less clear-cut stays uncited and is counted, so the student sees
how much of a proposal is not tied to a source before accepting it.

Only lines the edit added are considered: text the student wrote is never
given a citation it did not have.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from src.backend.artifacts.content import CITATION_RE
from src.backend.retrieval.funnel import STOPWORDS

_WORD = re.compile(r"[a-z0-9]+")
# A line needs this many meaningful words before overlap says anything.
MIN_WORDS = 5
# Share of the line's meaningful words that must appear in the passage.
MIN_OVERLAP = 0.6
_SKIP = re.compile(r"^\s*(?:#{1,6}\s|```|\||[-*_]{3,}\s*$|\$\$)")


@dataclass(frozen=True)
class Attributed:
    text: str
    cited_now: int
    uncited: int


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2 and w not in STOPWORDS}


def _best_passage(line: str, passages: Sequence[set[str]]) -> int | None:
    words = _words(line)
    if len(words) < MIN_WORDS:
        return None
    best, best_score = None, 0.0
    for index, passage in enumerate(passages):
        score = len(words & passage) / len(words)
        if score > best_score:
            best, best_score = index, score
    return best if best is not None and best_score >= MIN_OVERLAP else None


def _normalised(text: str) -> str:
    return " ".join(_WORD.findall(text.lower()))


_LEADING_NUMBER = re.compile(r"^\s*\[\d+\]\s*")
_LIST_OR_HEADING = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|#)")
# A pasted run: this many consecutive lines copied from one passage.
ECHO_RUN = 3
ECHO_MIN_CHARS = 25


def strip_echo(text: str, material: Sequence[str], before: str = "") -> str:
    """Remove course material the model pasted back instead of writing:
    a line that starts with a material number ("[1] Fraga ...") and copies
    that material, or a run of lines copied verbatim with the PDF's line
    breaks (they end mid-sentence). Quoting a sentence or two stays."""
    passages = [_normalised(passage) for passage in material]
    existing = {line.strip() for line in before.splitlines() if line.strip()}
    lines = text.splitlines()

    def copied(line: str) -> bool:
        plain = _normalised(_LEADING_NUMBER.sub("", line))
        return len(plain) >= ECHO_MIN_CHARS and any(plain in p for p in passages)

    echo = [False] * len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped in existing:
            continue
        if _LEADING_NUMBER.match(line) and copied(line):
            echo[index] = True
    run: list[int] = []
    for index, line in enumerate([*lines, ""]):
        stripped = line.strip()
        wrapped = (
            bool(stripped)
            and stripped not in existing
            and not _LIST_OR_HEADING.match(line)
            and not stripped.endswith((".", "!", "?", ":"))
            and copied(line)
        )
        if wrapped:
            run.append(index)
            continue
        if len(run) >= ECHO_RUN:
            for position in run:
                echo[position] = True
        run = []
    kept = [line for index, line in enumerate(lines) if not echo[index]]
    suffix = "\n" if text.endswith("\n") else ""
    return "\n".join(kept).strip("\n") + suffix


def attach(text: str, material: Sequence[str], before: str = "") -> Attributed:
    """`text` with "[n]" added to new, uncited lines that clearly come from
    material passage n (1-based). Headings, code, tables and rules are
    left alone; so is every line already present in `before`."""
    passages = [_words(passage) for passage in material]
    existing = {line.strip() for line in before.splitlines() if line.strip()}
    out: list[str] = []
    cited_now = uncited = 0
    in_code = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_code = not in_code
        if (
            in_code
            or not stripped
            or stripped in existing
            or _SKIP.match(line)
            or CITATION_RE.search(line)
        ):
            out.append(line)
            continue
        best = _best_passage(stripped, passages)
        if best is None:
            if len(_words(stripped)) >= MIN_WORDS:
                uncited += 1
            out.append(line)
            continue
        cited_now += 1
        out.append(f"{line.rstrip()} [{best + 1}]")
    suffix = "\n" if text.endswith("\n") else ""
    return Attributed(
        text="\n".join(out) + suffix, cited_now=cited_now, uncited=uncited
    )
