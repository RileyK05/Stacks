"""The course schedule read from a syllabus: what an exam or week assigns
that is not uploaded, and which week "this week" is."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from src.backend.tutor import syllabus

OUTLINE = """POLS 347 Syllabus, Fall 2026
Course Outline & Required Readings
Week 1 (Aug 26) - Conceptualizing Latinx Politics
• García and Sanchez, Ch. 1-3.
Week 2 (Aug 31) - Context, Conquest, and Mestizaje
• Reséndez, Andrés. (2016) The Other Slavery: The Uncovered Story of Indian
Enslavement in America. Boston, MA: Houghton. pp. 1-12.
• Gonzalez, Juan. (2022) Harvest of Empire: A History of Latinos in America.
New York: Penguin. Ch. 1.
• No Class on September 2 (APSA Annual Meeting)
Week 3 (Sep 9) - War and the Creation of U.S. Latinidad
• Gutiérrez, David G. (1995) Walls and Mirrors. Berkeley: University of
California Press. pp. 13-38.
• September 30: FIRST EXAMINATION (In Person, during our regular class meeting)
Week 4 (Sep 14 & 16) - El Movimiento Chicano
• Gutiérrez, David G. (1995) Walls and Mirrors. pp. 39-68.
"""

FILES = {
    "syllabus": "POLS347_Syllabus.pdf",
    "gs": "GarciaSanchez_2021_Ch2.pdf",
    "resendez": "Resendez_2016.pdf",
    "gutierrez": "Gutierrez_1995_p13-38.pdf",
}


def _weeks() -> tuple[list[syllabus.Week], dict[str, object]]:
    ids = {key: uuid4() for key in FILES}
    weeks = syllabus.parse_schedule(OUTLINE)
    syllabus.match(weeks, {ids[key]: name for key, name in FILES.items()})
    return weeks, ids


def test_the_outline_is_read_week_by_week() -> None:
    weeks, _ids = _weeks()
    assert [w.number for w in weeks] == [1, 2, 3, 4]
    assert [len(w.readings) for w in weeks] == [1, 2, 1, 1], "no-class lines skipped"
    assert weeks[2].exam == "first"
    assert weeks[1].start == date(2026, 8, 31)


def test_an_exam_lists_what_is_assigned_but_not_uploaded() -> None:
    """A student preparing for exam 1 from Stacks would have missed half the
    reading without knowing."""
    weeks, _ids = _weeks()
    note = syllabus.missing_note(weeks, "study guide for exam 1")
    assert "Exam 1" in note
    assert "García and Sanchez, Ch. 1–3 (Week 1; you have Ch. 2)" in note
    assert "Gonzalez (2022) Harvest of Empire, Ch. 1 (Week 2)" in note
    assert "Reséndez" not in note and "pp. 13–38" not in note, "uploaded"
    assert "pp. 39–68" not in note, "week 4 is after exam 1"


def test_a_week_uploaded_in_full_needs_no_note() -> None:
    weeks, _ids = _weeks()
    assert syllabus.missing_note(weeks, "quiz me on week 3", [3]) == ""
    assert "pp. 39–68" in syllabus.missing_note(weeks, "quiz me on week 4", [4])


def test_the_exam_is_built_from_its_own_readings() -> None:
    weeks, ids = _weeks()
    assert set(syllabus.exam_sources(weeks, "practice test for exam 1")) == {
        ids["gs"],
        ids["resendez"],
        ids["gutierrez"],
    }
    assert syllabus.exam_sources(weeks, "quiz me on resendez") == ()


def test_this_week_comes_from_the_schedule_and_today() -> None:
    weeks, _ids = _weeks()
    note = syllabus.calendar_note(weeks, "whats due this week", date(2026, 9, 1))
    assert "Today is Tuesday, September 1, 2026." in note
    assert "This week by the syllabus: Week 2 (Aug 31)" in note
    assert "Reséndez (2016) The Other Slavery, pp. 1–12" in note
    assert "Next by the syllabus: Week 3 (Sep 9)" in note
    assert syllabus.calendar_note(weeks, "what does resendez argue", date.today()) == ""


def test_slides_and_prose_are_not_a_schedule() -> None:
    slides = "Week 1 (Aug 26)\n• Attend class\n• Turn in name card\nWeek 1 (Aug 26)"
    assert syllabus.parse_schedule(slides) == []
