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


class CourseVisibility(StrEnum):
    PRIVATE = "private"
    INVITE_ONLY = "invite_only"
    PUBLIC = "public"


class CourseLifecycleStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class CourseEnrollmentRole(StrEnum):
    LEARNER = "learner"


class EnrollmentStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    DECLINED = "declined"
    REVOKED = "revoked"


class EnrollmentSource(StrEnum):
    SELF_SERVICE = "self_service"
    INVITATION = "invitation"
    JOIN_CODE = "join_code"


class SpendKind(StrEnum):
    """Which weekly pool a billed call draws from. Pools are separate so a
    large ingestion upload can never drain the budget a user needs for
    interactive answers."""

    GENERATION = "generation"
    INGESTION = "ingestion"


class ObjectAccessScope(StrEnum):
    PUBLISHED = "published"
    ENROLLED = "enrolled"
    PRIVATE = "private"


class TutorVerbosity(StrEnum):
    CONCISE = "concise"
    BALANCED = "balanced"
    DETAILED = "detailed"


class AnalogyUsage(StrEnum):
    RARE = "rare"
    WHEN_HELPFUL = "when_helpful"
    FREQUENT = "frequent"


class ResponseStructure(StrEnum):
    PROSE = "prose"
    MIXED = "mixed"
    BULLETS = "bullets"


class SourcePresentation(StrEnum):
    PARAPHRASE_FIRST = "paraphrase_first"
    BALANCED = "balanced"
    QUOTE_FORWARD = "quote_forward"


class IngestionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class IngestionStage(StrEnum):
    EXTRACT_TEXT = "extract_text"
    BUILD_LOCATORS = "build_locators"
    BUILD_CHUNKS = "build_chunks"
    UPDATE_TOC = "update_toc"
    EXTRACT_KNOWLEDGE = "extract_knowledge"


class UserTier(StrEnum):
    FREE = "free"
    PAID = "paid"


# Canonical free-string values. These fields stay free strings for extensibility,
# but this is the single source of truth for the values the system emits, so
# different parts of the code agree on spelling.
KNOWN_CLAIM_TYPES = frozenset(
    {"academic", "inference", "hypothesis", "recommendation"}
)
KNOWN_CITATION_TARGETS = frozenset(
    {"chunk", "memory_object", "toc_entry", "source", "conversation_turn"}
)
KNOWN_GENERATION_TASKS = frozenset(
    {
        "tutor_answer",
        "probe_generation",
        "probe_evaluation",
        "toc_update",
        "course_knowledge_extraction",
        "artifact_generation",
    }
)
