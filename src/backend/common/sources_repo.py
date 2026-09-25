from __future__ import annotations

import sqlite3
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO
from uuid import UUID, uuid4

from src.backend.common import storage
from src.backend.common.db import Connection, connection
from src.backend.common.lifecycle_config import load_lifecycle_policy
from src.backend.common.queries import get
from src.backend.common.schemas.base import SourceStatus, SourceType
from src.backend.common.schemas.source_content import Source
from src.backend.ingest import runs as _ingest_runs

_FILE = "sources"


class UnknownCourseError(RuntimeError):
    pass


class DuplicateSourceError(RuntimeError):
    def __init__(self, source_id: UUID) -> None:
        self.source_id = source_id
        super().__init__(f"source content already exists: {source_id}")


@dataclass(frozen=True)
class StoredSource:
    source_id: UUID
    course_id: UUID
    filename: str
    mime_type: str
    source_type: SourceType
    status: SourceStatus
    file_hash: str
    raw_size_bytes: int
    stored_size_bytes: int
    stored_encoding: str


def _stored_source(row: dict[str, Any], raw_size_bytes: int) -> StoredSource:
    return StoredSource(
        source_id=row["source_id"],
        course_id=row["course_id"],
        filename=row["filename"],
        mime_type=row["mime_type"],
        source_type=SourceType(row["source_type"]),
        status=SourceStatus(row["status"]),
        file_hash=row["file_hash"],
        raw_size_bytes=raw_size_bytes,
        stored_size_bytes=int(row["size_bytes"]),
        stored_encoding=row["stored_encoding"],
    )


def upload_source(
    course_id: UUID,
    *,
    filename: str,
    mime_type: str,
    source_type: SourceType,
    stream: BinaryIO,
) -> StoredSource:
    """Stream the upload to disk (hashing as it goes), store it, insert
    the row, and enqueue ingestion. The file write happens before the row
    commits; on any failure the file is removed, and a crash in between
    leaves only an orphan the maintenance sweep collects."""
    temp_path, file_hash, raw_size = storage.stream_to_temp(
        stream, max_bytes=load_lifecycle_policy().max_raw_upload_bytes
    )
    stored_temp: Path = temp_path
    source_id = uuid4()
    final_written = False
    try:
        stored_temp, stored_encoding, stored_size = storage.compress_temp_for_storage(
            temp_path, mime_type
        )
        with connection() as conn:
            if conn.execute(
                get(_FILE, "active_course_exists"), {"course_id": course_id}
            ).fetchone() is None:
                raise UnknownCourseError("course not found")
            duplicate = conn.execute(
                get(_FILE, "find_by_hash"),
                {"course_id": course_id, "file_hash": file_hash},
            ).fetchone()
            if duplicate is not None:
                raise DuplicateSourceError(duplicate["source_id"])
            final_path = storage.write_stored_from_temp(
                course_id, source_id, stored_temp
            )
            final_written = True
            try:
                row = conn.execute(
                    get(_FILE, "insert_source"),
                    {
                        "source_id": source_id,
                        "course_id": course_id,
                        "filename": storage.sanitize_display_name(filename),
                        "mime_type": mime_type,
                        "source_type": source_type.value,
                        "uri": str(final_path),
                        "file_hash": file_hash,
                        "size_bytes": stored_size,
                        "stored_encoding": stored_encoding,
                    },
                ).fetchone()
            except sqlite3.IntegrityError:
                # A concurrent upload of the same bytes won the unique
                # (course_id, file_hash) index between our check and insert.
                conn.rollback()
                duplicate = conn.execute(
                    get(_FILE, "find_by_hash"),
                    {"course_id": course_id, "file_hash": file_hash},
                ).fetchone()
                if duplicate is None:
                    raise
                raise DuplicateSourceError(duplicate["source_id"]) from None
            assert row is not None
            _ingest_runs.enqueue_pending(
                conn, source_id, course_id, "uploaded_new_source"
            )
            conn.commit()
        return _stored_source(row, raw_size)
    except BaseException:
        storage.discard_temp(temp_path)
        storage.discard_temp(stored_temp)
        if final_written:
            with suppress(OSError):
                storage.remove_stored(course_id, source_id)
        raise


def _to_source(row: dict[str, Any]) -> Source:
    return Source(
        source_id=row["source_id"],
        course_id=row["course_id"],
        filename=row["filename"],
        mime_type=row["mime_type"],
        source_type=row["source_type"],
        status=row["status"],
        size_bytes=row["size_bytes"],
        file_hash=row["file_hash"],
        error_message=row["error_message"],
        created_at=row["created_at"],
    )


def list_sources(course_id: UUID) -> list[Source]:
    with connection() as conn:
        rows = conn.execute(
            get(_FILE, "list_sources"), {"course_id": course_id}
        ).fetchall()
    return [_to_source(row) for row in rows]


def get_source(course_id: UUID, source_id: UUID) -> Source | None:
    with connection() as conn:
        row = conn.execute(
            get(_FILE, "get_source"),
            {"course_id": course_id, "source_id": source_id},
        ).fetchone()
    return _to_source(row) if row else None


def reindex_source(course_id: UUID, source_id: UUID) -> bool:
    """Queue fresh extraction while keeping every existing citation readable."""
    with connection() as conn:
        params = {"course_id": course_id, "source_id": source_id}
        row = conn.execute(get(_FILE, "get_source"), params).fetchone()
        if row is None or row["status"] != "indexed":
            return False
        conn.execute(get(_FILE, "snapshot_citations_before_reindex"), params)
        changed = conn.execute(get(_FILE, "mark_for_reindex"), params)
        if changed.rowcount != 1:
            conn.rollback()
            return False
        conn.execute(get(_FILE, "enqueue_reindex"), params)
        conn.commit()
    return True


def delete_source(course_id: UUID, source_id: UUID) -> bool:
    """Remove one source: its rows cascade, then its stored file goes."""
    with connection() as conn:
        row = conn.execute(
            get(_FILE, "delete_source"),
            {"course_id": course_id, "source_id": source_id},
        ).fetchone()
        conn.commit()
    if row is None:
        return False
    with suppress(OSError):
        storage.remove_stored(course_id, source_id)
    return True


def requeue_failed(conn: Connection, source_id: UUID, course_id: UUID) -> bool:
    """The deliberate retry path: failed → uploaded + re-enqueued. Returns
    False when the source is not in a failed state (or not in this
    course)."""
    if conn.execute(
        get(_FILE, "get_source"), {"course_id": course_id, "source_id": source_id}
    ).fetchone() is None:
        return False
    return _ingest_runs.requeue_failed_source(conn, source_id, course_id)
