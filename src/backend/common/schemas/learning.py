from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Capability = Literal[
    "recognition", "explanation", "application", "counterexample", "transfer"
]
TeachingMethod = Literal[
    "step_by_step", "worked_example", "analogy", "visual_structure"
]

HelpKind = Literal["hint", "explain"]
FeedbackTarget = Literal["question", "hint", "explain"]


class PracticeHelpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    kind: HelpKind


class HelpContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=6000)
    sources: list[int] = Field(min_length=1, max_length=8)


class PracticeHelp(BaseModel):
    help_id: UUID
    question_index: int
    kind: HelpKind
    content: HelpContent
    model: str = ""
    prompt_version: str = ""
    fell_back_to_local: bool = False


class ContentFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: FeedbackTarget = "question"
    help_id: UUID | None = None
    rating: Literal["good", "bad"] | None
    reason: str = Field(default="", max_length=500)


class ContentFeedback(ContentFeedbackRequest):
    suite_id: UUID
    question_index: int
    updated_at: datetime


class PracticeQuestion(BaseModel):
    format: Literal["multiple_choice", "short_answer"] = "multiple_choice"
    prompt: str = Field(min_length=1, max_length=5000)
    stem: str = Field(default="", max_length=2000)
    part: str = Field(default="", max_length=8)
    options: list[str] = Field(default_factory=list, max_length=8)
    answer: int = Field(default=0, ge=0)
    expected: str = Field(default="", max_length=5000)
    # Blank lines from the editor sit between real points. They are removed
    # below; the cap is the raw list, and six is the cap after cleaning.
    points: list[str] = Field(default_factory=list, max_length=24)
    explanation: str = Field(default="", max_length=5000)
    sources: list[int] = Field(default_factory=list)
    topic: str = Field(default="", max_length=160)
    capability: Capability = "recognition"

    @model_validator(mode="after")
    def valid_key(self) -> PracticeQuestion:
        if self.format == "short_answer":
            if self.options:
                raise ValueError("a short answer has no options")
            if not self.expected.strip():
                raise ValueError("a short answer needs an expected answer")
            cleaned: list[str] = []
            for point in self.points:
                if not isinstance(point, str):
                    raise ValueError("a short answer needs required points")
                text = point.strip()
                if text:
                    cleaned.append(text)
            if not cleaned or any(len(point) > 300 for point in cleaned):
                raise ValueError("a short answer needs required points")
            if len(cleaned) > 6:
                raise ValueError("a short answer can have at most 6 required points")
            self.points = cleaned
            self.answer = 0
            return self
        if len(self.options) < 2:
            raise ValueError("a multiple-choice question needs options")
        if self.answer >= len(self.options):
            raise ValueError("the answer key must be one of the options")
        return self


class PracticeSuite(BaseModel):
    suite_id: UUID
    course_id: UUID
    title: str
    questions: list[PracticeQuestion] = Field(min_length=1, max_length=100)
    evidence: list[dict[str, Any]]
    origin: dict[str, Any]
    method: TeachingMethod | None = None
    created_at: datetime


class PracticeSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    answers: list[int | str] = Field(min_length=1, max_length=100)
    helped: list[bool] = Field(default_factory=list, max_length=100)


class PracticeRun(BaseModel):
    run_id: UUID
    suite_id: UUID
    course_id: UUID
    answers: list[int | str]
    helped: list[bool]
    policy_version: str
    created_at: datetime
    results: list[bool | None]
    correct_answers: list[int | None]
    # Required points a short answer did not cover. Empty for other questions.
    missed_points: list[list[str]] = Field(default_factory=list)


class SuiteState(BaseModel):
    suite: PracticeSuite
    latest_run: PracticeRun | None = None
    feedback: list[ContentFeedback] = Field(default_factory=list)


class TargetMemory(BaseModel):
    topic: str
    capability: Capability
    proficiency: int | None
    independent_items: int
    observations: int
    last_checked: datetime | None
    evidence: list[dict[str, Any]]


class LearningExperiment(BaseModel):
    experiment_id: UUID
    course_id: UUID
    message_ref: UUID
    topic: str
    capability: Capability
    hypothesis: str
    proposed_check: str
    evidence: dict[str, Any]
    status: Literal["proposed", "cooldown", "resolved", "retired"]
    checks: int
    next_check_at: datetime
    expires_at: datetime
    created_at: datetime


class MethodMemory(BaseModel):
    method: TeachingMethod
    successes: int
    checks: int
    courses: int
    evidence: list[dict[str, Any]]


class CoreMemory(BaseModel):
    preferred_method: TeachingMethod | None = None
    methods: list[MethodMemory]


class LearningView(BaseModel):
    targets: list[TargetMemory]
    experiments: list[LearningExperiment]
    runs: list[PracticeRun]
    core: CoreMemory


class ResearchHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str = Field(min_length=1, max_length=160)
    capability: Capability
    hypothesis: str = Field(min_length=1, max_length=400)
    proposed_check: str = Field(min_length=1, max_length=400)
    student_quote: str = Field(min_length=8, max_length=500)
    sources: list[int] = Field(min_length=1, max_length=8)


class ResearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    experiments: list[ResearchHypothesis] = Field(max_length=2)
