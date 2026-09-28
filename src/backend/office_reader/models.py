"""Shared types for the redundant Office readers.

Stacks reads a document the student is looking at through *several*
independent methods and keeps them side by side, so a bad read in one
method is caught by the others (plan-notebook.md, "Reading Office
documents — redundant methods"). Every method returns the same shape: an
ordered list of labelled text units plus what the method could not do.

Nothing here ever writes an Office file. The readers are read-only
projections; Office remains the only thing that saves a `.docx`/`.xlsx`/
`.pptx`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# How a document was read. Each is independent: the host can supply one,
# all, or none (the pane falls back to a plain text selection).
SCRAPE = "scrape"
OCR = "ocr"
PACKAGE = "package"
KNOWN_METHODS = (SCRAPE, OCR, PACKAGE)


@dataclass(frozen=True)
class TextUnit:
    """One labelled piece of a document: a paragraph, a cell range, a
    slide, a rendered page. `label` is human-facing ("slide 3", "B2",
    "page 1"); `text` is what was read there."""

    label: str
    text: str

    @property
    def empty(self) -> bool:
        return not self.text.strip()


@dataclass(frozen=True)
class DocumentRead:
    """One method's reading of one document.

    `units` is in document order. `warnings` names what the method could
    not read (a scanned image, a chart, an encrypted part) so the pane can
    show the gap rather than pretend the read was complete."""

    method: str
    host: str
    units: tuple[TextUnit, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def text(self) -> str:
        return "\n\n".join(unit.text for unit in self.units if not unit.empty)

    @property
    def char_count(self) -> int:
        return len(self.text)


@dataclass(frozen=True)
class Agreement:
    """How one method's units line up with the merged reading: how many of
    its units matched the consensus, and how many were only seen by it."""

    method: str
    matched: int
    unique: int
    total: int


@dataclass(frozen=True)
class MergedRead:
    """The union of several ``DocumentRead``s plus the agreement between
    them. ``text`` is the consensus text (deduplicated, in order); the
    ``reads`` and ``agreement`` are kept so the pane can show exactly what
    each method saw — redundancy you can inspect, not a black box."""

    host: str
    units: tuple[TextUnit, ...]
    reads: tuple[DocumentRead, ...]
    agreement: tuple[Agreement, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def text(self) -> str:
        return "\n\n".join(unit.text for unit in self.units if not unit.empty)
