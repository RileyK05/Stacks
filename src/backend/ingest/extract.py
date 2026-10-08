"""Stage 1-2 handlers: text extraction and per-format locators.

Locators are character offsets into the joined extracted text, and they
are the anchors citations will use — page/section spans must therefore be
built from the exact same join the text uses (`_join_pages`), or every
locator after the first drifts. Markdown sections skip fenced code blocks
(a `#` inside a code fence is content, not a heading). Unsupported mime
types raise `UnsupportedSourceTypeError` at dispatch — nothing silently
decodes a zip as text. Decoding strips the BOM (utf-8-sig) and falls back
to cp1252 for legacy lecture notes, retaining undefined bytes through a
warned latin-1 fallback.
"""

from __future__ import annotations

import codecs
import io
import logging
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import PurePath
from uuid import UUID, uuid4

from src.backend.common import storage
from src.backend.common.lifecycle_config import load_lifecycle_policy

logger = logging.getLogger(__name__)

PAGE_SEPARATOR = "\n"
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_FENCE_RE = re.compile(r"^(?:```|~~~)", re.MULTILINE)

_TEXT_MIME_EXACT = {
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "text/csv",
    "application/json",
    "application/xml",
    "application/yaml",
}
_PDF_MIME = "application/pdf"
_OFFICE = "application/vnd.openxmlformats-officedocument"
_DOCX_MIME = f"{_OFFICE}.wordprocessingml.document"
_PPTX_MIME = f"{_OFFICE}.presentationml.presentation"
_XLSX_MIME = f"{_OFFICE}.spreadsheetml.sheet"
# Layout-mode table detection: how far (in characters) a cell may drift
# between rows and still count as the same column, and the most cells a
# row may have before it looks like spaced-out prose rather than a table.
_TABLE_COLUMN_SLACK = 2
_TABLE_MAX_COLUMNS = 6
# Old-style digits stored as glyph names (`/one.o`, `/one.o$`, `/one.osf`).
# Glyph names can coexist with ambiguous punctuation-to-digit font maps.
# Detect them for OCR; rewriting only the named digits would invent numbers.
_GLYPH_NAME = re.compile(
    r"/(zero|one|two|three|four|five|six|seven|eight|nine)"
    r"\.(?:oldstyle|osf|lf|o)\$?"
)
_STOPWORDS = frozenset(
    {
        "the",
        "of",
        "and",
        "to",
        "in",
        "a",
        "is",
        "that",
        "for",
        "was",
        "de",
        "la",
        "el",
        "y",
    }
)
_PROSE_WORD = re.compile(r"[^\W\d_]{2,}")
_CAMEL_JOIN = re.compile(r"[a-z][A-Z]")

# The upload boundary (api/sources.py) rejects anything outside this set
# BEFORE storage and quota charge — a zip charged against quota then
# failed at extraction was the review's "quota is a one-way ratchet"
# half. Keep in sync with extract()'s dispatch (they share the module so
# drift fails loudly at the dispatch's UnsupportedSourceTypeError).
INGESTABLE_MIME_TYPES = frozenset(
    _TEXT_MIME_EXACT | {_PDF_MIME, _DOCX_MIME, _PPTX_MIME, _XLSX_MIME}
)

# What a browser or webview reports for a picked file is a guess from the
# OS's extension registry: `.md` is usually "" (→ application/octet-stream)
# on Windows, `.csv` is "application/vnd.ms-excel" wherever Excel is
# installed, and some servers add parameters ("text/plain; charset=utf-8").
# Trusting it verbatim rejected ordinary notes files as "unsupported".
SUPPORTED_FILES_HINT = (
    "Supported: PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx), "
    "Markdown, plain text, CSV, JSON, XML and YAML files."
)
_MIME_ALIASES = {
    "application/x-pdf": _PDF_MIME,
    "text/x-csv": "text/csv",
    "application/csv": "text/csv",
    "text/json": "application/json",
    "text/xml": "application/xml",
    "text/yaml": "application/yaml",
    "text/x-yaml": "application/yaml",
    "application/x-yaml": "application/yaml",
}
_EXTENSION_MIME = {
    ".pdf": _PDF_MIME,
    ".docx": _DOCX_MIME,
    ".pptx": _PPTX_MIME,
    ".xlsx": _XLSX_MIME,
    ".txt": "text/plain",
    ".text": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".xml": "application/xml",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
}


