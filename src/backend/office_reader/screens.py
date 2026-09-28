"""Read a document by OCRing pictures of it.

This is the "screenshots" method: the host (or the desktop shell) hands
over one or more PNG renders of the visible page, slide, or sheet, and the
multimodal OCR seam transcribes them. It is the method that still works
when nothing else can — a scanned page, an image-only slide, a chart with
text baked in, a region the OOXML readers cannot see.

It uses the same ``provider.generate(..., images=...)`` seam the ingest
pipeline's OCR stage uses, so a multimodal model the user already runs for
scanned PDFs serves this too. A read that returns no text records a warning
rather than raising: a blank render must not fail the whole merged read.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from src.backend.common import provider
from src.backend.common.db import Connection
from src.backend.common.prompt_registry import load_prompt
from src.backend.ingest.ocr_pages import split_ocr_pages
from src.backend.office_reader.models import OCR, DocumentRead, TextUnit

_MAX_IMAGES = 40


class OcrUnavailableError(RuntimeError):
    """No multimodal provider is configured, so screenshots cannot be read."""


def read_screens(
    conn: Connection,
    images: Sequence[bytes],
    *,
    host: str = "",
    course_id: UUID | None = None,
) -> DocumentRead:
    """Transcribe rendered page/slide images into labelled text units.

    One image is one labelled unit ("image 1", "image 2", …) in order, so
    the pane can line each transcript up with the render it came from. The
    caller commits; this does no database work itself beyond what
    ``provider.generate`` records in the usage ledger."""
    del conn  # the OCR seam needs no database; kept for a uniform reader API
    if not images:
        return DocumentRead(
            method=OCR, host=host or "image", warnings=("no images to read",)
        )
    if len(images) > _MAX_IMAGES:
        raise ValueError(f"at most {_MAX_IMAGES} images can be read at once")
    try:
        result = provider.generate(
            "ocr",
            load_prompt("ocr"),
            course_id=course_id,
            images=list(images),
        )
    except provider.ProviderUnavailableError as err:
        raise OcrUnavailableError(
            "reading screenshots needs a model that can see images; "
            "configure one in Settings to use this method"
        ) from err
    page_texts = split_ocr_pages(result.text, len(images))
    units = tuple(
        TextUnit(label=f"image {index + 1}", text=text.strip())
        for index, text in enumerate(page_texts)
    )
    warnings: tuple[str, ...] = ()
    if not any(unit.text for unit in units):
        warnings = ("the model returned no text for these images",)
    return DocumentRead(
        method=OCR, host=host or "image", units=units, warnings=warnings
    )
