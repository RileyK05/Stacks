"""Extraction correctness: locator alignment is a golden-rule-1 concern
(citations point at these offsets), so the tests pin text/locator
agreement, not just shape."""

import io
import json
import math
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from src.backend.common import storage
from src.backend.ingest.extract import (
    EmptyExtractionError,
    ScannedPdfNeedsOcrError,
    UnsupportedSourceTypeError,
    _bounded_render_scale,
    _join_pages,
    _line_locators,
    _markdown_locators,
    _normalize_layout_tables,
    _pdf_locators,
    apply_page_ocr,
    assess_pages,
    choose_page_text,
    clean_text,
    extract,
    ocr_extracted_source,
    page_quality,
    rasterize_pages,
)

MD_TEXT = """# Chapter 1

Intro paragraph about the topic.

## Section A

Details of section A.

```python
# not a heading, this is a comment
code_line = 1
```

## Section B

Details of section B.
"""


def test_pdf_locators_align_with_joined_text() -> None:
    page_texts = ["short page", "a much longer second page with more text", "p3"]
    text = _join_pages(page_texts)
    spans = _pdf_locators(page_texts)
    assert len(spans) == 3
    for index, span in enumerate(spans):
        assert text[span.start : span.end] == page_texts[index], (
            "page locator must slice out exactly its own page text"
        )
    assert spans[0].label == "page 1"
    assert spans[1].label == "page 2"
    assert spans[2].end == len(text)
    assert spans[1].start == spans[0].end + 1


def test_two_column_grading_table_eval() -> None:
    cases = json.loads(Path("data/eval/extraction/table_cases.json").read_text())
    for case in cases["cases"]:
        normalized, has_table = _normalize_layout_tables(case["layout"])
        assert has_table, case["id"]
        for expected in case["expected"]:
            assert expected in normalized, (case["id"], expected)
        assert "100%A 73" not in normalized


def test_justified_prose_is_not_a_table() -> None:
    """Layout mode pads justified lines with wide gaps. The first version
    split every such line into word "cells" (17 of 18 pages of a book
    chapter); gaps that don't line up across rows are not columns."""
    layout = (
        "pinta   de   acuerdo   su   propio   punto   de   vista.\n"
        "Todas  las   perspectivas,  la   abundancia   de   rostros\n"
        "y   figuras    forman   el   caracter   de   lo    que   es\n"
        "significa   ser  parte   de    una   comunidad   que   es\n"
    )
    assert _normalize_layout_tables(layout) == (layout, False)


def test_pdf_locators_drift_regression_unequal_pages() -> None:
    pages = ["x" * 10, "y" * 3000, "z" * 5]
    text = _join_pages(pages)
    spans = _pdf_locators(pages)
    for index, span in enumerate(spans):
        assert text[span.start : span.end] == pages[index]


def test_markdown_locators_skip_code_fences() -> None:
    spans = _markdown_locators(MD_TEXT)
    labels = [span.label for span in spans]
    assert labels == ["§ Chapter 1", "§ Section A", "§ Section B"]
    for span in spans:
        assert span.start < span.end


def test_markdown_sections_slice_correct_text() -> None:
    spans = _markdown_locators(MD_TEXT)
    section_a = next(span for span in spans if span.label == "§ Section A")
    sliced = MD_TEXT[section_a.start : section_a.end]
    assert "Details of section A." in sliced
    assert "Details of section B." not in sliced
    assert "# not a heading" in sliced, "fence body is content, kept in slice"


def test_line_locators_partition_text() -> None:
    text = "line 1\nline 2\nline 3\nline 4\n"
    spans = _line_locators(text, block_size=2)
    assert spans[0].label == "lines 1-2"
    assert spans[1].label == "lines 3-4"
    assert spans[-1].end == len(text)


