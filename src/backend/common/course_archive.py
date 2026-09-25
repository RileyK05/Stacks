"""Course export/import as one `.course` file (plan §12, decisions log §14).

Format v2 is a zip holding:

- `manifest.json` — format id and version, the course name, and one entry
  per source (archive path, display filename, MIME type, source type,
  sha256 of the original bytes);
- `sources/<n>-<filename>` — each source's original bytes.
- `notebook.json` — chats, artifacts, versions, and the passages they cite.

The importer also accepts source-only format v1.

The full search index, embeddings, TOC, and course memory are rebuilt on
import. Cited passages have small snapshots so old answers and artifact
citations stay readable even after the search index is rebuilt.

Import treats the archive as untrusted input. Only members the manifest
names are read, by exact name (nothing is extracted by path); declared and
actual sizes are capped; MIME and source types must be ones upload
accepts; every file must match its manifest hash. A failed import leaves
nothing behind.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Literal, cast
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from src.backend.common import archive_notebook, courses_repo, sources_repo, storage
from src.backend.common.db import connection
from src.backend.common.lifecycle_config import load_lifecycle_policy
from src.backend.common.queries import get
from src.backend.common.schemas.base import SourceType
from src.backend.common.schemas.identity import Course
from src.backend.ingest.extract import INGESTABLE_MIME_TYPES

FORMAT_ID: Literal["stacks/course"] = "stacks/course"
FORMAT_VERSION: Literal[2] = 2
EXTENSION = ".course"
MANIFEST_NAME = "manifest.json"
NOTEBOOK_NAME = "notebook.json"
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_NOTEBOOK_BYTES = 64 * 1024 * 1024
_UNSAFE_FILENAME_CHARS = re.compile(r"[^\w\-. ()]+")


class InvalidArchiveError(ValueError):
    """The file is not a usable `.course` archive; the message says why."""


class ArchiveSource(BaseModel):
    path: str = Field(min_length=1, max_length=512)
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str
    source_type: SourceType
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_id: UUID | None = None


class Manifest(BaseModel):
    format: Literal["stacks/course"]
    format_version: Literal[1, 2]
    name: str = Field(min_length=1, max_length=200)
    exported_at: str
    sources: list[ArchiveSource]
    notebook_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ExportResult:
    path: Path
    source_count: int
    size_bytes: int


@dataclass(frozen=True)
class ImportResult:
    course: Course
    imported: int
    duplicates_skipped: int


def _safe_filename(name: str) -> str:
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", name).strip(" .")
    return cleaned[:120] or "course"


def _unique_path(directory: Path, stem: str) -> Path:
    candidate = directory / f"{stem}{EXTENSION}"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem} ({counter}){EXTENSION}"
        counter += 1
    return candidate


def export_course(course_id: UUID, directory: Path) -> ExportResult:
    """Write the course to `<directory>/<name>.course` (never overwriting)
    and return where it went. Raises LookupError for an unknown course."""
    course = courses_repo.get_course(course_id)
    if course is None:
        raise LookupError("course not found")
    with connection() as conn:
        rows = conn.execute(
            get("sources", "archive_sources"), {"course_id": course_id}
        ).fetchall()
    policy = load_lifecycle_policy()
    directory.mkdir(parents=True, exist_ok=True)
    target = _unique_path(directory, _safe_filename(course.name))
    partial = target.with_name(target.name + ".part")
    entries: list[ArchiveSource] = []
    try:
        with zipfile.ZipFile(partial, "w") as archive:
            for index, row in enumerate(rows, start=1):
                filename = storage.sanitize_display_name(row["filename"])
                path = f"sources/{index:04d}-{_safe_filename(filename)}"
                data = storage.read_stored(
                    course_id,
                    row["source_id"],
                    row["stored_encoding"],
                    max_decompressed_bytes=policy.max_decompressed_bytes,
                )
                compression = (
                    zipfile.ZIP_DEFLATED
                    if storage.is_compressible(row["mime_type"])
                    else zipfile.ZIP_STORED
                )
                archive.writestr(path, data, compress_type=compression)
                entries.append(
                    ArchiveSource(
                        path=path,
                        filename=filename,
                        mime_type=row["mime_type"],
                        source_type=SourceType(row["source_type"]),
                        sha256=row["file_hash"],
                        source_id=row["source_id"],
                    )
                )
            notebook = archive_notebook.export_notebook(course_id)
            notebook_bytes = notebook.model_dump_json().encode("utf-8")
            archive.writestr(
                NOTEBOOK_NAME, notebook_bytes, compress_type=zipfile.ZIP_DEFLATED
            )
            manifest = Manifest(
                format=FORMAT_ID,
                format_version=FORMAT_VERSION,
                name=course.name,
                exported_at=datetime.now(UTC).isoformat(timespec="seconds"),
                sources=entries,
                notebook_sha256=hashlib.sha256(notebook_bytes).hexdigest(),
            )
            archive.writestr(
                MANIFEST_NAME,
                manifest.model_dump_json(indent=2),
                compress_type=zipfile.ZIP_DEFLATED,
            )
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return ExportResult(
        path=target, source_count=len(entries), size_bytes=target.stat().st_size
    )


def _read_manifest(archive: zipfile.ZipFile) -> Manifest:
    try:
        info = archive.getinfo(MANIFEST_NAME)
    except KeyError:
        raise InvalidArchiveError("not a .course file: no manifest") from None
    if info.file_size > MAX_MANIFEST_BYTES:
        raise InvalidArchiveError("the manifest is too large")
    try:
        raw = json.loads(archive.read(info))
    except (ValueError, zipfile.BadZipFile) as err:
        raise InvalidArchiveError("the manifest is not valid JSON") from err
    if isinstance(raw, dict) and raw.get("format_version", 1) not in (1, 2):
        raise InvalidArchiveError(
            f"this .course file uses format version {raw.get('format_version')}; "
            "update the app to open it"
        )
    try:
        return Manifest.model_validate(raw)
    except ValidationError as err:
        raise InvalidArchiveError(f"the manifest is malformed: {err}") from err


def _read_notebook(
    archive: zipfile.ZipFile, manifest: Manifest
) -> archive_notebook.Notebook | None:
    if manifest.format_version == 1:
        return None
    if not manifest.notebook_sha256:
        raise InvalidArchiveError("format v2 is missing the notebook checksum")
    if any(entry.source_id is None for entry in manifest.sources):
        raise InvalidArchiveError("format v2 is missing a source id")
    try:
        info = archive.getinfo(NOTEBOOK_NAME)
    except KeyError:
        raise InvalidArchiveError("format v2 is missing notebook.json") from None
    if info.file_size > MAX_NOTEBOOK_BYTES:
        raise InvalidArchiveError("the notebook is too large")
    with archive.open(info) as stream:
        data = stream.read(MAX_NOTEBOOK_BYTES + 1)
    if len(data) > MAX_NOTEBOOK_BYTES:
        raise InvalidArchiveError("the notebook is too large")
    if hashlib.sha256(data).hexdigest() != manifest.notebook_sha256:
        raise InvalidArchiveError("the notebook does not match its checksum")
    try:
        notebook = archive_notebook.Notebook.model_validate_json(data)
    except ValidationError as err:
        raise InvalidArchiveError(f"the notebook is malformed: {err}") from err
    source_ids = {entry.source_id for entry in manifest.sources}
    if len(source_ids) != len(manifest.sources):
        raise InvalidArchiveError("the notebook has duplicate source ids")
    if any(citation.source_id not in source_ids for citation in notebook.citations):
        raise InvalidArchiveError("a cited passage names a source outside this course")
    if len({c.chunk_id for c in notebook.citations}) != len(notebook.citations):
        raise InvalidArchiveError("the notebook has duplicate cited passages")
    if len({t.trace_id for t in notebook.traces}) != len(notebook.traces):
        raise InvalidArchiveError("the notebook has duplicate traces")
    return notebook


def _checked_members(
    archive: zipfile.ZipFile, manifest: Manifest
) -> list[tuple[ArchiveSource, zipfile.ZipInfo]]:
    policy = load_lifecycle_policy()
    if len(manifest.sources) > policy.max_import_sources:
        raise InvalidArchiveError(
            f"too many files ({len(manifest.sources)}; "
            f"the limit is {policy.max_import_sources})"
        )
    checked: list[tuple[ArchiveSource, zipfile.ZipInfo]] = []
    total = 0
    for entry in manifest.sources:
        if not entry.path.startswith("sources/"):
            raise InvalidArchiveError(f"unexpected file location: {entry.path}")
        if entry.mime_type not in INGESTABLE_MIME_TYPES:
            raise InvalidArchiveError(
                f"unsupported file type for {entry.filename}: {entry.mime_type}"
            )
        try:
            info = archive.getinfo(entry.path)
        except KeyError:
            raise InvalidArchiveError(f"missing file: {entry.path}") from None
        if info.file_size > policy.max_raw_upload_bytes:
            raise InvalidArchiveError(
                f"{entry.filename} is larger than the upload limit"
            )
        total += info.file_size
        if total > policy.max_import_bytes:
            raise InvalidArchiveError("the course is larger than the import limit")
        checked.append((entry, info))
    return checked


def _discard(course_id: UUID) -> None:
    """Remove a half-imported course completely, keepsake included: it
    never existed as far as the user is concerned."""
    courses_repo.move_to_trash(course_id)
    courses_repo.purge_course(course_id)
    with connection() as conn:
        conn.execute("DELETE FROM course_memories WHERE course_id = ?", (course_id,))
        conn.commit()


def import_course(archive_path: Path) -> ImportResult:
    """Create a new course from a `.course` file and queue its sources for
    ingestion. Raises InvalidArchiveError with a readable reason."""
    try:
        archive = zipfile.ZipFile(archive_path)
    except (zipfile.BadZipFile, OSError) as err:
        raise InvalidArchiveError("not a .course file (unreadable zip)") from err
    with archive:
        manifest = _read_manifest(archive)
        members = _checked_members(archive, manifest)
        notebook = _read_notebook(archive, manifest)
        course = courses_repo.create_course(manifest.name.strip() or "Imported course")
        imported = duplicates = 0
        source_map: dict[UUID, UUID] = {}
        try:
            for entry, info in members:
                with archive.open(info) as stream:
                    try:
                        stored = sources_repo.upload_source(
                            course.course_id,
                            filename=entry.filename,
                            mime_type=entry.mime_type,
                            source_type=entry.source_type,
                            stream=cast(BinaryIO, stream),
                        )
                    except sources_repo.DuplicateSourceError as err:
                        existing = sources_repo.get_source(
                            course.course_id, err.source_id
                        )
                        if existing is None or existing.file_hash != entry.sha256:
                            raise InvalidArchiveError(
                                f"{entry.filename} does not match its checksum"
                            ) from None
                        duplicates += 1
                        if entry.source_id is not None:
                            source_map[entry.source_id] = err.source_id
                        continue
                    except storage.EmptyUploadError:
                        raise InvalidArchiveError(
                            f"{entry.filename} is empty"
                        ) from None
                if stored.file_hash != entry.sha256:
                    raise InvalidArchiveError(
                        f"{entry.filename} does not match its checksum"
                    )
                imported += 1
                if entry.source_id is not None:
                    source_map[entry.source_id] = stored.source_id
            if notebook is not None:
                with connection() as conn:
                    archive_notebook.import_notebook(
                        conn, course.course_id, notebook, source_map
                    )
                    conn.commit()
        except BaseException as err:
            _discard(course.course_id)
            if isinstance(err, (zipfile.BadZipFile, EOFError)):
                raise InvalidArchiveError("the .course file is corrupt") from err
            if isinstance(err, sqlite3.IntegrityError):
                raise InvalidArchiveError(
                    "the notebook has conflicting records"
                ) from err
            raise
    return ImportResult(course=course, imported=imported, duplicates_skipped=duplicates)