def resolve_mime_type(filename: str, declared: str | None) -> str:
    """The MIME type to store and ingest under: the declared one
    (normalized), or — when that is not one we can ingest — the type the
    file's extension names. Returns the normalized declared type when
    neither works, so the caller's rejection names what the client sent."""
    normalized = (declared or "").split(";", 1)[0].strip().lower()
    normalized = _MIME_ALIASES.get(normalized, normalized)
    if normalized in INGESTABLE_MIME_TYPES:
        return normalized
    extension = PurePath(filename.replace("\\", "/")).suffix.lower()
    return _EXTENSION_MIME.get(extension, normalized or "application/octet-stream")


@dataclass(frozen=True)
class ExtractionReport:
    """How much of a PDF's text layer survived extraction.

    `ocr_pages` is garbled pages worst-first, then blank pages.
    `pages_ocr` is how many of those were replaced by a later OCR pass.
    Non-PDF sources leave the report unset.
    """

    pages_total: int
    pages_empty: int
    pages_low_quality: int
    pages_ocr: int = 0
    ocr_pages: tuple[int, ...] = ()


@dataclass(frozen=True)
class ExtractedSource:
    """The full extracted text of a source with its locator map."""

    text: str
    locators: tuple[LocatorSpan, ...]
    page_texts: tuple[str, ...] = ()
    report: ExtractionReport | None = None


@dataclass(frozen=True)
class LocatorSpan:
    """One addressable location inside the extracted text.

    start/end are character offsets into `text` computed with the exact
    same join that produced it; `label` is what citations display.
    """

    locator_id: UUID
    locator_type: str
    start: int
    end: int
    label: str
    description: str | None = None


@dataclass(frozen=True)
class RasterizedPage:
    page_index: int
    image: bytes


class UnsupportedSourceTypeError(RuntimeError):
    def __init__(self, mime_type: str) -> None:
        self.mime_type = mime_type
        super().__init__(f"no text extraction handler for mime type: {mime_type}")


class EmptyExtractionError(RuntimeError):
    """A source yielded no retrievable text (e.g. a scanned image-only
    PDF). Fail the stage loudly — a silent empty knowledge base is worse
    than a failure the operator can see."""

    def __init__(self, source_id: UUID) -> None:
        super().__init__(
            f"source {source_id} produced no extractable text; scanned or "
            "image-only sources need OCR before ingestion"
        )


class ScannedPdfNeedsOcrError(EmptyExtractionError):
    """A PDF with no text layer at all. Distinct from a genuinely empty
    file so the pipeline can route it to the OCR stage instead of failing
    extraction outright. Subclasses EmptyExtractionError so a caller that
    only knows "no text" still treats it as such."""

    def __init__(self, source_id: UUID) -> None:
        self.source_id = source_id
        RuntimeError.__init__(
            self,
            f"source {source_id} has no text layer; it needs OCR",
        )