def test_bom_is_stripped_not_located() -> None:
    course_id = uuid4()
    source_id = uuid4()
    body = "﻿# Heading one\n\nbody".encode()
    assert body.startswith(b"\xef\xbb\xbf")
    path = storage.write_stored(course_id, source_id, body)
    try:
        extracted = extract(
            course_id,
            source_id,
            "text/markdown",
            stored_encoding="identity",
        )
        assert not extracted.text.startswith("\ufeff")
        assert extracted.locators[0].label == "§ Heading one"
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def test_cp1252_fallback_decodes_legacy_notes() -> None:
    course_id = uuid4()
    source_id = uuid4()
    body = "caf\xe9 notes".encode("cp1252")
    path = storage.write_stored(course_id, source_id, body)
    try:
        extracted = extract(
            course_id,
            source_id,
            "text/plain",
            stored_encoding="identity",
        )
        assert extracted.text == "café notes"
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def test_unsupported_mime_raises_at_dispatch() -> None:
    with pytest.raises(UnsupportedSourceTypeError, match="application/zip"):
        extract(uuid4(), uuid4(), "application/zip", stored_encoding="identity")


def test_empty_text_extraction_fails_loudly() -> None:
    course_id = uuid4()
    source_id = uuid4()
    path = storage.write_stored(course_id, source_id, b"   \n \t")
    try:
        with pytest.raises(EmptyExtractionError):
            extract(
                course_id,
                source_id,
                "text/plain",
                stored_encoding="identity",
            )
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def test_scanned_pdf_fails_loudly() -> None:
    """An image-only PDF has no text layer. It must be classified as the
    OCR case (ScannedPdfNeedsOcrError, which inherits EmptyExtractionError
    so old callers still see "no text"), never silently empty."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    course_id = uuid4()
    source_id = uuid4()
    path = storage.write_stored(course_id, source_id, buffer.getvalue())
    try:
        with pytest.raises(ScannedPdfNeedsOcrError):
            extract(
                course_id,
                source_id,
                "application/pdf",
                stored_encoding="identity",
            )
        # Back-compat: it is still an EmptyExtractionError.
        with pytest.raises(EmptyExtractionError):
            extract(
                course_id,
                source_id,
                "application/pdf",
                stored_encoding="identity",
            )
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()


@pytest.mark.parametrize(
    "width,height,scale,limit",
    [(10000, 10000, 2, 8000000), (100, 10000, 2, 100000), (612, 792, 2, 8000000)],
)
def test_render_scale_caps_allocated_bitmap_pixels(width, height, scale, limit) -> None:
    bounded = _bounded_render_scale(width, height, scale, limit)
    assert 0 < bounded <= scale
    assert math.ceil(width * bounded) * math.ceil(height * bounded) <= limit


def test_rasterize_pages_renders_bounded_png_pages() -> None:
    """The OCR path renders pages to PNG, capped at max_pages so a huge
    scan cannot fan out into unbounded billed model calls."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    course_id = uuid4()
    source_id = uuid4()
    path = storage.write_stored(course_id, source_id, buffer.getvalue())
    try:
        pages = rasterize_pages(
            course_id, source_id, "identity", max_pages=2, scale=1.0
        )
        assert len(pages) == 2, "max_pages must cap the render count"
        assert all(page.startswith(b"\x89PNG") for page in pages)
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def test_ocr_extracted_source_aligns_page_citations() -> None:
    """OCR text is joined and located with the exact page builder used for
    text-layer PDFs, so a citation resolves to the page it came from."""
    page_texts = ["first page words", "second page words", "third page"]
    extracted = ocr_extracted_source(page_texts)
    assert extracted.text[extracted.locators[1].start : extracted.locators[1].end] == (
        "second page words"
    )
    assert extracted.locators[1].label == "page 2"


def test_pdf_roundtrip_pages_and_text() -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    course_id = uuid4()
    source_id = uuid4()
    path = storage.write_stored(course_id, source_id, buffer.getvalue())
    try:
        with pytest.raises(EmptyExtractionError):
            extract(
                course_id,
                source_id,
                "application/pdf",
                stored_encoding="identity",
            )
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def test_markdown_without_headings_is_still_grounded() -> None:
    """Plain notes need a source location even without authored headings."""
    text = "Just notes with no markdown headings.\nA second line of notes.\n"
    locators = _markdown_locators(text)
    assert len(locators) == 1
    assert (locators[0].start, locators[0].end) == (0, len(text))


