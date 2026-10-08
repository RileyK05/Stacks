from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Purpose = Literal["paper", "slides", "practice", "reference"]
WorkAction = Literal["review", "find", "revise", "explain", "summarize", "critique"]
EssayGenre = Literal[
    "argumentative",
    "analytical",
    "research",
    "comparative",
    "creative",
    "reflective",
    "rhetorical",
]
CritiqueDimension = Literal[
    "requirements", "reasoning", "evidence", "structure", "craft", "clarity"
]
CritiqueGrounding = Literal["course", "craft"]
CritiqueFallacy = Literal[
    "none",
    "straw_man",
    "false_dilemma",
    "hasty_generalization",
    "post_hoc",
    "appeal_to_authority",
    "circular",
    "slippery_slope",
    "ad_hominem",
    "equivocation",
    "unsupported_claim",
    "missing_counterargument",
]
CritiqueFocus = Literal["draft", "unread"]


class WorkModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentInput(WorkModel):
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=300000)
    origin: Literal["paste", "file", "accessibility", "screen", "office"] = "paste"
    external_id: str = Field(default="", max_length=2000)
    coverage: Literal["document", "partial", "unknown"] = "unknown"
    warnings: list[str] = Field(default_factory=list, max_length=30)


class WorkCreate(WorkModel):
    title: str = Field(min_length=1, max_length=300)
    purpose: Purpose = "paper"


class WorkSummary(WorkCreate):
    session_id: UUID
    course_id: UUID
    revision: int = Field(ge=0)
    updated_at: datetime
    critic_score: int = Field(default=50, ge=10, le=100)
    essay_genre: EssayGenre = "argumentative"


class WorkDocument(DocumentInput):
    revision: int = Field(ge=1)
    captured_at: datetime


class WorkCitation(WorkModel):
    number: int
    chunk_id: str
    source_id: str | None
    filename: str
    label: str
    text: str


class ContextCoverage(WorkModel):
    total_sections: int
    included_sections: list[int]
    complete: bool


class ProposedEdit(WorkModel):
    original: str = Field(min_length=1, max_length=2000)
    replacement: str = Field(min_length=1, max_length=4000)
    explanation: str = Field(min_length=1, max_length=2000)


class ReviewFinding(WorkModel):
    original: str = Field(min_length=1, max_length=2000)
    feedback: str = Field(min_length=1, max_length=2000)


class DocumentReview(WorkModel):
    findings: list[ReviewFinding] = Field(min_length=1, max_length=3)


class CritiqueFinding(WorkModel):
    original: str = Field(min_length=1, max_length=2000)
    feedback: str = Field(min_length=1, max_length=2000)
    dimension: CritiqueDimension
    grounding: CritiqueGrounding
    fallacy: CritiqueFallacy = "none"


class PriorFindingStatus(WorkModel):
    original: str = Field(min_length=1, max_length=2000)
    feedback: str = Field(min_length=1, max_length=2000)
    status: Literal["still_present", "passage_changed"]


class CritiqueResult(WorkModel):
    genre: EssayGenre
    critic_score: int = Field(ge=10, le=100)
    syllabus_in_context: bool
    coverage: ContextCoverage
    findings: list[CritiqueFinding] = Field(default_factory=list, max_length=8)
    prior: list[PriorFindingStatus] = Field(default_factory=list, max_length=8)
    note: str = Field(default="", max_length=500)


class CritiqueModelOutput(WorkModel):
    findings: list[CritiqueFinding] = Field(default_factory=list, max_length=12)


class WorkReply(WorkModel):
    text: str
    citations: list[WorkCitation]
    trace_id: str | None
    model: str
    coverage: ContextCoverage
    document_revision: int = Field(ge=1)
    proposed_edit: ProposedEdit | None = None
    critique: CritiqueResult | None = None


class WorkTurn(WorkModel):
    request_id: UUID
    action: WorkAction
    instruction: str
    document_revision: int = Field(ge=1)
    reply: WorkReply
    created_at: datetime


class WorkSession(WorkSummary):
    document: WorkDocument | None
    turns: list[WorkTurn]


class DocumentUpdate(DocumentInput):
    expected_revision: int = Field(ge=0)


class WorkCritiqueSettings(WorkModel):
    critic_score: int = Field(ge=10, le=100)
    essay_genre: EssayGenre


class WorkAsk(WorkModel):
    request_id: UUID
    expected_revision: int = Field(ge=1)
    action: WorkAction = "review"
    instruction: str = Field(default="", max_length=2000)
    selection: str = Field(default="", max_length=4000)
    critic_score: int | None = Field(default=None, ge=10, le=100)
    essay_genre: EssayGenre | None = None
    focus: CritiqueFocus = "draft"


class WorkPublish(WorkModel):
    course_id: UUID
    session_id: UUID | None = None
    expected_revision: int = Field(default=0, ge=0)
    purpose: Purpose = "paper"
    document: DocumentInput


class WorkPackage(WorkModel):
    course_id: UUID
    session_id: UUID | None = None
    expected_revision: int = Field(default=0, ge=0)
    purpose: Purpose = "paper"
    filename: str = Field(max_length=300)
    external_id: str = Field(default="", max_length=2000)
    package_b64: str = Field(max_length=27000000)


class ArchivedWorkTurn(WorkTurn):
    selection: str = ""


class ArchivedWork(WorkSummary):
    documents: list[WorkDocument]
    turns: list[ArchivedWorkTurn]
