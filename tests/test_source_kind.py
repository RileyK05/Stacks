from pathlib import Path

from pypdf import PdfWriter
from src.backend.common.schemas.base import SourceType
from src.backend.ingest.extract import _PPTX_MIME
from src.backend.ingest.source_kind import infer_source_type, sniff_source_type


def test_infer_source_type_from_deck_shape_name_and_first_page() -> None:
    assert infer_source_type("week.pptx", _PPTX_MIME) is SourceType.SLIDES
    assert infer_source_type("syllabus.pptx", "application/octet-stream") is (
        SourceType.SLIDES
    )
    assert (
        infer_source_type("packet.pdf", "application/pdf", page_sizes=[(960, 540)])
        is SourceType.SLIDES
    )
    assert (
        infer_source_type("packet.pdf", "application/pdf", page_sizes=[(720, 540)])
        is SourceType.NOTES
    )
    assert (
        infer_source_type(
            "POLS347_Syllabus.pdf", "application/pdf", page_sizes=[(612, 792)]
        )
        is SourceType.SYLLABUS
    )
    assert (
        infer_source_type(
            "week2.pdf",
            "application/pdf",
            first_page_text="Course syllabus\nFall 2024",
            page_sizes=[(612, 792)],
        )
        is SourceType.SYLLABUS
    )
    assert infer_source_type("week2.pdf", "application/pdf") is SourceType.NOTES


def test_sniff_reads_a_widescreen_pdf(tmp_path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=960, height=540)
    path = tmp_path / "deck.pdf"
    with path.open("wb") as handle:
        writer.write(handle)
    assert sniff_source_type(path, "deck.pdf", "application/pdf") is SourceType.SLIDES

    letter = PdfWriter()
    letter.add_blank_page(width=612, height=792)
    letter_path = tmp_path / "POLS_Syllabus.pdf"
    with letter_path.open("wb") as handle:
        letter.write(handle)
    assert sniff_source_type(letter_path, letter_path.name, "application/pdf") is (
        SourceType.SYLLABUS
    )


def test_unreadable_pdf_falls_through_to_the_filename(tmp_path: Path) -> None:
    path = tmp_path / "notes.pdf"
    path.write_bytes(b"not a pdf")
    assert sniff_source_type(path, "notes.pdf", "application/pdf") is SourceType.NOTES
    assert sniff_source_type(path, "Syllabus.pdf", "application/pdf") is (
        SourceType.SYLLABUS
    )
