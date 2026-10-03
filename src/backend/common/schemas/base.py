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
    OCR = "ocr"
    PREPARE_PASSAGES = "prepare_passages"
    PUBLISH_INDEX = "publish_index"


# Canonical free-string values. These fields stay free strings for extensibility,
# but this is the single source of truth for the values the system emits, so
# different parts of the code agree on spelling.
KNOWN_GENERATION_TASKS = frozenset(
    {
        "tutor_answer",
        "artifact_generation",
        "ocr",
        "conversation_summary",
        "learning_research",
    }
)

# Background work (nobody is waiting on it) vs interactive generation.
# Per-task provider routing (configs/models.toml) and the usage ledger read
# this; it is the single source of truth for task classification. The
# classification includes ingestion, chat summaries and learning research.
BACKGROUND_TASKS = frozenset(
    {
        "ocr",
        "conversation_summary",
        "learning_research",
    }
)
