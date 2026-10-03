"""Split a multimodal OCR model's output back into per-page texts.

Shared by the ingest pipeline's OCR stage (`orchestrator.py`) and the
Office add-in's screenshot reader (`office_reader/screens.py`) so page
alignment behaves identically in both. The OCR prompt asks for a sentinel
separator between pages; when the model does not comply we cannot invent
page alignment, so the whole text becomes page 1's span and the remaining
pages are empty — honest degradation, never a miscitation.
"""

from __future__ import annotations

OCR_PAGE_BOUNDARY = "\n\n---\n\n"


def split_ocr_pages(text: str, page_count: int) -> list[str]:
    if page_count < 1:
        raise ValueError("OCR requires at least one page")
    parts = text.split(OCR_PAGE_BOUNDARY)
    if len(parts) == page_count:
        return parts
    if len(parts) == 1:
        return [text] + [""] * (page_count - 1)
    raise ValueError("OCR page boundaries do not match the rendered pages")
