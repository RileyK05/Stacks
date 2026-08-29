from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import Field, SecretStr, model_validator
from src.backend.common.schemas.base import (
    BaseRecord,
    CourseEnrollmentRole,
    CourseVisibility,
    EnrollmentSource,
    EnrollmentStatus,
    ObjectAccessScope,
    UserTier,
    _new_id,
    _now,
)


class User(BaseRecord):
    user_id: UUID = Field(default_factory=_new_id)
    name: str
    email: str | None = None
    tier: UserTier = UserTier.FREE
    created_at: datetime = Field(default_factory=_now)


class UserAccount(User):
    """Internal account state. Never use this model as an API response."""

    password_hash: SecretStr | None = None
    delete_requested_at: datetime | None = None


class Course(BaseRecord):
    course_id: UUID = Field(default_factory=_new_id)
    owner_user_id: UUID
    code: str
    name: str
    visibility: CourseVisibility = CourseVisibility.PRIVATE


class CourseEnrollment(BaseRecord):
    enrollment_id: UUID = Field(default_factory=_new_id)
    course_id: UUID
    user_id: UUID
    role: CourseEnrollmentRole = CourseEnrollmentRole.LEARNER
    status: EnrollmentStatus = EnrollmentStatus.ACTIVE
    enrollment_source: EnrollmentSource
    invited_by_user_id: UUID | None = None
    created_at: datetime = Field(default_factory=_now)
    revoked_at: datetime | None = None

    @model_validator(mode="after")
    def _state_consistency(self) -> CourseEnrollment:
        if self.status == EnrollmentStatus.ACTIVE and self.revoked_at is not None:
            raise ValueError("active enrollment cannot have revoked_at")
        if self.status == EnrollmentStatus.REVOKED and self.revoked_at is None:
            raise ValueError("revoked enrollment requires revoked_at")
        if (
            self.enrollment_source == EnrollmentSource.SELF_SERVICE
            and self.invited_by_user_id is not None
        ):
            raise ValueError("self-service enrollment cannot have an inviter")
        if (
            self.enrollment_source == EnrollmentSource.INVITATION
            and self.invited_by_user_id is None
        ):
            raise ValueError("invitation enrollment requires an inviter")
        return self


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
    """Canonical content owned by a course and created by its owner.

    `kind` is the semantic purpose, `content_type` is the format, and
    `content_uri` points to where the content actually lives (file for binaries,
    jsonb for structured data, text for markdown). New formats = new
    `content_type`, no schema change. Learner generations are `UserArtifact`
    records instead, so course ownership never implies access to private work.
    """

    object_id: UUID = Field(default_factory=_new_id)
    course_id: UUID
    created_by_user_id: UUID
    kind: str
    content_type: str
    content_uri: str | None = None
    content: dict[str, Any] | None = None
    origin: str | None = None
    status: str = "draft"
    access_scope: ObjectAccessScope = ObjectAccessScope.PRIVATE
    created_at: datetime = Field(default_factory=_now)

    @model_validator(mode="after")
    def _content_or_uri(self) -> CourseObject:
        if self.content_uri is None and self.content is None:
            raise ValueError("course object must have content_uri or content")
        return self


class UserArtifact(BaseRecord):
    """A private generated object owned by a learner, not by the source course."""

    artifact_id: UUID = Field(default_factory=_new_id)
    user_id: UUID
    source_course_id: UUID | None
    source_course_label: str
    kind: str
    content_type: str
    content_uri: str | None = None
    content: dict[str, Any] | None = None
    status: str = "draft"
    created_at: datetime = Field(default_factory=_now)

    @model_validator(mode="after")
    def _content_or_uri(self) -> UserArtifact:
        if self.content_uri is None and self.content is None:
            raise ValueError("user artifact must have content_uri or content")
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