def read_decoded(
    course_id: UUID,
    source_id: UUID,
    stored_encoding: str | None,
) -> str:
    """Read a stored file back through the capped streaming seam and
    decode it. utf-8-sig strips the Windows BOM; cp1252 covers legacy
    lecture notes; anything else fails the stage."""
    from src.backend.ingest.config import load_ingestion_config

    cap = min(
        load_lifecycle_policy().max_decompressed_bytes,
        load_ingestion_config().text.max_decode_bytes,
    )

    def decode(encoding: str | None) -> str:
        blocks = storage.iter_stored(
            course_id, source_id, stored_encoding, max_decompressed_bytes=cap
        )
        first = next(blocks, b"")
        chosen = encoding
        if chosen is None:
            if first.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
                chosen = "utf-32"
            elif first.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
                chosen = "utf-16"
            else:
                sample = first[:4096]
                bomless_utf16 = _bomless_utf16_encoding(sample)
                if bomless_utf16 is not None:
                    chosen = bomless_utf16
                elif sample.startswith((b"%PDF-", b"PK\x03\x04")) or (
                    len(sample) >= 8 and sample.count(b"\x00") > len(sample) / 10
                ):
                    raise ValueError(
                        "this file contains binary data rather than readable text"
                    )
                else:
                    chosen = "utf-8-sig"
        decoder = codecs.getincrementaldecoder(chosen)(errors="strict")
        try:
            parts = [decoder.decode(first)]
            parts.extend(decoder.decode(block) for block in blocks)
            parts.append(decoder.decode(b"", final=True))
        except UnicodeDecodeError as err:
            if chosen in {"utf-16", "utf-32"}:
                raise ValueError(
                    "this Unicode text file has a damaged encoding"
                ) from err
            raise
        finally:
            blocks.close()
        decoded = "".join(parts)
        # A wide encoding already resolved its bytes: stripping here would
        # drop a character the file really contains (CR-22).
        if chosen in {"utf-16", "utf-32"}:
            return decoded
        return decoded.replace("\x00", "")

    try:
        return decode(None)
    except UnicodeDecodeError:
        try:
            return decode("cp1252")
        except UnicodeDecodeError:
            logger.warning(
                "text source %s contains bytes undefined by cp1252; decoding "
                "those bytes as latin-1",
                source_id,
            )
            return decode("latin-1")


def _bomless_utf16_encoding(sample: bytes) -> str | None:
    if len(sample) < 4:
        return None
    even = sample[0::2]
    odd = sample[1::2]
    even_nuls = even.count(0)
    odd_nuls = odd.count(0)
    if even_nuls >= 2 and even_nuls / len(even) >= 0.5 and odd_nuls / len(odd) <= 0.1:
        return "utf-16-be"
    if odd_nuls >= 2 and odd_nuls / len(odd) >= 0.5 and even_nuls / len(even) <= 0.1:
        return "utf-16-le"
    return None


def _line_of(line_starts: list[int], offset: int) -> int:
    """1-based line number containing `offset` (binary search over the
    cached line-start table)."""
    low, high = 0, len(line_starts) - 1
    while low < high:
        mid = (low + high + 1) // 2
        if line_starts[mid] <= offset:
            low = mid
        else:
            high = mid - 1
    return low + 1


def _line_locators(text: str, *, block_size: int = 80) -> tuple[LocatorSpan, ...]:
    spans: list[LocatorSpan] = []
    line_starts = [0] + [match.end() for match in re.finditer(r"\n", text)]
    # A trailing newline's end offset is the end of the file, not another line.
    if len(line_starts) > 1 and line_starts[-1] == len(text):
        line_starts.pop()
    total_lines = len(line_starts)
    for block_start in range(0, total_lines, block_size):
        block_end = min(block_start + block_size, total_lines)
        char_start = line_starts[block_start]
        char_end = line_starts[block_end] if block_end < total_lines else len(text)
        spans.append(
            LocatorSpan(
                locator_id=uuid4(),
                locator_type="line_range",
                start=char_start,
                end=char_end,
                label=f"lines {block_start + 1}-{block_end}",
            )
        )
    return tuple(spans)


def _mask_code_fences(text: str) -> str:
    """Mask fenced code blocks for the heading scan: every character of
    fence marker lines AND in-fence lines becomes a space, preserving line
    lengths exactly so heading offsets stay aligned with the original
    text (spans slice the original). A `#` inside a fence is content, not
    a heading; the fence body still reaches chunks via the original text."""
    lines = text.split("\n")
    in_fence = False
    fence_marker = ""
    masked: list[str] = []
    for line in lines:
        stripped_line = line.lstrip()
        is_fence = stripped_line.startswith("```") or stripped_line.startswith("~~~")
        if is_fence:
            if not in_fence:
                in_fence = True
                fence_marker = stripped_line[:3]
            elif stripped_line.startswith(fence_marker):
                in_fence = False
            masked.append(" " * len(line))
            continue
        if in_fence:
            masked.append(" " * len(line))
        else:
            masked.append(line)
    return "\n".join(masked)


