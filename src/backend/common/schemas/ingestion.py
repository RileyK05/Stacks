from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator
from src.backend.common.schemas.base import (
    BaseRecord,
    IngestionStage,
    IngestionStatus,
    _new_id,
    _now,
)


class IngestionRun(BaseRecord):
    run_id: UUID = Field(default_factory=_new_id)
    source_id: UUID
    pipeline_version: str
    status: IngestionStatus = IngestionStatus.PENDING
    configuration: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime = Field(default_factory=_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class IngestionStageRun(BaseRecord):
    stage_run_id: UUID = Field(default_factory=_new_id)
    run_id: UUID
    stage: IngestionStage
    position: int
    depends_on_stage_id: UUID | None = None
    status: IngestionStatus = IngestionStatus.PENDING
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(ge=1)
    handler_version: str
    configuration: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def _attempt_limit(self) -> IngestionStageRun:
        if self.attempt_count > self.max_attempts:
            raise ValueError("attempt_count cannot exceed max_attempts")
        return self
