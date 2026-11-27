"""The course schedule, read from the uploaded syllabus.

Students prepare from what is in Stacks, so a reading the syllabus assigns
but nobody uploaded is invisible: a student studying "for exam 1" from the
library would miss it without knowing. This module reads the syllabus's
week-by-week outline ("Week 2 (Aug 31) - …" followed by bulleted readings),
matches each reading to the uploaded files by author (and year, pages and
chapters when both name them), and answers two questions deterministically:

- which readings an exam or a set of weeks assigns that are not uploaded
  (`missing_note`, appended to the tutor's reply, never generated), and
- which week "this week" is (`calendar_note`, trusted instruction text with
  today's date and that week's readings).

Everything fails closed to "say nothing": a course with no recognisable
schedule gets no note.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from src.backend.common.db import Connection
from src.backend.retrieval import route

# "Week 2 (Aug 31) - Context, Conquest…": a numbered week, optional dates, a
# dash and its title. Slide footers ("Week 1 (Aug 26)") have no title.
_WEEK = re.compile(
    r"^\s*Week\s+(\d{1,2})\b((?:\s*\([^)]*\))?\s*[-\u2013\u2014]\s*\S.*)$",
    re.MULTILINE | re.IGNORECASE,
)
_BULLET = re.compile(r"^\s*[•\-•●]\s*(.+)$")
_YEAR = re.compile(r"\((\d{4})\)")
_PAGES = re.compile(r"\bpp?\.\s*(\d+)\s*[-–]\s*(\d+)", re.IGNORECASE)
_CHAPTERS = re.compile(
    r"\b(?:Ch(?:apters?)?\.?|Chapter)\s*(\d+)(?:\s*[-–]\s*(\d+))?", re.IGNORECASE
)
_FILE_PAGES = re.compile(r"p{1,2}(\d+)\s*[-_]\s*(\d+)", re.IGNORECASE)
_FILE_CHAPTERS = re.compile(r"ch(\d+)(?:\s*[-_]\s*(\d+))?", re.IGNORECASE)
_FILE_YEAR = re.compile(r"(?<!\d)(1[89]\d\d|20\d\d)(?!\d)")
_EXAM = re.compile(r"\b(FIRST|SECOND|THIRD|FINAL)\s+EXAMINATION\b", re.IGNORECASE)
_MONTHS = {
    m: i
    for i, m in enumerate(
        (
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ),
        start=1,
    )
}
_DATE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})\b"
)
_TERM_YEAR = re.compile(r"\b(?:Fall|Spring|Summer|Winter)\s+(20\d\d)\b", re.IGNORECASE)
_NOT_READINGS = re.compile(
    r"\bno class\b|\bexamination\b|\blecture will be held\b|\bTBD\b", re.IGNORECASE
)


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text)
    return "".join(c for c in plain if not unicodedata.combining(c)).casefold()


@dataclass
class Reading:
    text: str
    authors: frozenset[str]
    year: str | None
    pages: tuple[int, int] | None
    chapters: tuple[int, int] | None
    # Filled by match(): "present", "partial" or "missing", and what part of
    # a partial reading is uploaded.
    status: str = "missing"
    have: str = ""
    source_id: UUID | None = None

    def label(self) -> str:
        """ "Reséndez (2016) The Other Slavery, pp. 1–12"."""
        author = re.split(
            r"\.?\s*\(\d{4}\)|,\s*Ch\b|,\s*pp?\.|\.\s", self.text, maxsplit=1
        )[0].strip(" .,")
        if "," in author:
            surname, rest = author.split(",", 1)
            author = surname + (" et al." if " and " in rest else "")
        title = ""
        dated = re.search(r"\(\d{4}\)\s*[\"“]?([^.:”\"]+)", self.text)
        if dated:
            title = dated.group(1).strip()
            title = title if len(title) <= 50 else title[:47].rsplit(" ", 1)[0] + "…"
        parts = [author + (f" ({self.year})" if self.year else "")]
        if title:
            parts[0] += f" {title}"
        if self.chapters:
            first, last = self.chapters
            parts.append(f"Ch. {first}" if first == last else f"Ch. {first}–{last}")
        if self.pages:
            parts.append(f"pp. {self.pages[0]}–{self.pages[1]}")
        return ", ".join(parts)


@dataclass
class Week:
    number: int
    heading: str
    readings: list[Reading] = field(default_factory=list)
    exam: str | None = None
    start: date | None = None


def _authors(entry: str) -> frozenset[str]:
    before = re.split(r"\(\d{4}\)|,\s*Ch\.|,\s*Ch\b", entry, maxsplit=1)[0]
    words = re.findall(r"[^\W\d_][\w'-]*", before)
    return frozenset(
        _fold(w)
        for w in words
        if len(w) >= 4 and w[0].isupper() and _fold(w) not in {"and", "eds", "with"}
    )


def _span(match: re.Match[str] | None) -> tuple[int, int] | None:
    if match is None:
        return None
    first = int(match.group(1))
    last = int(match.group(2)) if match.group(2) else first
    return (first, last)


def _week_start(heading: str, year: int | None) -> date | None:
    found = _DATE.search(heading)
    if found is None or year is None:
        return None
    try:
        return date(year, _MONTHS[found.group(1)[:3].casefold()], int(found.group(2)))
    except ValueError:
        return None


def parse_schedule(text: str) -> list[Week]:
    """The weeks of a course outline: each "Week N (date) - title" heading
    with the bulleted readings under it, and any examination in that week."""
    term = _TERM_YEAR.search(text)
    year = int(term.group(1)) if term else None
    weeks: list[Week] = []
    matches = list(_WEEK.finditer(text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end]
        week = Week(
            number=int(match.group(1)),
            heading=match.group(0).strip(),
            start=_week_start(match.group(2), year),
        )
        exam = _EXAM.search(body)
        if exam:
            week.exam = exam.group(1).casefold()
        entry: list[str] = []

        def close(lines: list[str], target: Week = week) -> None:
            if not lines:
                return
            joined = " ".join(lines).strip()
            if _NOT_READINGS.search(joined) or not _authors(joined):
                return
            # A reading cites something: a year, chapters or pages.
            if not (
                _YEAR.search(joined)
                or _CHAPTERS.search(joined)
                or _PAGES.search(joined)
            ):
                return
            target.readings.append(
                Reading(
                    text=joined,
                    authors=_authors(joined),
                    year=(_YEAR.search(joined) or [None, None])[1],
                    pages=_span(_PAGES.search(joined)),
                    chapters=_span(_CHAPTERS.search(joined)),
                )
            )

        for line in body.splitlines():
            bullet = _BULLET.match(line)
            if bullet:
                close(entry)
                entry = [bullet.group(1)]
            elif entry and line.strip() and not _WEEK.match(line):
                entry.append(line.strip())
        close(entry)
        weeks.append(week)
    # Keep only a plausible outline: several numbered weeks with readings.
    if sum(1 for w in weeks if w.readings) < 3:
        return []
    return weeks


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def match(weeks: Sequence[Week], filenames: dict[UUID, str]) -> None:
    """Mark each reading present, partial or missing against the uploads."""
    files = [
        (
            source_id,
            route.filename_names(name),
            (_FILE_YEAR.search(name) or [None, None])[1],
            _span(_FILE_PAGES.search(name)),
            _span(_FILE_CHAPTERS.search(name)),
        )
        for source_id, name in filenames.items()
    ]
    for week in weeks:
        for reading in week.readings:
            for source_id, names, year, pages, chapters in files:
                if not reading.authors & names:
                    continue
                if reading.year and year and reading.year != year:
                    continue
                if reading.pages and pages:
                    if not _overlap(reading.pages, pages):
                        continue
                    if pages[0] > reading.pages[0] or pages[1] < reading.pages[1]:
                        reading.status, reading.have = (
                            "partial",
                            f"pp. {pages[0]}–{pages[1]}",
                        )
                        continue
                if reading.chapters and chapters:
                    if not _overlap(reading.chapters, chapters):
                        continue
                    if chapters != reading.chapters:
                        first, last = chapters
                        reading.status = "partial"
                        reading.have = (
                            f"Ch. {first}" if first == last else f"Ch. {first}–{last}"
                        )
                        reading.source_id = source_id
                        continue
                reading.status, reading.have = "present", ""
                reading.source_id = source_id
                break


def course_schedule(conn: Connection, course_id: UUID) -> list[Week]:
    """The schedule of the course's syllabus, matched against its uploads."""
    rows = conn.execute(
        "SELECT s.source_id, s.filename, c.text FROM chunks c "
        "JOIN sources s ON s.source_id = c.source_id "
        "WHERE s.course_id = ? ORDER BY s.source_id, c.chunk_index",
        (course_id,),
    ).fetchall()
    texts: dict[UUID, list[str]] = {}
    filenames: dict[UUID, str] = {}
    for row in rows:
        texts.setdefault(row["source_id"], []).append(row["text"])
        filenames[row["source_id"]] = row["filename"] or ""
    best: list[Week] = []
    for parts in texts.values():
        weeks = parse_schedule("\n".join(parts))
        if sum(len(w.readings) for w in weeks) > sum(len(w.readings) for w in best):
            best = weeks
    if best:
        match(best, filenames)
    return best


