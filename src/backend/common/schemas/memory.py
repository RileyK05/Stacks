"""Course-knowledge models: what the course SAYS (concepts, evidence links)
and the TOC index for FINDING it. NOT memory in the decision-007 sense —
user/course memory lives in schemas/identity.CourseMemory and the
course_memories table. This module's historical name is a legacy misnomer;
see docs/decisions/007_memory_model.md for the vocabulary.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field
from src.backend.common.schemas.base import (
    BaseRecord,
    EvidenceLevel,
    MemoryObjectKind,
    PrereqKind,
    _new_id,
    _now,
)


class Concept(BaseRecord):
    concept_id: UUID = Field(default_factory=_new_id)
    course_id: UUID
    name: str
    definition: str
    synonyms: list[str] = Field(default_factory=list)
    evidence_level: EvidenceLevel = EvidenceLevel.DERIVED


class Dependency(BaseRecord):
    """A prerequisite link. A concept may have no prereq (prereq_id null), or a
    prereq outside the course (prereq_kind=external + external_ref)."""

    dep_id: UUID = Field(default_factory=_new_id)
    prereq_id: UUID | None = None
    dependent_id: UUID
    prereq_kind: PrereqKind = PrereqKind.IN_COURSE
    external_ref: str | None = None


class MemoryObject(BaseRecord):
    memory_id: UUID = Field(default_factory=_new_id)
    concept_id: UUID
    source_id: UUID
    kind: MemoryObjectKind
    content: str
    evidence_level: EvidenceLevel = EvidenceLevel.DERIVED


class TableOfContents(BaseRecord):
    """The model-written, per-course index of what's in the course and where.

    Grows as the course grows. Versioned so the current version is knowable and
    previous versions are recoverable. Written by a small, stable TOC model so
    descriptions stay consistent over time.
    """

    toc_id: UUID = Field(default_factory=_new_id)
    course_id: UUID
    version: int
    created_at: datetime = Field(default_factory=_now)


class TocEntry(BaseRecord):
    entry_id: UUID = Field(default_factory=_new_id)
    toc_id: UUID
    source_id: UUID
    locator_id: UUID | None = None
    title: str
    description: str
    concepts: list[UUID] = Field(default_factory=list)
    position: int = 0
