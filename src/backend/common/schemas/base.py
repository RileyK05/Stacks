from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> UUID:
    return uuid4()


class BaseRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SourceType(StrEnum):
    SYLLABUS = "syllabus"
    SLIDES = "slides"
    TEXTBOOK = "textbook"
    PROBLEM_SET = "problem_set"
    SOLUTIONS = "solutions"
    NOTES = "notes"
    FEEDBACK = "feedback"
    EXAM = "exam"
    VIDEO = "video"
    AUDIO = "audio"
    CODE = "code"


class SourceStatus(StrEnum):
    UPLOADED = "uploaded"
    SCANNED = "scanned"
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


class PrereqKind(StrEnum):
    IN_COURSE = "in_course"
    EXTERNAL = "external"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
