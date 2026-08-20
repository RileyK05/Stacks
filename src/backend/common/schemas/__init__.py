"""Validated schema objects, one module per storage-model layer.

See `system.md` §2 for the storage model these mirror. Cross-cutting enums and
helpers live in `base`.
"""

from src.backend.common.schemas.base import (
    KNOWN_CITATION_TARGETS,
    KNOWN_CLAIM_TYPES,
    ErrorCategory,
    EvidenceLevel,
    MasteryState,
    MemoryObjectKind,
    MessageRole,
    PrereqKind,
    SourceStatus,
    SourceType,
)
from src.backend.common.schemas.chat import ChatSummary, Conversation, ConversationTurn
from src.backend.common.schemas.evidence import (
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
    CourseObject,
    StudyPeriod,
    User,
)
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

__all__ = [
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
    "CourseObject",
    "Dependency",
    "ErrorCategory",
    "EvidenceLevel",
    "KNOWN_CLAIM_TYPES",
    "KNOWN_CITATION_TARGETS",
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
    "RetrievalTrace",
    "Source",
    "SourceStatus",
    "SourceType",
    "StudyPeriod",
    "TableOfContents",
    "TocEntry",
    "User",
]
