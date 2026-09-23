"""Extraction correctness: locator alignment is a golden-rule-1 concern
(citations point at these offsets), so the tests pin text/locator
agreement, not just shape."""

import io
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from src.backend.common import storage
from src.backend.ingest import chunking
from src.backend.ingest.extract import (
    EmptyExtractionError,
    ScannedPdfNeedsOcrError,
    UnsupportedSourceTypeError,
    _join_pages,
    _line_locators,
    _markdown_locators,
    _pdf_locators,
    extract,
    ocr_extracted_source,
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
    """A .md of notes with no '#' headings yielded ZERO locators, so every
    chunk mapped to none and build_chunks failed the whole ingestion. Plain
    notes are ordinary input, not an edge case."""
    text = "Just notes with no markdown headings.\nA second line of notes.\n"
    locators = _markdown_locators(text)
    assert locators
    spans = chunking.chunk_text(text, locators, max_tokens=64)
    assert spans
    assert all(span.locator_ids for span in spans)


def test_markdown_preamble_is_covered_and_not_miscited() -> None:
    """Text before the first heading was uncovered: long preambles orphaned
    their chunks (hard ingest failure), and a short preamble sharing a chunk
    with the first heading was CITED AS that heading — a wrong citation."""
    preamble = "Lecture notes week one, covering linearity. " * 12
    text = preamble + "\n\n# Chapter 1\n\n" + ("Content under the heading. " * 12)
    locators = _markdown_locators(text)
    spans = chunking.chunk_text(text, locators, max_tokens=64)
    assert all(span.locator_ids for span in spans)

    label_of = {loc.locator_id: loc.label for loc in locators}
    heading_start = text.index("# Chapter 1")
    for span in spans:
        if span.end <= heading_start:
            labels = [label_of[i] for i in span.locator_ids]
            assert all(not label.startswith("§") for label in labels), (
                f"preamble chunk cited as a section it is not in: {labels}"
            )


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