_EXAM_ASK = re.compile(
    r"\b(?:(first|second|third|final)\s+(?:exam|examination|midterm|test)"
    r"|(?:exam|examination|midterm|test)\s*(?:#\s*)?(\d|one|two|three|i{1,3})\b"
    r"|(final)\b|(midterm)\b)",
    re.IGNORECASE,
)
_ORDINAL = {
    "first": 1,
    "1": 1,
    "one": 1,
    "i": 1,
    "second": 2,
    "2": 2,
    "two": 2,
    "ii": 2,
    "third": 3,
    "3": 3,
    "three": 3,
    "iii": 3,
}


def exam_weeks(weeks: Sequence[Week], question: str) -> tuple[str, list[Week]] | None:
    """The weeks an exam the question names covers: up to and including the
    week it is held, after the previous exam; the final covers everything."""
    asked = _EXAM_ASK.search(question)
    if asked is None:
        return None
    word = next(g for g in asked.groups() if g)
    exams = [w for w in weeks if w.exam and w.exam != "final"]
    if word.casefold() == "final":
        return "the final exam", list(weeks)
    number = 1 if word.casefold() == "midterm" else _ORDINAL.get(word.casefold())
    if number is None or number > len(exams):
        return None
    held = exams[number - 1]
    previous = exams[number - 2].number if number > 1 else 0
    return (
        f"Exam {number}",
        [w for w in weeks if previous < w.number <= held.number],
    )


