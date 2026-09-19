from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.rows import dict_row
from src.backend.common import budget, storage
from src.backend.common.db import connection
from src.backend.common.queries import get
from src.backend.common.schemas.base import SourceStatus, SourceType, UserTier
from src.backend.common.schemas.source_content import Source
from src.backend.common.tiers import TierPolicy
from src.backend.ingest import runs as _ingest_runs

_FILE = "sources"


class UnknownOwnedCourseError(RuntimeError):
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
    owner_user_id: UUID,
    tier: UserTier,
    policy: TierPolicy,
    *,
    filename: str,
    mime_type: str,
    source_type: SourceType,
    stream: BinaryIO,
) -> StoredSource:
    temp_path, file_hash, raw_size = storage.stream_to_temp(
        stream, max_bytes=policy.max_raw_upload_bytes
    )
    stored_temp: Path = temp_path
    source_id = uuid4()
    final_written = False
    try:
        stored_temp, stored_encoding, stored_size = (
            storage.compress_temp_for_storage(temp_path, mime_type)
        )
        with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            user_row = cur.execute(
                get(_FILE, "lock_user_for_quota"), {"user_id": owner_user_id}
            ).fetchone()
            if user_row is None:
                raise UnknownOwnedCourseError("course not found")
            course = cur.execute(
                get(_FILE, "lock_owned_active_course"),
                {"course_id": course_id, "owner_user_id": owner_user_id},
            ).fetchone()
            if course is None:
                raise UnknownOwnedCourseError("course not found")
            duplicate = cur.execute(
                get(_FILE, "find_by_hash"),
                {"course_id": course_id, "file_hash": file_hash},
            ).fetchone()
            if duplicate is not None:
                raise DuplicateSourceError(duplicate["source_id"])
            course_size_row = cur.execute(
                get(_FILE, "course_storage"), {"course_id": course_id}
            ).fetchone()
            owner_size_row = cur.execute(
                get(_FILE, "owner_storage"),
                {"owner_user_id": owner_user_id},
            ).fetchone()
            assert course_size_row is not None and owner_size_row is not None
            course_size = int(course_size_row["stored"])
            owner_size = int(owner_size_row["stored"])
            if course_size + stored_size > policy.max_course_storage_bytes:
                raise budget.StorageLimitExceededError(
                    tier,
                    course_size,
                    stored_size,
                    policy.max_course_storage_bytes,
                    "per course",
                )
            if owner_size + stored_size > policy.max_total_storage_bytes:
                raise budget.StorageLimitExceededError(
                    tier,
                    owner_size,
                    stored_size,
                    policy.max_total_storage_bytes,
                    "total",
                )
            object_id = uuid4()
            final_path = storage.write_stored_from_temp(
                course_id, source_id, stored_temp
            )
            final_written = True
            cur.execute(
                get(_FILE, "insert_source_object"),
                {
                    "object_id": object_id,
                    "course_id": course_id,
                    "owner_user_id": owner_user_id,
                    "mime_type": mime_type,
                    "content": json.dumps({"source_id": str(source_id)}),
                },
            )
            row = cur.execute(
                get(_FILE, "insert_source"),
                {
                    "source_id": source_id,
                    "object_id": object_id,
                    "owner_user_id": owner_user_id,
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
            assert row is not None
            cur.execute(
                get("ingestion", "enqueue_pending"),
                {
                    "source_id": source_id,
                    "course_id": course_id,
                    "reason": "uploaded_new_source",
                },
            )
            # Course-memory refresh moved off the upload path (ratified
            # fix #9): the ingestion worker refreshes once per successful
            # batch, instead of rebuilding the same summary inside every
            # upload's quota-locked transaction.
            conn.commit()
        return _stored_source(row, raw_size)
    except BaseException:
        storage.discard_temp(temp_path)
        storage.discard_temp(stored_temp)
        if final_written:
            with suppress(OSError):
                storage.remove_stored(course_id, source_id)
        raise


def list_sources(course_id: UUID) -> list[Source]:
    """The course's source rows (owner-facing; includes failure reasons).
    Review catch #6: the API was write-only, so a user never learned
    their upload failed."""
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            get(_FILE, "list_sources"), {"course_id": course_id}
        ).fetchall()
    return [
        Source(
            source_id=row["source_id"],
            object_id=row["source_id"],
            uploaded_by_user_id=row["uploaded_by_user_id"],
            course_id=course_id,
            filename=row["filename"],
            mime_type=row["mime_type"],
            source_type=row["source_type"],
            status=row["status"],
            size_bytes=row["size_bytes"],
            error_message=row["error_message"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


def requeue_failed(
    conn: Connection, source_id: UUID, course_id: UUID, owner_user_id: UUID
) -> bool:
    """Owner-facing requeue: verify the caller owns the source's course,
    then run the same deliberate failed→uploaded transition the
    orchestrator describes. Returns False when the source is not in a
    failed state."""
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "verify_owner_source"),
            {
                "source_id": source_id,
                "owner_user_id": owner_user_id,
            },
        ).fetchone()
    if row is None:
        return False
    return _ingest_runs.requeue_failed_source(conn, source_id, course_id)
