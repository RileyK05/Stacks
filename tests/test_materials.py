"""Draft structure (tutor/materials.py): heading handling and title bounds."""

from src.backend.tutor.materials import (
    DeckDraft,
    DocumentDraft,
    Section,
    Slide,
    has_body,
)


def test_paragraph_starting_with_heading_marker_is_body() -> None:
    assert has_body("### Key term – definition [1]")


def test_heading_only_line_is_not_body() -> None:
    assert not has_body("# Notes", "Notes")


def test_horizontal_rule_is_not_body() -> None:
    assert not has_body("---")


def test_placeholder_only_is_not_body() -> None:
    assert not has_body("content")
    assert not has_body("markdown")


def test_section_preserves_numbered_heading_text() -> None:
    section = Section(
        heading="#1 Priority: land", paragraphs=["The land was the key issue [1]."]
    )
    assert (
        section.markdown() == "## #1 Priority: land\n\nThe land was the key issue [1]."
    )


def test_section_strips_real_heading_marker() -> None:
    section = Section(heading="## Notes", paragraphs=["A note [1]."])
    assert section.markdown() == "## Notes\n\nA note [1]."


def test_slide_preserves_numbered_title_text() -> None:
    slide = Slide(
        title="#1 Priority: land", paragraphs=["The land was the key issue [1]."]
    )
    assert slide.markdown() == "# #1 Priority: land\n\nThe land was the key issue [1]."


def test_document_title_is_truncated_not_rejected() -> None:
    title = "A" * 200
    draft = DocumentDraft(
        type="document",
        title=title,
        sections=[Section(heading="Notes", paragraphs=["A note [1]."])],
        sources=[1],
    )
    assert len(draft.title) == 120
    assert draft.workspace()["title"] == "A" * 120


def test_deck_title_is_truncated_not_rejected() -> None:
    title = "B" * 200
    draft = DeckDraft(
        type="slides",
        title=title,
        slides=[Slide(title="Overview", paragraphs=["A fact [1]."])],
        sources=[1],
    )
    assert len(draft.title) == 120
