"""Validated schema objects, one module per storage-model layer.

See `system.md` §2 for the storage model these mirror. Cross-cutting enums and
helpers live in `base`.
"""

from src.backend.common.schemas.base import (
    INGESTION_TASKS,
    KNOWN_CITATION_TARGETS,
    KNOWN_CLAIM_TYPES,
    KNOWN_GENERATION_TASKS,
    AnalogyUsage,
    ErrorCategory,
    EvidenceLevel,
    IngestionStage,
    IngestionStatus,
    MasteryState,
    MemoryObjectKind,
    MessageRole,
    PrereqKind,
    ResponseStructure,
    SourcePresentation,
    SourceStatus,
    SourceType,
    TutorVerbosity,
)
from src.backend.common.schemas.chat import ChatSummary, Conversation, ConversationTurn
from src.backend.common.schemas.evidence import (
    ArchivedCitation,
    ArtifactOrigin,
    Citation,
    CitationSnapshot,
    Claim,
    MemoryObjectEvidence,
    ModelDecision,
    Response,
    RetrievalTrace,
)
from src.backend.common.schemas.identity import (
    Course,
    CourseMemory,
    StudyPeriod,
)
from src.backend.common.schemas.ingestion import IngestionRun, IngestionStageRun
from src.backend.common.schemas.memory import (
    Concept,
    Dependency,
    MemoryObject,
    TableOfContents,
    TocEntry,
)
from src.backend.common.schemas.source_content import Chunk, Locator, Source
from src.backend.common.schemas.student_model import (
    AssessmentItem,
    Attempt,
    ConceptMastery,
    Recommendation,
)
from src.backend.common.schemas.tutor import TutorProfile
from src.backend.common.schemas.usage import UsageLedgerEntry

__all__ = [
    "ArchivedCitation",
    "AnalogyUsage",
    "ArtifactOrigin",
    "AssessmentItem",
    "Attempt",
    "ChatSummary",
    "Chunk",
    "Citation",
    "CitationSnapshot",
    "Claim",
    "Concept",
    "ConceptMastery",
    "Conversation",
    "ConversationTurn",
    "Course",
    "CourseMemory",
    "Dependency",
    "ErrorCategory",
    "EvidenceLevel",
    "IngestionRun",
    "IngestionStage",
    "IngestionStageRun",
    "IngestionStatus",
    "KNOWN_CLAIM_TYPES",
    "KNOWN_CITATION_TARGETS",
    "INGESTION_TASKS",
    "KNOWN_GENERATION_TASKS",
    "Locator",
    "MasteryState",
    "MemoryObject",
    "MemoryObjectEvidence",
    "MemoryObjectKind",
    "MessageRole",
    "ModelDecision",
    "PrereqKind",
    "Recommendation",
    "Response",
    "ResponseStructure",
    "RetrievalTrace",
    "Source",
    "SourceStatus",
    "SourcePresentation",
    "SourceType",
    "StudyPeriod",
    "TableOfContents",
    "TocEntry",
    "TutorProfile",
    "TutorVerbosity",
    "UsageLedgerEntry",
]
