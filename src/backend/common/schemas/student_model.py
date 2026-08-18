from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field
from src.backend.common.schemas.base import (
    BaseRecord,
    ErrorCategory,
    MasteryState,
    _new_id,
    _now,
)


class AssessmentItem(BaseRecord):
    """A practice/assessment question. The unit the cold probe uses."""

    item_id: UUID = Field(default_factory=_new_id)
    course_id: UUID
    concepts: list[UUID] = Field(default_factory=list)
    source_id: UUID | None = None
    prompt: str
    solution: str | None = None
    difficulty: int = Field(default=1, ge=1, le=5)
    rubric: str | None = None
    created_at: datetime = Field(default_factory=_now)


class Attempt(BaseRecord):
    attempt_id: UUID = Field(default_factory=_new_id)
    user_id: UUID
    course_id: UUID
    item_id: UUID
    concept_ids: list[UUID] = Field(default_factory=list)
    chunk_id: UUID | None = None
    answer: str
    confidence_before: int = Field(ge=0, le=100)
    evaluation: str
    error_category: ErrorCategory | None = None
    used_help: bool = False
    time_spent: int | None = None
    created_at: datetime = Field(default_factory=_now)


class ConceptMastery(BaseRecord):
    """Current mastery state for a concept.

    A ladder, not a single fake-precise score.
    """

    mastery_id: UUID = Field(default_factory=_new_id)
    user_id: UUID
    concept_id: UUID
    state: MasteryState = MasteryState.UNSEEN
    confidence: int | None = Field(default=None, ge=0, le=100)
    updated_at: datetime = Field(default_factory=_now)


class Recommendation(BaseRecord):
    """A 'what to study next' suggestion, traceable to attempts and concepts."""

    recommendation_id: UUID = Field(default_factory=_new_id)
    user_id: UUID
    course_id: UUID
    concept_id: UUID
    reason: str
    source: str
    created_at: datetime = Field(default_factory=_now)