def _markdown_locators(text: str) -> tuple[LocatorSpan, ...]:
    """Section locators for markdown, with total character coverage.

    Regions outside authored headings use plain-text line-range locators.
    Every character stays addressable, and preambles cite their own lines
    rather than the section that follows them.
    """
    heading_text = _mask_code_fences(text)
    spans: list[LocatorSpan] = []
    line_starts = [0] + [match.end() for match in re.finditer(r"\n", text)]
    headings = list(_HEADING_RE.finditer(heading_text))
    if not headings:
        return _line_locators(text)
    first_start = headings[0].start()
    if first_start > 0:
        spans.extend(
            span for span in _line_locators(text[:first_start]) if span.end > span.start
        )
    for index, match in enumerate(headings):
        char_start = match.start()
        if index + 1 < len(headings):
            char_end = headings[index + 1].start()
        else:
            char_end = len(text)
        start_line = _line_of(line_starts, char_start)
        end_line = _line_of(line_starts, char_end - 1)
        title = match.group(1).strip()
        spans.append(
            LocatorSpan(
                locator_id=uuid4(),
                locator_type="section",
                start=char_start,
                end=char_end,
                label=f"§ {title}",
                description=f"lines {start_line}-{end_line}",
            )
        )
    return tuple(spans)


_PRINTABLE = re.compile(r"[^\x00-\x1f\x7f-\x9f]")


def clean_text(text: str) -> str:
    """Text the database can store. A PDF with a broken font map (or a model
    that answered with half an emoji) yields lone UTF-16 surrogates, which
    cannot be encoded as UTF-8: the insert then failed the whole file at the
    build stage. NUL and extraction sentinels are removed. Broken glyph
    names stay visible for quality detection and OCR."""
    without_controls = (
        text.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u00a0", " ")
        .replace("\ufffe", "")
        .replace("\u00ad", "")
    )
    cleaned = "".join(
        character
        for character in without_controls
        if character in "\t\n" or _PRINTABLE.match(character)
    )
    return cleaned.encode("utf-8", "replace").decode("utf-8")


def page_quality(text: str) -> float:
    """1.0 for a page under 200 characters. Longer pages fall when they
    lack stopwords or are full of `/one.o`-style glyph names."""
    if _GLYPH_NAME.search(text):
        return 0.0
    if len(text) < 200:
        return 1.0
    words = _PROSE_WORD.findall(text.lower())
    word_count = max(1, len(words))
    glyph_penalty = len(_GLYPH_NAME.findall(text)) / word_count
    stop_ratio = sum(word in _STOPWORDS for word in words) / word_count
    alpha_ratio = sum(char.isalpha() or char.isspace() for char in text) / len(text)
    return max(0.0, min(1.0, min(stop_ratio / 0.15, 1.0) * alpha_ratio - glyph_penalty))


def choose_page_text(primary: str, alternate: str | None, *, has_table: bool) -> str:
    """Keep the pypdf text when it found a table, or when pdfium returned
    nothing. Otherwise take the higher quality text, then the one with
    fewer mid-word font joins, then the longer one."""
    if has_table or not alternate:
        return primary
    if _page_rank(alternate) > _page_rank(primary):
        return alternate
    return primary


def _page_rank(text: str) -> tuple[float, int, int]:
    return (
        page_quality(text),
        -len(_CAMEL_JOIN.findall(text)),
        len(text.strip()),
    )


def _text_limits() -> tuple[int, float]:
    from src.backend.ingest.config import load_ingestion_config

    policy = load_ingestion_config().text
    return policy.min_page_chars, policy.quality_floor


