from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator
from src.backend.common.schemas.base import BaseRecord, _new_id, _now


class User(BaseRecord):
    user_id: UUID = Field(default_factory=_new_id)
    name: str
    email: str | None = None
    password_hash: str | None = None
    delete_requested_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)


class Course(BaseRecord):
    course_id: UUID = Field(default_factory=_new_id)
    user_id: UUID
    code: str
    name: str


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


class CourseObject(BaseRecord):
    """Any object a course owns: an uploaded source or a generated artifact.

    `kind` is the semantic purpose, `content_type` is the format, and
    `content_uri` points to where the content actually lives (file for binaries,
    jsonb for structured data, text for markdown). New formats = new
    `content_type`, no schema change.
    """

    object_id: UUID = Field(default_factory=_new_id)
    course_id: UUID
    user_id: UUID
    kind: str
    content_type: str
    content_uri: str | None = None
    content: dict[str, Any] | None = None
    origin: str | None = None
    status: str = "draft"
    created_at: datetime = Field(default_factory=_now)

    @model_validator(mode="after")
    def _content_or_uri(self) -> CourseObject:
        if self.content_uri is None and self.content is None:
            raise ValueError("course object must have content_uri or content")
        return self


class CourseMemory(BaseRecord):
    """Distilled record of a course that survives course deletion."""

    memory_id: UUID = Field(default_factory=_new_id)
    user_id: UUID
    course_id: UUID
    code: str
    name: str
    summary: str
    key_concepts: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
