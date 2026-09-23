"""Stage 1-2 handlers: text extraction and per-format locators.

Locators are character offsets into the joined extracted text, and they
are the anchors citations will use — page/section spans must therefore be
built from the exact same join the text uses (`_join_pages`), or every
locator after the first drifts. Markdown sections skip fenced code blocks
(a `#` inside a code fence is content, not a heading). Unsupported mime
types raise `UnsupportedSourceTypeError` at dispatch — nothing silently
decodes a zip as text. Decoding strips the BOM (utf-8-sig) and falls back
to cp1252 for legacy lecture notes before failing.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from src.backend.common import storage
from src.backend.common.lifecycle_config import load_lifecycle_policy

if TYPE_CHECKING:
    pass

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

# The upload boundary (api/sources.py) rejects anything outside this set
# BEFORE storage and quota charge — a zip charged against quota then
# failed at extraction was the review's "quota is a one-way ratchet"
# half. Keep in sync with extract()'s dispatch (they share the module so
# drift fails loudly at the dispatch's UnsupportedSourceTypeError).
INGESTABLE_MIME_TYPES = frozenset(_TEXT_MIME_EXACT | {_PDF_MIME})


@dataclass(frozen=True)
class ExtractedSource:
    """The full extracted text of a source with its locator map."""

    text: str
    locators: tuple[LocatorSpan, ...]


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
    raw = storage.read_stored(
        course_id,
        source_id,
        stored_encoding,
        max_decompressed_bytes=load_lifecycle_policy().max_decompressed_bytes,
    )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    # Postgres TEXT rejects NUL outright (storage.py documents the same
    # hazard for filenames): a binary uploaded as text/plain decodes via
    # the cp1252 fallback carrying \x00, turning the extract stage into
    # a NotNullViolation 500 inside the chunk insert. Control bytes carry
    # no citable content; drop them at the decode choke point.
    return text.replace("\x00", "")


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
        is_fence = stripped_line.startswith("```") or stripped_line.startswith(
            "~~~"
        )
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

    Headings alone do not cover the whole document: a file with no headings
    yields no locators at all, and a file with a preamble before its first
    heading leaves that preamble uncovered. Both matter because build_chunks
    rejects any chunk that maps to no locator ("citation grounding is
    mandatory") — so an ordinary .md of notes would fail ingestion outright.
    Worse, an uncovered preamble that shares a chunk with the first heading
    gets CITED as that heading, which is a wrong citation rather than a
    missing one.

    So any region no heading covers falls back to the same line-range
    locators plain text uses: every character stays addressable, and
    preamble text is cited as lines rather than as somebody else's section.
    """
    heading_text = _mask_code_fences(text)
    spans: list[LocatorSpan] = []
    line_starts = [0] + [match.end() for match in re.finditer(r"\n", text)]
    headings = list(_HEADING_RE.finditer(heading_text))
    if not headings:
        return _line_locators(text)
    first_start = headings[0].start()
    if text[:first_start].strip():
        spans.extend(
            span
            for span in _line_locators(text[:first_start])
            if span.end > span.start
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


def _join_pages(page_texts: list[str]) -> str:
    """The one join the locators and the text share. Any change here must
    keep `_pdf_locators` in lockstep — the separator is what keeps page
    offsets aligned (citation alignment is a golden-rule-1 concern)."""
    return PAGE_SEPARATOR.join(page_texts)


def _pdf_locators(page_texts: list[str]) -> tuple[LocatorSpan, ...]:
    spans: list[LocatorSpan] = []
    offset = 0
    for index, page_text in enumerate(page_texts):
        end = offset + len(page_text)
        spans.append(
            LocatorSpan(
                locator_id=uuid4(),
                locator_type="page",
                start=offset,
                end=end,
                label=f"page {index + 1}",
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
        page_texts = _pdf_page_texts(
            course_id, source_id, stored_encoding, raw_pdf_bytes
        )
        if not any(page_text.strip() for page_text in page_texts):
            # No text layer: this is the OCR case, not an empty file. The
            # pipeline routes it to the ocr stage; if OCR is unavailable
            # the stage fails loudly there with an actionable message.
            raise ScannedPdfNeedsOcrError(source_id)
        return ExtractedSource(
            text=_join_pages(page_texts),
            locators=_pdf_locators(page_texts),
        )
    if mime_type in _TEXT_MIME_EXACT:
        text = read_decoded(course_id, source_id, stored_encoding)
        if not text.strip():
            raise EmptyExtractionError(source_id)
        if mime_type in ("text/markdown", "text/x-markdown"):
            locators = _markdown_locators(text)
        else:
            locators = _line_locators(text)
        return ExtractedSource(text=text, locators=locators)
    raise UnsupportedSourceTypeError(mime_type)


def _pdf_page_texts(
    course_id: UUID,
    source_id: UUID,
    stored_encoding: str | None,
    raw_pdf_bytes: bytes | None,
) -> list[str]:
    import pypdf

    if raw_pdf_bytes is not None:
        reader = pypdf.PdfReader(io.BytesIO(raw_pdf_bytes))
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
        reader = pypdf.PdfReader(io.BytesIO(raw))
    return [page.extract_text() or "" for page in reader.pages]


def rasterize_pages(
    course_id: UUID,
    source_id: UUID,
    stored_encoding: str | None,
    *,
    max_pages: int,
    scale: float,
) -> list[bytes]:
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
        page_count = min(len(pdf), max_pages)
        renders: list[bytes] = []
        for index in range(page_count):
            page = pdf[index]
            try:
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil()
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                renders.append(buffer.getvalue())
            finally:
                page.close()
        return renders
    finally:
        pdf.close()


def ocr_extracted_source(page_texts: list[str]) -> ExtractedSource:
    """Build an ExtractedSource from per-page OCR output, using the exact
    same page join and locator builder as a text-layer PDF so OCR
    citations align identically."""
    return ExtractedSource(
        text=_join_pages(page_texts),
        locators=_pdf_locators(page_texts),
    )