def assess_pages(
    page_texts: Sequence[str], *, min_page_chars: int, quality_floor: float
) -> ExtractionReport:
    """Prioritize known garbling before blank pages when OCR is capped."""
    empty: list[int] = []
    low: list[tuple[float, int]] = []
    for index, text in enumerate(page_texts):
        if len(text.strip()) < min_page_chars:
            empty.append(index)
            continue
        score = page_quality(text)
        if score < quality_floor:
            low.append((score, index))
    low.sort()
    return ExtractionReport(
        pages_total=len(page_texts),
        pages_empty=len(empty),
        pages_low_quality=len(low),
        ocr_pages=tuple([index for _score, index in low] + empty),
    )


def _join_pages(page_texts: list[str]) -> str:
    """The one join the locators and the text share. Any change here must
    keep `_pdf_locators` in lockstep — the separator is what keeps page
    offsets aligned (citation alignment is a golden-rule-1 concern)."""
    return PAGE_SEPARATOR.join(page_texts)


def _pdf_locators(
    page_texts: list[str],
    *,
    locator_type: str = "page",
    labels: list[str] | None = None,
) -> tuple[LocatorSpan, ...]:
    spans: list[LocatorSpan] = []
    offset = 0
    for index, page_text in enumerate(page_texts):
        end = offset + len(page_text)
        spans.append(
            LocatorSpan(
                locator_id=uuid4(),
                locator_type=locator_type,
                start=offset,
                end=end,
                label=labels[index] if labels else f"page {index + 1}",
            )
        )
        offset = end + len(PAGE_SEPARATOR)
    return tuple(spans)


def extract(
    course_id: UUID,
    source_id: UUID,
    mime_type: str,
    *,
    stored_encoding: str | None,
    raw_pdf_bytes: bytes | None = None,
) -> ExtractedSource:
    """Extract text + locators for a stored source. Dispatches on the
    whitelist: PDF pages via pypdf, markdown sections (fence-aware), the
    listed text mimes as line ranges. Anything else raises
    UnsupportedSourceTypeError. Raises EmptyExtractionError when a source
    yields no text — silent empties are not acceptable."""
    if mime_type == _PDF_MIME:
        page_texts, report = _pdf_page_texts(
            course_id, source_id, stored_encoding, raw_pdf_bytes
        )
        if not any(page_text.strip() for page_text in page_texts):
            # No text layer: this is the OCR case, not an empty file. The
            # pipeline routes it to the ocr stage; if OCR is unavailable
            # the stage fails loudly there with an actionable message.
            raise ScannedPdfNeedsOcrError(source_id)
        return _source_from_pages(page_texts, report)
    if mime_type in _TEXT_MIME_EXACT:
        text = clean_text(read_decoded(course_id, source_id, stored_encoding))
        if not text.strip():
            raise EmptyExtractionError(source_id)
        if mime_type in ("text/markdown", "text/x-markdown"):
            locators = _markdown_locators(text)
        else:
            locators = _line_locators(text)
        return ExtractedSource(text=text, locators=locators)
    if mime_type in (_DOCX_MIME, _PPTX_MIME, _XLSX_MIME):
        return _extract_office(course_id, source_id, mime_type, stored_encoding)
    raise UnsupportedSourceTypeError(mime_type)


def _extract_office(
    course_id: UUID,
    source_id: UUID,
    mime_type: str,
    stored_encoding: str | None,
) -> ExtractedSource:
    from src.backend.ingest import office

    raw = read_pdf_bytes(course_id, source_id, stored_encoding)
    if mime_type == _DOCX_MIME:
        text = clean_text(office.docx_text(raw))
        if not text.strip():
            raise EmptyExtractionError(source_id)
        return ExtractedSource(text=text, locators=_markdown_locators(text))
    read_pages = office.pptx_pages if mime_type == _PPTX_MIME else office.xlsx_pages
    pages = read_pages(raw)
    if not any(text.strip() for _label, text in pages):
        raise EmptyExtractionError(source_id)
    page_texts = [clean_text(text) for _label, text in pages]
    return ExtractedSource(
        text=_join_pages(page_texts),
        locators=_pdf_locators(
            page_texts,
            locator_type="slide" if mime_type == _PPTX_MIME else "sheet",
            labels=[label for label, _text in pages],
        ),
    )