def missing_note(
    weeks: Sequence[Week], question: str, asked_weeks: Sequence[int] = ()
) -> str:
    """One line listing what the exam or weeks the question names assign but
    the library does not hold. Empty when everything is uploaded or nothing
    is named."""
    if not weeks:
        return ""
    scope = exam_weeks(weeks, question)
    if scope is None and asked_weeks:
        chosen = [w for w in weeks if w.number in set(asked_weeks)]
        label = (
            f"Week {asked_weeks[0]}"
            if len(asked_weeks) == 1
            else f"Weeks {asked_weeks[0]}–{asked_weeks[-1]}"
        )
        scope = (label, chosen)
    if scope is None:
        return ""
    label, chosen = scope
    gaps: list[str] = []
    for week in chosen:
        for reading in week.readings:
            if reading.status == "missing":
                gaps.append(f"{reading.label()} (Week {week.number})")
            elif reading.status == "partial":
                gaps.append(
                    f"{reading.label()} (Week {week.number}; you have {reading.have})"
                )
    if not gaps:
        return ""
    return (
        f"**Not in your library:** the syllabus assigns these for {label}, so "
        "nothing here covers them:\n"
        + "\n".join(f"- {gap}" for gap in gaps)
        + "\n\nAdd them under Sources to study them here."
    )


_WHEN = re.compile(
    r"\b(?:this|next|last)\s+(?:week|class|lecture|monday|wednesday)\b|\btoday\b"
    r"|\btomorrow\b|\bdue\b|\bupcoming\b|\bcoming up\b|\bright now\b",
    re.IGNORECASE,
)


def calendar_note(weeks: Sequence[Week], question: str, today: date) -> str:
    """Trusted instruction text for "what's due this week": today's date and,
    from the syllabus schedule, the current and next week with their
    readings. Empty when the question is not about the calendar."""
    if not _WHEN.search(question):
        return ""
    lines = [f"Today is {today:%A, %B} {today.day}, {today.year}."]
    dated = [w for w in weeks if w.start is not None]
    current = next(
        (w for w in reversed(dated) if w.start is not None and w.start <= today), None
    )
    following = next((w for w in dated if w.start and w.start > today), None)
    for name, week in (("This week", current), ("Next", following)):
        if week is None:
            continue
        readings = "; ".join(r.label() for r in week.readings) or "no readings listed"
        exam = f" Exam in this week: {week.exam} examination." if week.exam else ""
        lines.append(
            f"{name} by the syllabus: {week.heading}. Readings: {readings}.{exam}"
        )
    if len(lines) == 1:
        return lines[0]
    lines.append(
        "Use these dates for words like this week, next class or upcoming; the "
        "schedule comes from the student's own syllabus."
    )
    return "\n".join(lines)


_STUDY = re.compile(
    r"\b(?:study|studying|prep|prepare|review|revise|cover|covers|covered|readings?"
    r"|material|on the|for the|quiz|test me|practice|guide|outline|flash ?cards?)\b",
    re.IGNORECASE,
)


def about_schedule(question: str, asked_weeks: Sequence[int] = ()) -> bool:
    """Whether the question could need the schedule: it names an exam or
    weeks, or asks about this week. Cheap, so the syllabus is only read when
    it might matter."""
    return bool(_EXAM_ASK.search(question) or asked_weeks or _WHEN.search(question))


def wants_coverage(question: str) -> bool:
    """A request to study for an exam or weeks, not a question about one
    ("when is exam 1?" needs no reading list)."""
    return _STUDY.search(question) is not None


def exam_sources(weeks: Sequence[Week], question: str) -> tuple[UUID, ...]:
    """The uploaded readings an exam the question names covers: what "a
    practice test for exam 1" should be built from. Empty when no exam is
    named or none of its readings is uploaded."""
    scope = exam_weeks(weeks, question)
    if scope is None:
        return ()
    found = {
        reading.source_id
        for week in scope[1]
        for reading in week.readings
        if reading.source_id is not None
    }
    return tuple(sorted(found, key=str))
