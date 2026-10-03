"""Guess a source type when an upload does not name one.

The stored type is always a real `SourceType`. "Auto" is only the absence
of a choice: a deck is slides, a file that says syllabus is a syllabus,
and everything else is notes.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from src.backend.common.schemas.base import SourceType
from src.backend.ingest.extract import _PDF_MIME, _PPTX_MIME

logger = logging.getLogger(__name__)

# Lecture slides are 16:9. 4:3 and letter pages stay notes unless the
# name or the first page says syllabus.
_WIDE_RATIO = 16 / 9
_WIDE_TOLERANCE = 0.08


def infer_source_type(
    filename: str,
    mime: str,
    first_page_text: str = "",
    page_sizes: Sequence[tuple[float, float]] = (),
) -> SourceType:
    if mime == _PPTX_MIME or Path(filename).suffix.lower() == ".pptx":
        return SourceType.SLIDES
    if page_sizes and _near_widescreen(page_sizes[0]):
        return SourceType.SLIDES
    if "syllabus" in f"{filename}\n{first_page_text}".casefold():
        return SourceType.SYLLABUS
    return SourceType.NOTES


def sniff_source_type(path: Path, filename: str, mime: str) -> SourceType:
    text = ""
    sizes: list[tuple[float, float]] = []
    if mime == _PDF_MIME:
        try:
            text, sizes = _pdf_hints(path)
        except Exception:
            logger.warning(
                "could not read %s to infer its type", filename, exc_info=True
            )
    return infer_source_type(filename, mime, text, sizes)


def _near_widescreen(size: tuple[float, float]) -> bool:
    width, height = size
    if width <= 0 or height <= 0 or width <= height:
        return False
    return abs(width / height - _WIDE_RATIO) / _WIDE_RATIO <= _WIDE_TOLERANCE


def _pdf_hints(path: Path) -> tuple[str, list[tuple[float, float]]]:
    from pypdf import PdfReader

    reader = PdfReader(path)
    if not reader.pages:
        return "", []
    page = reader.pages[0]
    box = page.mediabox
    width, height = float(box.width), float(box.height)
    if page.rotation in (90, 270):
        width, height = height, width
    try:
        text = page.extract_text() or ""
    except Exception:
        logger.warning("could not read the first page of %s", path.name, exc_info=True)
        text = ""
    return text, [(width, height)]