def viewer_text(
    course_id: UUID, source_id: UUID, mime_type: str, stored_encoding: str | None
) -> str | None:
    """The readable text of a source whose original bytes are not text (an
    Office file), exactly as ingestion saw it, so a cited passage can be
    found in it. None for formats the viewer shows as they are."""
    if mime_type not in (_DOCX_MIME, _PPTX_MIME, _XLSX_MIME):
        return None
    return _extract_office(course_id, source_id, mime_type, stored_encoding).text


def read_pdf_bytes(
    course_id: UUID, source_id: UUID, stored_encoding: str | None
) -> bytes:
    """A stored PDF's bytes through the decompression-capped seam."""
    return storage.read_stored(
        course_id,
        source_id,
        stored_encoding,
        max_decompressed_bytes=load_lifecycle_policy().max_decompressed_bytes,
    )


def _pdf_page_texts(
    course_id: UUID,
    source_id: UUID,
    stored_encoding: str | None,
    raw_pdf_bytes: bytes | None,
) -> tuple[list[str], ExtractionReport]:
    if raw_pdf_bytes is not None:
        raw = raw_pdf_bytes
    else:
        # Every read goes through the capped seam regardless of stored
        # encoding: read_stored's identity branch applies the ceiling
        # itself (review catch #3's PDF fix — the branches were
        # character-for-character identical and are collapsed here).
        raw = storage.read_stored(
            course_id,
            source_id,
            stored_encoding,
            max_decompressed_bytes=load_lifecycle_policy().max_decompressed_bytes,
        )
    pypdf_pages = _pypdf_pages(raw)
    pdfium_pages = _pdfium_texts(raw)
    chosen: list[str] = []
    for index, (primary, has_table) in enumerate(pypdf_pages):
        alternate = None
        if pdfium_pages is not None and index < len(pdfium_pages):
            alternate = pdfium_pages[index]
        chosen.append(choose_page_text(primary, alternate, has_table=has_table))
    min_chars, floor = _text_limits()
    return chosen, assess_pages(chosen, min_page_chars=min_chars, quality_floor=floor)


def _pypdf_pages(raw: bytes) -> list[tuple[str, bool]]:
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(raw))
    pages: list[tuple[str, bool]] = []
    for page in reader.pages:
        plain = clean_text(page.extract_text() or "")
        if not plain.strip():
            pages.append((plain, False))
            continue
        layout = clean_text(page.extract_text(extraction_mode="layout") or "")
        normalized, has_table = _normalize_layout_tables(layout)
        pages.append((normalized if has_table else plain, has_table))
    return pages


def _pdfium_texts(raw: bytes) -> list[str] | None:
    """Per-page text from pypdfium2, or None when it cannot read the file.

    A failure here keeps the pypdf text. It must not fail the source:
    pdfium is the spacing candidate, not the only reader.
    """
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(io.BytesIO(raw))
    except Exception:
        logger.exception("pypdfium2 could not open the PDF; using pypdf text")
        return None
    try:
        texts: list[str] = []
        for index in range(len(pdf)):
            page = pdf[index]
            textpage = None
            try:
                textpage = page.get_textpage()
                texts.append(clean_text(textpage.get_text_range() or ""))
            finally:
                if textpage is not None:
                    textpage.close()
                page.close()
        return texts
    except Exception:
        logger.exception("pypdfium2 text extraction failed; using pypdf text")
        return None
    finally:
        pdf.close()


def _source_from_pages(
    page_texts: list[str], report: ExtractionReport
) -> ExtractedSource:
    return ExtractedSource(
        text=_join_pages(page_texts),
        locators=_pdf_locators(page_texts),
        page_texts=tuple(page_texts),
        report=report,
    )


