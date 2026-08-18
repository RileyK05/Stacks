"""Validated schema objects, one module per storage-model layer.

See `system.md` §2 for the storage model these mirror. Cross-cutting enums and
helpers live in `base`.
"""

from src.backend.common.schemas.base import (
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
    Claim,
    MemoryObjectEvidence,
    ModelDecision,
    Response,
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
    "ArtifactOrigin",
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
