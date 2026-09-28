"""Redundant, read-only readers for Office documents.

The Office add-in may have several ways to see what the student is looking
at, and none of them is trusted alone (plan-notebook.md, "Reading Office
documents — redundant methods"):

- ``package.read_package`` — download and break the `.docx`/`.xlsx`/`.pptx`
  down, pulling text out of the OOXML parts;
- ``screens.read_screens`` — OCR one or more PNG renders (the screenshot
  method), which is the fallback when the parts cannot be read;
- the host's own ``scrape`` of the live selection, supplied by the add-in.

``merge.merge_reads`` combines them into one consensus and reports how much
each method agreed, so the pane can show the redundancy rather than hide it.

Every reader is read-only: none serializes or saves an Office file.
"""

from src.backend.office_reader.merge import merge_reads
from src.backend.office_reader.models import (
    KNOWN_METHODS,
    OCR,
    PACKAGE,
    SCRAPE,
    Agreement,
    DocumentRead,
    MergedRead,
    TextUnit,
)
from src.backend.office_reader.package import UnreadablePackageError, read_package
from src.backend.office_reader.screens import OcrUnavailableError, read_screens

__all__ = [
    "Agreement",
    "DocumentRead",
    "KNOWN_METHODS",
    "MergedRead",
    "OCR",
    "OcrUnavailableError",
    "PACKAGE",
    "SCRAPE",
    "TextUnit",
    "UnreadablePackageError",
    "merge_reads",
    "read_package",
    "read_screens",
]