def _normalize_layout_tables(layout: str) -> tuple[str, bool]:
    """Make repeated visual columns explicit before chunking PDF text.

    pypdf's plain mode joins adjacent table cells (``100%A 73% C``).
    Layout mode preserves their horizontal gap. A table is a run of at
    least three rows with the same few cells starting at the same columns.
    Justified prose also has wide gaps, but they fall in different places
    on every line, so it stays untouched.
    """
    lines = [line.rstrip() for line in layout.splitlines()]
    cells: list[list[str]] = []
    starts: list[list[int]] = []
    for line in lines:
        found = list(re.finditer(r"\S+(?: {1,2}\S+)*", line))
        cells.append([match.group() for match in found])
        starts.append([match.start() for match in found])

    def aligned(first: int, other: int) -> bool:
        return len(starts[other]) == len(starts[first]) and all(
            abs(a - b) <= _TABLE_COLUMN_SLACK
            for a, b in zip(starts[first], starts[other], strict=True)
        )

    table_rows: set[int] = set()
    start = 0
    while start < len(lines):
        if not 2 <= len(cells[start]) <= _TABLE_MAX_COLUMNS:
            start += 1
            continue
        end = start + 1
        while end < len(lines) and aligned(start, end):
            end += 1
        if end - start >= 3:
            table_rows.update(range(start, end))
            start = end
        else:
            start += 1
    if not table_rows:
        return layout, False
    normalized: list[str] = []
    for index, line in enumerate(lines):
        if index in table_rows:
            fields = [re.sub(r"%(?=[A-Za-z])", "% ", cell) for cell in cells[index]]
            normalized.append(re.sub(r" {2,}", " ", " | ".join(fields)))
        else:
            # Layout mode pads words to their printed positions.
            normalized.append(re.sub(r" {2,}", " ", line.strip()))
    return "\n".join(normalized), True


def rasterize_pages_with_ids(
    course_id: UUID,
    source_id: UUID,
    stored_encoding: str | None,
    *,
    max_pages: int,
    scale: float,
    pages: Sequence[int] | None = None,
    max_pixels: int = 8_000_000,
) -> list[RasterizedPage]:
    """Render a PDF's pages to PNG bytes for the multimodal OCR model.

    Bounded by construction: at most `max_pages` are rendered (a 500-page
    scan must not fan out into 500 model calls), and the source is read
    back through the same capped seam every other read uses. pypdfium2 is
    used (Apache/BSD licensed, no system binary) rather than a renderer
    that would be AGPL or need an external install.
    """
    import pypdfium2 as pdfium

    raw = storage.read_stored(
        course_id,
        source_id,
        stored_encoding,
        max_decompressed_bytes=load_lifecycle_policy().max_decompressed_bytes,
    )
    pdf = pdfium.PdfDocument(io.BytesIO(raw))
    try:
        if pages is None:
            indexes: Sequence[int] = range(min(len(pdf), max_pages))
        else:
            indexes = [index for index in pages if 0 <= index < len(pdf)][:max_pages]
        renders: list[RasterizedPage] = []
        for index in indexes:
            page = pdf[index]
            try:
                width, height = page.get_size()
                render_scale = _bounded_render_scale(width, height, scale, max_pixels)
                bitmap = page.render(scale=render_scale)
                try:
                    with bitmap.to_pil() as image, io.BytesIO() as buffer:
                        image.save(buffer, format="PNG")
                        renders.append(RasterizedPage(index, buffer.getvalue()))
                finally:
                    bitmap.close()
            finally:
                page.close()
        return renders
    finally:
        pdf.close()


def _bounded_render_scale(
    width: float, height: float, scale: float, max_pixels: int
) -> float:
    if (
        not all(math.isfinite(value) and value > 0 for value in (width, height, scale))
        or max_pixels < 1
    ):
        raise ValueError("PDF page dimensions or OCR rendering limits are invalid")
    scale = min(scale, math.sqrt(max_pixels / (width * height)))
    while math.ceil(width * scale) * math.ceil(height * scale) > max_pixels:
        scale *= 0.99
    return scale


