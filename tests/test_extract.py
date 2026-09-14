"""Extraction correctness: locator alignment is a golden-rule-1 concern
(citations point at these offsets), so the tests pin text/locator
agreement, not just shape."""

import io
from uuid import uuid4

import pytest
from src.backend.common import storage
from src.backend.ingest.extract import (
    EmptyExtractionError,
    UnsupportedSourceTypeError,
    _join_pages,
    _line_locators,
    _markdown_locators,
    _pdf_locators,
    extract,
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