def test_markdown_preamble_is_covered_and_not_miscited() -> None:
    """Text before the first heading was uncovered: long preambles orphaned
    their chunks (hard ingest failure), and a short preamble sharing a chunk
    with the first heading was CITED AS that heading — a wrong citation."""
    preamble = "Lecture notes week one, covering linearity. " * 12
    text = preamble + "\n\n# Chapter 1\n\n" + ("Content under the heading. " * 12)
    locators = _markdown_locators(text)
    heading_start = text.index("# Chapter 1")
    assert locators[0].start == 0
    assert locators[0].end == heading_start
    assert not locators[0].label.startswith("§")
    assert locators[1].start == heading_start
    assert locators[-1].end == len(text)


def test_whitespace_only_markdown_preamble_has_its_own_locator() -> None:
    text = " \t\n\n# Heading\nBody"
    locators = _markdown_locators(text)
    assert locators[0].start == 0
    assert locators[0].end == text.index("# Heading")
    assert not locators[0].label.startswith("§")


def test_pdf_identity_path_reads_through_the_capped_seam() -> None:
    """PDFs always store as identity, and the identity branch of
    _pdf_page_texts used to call path.read_bytes() directly — the one file
    type that always took that path skipped the decompression ceiling that
    every other read goes through. It must read via read_stored, which
    caps identity files at their on-disk size."""
    from pypdf import PdfWriter
    from src.backend.common.storage import DecompressionLimitExceededError

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    pdf_bytes = buffer.getvalue() + b"x" * 64
    course_id = uuid4()
    source_id = uuid4()
    path = storage.write_stored(course_id, source_id, pdf_bytes)
    try:
        original = storage.read_stored

        def capped_read(
            course_id: UUID,
            source_id: UUID,
            stored_encoding: str | None,
            *,
            max_decompressed_bytes: int,
        ):
            return original(
                course_id,
                source_id,
                stored_encoding,
                max_decompressed_bytes=len(pdf_bytes) - 1,
            )

        with (
            patch.object(storage, "read_stored", capped_read),
            pytest.raises(DecompressionLimitExceededError),
        ):
            extract(
                course_id,
                source_id,
                "application/pdf",
                stored_encoding="identity",
            )
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def test_read_decoded_strips_nul_bytes() -> None:
    """Review catch #4: a binary uploaded as text/plain decodes via the
    cp1252 fallback carrying \x00; Postgres TEXT rejects NUL, so the
    chunk insert 500'd. Control bytes are stripped at the decode choke
    point."""
    import gzip as gzip_module

    from src.backend.ingest.extract import read_decoded

    course_id = uuid4()
    source_id = uuid4()
    raw = b"linearity notes\x00with embedded binary\x00\nmore text"
    path = storage.write_stored(course_id, source_id, gzip_module.compress(raw))
    try:
        text = read_decoded(course_id, source_id, "gzip")
        assert "\x00" not in text
        assert "linearity notes" in text
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def _pdf_with_pages(contents: list[str]) -> bytes:
    """A PDF whose page streams are the given content operators.

    The content stream is an indirect object: pypdfium2 ignores a stream
    written inline on the page dictionary.
    """
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()

    def font(base: str) -> DictionaryObject:
        return DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject(base),
                NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
            }
        )

    for content in contents:
        writer.add_blank_page(width=612, height=792)
        page = writer.pages[-1]
        stream = DecodedStreamObject()
        stream.set_data(content.encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(stream)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {
                        NameObject("/F1"): font("/Helvetica"),
                        NameObject("/F2"): font("/Times-Italic"),
                    }
                )
            }
        )
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _show(text: str) -> str:
    return f"BT\n/F1 12 Tf\n72 700 Td\n({text}) Tj\nET\n"


def _stored_pdf(body: bytes) -> tuple[UUID, UUID, Path]:
    course_id = uuid4()
    source_id = uuid4()
    path = storage.write_stored(course_id, source_id, body)
    return course_id, source_id, path


def test_clean_text_preserves_ambiguous_glyph_digits_for_ocr() -> None:
    assert (
        clean_text("of /one.o/eight.o/three.o/six.o")
        == "of /one.o/eight.o/three.o/six.o"
    )
    assert clean_text("of /one.o$/three.o") == "of /one.o$/three.o"
    assert page_quality(clean_text("of /one.o-.")) < 0.35


