from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import Field, model_validator
from src.backend.common.schemas.base import BaseRecord, _new_id, _now


class Course(BaseRecord):
    """A course on this machine. One local user per database, so a course
    has no owner, visibility, or enrollment — the OS account is the
    boundary. `deleted_at`/`purge_after` mark a course in the trash."""

    course_id: UUID = Field(default_factory=_new_id)
    name: str = Field(min_length=1, max_length=200)
    created_at: datetime = Field(default_factory=_now)
    deleted_at: datetime | None = None
    purge_after: datetime | None = None

    @model_validator(mode="after")
    def _trash_consistency(self) -> Course:
        if (self.deleted_at is None) != (self.purge_after is None):
            raise ValueError("deleted_at and purge_after are set together")
        return self

    @property
    def in_trash(self) -> bool:
        return self.deleted_at is not None


class StudyPeriod(BaseRecord):
    """A user-definable sliding time window over a course.

    Replaces the rigid "week": a study period may be a lecture, a month, a
    semester, or the stretch before an exam. The user sets the granularity.
    """

    period_id: UUID = Field(default_factory=_new_id)
    course_id: UUID
    label: str
    start_date: date
    end_date: date


class CourseMemory(BaseRecord):
    """A course-memory node (decision 007): the per-course focus record.
    Facts about understanding only — never behavior instructions.
    Outlives the course row (the deletion keepsake, golden rule 6)."""

    memory_id: UUID = Field(default_factory=_new_id)
    course_id: UUID
    course_ref: str
    name: str
    summary: str
    key_concepts: list[str] = Field(default_factory=list)
    token_budget: int = Field(gt=0)
    summary_version: str
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
