"""Validated schema objects, one module per storage-model layer.

See `system.md` §2 for the storage model these mirror. Cross-cutting enums and
helpers live in `base`.
"""

from src.backend.common.schemas.base import (
    ErrorCategory,
    EvidenceLevel,
    LocatorType,
    MasteryState,
    MemoryObjectKind,
    PrereqKind,
    SourceStatus,
    SourceType,
)
from src.backend.common.schemas.chat import ChatSummary, Conversation, ConversationTurn
from src.backend.common.schemas.evidence import (
    ArtifactProvenance,
    Citation,
    Claim,
    MemoryObjectEvidence,
    ProvenanceRecord,
    RetrievalTrace,
)
from src.backend.common.schemas.identity import (
    Course,
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
    "ArtifactProvenance",
    "AssessmentItem",
    "Attempt",
    "ChatSummary",
    "Chunk",
    "Citation",
    "Claim",
    "Concept",
    "ConceptMastery",
    "Conversation",
    "ConversationTurn",
    "Course",
    "CourseObject",
    "Dependency",
    "ErrorCategory",
    "EvidenceLevel",
    "Locator",
    "LocatorType",
    "MasteryState",
    "MemoryObject",
    "MemoryObjectEvidence",
    "MemoryObjectKind",
    "PrereqKind",
    "ProvenanceRecord",
    "Recommendation",
    "RetrievalTrace",
    "Source",
    "SourceStatus",
    "SourceType",
    "StudyPeriod",
    "TableOfContents",
    "TocEntry",
    "User",
]
