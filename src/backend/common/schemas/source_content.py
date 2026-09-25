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
    size_bytes: int | None = Field(default=None, ge=0)
    file_hash: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=_now)


class Locator(BaseRecord):
    """A reference to a location inside a source.

    `locator_type` is a free string (slide, page, section, timestamp,
    line_range, cell_range, scene, ...) so each format keeps its natural unit
    and new formats need no schema change. Citations use the locator label. The
    object is stored whole; locators form its table of contents.
    """

    locator_id: UUID = Field(default_factory=_new_id)
    source_id: UUID
    locator_type: str
    start: str
    end: str | None = None
    label: str
    description: str | None = None


class Chunk(BaseRecord):
    """A token-bounded retrieval slice, pointing back to the locators it spans.

    Chunks are sized to fit the model's context window, never arbitrary lines.
    """

    chunk_id: UUID = Field(default_factory=_new_id)
    source_id: UUID
    locator_id: UUID
    chunk_index: int
    text: str
