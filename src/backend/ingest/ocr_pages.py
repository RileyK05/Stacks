"""Split a multimodal OCR model's output back into per-page texts.

Shared by the ingest pipeline's OCR stage (`orchestrator.py`) and the
Office add-in's screenshot reader (`office_reader/screens.py`) so page
alignment behaves identically in both. The OCR prompt asks for a sentinel
separator between pages; when the model does not comply we cannot invent
page alignment, so the response is rejected for that batch.
"""

from __future__ import annotations

import re

OCR_PAGE_BOUNDARY = "\n\n---\n\n"
_PAGE_BOUNDARY = re.compile(r"(?:^|(?:\r?\n)+)[ \t]*---[ \t]*(?=\r?\n|$)")


def split_ocr_pages(text: str, page_count: int) -> list[str]:
    if page_count < 1:
        raise ValueError("OCR requires at least one page")
    parts = _PAGE_BOUNDARY.split(text)
    if len(parts) == page_count + 1 and not parts[-1].strip():
        parts.pop()
    if len(parts) == page_count:
        stripped = [p.strip() for p in parts]
        return ["" if p.casefold() == "[blank]" else p for p in stripped]
    raise ValueError("OCR page boundaries do not match the rendered pages")