def test_page_quality_flags_cipher_and_glyph_names_only() -> None:
    cipher = ",N>KMH .B<:GL ;>@:G" * 50
    glyphs = "of /one.o$/three.o " * 30
    english = (
        "The treaty of Guadalupe Hidalgo ended the war and the United States "
        "paid for the land that was ceded in the agreement to Mexico. "
    ) * 3
    spanish = (
        "La historia de la frontera y el pueblo de Texas es la historia de "
        "la comunidad y de la tierra que el pueblo habita. "
    ) * 3
    assert len(cipher) >= 200 and len(glyphs) >= 200
    assert page_quality(cipher) < 0.35
    assert page_quality(glyphs) < 0.35
    assert page_quality(clean_text(glyphs)) < 0.35
    assert page_quality(english) >= 0.35
    assert page_quality(spanish) >= 0.35
    assert page_quality("Hello") == 1.0


def test_page_text_prefers_spaced_text_unless_a_table_was_found() -> None:
    joined = "cedesLas CaliforniasandNuevo"
    spaced = "cedes Las Californias and Nuevo"
    assert choose_page_text(joined, spaced, has_table=False) == spaced
    assert choose_page_text("A | 100%", "A100%", has_table=True) == "A | 100%"
    assert choose_page_text("hello", None, has_table=False) == "hello"
    assert choose_page_text("hello", "", has_table=False) == "hello"


def test_mixed_font_pdf_keeps_the_space_between_runs() -> None:
    """pypdf drops the gap at a font change; pdfium keeps it."""
    body = _pdf_with_pages(
        [
            """BT
/F1 12 Tf
72 700 Td
(cedes) Tj
/F2 12 Tf
4 0 Td
(Las Californias) Tj
/F1 12 Tf
4 0 Td
(and) Tj
/F2 12 Tf
4 0 Td
(Nuevo) Tj
ET
"""
        ]
    )
    course_id, source_id, path = _stored_pdf(body)
    try:
        extracted = extract(
            course_id, source_id, "application/pdf", stored_encoding="identity"
        )
        assert "Californias and Nuevo" in extracted.text
        assert "cedesLas" not in extracted.text
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def test_blank_page_inside_a_text_pdf_is_reported() -> None:
    prose = _show("The treaty ended the war and paid for the land.")
    body = _pdf_with_pages([prose, "", prose])
    course_id, source_id, path = _stored_pdf(body)
    try:
        extracted = extract(
            course_id, source_id, "application/pdf", stored_encoding="identity"
        )
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()
    assert extracted.report is not None
    assert extracted.report.pages_total == 3
    assert extracted.report.pages_empty == 1
    assert extracted.report.ocr_pages[0] == 1


def test_garbled_page_is_queued_after_blank_pages() -> None:
    cipher = _show(",N>KMH .B<:GL ;>@:G" * 50)
    prose = _show("The treaty ended the war and paid for the land.")
    body = _pdf_with_pages([cipher, "", prose])
    course_id, source_id, path = _stored_pdf(body)
    try:
        extracted = extract(
            course_id, source_id, "application/pdf", stored_encoding="identity"
        )
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()
    assert extracted.report is not None
    assert extracted.report.ocr_pages == (0, 1)
    assert extracted.report.pages_low_quality == 1


def test_ambiguous_glyph_page_requires_ocr_instead_of_inventing_digits() -> None:
    line = (
        "February of /one.o/eight.o/three.o/six.o, some Anglo-Texans "
        "and the Mexican troops of the war. "
    )
    body = _pdf_with_pages([_show(line * 6)])
    course_id, source_id, path = _stored_pdf(body)
    try:
        extracted = extract(
            course_id, source_id, "application/pdf", stored_encoding="identity"
        )
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()
    assert "/one.o" in extracted.text
    assert extracted.report is not None
    assert extracted.report.ocr_pages == (0,)


def test_apply_page_ocr_splices_only_the_blank_page() -> None:
    prose = "The treaty ended the war and paid for the land."
    body = _pdf_with_pages([_show(prose), "", _show(prose)])
    course_id, source_id, path = _stored_pdf(body)
    try:
        extracted = extract(
            course_id, source_id, "application/pdf", stored_encoding="identity"
        )
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()
    rescued = "Resendez describes the border after the expedition north."
    updated = apply_page_ocr(extracted, extracted.report.ocr_pages, [rescued])
    assert rescued in updated.text
    assert prose in updated.text
    assert updated.report is not None
    assert updated.report.pages_ocr == 1
    assert updated.report.pages_empty == 0
    assert updated.text[updated.locators[1].start : updated.locators[1].end] == rescued


