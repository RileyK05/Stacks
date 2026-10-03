"""Read a `.docx`/`.xlsx`/`.pptx` by breaking down its OOXML package.

This is the "download and break it down" method: given the real bytes the
student's Office file already has on disk (or that the host hands over),
unzip the package in memory and pull the visible text out of the parts —
Word paragraphs and tables, Excel shared strings and inline cell values,
PowerPoint slide and notes text.

It is strictly read-only. It never re-serializes the file, never writes a
part back, and never saves: Office owns the save. A method that cannot
read a part (a chart, an embedded object, a shape with no text) records a
warning instead, so the pane sees the gap.
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
from xml.etree import ElementTree

from src.backend.office_reader.models import PACKAGE, DocumentRead, TextUnit

# OOXML part namespaces.
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"

_MAX_PART_BYTES = 40 * 1024 * 1024
_MAX_EXPANDED_BYTES = 4 * _MAX_PART_BYTES


class UnreadablePackageError(ValueError):
    """The bytes are not a readable OOXML package."""


def _xml(data: bytes) -> ElementTree.Element:
    declarations = data.upper().replace(b"\x00", b"")
    if b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
        raise UnreadablePackageError("document parts cannot contain XML entities")
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as err:
        raise UnreadablePackageError(
            f"a document part is not valid XML: {err}"
        ) from err


def _tag(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


class _BoundedPackage(zipfile.ZipFile):
    def __init__(self, data: bytes) -> None:
        super().__init__(io.BytesIO(data))
        self._expanded = 0

    def read(self, name: str | zipfile.ZipInfo, pwd: bytes | None = None) -> bytes:
        info = self.getinfo(name) if isinstance(name, str) else name
        if (
            info.file_size > _MAX_PART_BYTES
            or self._expanded + info.file_size > _MAX_EXPANDED_BYTES
        ):
            raise UnreadablePackageError("the expanded document exceeds the read limit")
        with self.open(info, pwd=pwd) as stream:
            data = stream.read(
                min(_MAX_PART_BYTES, _MAX_EXPANDED_BYTES - self._expanded) + 1
            )
        self._expanded += len(data)
        if len(data) > _MAX_PART_BYTES or self._expanded > _MAX_EXPANDED_BYTES:
            raise UnreadablePackageError("the expanded document exceeds the read limit")
        return data


def _part_number(name: str) -> int:
    match = re.search(r"(\d+)\.xml$", name)
    if match is None:
        raise UnreadablePackageError("document part has no numeric identifier")
    return int(match.group(1))


def _ordered_parts(
    archive: zipfile.ZipFile, manifest: str, child: str, fallback: list[str]
) -> list[str]:
    rels_name = posixpath.join(
        posixpath.dirname(manifest), "_rels", posixpath.basename(manifest) + ".rels"
    )
    if manifest not in archive.namelist() or rels_name not in archive.namelist():
        return sorted(fallback, key=_part_number)
    relations = {
        rel.get("Id"): posixpath.normpath(
            posixpath.join(posixpath.dirname(manifest), rel.get("Target", ""))
        ).lstrip("/")
        for rel in _xml(archive.read(rels_name))
        if rel.get("TargetMode") != "External"
    }
    ordered = [
        relations.get(
            node.get(
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            )
        )
        for node in _xml(archive.read(manifest)).iter()
        if node.tag.rsplit("}", 1)[-1] == child
    ]
    if not ordered or any(name not in fallback for name in ordered):
        raise UnreadablePackageError("document ordering references a missing part")
    return [name for name in ordered if name is not None]


def _paragraph_text(node: ElementTree.Element) -> str:
    return "".join(t.text or "" for t in node.iter(_tag(_W, "t"))).strip()


def _read_docx(archive: zipfile.ZipFile) -> tuple[list[TextUnit], list[str]]:
    warnings: list[str] = []
    try:
        body = _xml(archive.read("word/document.xml"))
    except KeyError as err:
        raise UnreadablePackageError("the .docx has no word/document.xml") from err
    units: list[TextUnit] = []

    def visit(node: ElementTree.Element) -> None:
        if node.tag == _tag(_W, "p"):
            text = _paragraph_text(node)
            if text:
                units.append(TextUnit(label=f"paragraph {len(units) + 1}", text=text))
        elif node.tag == _tag(_W, "tbl"):
            for row in node.findall(_tag(_W, "tr")):
                cells = [
                    " ".join(_paragraph_text(p) for p in cell.iter(_tag(_W, "p")))
                    for cell in row.findall(_tag(_W, "tc"))
                ]
                if any(cells):
                    units.append(
                        TextUnit(
                            label=f"table row {len(units) + 1}", text=" | ".join(cells)
                        )
                    )
        else:
            for child in node:
                visit(child)

    visit(body)
    if any(
        re.fullmatch(
            r"word/(?:header\d+|footer\d+|footnotes|endnotes|comments)\.xml", name
        )
        for name in archive.namelist()
    ):
        warnings.append(
            "headers, footers, notes and comments are not included in the body read"
        )
    if not units:
        warnings.append("no paragraph or table text found in the document")
    return units, warnings


def _read_xlsx(archive: zipfile.ZipFile) -> tuple[list[TextUnit], list[str]]:
    warnings: list[str] = []
    shared: list[str] = []
    if "xl/sharedStrings.xml" in archive.namelist():
        root = _xml(archive.read("xl/sharedStrings.xml"))
        for item in root.iter(_tag(_S, "si")):
            shared.append("".join(t.text or "" for t in item.iter(_tag(_S, "t"))))
    else:
        warnings.append("no shared strings part; only inline cell values are read")
    sheets = [
        name
        for name in archive.namelist()
        if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
    ]
    if not sheets:
        raise UnreadablePackageError("the .xlsx has no worksheets")
    units: list[TextUnit] = []
    formulas = 0
    for sheet_name in _ordered_parts(archive, "xl/workbook.xml", "sheet", sheets):
        root = _xml(archive.read(sheet_name))
        formulas += sum(1 for _ in root.iter(_tag(_S, "f")))
        for row in root.iter(_tag(_S, "row")):
            row_number = row.get("r", str(len(units) + 1))
            cells: list[str] = []
            for cell in row.iter(_tag(_S, "c")):
                ref = cell.get("r", "")
                value_node = cell.find(_tag(_S, "v"))
                inline = cell.find(_tag(_S, "is"))
                cell_text: str
                if cell.get("t") == "s" and value_node is not None:
                    try:
                        index = int(value_node.text or "0")
                        if index < 0:
                            raise IndexError
                        cell_text = shared[index]
                    except (ValueError, IndexError):
                        cell_text = ""
                        warnings.append(
                            f"{sheet_name} {ref} has an invalid shared-string index"
                        )
                elif inline is not None:
                    cell_text = "".join(
                        t.text or "" for t in inline.iter(_tag(_S, "t"))
                    )
                elif value_node is not None and value_node.text:
                    cell_text = value_node.text
                else:
                    cell_text = ""
                if cell_text:
                    cells.append(f"{ref}={cell_text}")
            if cells:
                units.append(TextUnit(label=f"row {row_number}", text="; ".join(cells)))
    if not units:
        warnings.append("the workbook has no cell values")
    if formulas:
        warnings.append(f"{formulas} formula cell(s) show cached values only")
    return units, warnings


def _read_pptx(archive: zipfile.ZipFile) -> tuple[list[TextUnit], list[str]]:
    warnings: list[str] = []
    slide_parts = sorted(
        name
        for name in archive.namelist()
        if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
    )
    if not slide_parts:
        raise UnreadablePackageError("the .pptx has no slides")
    units: list[TextUnit] = []
    linked_notes: dict[str, int] = {}
    for index, part in enumerate(
        _ordered_parts(archive, "ppt/presentation.xml", "sldId", slide_parts), start=1
    ):
        root = _xml(archive.read(part))
        texts = [t.text or "" for t in root.iter(_tag(_A, "t"))]
        body = " ".join(text.strip() for text in texts if text.strip())
        if body:
            units.append(TextUnit(label=f"slide {index}", text=body))
        else:
            warnings.append(f"slide {index} has no text (an image or a graphic)")
        rels_name = posixpath.join(
            posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels"
        )
        if rels_name in archive.namelist():
            for rel in _xml(archive.read(rels_name)):
                if rel.get("TargetMode") == "External" or not rel.get(
                    "Type", ""
                ).endswith("/notesSlide"):
                    continue
                target = posixpath.normpath(
                    posixpath.join(posixpath.dirname(part), rel.get("Target", ""))
                ).lstrip("/")
                if target not in archive.namelist():
                    warnings.append(f"slide {index} references missing speaker notes")
                elif target in linked_notes:
                    raise UnreadablePackageError(
                        "multiple slides reference the same speaker notes"
                    )
                else:
                    linked_notes[target] = index
    notes_parts = sorted(
        name
        for name in archive.namelist()
        if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", name)
    )
    for part in sorted(notes_parts, key=_part_number):
        note_index = linked_notes.get(part)
        root = _xml(archive.read(part))
        texts = [t.text or "" for t in root.iter(_tag(_A, "t"))]
        body = " ".join(text.strip() for text in texts if text.strip())
        if body:
            if note_index is None:
                label = f"unlinked speaker notes ({posixpath.basename(part)})"
                warnings.append(f"{label} cannot be assigned to a slide")
            else:
                label = f"speaker notes {note_index}"
            units.append(TextUnit(label=label, text=body))
    return units, warnings


_READERS = {
    "word": _read_docx,
    "excel": _read_xlsx,
    "powerpoint": _read_pptx,
}


def read_package(data: bytes, *, kind: str, host: str = "") -> DocumentRead:
    """Break a package down into labelled text units.

    `kind` is ``word`` | ``excel`` | ``powerpoint``; `host` is the Office
    application it came from (for the merged read's provenance)."""
    reader = _READERS.get(kind)
    if reader is None:
        raise UnreadablePackageError(f"no package reader for {kind!r}")
    if len(data) > _MAX_PART_BYTES:
        raise UnreadablePackageError("the file is larger than the read limit")
    try:
        with _BoundedPackage(data) as archive:
            units, warnings = reader(archive)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as err:
        raise UnreadablePackageError(
            "the file is not a readable Office package"
        ) from err
    return DocumentRead(
        method=PACKAGE,
        host=host or kind,
        units=tuple(units),
        warnings=tuple(warnings),
    )
