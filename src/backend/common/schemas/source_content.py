from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field
from src.backend.common.schemas.base import (
    BaseRecord,
    SourceStatus,
    SourceType,
    _new_id,
    _now,
)


class Source(BaseRecord):
    """An uploaded course file, stored whole. Nothing is destroyed at ingest."""

    source_id: UUID = Field(default_factory=_new_id)
    course_id: UUID
    filename: str
    mime_type: str
    source_type: SourceType
    version: str | None = None
    uri: str | None = None
    status: SourceStatus = SourceStatus.UPLOADED
    has_index: bool = False
    size_bytes: int | None = Field(default=None, ge=0)
    file_hash: str | None = None
    error_message: str | None = None
    pages_total: int | None = None
    pages_empty: int | None = None
    pages_low_quality: int | None = None
    pages_ocr: int | None = None
    chunk_count: int = 0
    ingestion_stage: str | None = None
    index_stale: bool = False
    created_at: datetime = Field(default_factory=_now)
