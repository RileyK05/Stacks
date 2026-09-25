from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field
from src.backend.common.schemas.base import (
    AnalogyUsage,
    BaseRecord,
    ResponseStructure,
    SourcePresentation,
    TutorVerbosity,
    _new_id,
    _now,
)


class TutorProfile(BaseRecord):
    profile_id: UUID = Field(default_factory=_new_id)
    profile_version: str
    verbosity: TutorVerbosity = TutorVerbosity.BALANCED
    analogy_usage: AnalogyUsage = AnalogyUsage.WHEN_HELPFUL
    response_structure: ResponseStructure = ResponseStructure.MIXED
    source_presentation: SourcePresentation = SourcePresentation.BALANCED
    updated_at: datetime = Field(default_factory=_now)
