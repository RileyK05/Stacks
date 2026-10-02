from __future__ import annotations

import tomllib

from pydantic import BaseModel, Field
from src.backend.common.config import PROJECT_ROOT


class ScoringPolicy(BaseModel):
    assisted_weight: float = Field(gt=0, lt=1)
    assisted_only_cap: int = Field(ge=0, le=100)
    initial_cap: int = Field(ge=0, le=100)
    two_item_cap: int = Field(ge=0, le=100)
    three_item_cap: int = Field(ge=0, le=100)
    five_item_cap: int = Field(ge=0, le=100)
    proficient_items: int = Field(ge=5)


class PracticePolicy(BaseModel):
    focus_slots: int = Field(ge=0, le=5)
    maintenance_slots: int = Field(ge=0, le=2)
    weak_below: int = Field(ge=0, le=100)
    strong_at: int = Field(ge=0, le=100)
    cooldown_days: int = Field(ge=1)
    maintenance_days: int = Field(ge=1)
    experiment_lifetime_days: int = Field(ge=1)
    experiment_max_checks: int = Field(ge=1)
    max_open_experiments: int = Field(ge=1)
    context_chars: int = Field(ge=200)
    method_exploration_interval: int = Field(ge=2)


class SupportPolicy(BaseModel):
    claim_seconds: int = Field(ge=30)
    feedback_items: int = Field(ge=1, le=20)
    feedback_chars: int = Field(ge=200)
    passage_chars: int = Field(ge=1000)


class LearningPolicy(BaseModel):
    version: str
    scoring: ScoringPolicy
    practice: PracticePolicy
    methods: dict[str, str]
    support: SupportPolicy


def load_learning_policy() -> LearningPolicy:
    with (PROJECT_ROOT / "configs/learning.toml").open("rb") as stream:
        raw = tomllib.load(stream)
    return LearningPolicy(
        version=raw["version"]["learning_policy_version"],
        scoring=raw["scoring"],
        practice=raw["practice"],
        methods=raw["methods"],
        support=raw["support"],
    )
