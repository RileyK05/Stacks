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


class PracticeQuestion(BaseModel):
    prompt: str = Field(min_length=1, max_length=5000)
    options: list[str] = Field(min_length=2, max_length=8)
    answer: int = Field(ge=0)
    explanation: str = Field(default="", max_length=5000)
    sources: list[int] = Field(default_factory=list)
    topic: str = Field(default="", max_length=160)
    capability: Capability = "recognition"

    @model_validator(mode="after")
    def valid_key(self) -> PracticeQuestion:
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
    answers: list[int] = Field(min_length=1, max_length=100)
    helped: list[bool] = Field(default_factory=list, max_length=100)


class PracticeRun(BaseModel):
    run_id: UUID
    suite_id: UUID
    course_id: UUID
    answers: list[int]
    helped: list[bool]
    policy_version: str
    created_at: datetime
    results: list[bool | None]
    correct_answers: list[int | None]


class SuiteState(BaseModel):
    suite: PracticeSuite
    latest_run: PracticeRun | None = None


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
