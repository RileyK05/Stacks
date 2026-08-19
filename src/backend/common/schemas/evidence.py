from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field
from src.backend.common.schemas.base import BaseRecord, EvidenceLevel, _new_id, _now


class RetrievalTrace(BaseRecord):
    """Record of what the tutor retrieved and used to produce an answer.

    Enables auditing whether a citation actually supported the answer.
    """

    trace_id: UUID = Field(default_factory=_new_id)
    user_id: UUID
    course_id: UUID
    conversation_id: UUID | None = None
    query: str
    retrieved_chunk_ids: list[UUID] = Field(default_factory=list)
    retrieved_toc_entry_ids: list[UUID] = Field(default_factory=list)
    model: str | None = None
    created_at: datetime = Field(default_factory=_now)


class Response(BaseRecord):
    """A tutor's answer to a user question. The object that claims attach to.

    `response_id` is what `Claim.response_id` references. A response is produced
    by the tutor, grounded in a retrieval trace, and rendered as a conversation
    turn.
    """

    response_id: UUID = Field(default_factory=_new_id)
    conversation_id: UUID
    turn_id: UUID | None = None
    trace_id: UUID | None = None
    content: str
    model: str | None = None
    created_at: datetime = Field(default_factory=_now)


class Claim(BaseRecord):
    """A single claim the system makes, with the evidence that grounds it."""

    claim_id: UUID = Field(default_factory=_new_id)
    response_id: UUID
    claim_type: str
    text: str


class Citation(BaseRecord):
    """Links a claim to the evidence that grounds it (a chunk, memory object,
    or TOC entry)."""

    citation_id: UUID = Field(default_factory=_new_id)
    claim_id: UUID
    target_type: str
    target_id: UUID
    trace_id: UUID | None = None


class MemoryObjectEvidence(BaseRecord):
    """Direct link between a memory object and the chunk that supports it.
    Lets a citation on a memory object resolve to a chunk within 2 hops."""

    evidence_id: UUID = Field(default_factory=_new_id)
    memory_id: UUID
    chunk_id: UUID
    evidence_level: EvidenceLevel = EvidenceLevel.DIRECT


class ArtifactOrigin(BaseRecord):
    """How a generated artifact was produced: which sources, concepts, and
    model. Lets an artifact's origin be audited and regenerated."""

    artifact_id: UUID
    source_ids: list[UUID] = Field(default_factory=list)
    concept_ids: list[UUID] = Field(default_factory=list)
    model: str | None = None
    prompt_version: str | None = None
    created_at: datetime = Field(default_factory=_now)


class ModelDecision(BaseRecord):
    """Records a model's storage/description decisions, so they can be audited
    and regenerated if the model improves."""

    record_id: UUID = Field(default_factory=_new_id)
    source_id: UUID
    model: str | None = None
    decision: dict[str, Any]
    created_at: datetime = Field(default_factory=_now)