def pdf_page_count(
    course_id: UUID, source_id: UUID, stored_encoding: str | None
) -> int:
    import pypdfium2 as pdfium

    raw = storage.read_stored(
        course_id,
        source_id,
        stored_encoding,
        max_decompressed_bytes=load_lifecycle_policy().max_decompressed_bytes,
    )
    pdf = pdfium.PdfDocument(io.BytesIO(raw))
    try:
        return len(pdf)
    finally:
        pdf.close()


def pdf_page_plain_text(raw: bytes) -> list[str]:
    """Per-page text from a PDF's text layer. Empty strings are pages with no text."""
    return [text for text, _has_table in _pypdf_pages(raw)]


def rasterize_pdf_bytes(
    raw: bytes,
    *,
    max_pages: int,
    scale: float,
    pages: Sequence[int] | None = None,
    max_pixels: int = 8_000_000,
) -> list[RasterizedPage]:
    """Render PDF bytes that are not a stored course source.

    Used for an uploaded quiz that is read once and never indexed.
    """
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(io.BytesIO(raw))
    try:
        if pages is None:
            indexes: Sequence[int] = range(min(len(pdf), max_pages))
        else:
            indexes = [index for index in pages if 0 <= index < len(pdf)][:max_pages]
        renders: list[RasterizedPage] = []
        for index in indexes:
            page = pdf[index]
            try:
                width, height = page.get_size()
                render_scale = _bounded_render_scale(width, height, scale, max_pixels)
                bitmap = page.render(scale=render_scale)
                try:
                    with bitmap.to_pil() as image, io.BytesIO() as buffer:
                        image.save(buffer, format="PNG")
                        renders.append(RasterizedPage(index, buffer.getvalue()))
                finally:
                    bitmap.close()
            finally:
                page.close()
        return renders
    finally:
        pdf.close()


def rasterize_pages(
    course_id: UUID,
    source_id: UUID,
    stored_encoding: str | None,
    *,
    max_pages: int,
    scale: float,
    pages: Sequence[int] | None = None,
) -> list[bytes]:
    """Image-only compatibility wrapper around the identity-preserving renderer."""
    return [
        page.image
        for page in rasterize_pages_with_ids(
            course_id,
            source_id,
            stored_encoding,
            max_pages=max_pages,
            scale=scale,
            pages=pages,
        )
    ]


def ocr_extracted_source(page_texts: list[str]) -> ExtractedSource:
    """Build an ExtractedSource from per-page OCR output, using the exact
    same page join and locator builder as a text-layer PDF so OCR
    citations align identically."""
    cleaned = [clean_text(page_text) for page_text in page_texts]
    min_chars, floor = _text_limits()
    report = assess_pages(cleaned, min_page_chars=min_chars, quality_floor=floor)
    filled = sum(1 for text in cleaned if text.strip())
    return _source_from_pages(cleaned, replace(report, pages_ocr=filled, ocr_pages=()))


def apply_page_ocr(
    extracted: ExtractedSource,
    page_indexes: Sequence[int],
    recognized: Sequence[str],
) -> ExtractedSource:
    """Splice recognized text into the blank or garbled pages it belongs to.

    An empty recognition leaves that page's text layer in place. Locators
    are rebuilt from the same join as a first extraction.
    """
    texts = list(extracted.page_texts)
    replaced = 0
    for index, text in zip(page_indexes, recognized, strict=False):
        if not 0 <= index < len(texts):
            continue
        cleaned = clean_text(text)
        if not cleaned.strip():
            continue
        texts[index] = cleaned
        replaced += 1
    min_chars, floor = _text_limits()
    report = assess_pages(texts, min_page_chars=min_chars, quality_floor=floor)
    previous = extracted.report.pages_ocr if extracted.report else 0
    return _source_from_pages(texts, replace(report, pages_ocr=previous + replaced))
