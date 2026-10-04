"""The redundant Office readers (plan-notebook.md, "Reading Office
documents — redundant methods").

The package reader is exercised against tiny synthetic OOXML packages built
in-memory (no external libraries, no real course files), the screenshot
reader against the stubbed multimodal seam, and the merge against crafted
agreements. Nothing here writes an Office file.
"""

from __future__ import annotations

import io
import zipfile

import pytest
from src.backend.office_reader import (
    OCR,
    PACKAGE,
    SCRAPE,
    DocumentRead,
    TextUnit,
    UnreadablePackageError,
    merge_reads,
    read_package,
)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _zip(parts: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in parts.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def _docx(*paragraphs: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    return _zip(
        {
            "word/document.xml": (
                f'<w:document xmlns:w="{W_NS}"><w:body>{body}</w:body></w:document>'
            )
        }
    )


def _xlsx(rows: list[list[str]]) -> bytes:
    cells = ""
    for row_index, row in enumerate(rows, start=1):
        row_cells = "".join(
            f'<c r="{chr(65 + col)}{row_index}" t="inlineStr">'
            f"<is><t>{value}</t></is></c>"
            for col, value in enumerate(row)
        )
        cells += f'<row r="{row_index}">{row_cells}</row>'
    return _zip(
        {
            "xl/worksheets/sheet1.xml": (
                f'<worksheet xmlns="{S_NS}"><sheetData>{cells}</sheetData></worksheet>'
            )
        }
    )


def _pptx(slides: list[str]) -> bytes:
    parts: dict[str, str] = {}
    p_ns = "http://schemas.openxmlformats.org/presentationml/2006/main"
    for index, text in enumerate(slides, start=1):
        parts[f"ppt/slides/slide{index}.xml"] = (
            f'<p:sld xmlns:p="{p_ns}" xmlns:a="{A_NS}"><a:t>{text}</a:t></p:sld>'
        )
    return _zip(parts)


def test_word_package_reads_paragraphs_in_order() -> None:
    read = read_package(_docx("First idea.", "Second idea."), kind="word")
    assert read.method == PACKAGE
    assert [unit.text for unit in read.units] == ["First idea.", "Second idea."]


def test_excel_package_reads_cells_with_references() -> None:
    read = read_package(
        _xlsx([["term", "definition"], ["linearity", "preserves"]]), kind="excel"
    )
    assert read.method == PACKAGE
    assert read.units[0].text == "A1=term; B1=definition"
    assert read.units[1].text == "A2=linearity; B2=preserves"


def test_excel_chart_sheet_is_skipped_and_worksheet_order_is_kept() -> None:
    office_rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    parts = {
        "xl/workbook.xml": (
            f'<workbook xmlns="{S_NS}" xmlns:r="{office_rel}"><sheets>'
            '<sheet name="Chart" sheetId="1" r:id="rId1"/>'
            '<sheet name="Second" sheetId="2" r:id="rId2"/>'
            '<sheet name="First" sheetId="3" r:id="rId3"/>'
            "</sheets></workbook>"
        ),
        "xl/_rels/workbook.xml.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'chartsheet" Target="chartsheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'worksheet" Target="worksheets/sheet2.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        ),
        "xl/chartsheets/sheet1.xml": "<chartsheet/>",
        "xl/worksheets/sheet1.xml": (
            f'<worksheet xmlns="{S_NS}"><sheetData><row r="1">'
            '<c r="A1" t="inlineStr"><is><t>first</t></is></c>'
            "</row></sheetData></worksheet>"
        ),
        "xl/worksheets/sheet2.xml": (
            f'<worksheet xmlns="{S_NS}"><sheetData><row r="1">'
            '<c r="A1" t="inlineStr"><is><t>second</t></is></c>'
            "</row></sheetData></worksheet>"
        ),
    }
    read = read_package(_zip(parts), kind="excel")
    assert [unit.text for unit in read.units] == ["A1=second", "A1=first"]
    assert any("chartsheet 'Chart'" in warning for warning in read.warnings)


def test_powerpoint_package_reads_slide_text() -> None:
    read = read_package(_pptx(["Title slide", "Key result"]), kind="powerpoint")
    assert [unit.label for unit in read.units] == ["slide 1", "slide 2"]
    assert read.units[1].text == "Key result"


def test_powerpoint_notes_follow_their_slide_not_the_notes_part_number() -> None:
    # Slide 1's notes live in notesSlide2.xml and slide 2's in notesSlide1.xml;
    # notes must stay interleaved with the slide they belong to.
    parts = {
        "ppt/slides/slide1.xml": f'<root xmlns:a="{A_NS}"><a:t>Slide one</a:t></root>',
        "ppt/slides/slide2.xml": f'<root xmlns:a="{A_NS}"><a:t>Slide two</a:t></root>',
        "ppt/slides/_rels/slide1.xml.rels": (
            '<Relationships><Relationship Id="n1" Type="test/notesSlide" '
            'Target="../notesSlides/notesSlide2.xml"/></Relationships>'
        ),
        "ppt/slides/_rels/slide2.xml.rels": (
            '<Relationships><Relationship Id="n2" Type="test/notesSlide" '
            'Target="../notesSlides/notesSlide1.xml"/></Relationships>'
        ),
        "ppt/notesSlides/notesSlide1.xml": (
            f'<root xmlns:a="{A_NS}"><a:t>Notes two</a:t></root>'
        ),
        "ppt/notesSlides/notesSlide2.xml": (
            f'<root xmlns:a="{A_NS}"><a:t>Notes one</a:t></root>'
        ),
    }
    read = read_package(_zip(parts), kind="powerpoint")
    assert [(unit.label, unit.text) for unit in read.units] == [
        ("slide 1", "Slide one"),
        ("speaker notes 1", "Notes one"),
        ("slide 2", "Slide two"),
        ("speaker notes 2", "Notes two"),
    ]


def test_a_non_zip_is_refused() -> None:
    with pytest.raises(UnreadablePackageError):
        read_package(b"not a zip at all", kind="word")


def test_a_zip_without_the_document_part_is_refused() -> None:
    with pytest.raises(UnreadablePackageError):
        read_package(_zip({"other.txt": "hello"}), kind="word")


def test_unknown_kind_is_refused() -> None:
    with pytest.raises(UnreadablePackageError):
        read_package(_docx("x"), kind="pages")


def test_merge_collapses_near_duplicates_and_reports_agreement() -> None:
    scrape = DocumentRead(
        method=SCRAPE,
        host="powerpoint",
        units=(TextUnit("slide 1", "Linear maps preserve addition"),),
    )
    ocr = DocumentRead(
        method=OCR,
        host="powerpoint",
        units=(
            TextUnit("image 1", "linear maps preserve addition."),
            TextUnit("image 2", "and scaling"),
        ),
    )
    merged = merge_reads([scrape, ocr])
    assert [unit.text for unit in merged.units] == [
        "Linear maps preserve addition",
        "and scaling",
    ]
    by_method = {item.method: item for item in merged.agreement}
    assert by_method[SCRAPE].unique == 1
    assert by_method[OCR].matched == 1
    assert by_method[OCR].unique == 1


def test_merge_prefers_the_longer_reading() -> None:
    scrape = DocumentRead(
        method=SCRAPE, host="word", units=(TextUnit("p", "the full sentence here"),)
    )
    ocr = DocumentRead(
        method=OCR, host="word", units=(TextUnit("i", "the full sentence"),)
    )
    merged = merge_reads([scrape, ocr])
    assert len(merged.units) == 1
    assert merged.units[0].text == "the full sentence here"


def test_merge_collects_warnings_per_method() -> None:
    scrape = DocumentRead(method=SCRAPE, host="word", units=(TextUnit("p", "text"),))
    ocr = DocumentRead(
        method=OCR, host="word", units=(), warnings=("the model returned no text",)
    )
    merged = merge_reads([scrape, ocr])
    assert merged.warnings == ("ocr: the model returned no text",)


def test_merge_of_nothing_is_empty() -> None:
    merged = merge_reads([])
    assert merged.text == ""
    assert merged.agreement == ()


def test_screenshot_reader_transcribes_via_the_ocr_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.backend.common import provider
    from src.backend.office_reader import read_screens

    seen: dict[str, object] = {}

    def _reply(task, endpoint, prompt, *, images=None, response_schema=None):
        seen["task"] = task
        seen["images"] = images
        return ("page one\n\n---\n\npage two", 1, 1)

    monkeypatch.setattr(provider, "_call_provider", _reply)
    from src.backend.common import providers
    from src.backend.common.providers import ProviderChoice, TaskClass

    providers.save_choice(TaskClass.INTERACTIVE, ProviderChoice(preset="local"))
    read = read_screens([b"png-a", b"png-b"], host="powerpoint")
    assert seen["task"] == "ocr"
    assert seen["images"] == [b"png-a", b"png-b"]
    assert [unit.label for unit in read.units] == ["image 1", "image 2"]
    assert read.units[1].text == "page two"


def test_screenshot_reader_reports_ambiguous_page_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.backend.common import provider
    from src.backend.common.provider import GenerationResult
    from src.backend.office_reader.screens import OcrUnavailableError, read_screens

    monkeypatch.setattr(
        provider,
        "generate",
        lambda *args, **kwargs: GenerationResult("merged pages", "test", 1, 1),
    )
    with pytest.raises(OcrUnavailableError, match="boundaries"):
        read_screens([b"png-a", b"png-b"])
