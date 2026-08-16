from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> UUID:
    return uuid4()


class SourceType(StrEnum):
    SYLLABUS = "syllabus"
    SLIDES = "slides"
    TEXTBOOK = "textbook"
    PROBLEM_SET = "problem_set"
    SOLUTIONS = "solutions"
    NOTES = "notes"
    FEEDBACK = "feedback"
    EXAM = "exam"


class SourceStatus(StrEnum):
    UPLOADED = "uploaded"
    EXTRACTED = "extracted"
    CHUNKED = "chunked"
    INDEXED = "indexed"
    FAILED = "failed"


class EvidenceLevel(StrEnum):
    DIRECT = "direct"
    DERIVED = "derived"
    HYPOTHESIS = "hypothesis"


class MemoryObjectKind(StrEnum):
    CONCEPT = "concept"
    FORMULA = "formula"
    THEOREM = "theorem"
    EXAMPLE = "example"
    MISCONCEPTION = "misconception"
    ASSESSMENT_ITEM = "assessment_item"
    COURSE_WEEK = "course_week"


class MasteryState(StrEnum):
    UNSEEN = "unseen"
    EXPOSED = "exposed"
    CAN_RECOGNIZE = "can_recognize"
    CAN_REPRODUCE_WITH_CUES = "can_reproduce_with_cues"
    CAN_APPLY_INDEPENDENTLY = "can_apply_independently"
    CAN_TRANSFER = "can_transfer"


class ErrorCategory(StrEnum):
    DEFINITION = "definition"
    NOTATION = "notation"
    ASSUMPTION = "assumption"
    APPLICATION = "application"
    CALCULATION = "calculation"
    INCOMPLETE = "incomplete"


class BaseRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class User(BaseRecord):
    user_id: UUID = Field(default_factory=_new_id)
    name: str
    created_at: datetime = Field(default_factory=_now)


class Course(BaseRecord):
    course_id: UUID = Field(default_factory=_new_id)
    user_id: UUID
    code: str
    name: str


class Week(BaseRecord):
    week_id: UUID = Field(default_factory=_new_id)
    course_id: UUID
    week_num: int
    topic: str


class CourseObject(BaseRecord):
    object_id: UUID = Field(default_factory=_new_id)
    course_id: UUID
    user_id: UUID
    kind: str
    content_type: str
    content: dict[str, Any]
    provenance: str | None = None
    created_at: datetime = Field(default_factory=_now)


class Source(BaseRecord):
    source_id: UUID = Field(default_factory=_new_id)
    user_id: UUID
    course_id: UUID
    filename: str
    mime_type: str
    source_type: SourceType
    version: str | None = None
    raw_path: str | None = None
    status: SourceStatus = SourceStatus.UPLOADED
    created_at: datetime = Field(default_factory=_now)


class Page(BaseRecord):
    page_id: UUID = Field(default_factory=_new_id)
    source_id: UUID
    page_num: int
    text: str
    image_path: str | None = None


class Chunk(BaseRecord):
    chunk_id: UUID = Field(default_factory=_new_id)
    source_id: UUID
    page_id: UUID
    chunk_index: int
    section: str | None = None
    text: str
    embedding: list[float] | None = None


class Concept(BaseRecord):
    concept_id: UUID = Field(default_factory=_new_id)
    course_id: UUID
    name: str
    definition: str
    evidence_level: EvidenceLevel = EvidenceLevel.DERIVED


class Dependency(BaseRecord):
    dep_id: UUID = Field(default_factory=_new_id)
    prereq_id: UUID
    dependent_id: UUID


class MemoryObject(BaseRecord):
    memory_id: UUID = Field(default_factory=_new_id)
    concept_id: UUID
    source_id: UUID
    kind: MemoryObjectKind
    content: str
    evidence_level: EvidenceLevel = EvidenceLevel.DERIVED


class Attempt(BaseRecord):
    attempt_id: UUID = Field(default_factory=_new_id)
    user_id: UUID
    course_id: UUID
    concept_id: UUID
    chunk_id: UUID | None = None
    question_version: str
    answer: str
    confidence_before: int = Field(ge=0, le=100)
    evaluation: str
    error_category: ErrorCategory | None = None
    used_help: bool = False
    time_spent: int | None = None
    created_at: datetime = Field(default_factory=_now)