def test_garbled_pages_are_ordered_ahead_of_blank_pages() -> None:
    report = assess_pages(
        ["", ",N>KMH .B<:GL ;>@:G" * 50, "The treaty of the land. " * 12],
        min_page_chars=20,
        quality_floor=0.35,
    )
    assert report.ocr_pages[0] == 1
    assert 0 in report.ocr_pages
    assert 2 not in report.ocr_pages


def test_low_quality_pages_are_prioritized_before_blank_pages() -> None:
    report = assess_pages(
        ["" for _ in range(45)] + [",N>KMH .B<:GL ;>@:G" * 50 for _ in range(6)],
        min_page_chars=20,
        quality_floor=0.35,
    )
    assert report.ocr_pages[:6] == tuple(range(45, 51))


def test_clean_text_normalizes_line_endings_and_extraction_sentinels() -> None:
    assert (
        clean_text("first\r\nword\ufffe-soft\u00adhyphen") == "first\nword-softhyphen"
    )


def test_office_text_is_normalized_before_locator_offsets(monkeypatch) -> None:
    from src.backend.ingest import office

    course_id, source_id = uuid4(), uuid4()
    path = storage.write_stored(course_id, source_id, b"office fixture")
    monkeypatch.setattr(
        office,
        "docx_text",
        lambda _raw: "Opening\r\nsoft\ufffe-hy\u00adphen\r\n# Heading\r\nbody",
    )
    try:
        extracted = extract(
            course_id,
            source_id,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            stored_encoding="identity",
        )
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()
    assert extracted.text == "Opening\nsoft-hyphen\n# Heading\nbody"
    assert extracted.text[
        extracted.locators[0].start : extracted.locators[0].end
    ].startswith("Opening\nsoft-hyphen")


def test_read_decoded_handles_short_nuls_and_bomless_utf16() -> None:
    from src.backend.ingest.extract import read_decoded

    course_id, source_id = uuid4(), uuid4()
    path = storage.write_stored(course_id, source_id, b"a\x00b")
    try:
        assert read_decoded(course_id, source_id, "identity") == "ab"
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()

    course_id, source_id = uuid4(), uuid4()
    path = storage.write_stored(course_id, source_id, "hi there".encode("utf-16-le"))
    try:
        assert read_decoded(course_id, source_id, "identity") == "hi there"
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def test_cp1252_undefined_bytes_fall_back_without_replacement() -> None:
    from src.backend.ingest.extract import read_decoded

    course_id, source_id = uuid4(), uuid4()
    path = storage.write_stored(course_id, source_id, b"\x81 legacy notes")
    try:
        assert read_decoded(course_id, source_id, "identity") == "\x81 legacy notes"
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def test_rasterize_pages_can_render_a_chosen_page() -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    course_id, source_id, path = _stored_pdf(buffer.getvalue())
    try:
        pages = rasterize_pages(
            course_id,
            source_id,
            "identity",
            max_pages=50,
            scale=1.0,
            pages=[2, 0],
        )
        assert len(pages) == 2
        capped = rasterize_pages(
            course_id, source_id, "identity", max_pages=1, scale=1.0, pages=[2, 0]
        )
        assert len(capped) == 1
        assert all(page.startswith(b"\x89PNG") for page in pages)
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def test_clean_text_makes_extracted_text_storable() -> None:
    """A lone UTF-16 surrogate (broken PDF font map, half an emoji from an
    OCR model) cannot be encoded as UTF-8, and a NUL ends a C string; either
    one used to fail the whole file when its chunks were inserted."""
    from src.backend.ingest.extract import clean_text

    dirty = "a" + chr(0xD800) + "b" + chr(0) + "c ✓"
    cleaned = clean_text(dirty)
    assert cleaned == "a?bc ✓"
    cleaned.encode("utf-8")
    assert ocr_extracted_source([dirty]).text == cleaned
