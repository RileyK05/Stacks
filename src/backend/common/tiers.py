from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field, model_validator
from src.backend.common.config import PROJECT_ROOT
from src.backend.common.schemas.base import KNOWN_GENERATION_TASKS, UserTier

DEFAULT_TIERS_PATH = PROJECT_ROOT / "configs" / "tiers.toml"


class TierPolicy(BaseModel):
    tier: UserTier
    weekly_token_budget: int = Field(ge=0)
    ingestion_token_budget: int = Field(ge=0)
    max_owned_courses: int = Field(ge=1)
    max_course_storage_bytes: int = Field(ge=1)
    max_total_storage_bytes: int = Field(ge=1)
    max_raw_upload_bytes: int = Field(ge=1)
    free_tier_overhead_percent: int = Field(ge=0, le=100)
    models: dict[str, str]

    @model_validator(mode="after")
    def _complete_task_routing(self) -> TierPolicy:
        unknown = set(self.models).difference(KNOWN_GENERATION_TASKS)
        missing = KNOWN_GENERATION_TASKS.difference(self.models)
        if missing or unknown:
            raise ValueError(
                f"tier {self.tier} model routing must cover exactly the known "
                f"generation tasks (missing: {sorted(missing)}, "
                f"unknown: {sorted(unknown)})"
            )
        return self

    def model_for(self, task: str) -> str:
        if task not in KNOWN_GENERATION_TASKS:
            raise ValueError(f"unknown generation task: {task}")
        return self.models[task]


class TierPolicies(BaseModel):
    tiers_config_version: str
    tiers: dict[UserTier, TierPolicy]

    @model_validator(mode="after")
    def _complete_tier_coverage(self) -> TierPolicies:
        missing = set(UserTier).difference(self.tiers)
        if missing:
            names = ", ".join(tier.value for tier in missing)
            raise ValueError(f"tier policies missing for: {names}")
        for tier, policy in self.tiers.items():
            if policy.tier != tier:
                raise ValueError(f"policy tier mismatch for {tier.value}")
        return self

    def policy_for(self, tier: UserTier) -> TierPolicy:
        return self.tiers[tier]


def load_tier_policies(path: Path = DEFAULT_TIERS_PATH) -> TierPolicies:
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    return TierPolicies(
        tiers_config_version=raw["version"]["tiers_config_version"],
        tiers={
            UserTier(tier): TierPolicy(tier=UserTier(tier), **section)
            for tier, section in raw.items()
            if tier != "version"
        },
    )
