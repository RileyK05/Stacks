from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field, model_validator
from src.backend.common.config import PROJECT_ROOT
from src.backend.common.schemas.base import UserTier

DEFAULT_LIFECYCLE_PATH = PROJECT_ROOT / "configs" / "lifecycle.toml"


class LifecyclePolicy(BaseModel):
    lifecycle_config_version: str
    archive_grace_days: int = Field(ge=1)
    maintenance_interval_seconds: int = Field(ge=60)
    summary_version: str
    summary_base_tokens: int = Field(ge=1)
    memory_tokens: dict[UserTier, int]
    cleanup_max_attempts: int = Field(default=5, ge=1)
    cleanup_retry_delay_seconds: int = Field(default=300, ge=1)
    orphan_min_age_seconds: int = Field(default=3600, ge=60)
    max_decompressed_bytes: int = Field(ge=1)

    @model_validator(mode="after")
    def _covers_all_tiers(self) -> LifecyclePolicy:
        missing = set(UserTier).difference(self.memory_tokens)
        if missing:
            raise ValueError(f"memory token limits missing for: {sorted(missing)}")
        return self

    def memory_limit(self, tier: UserTier) -> int:
        return self.memory_tokens[tier]


def load_lifecycle_policy(path: Path = DEFAULT_LIFECYCLE_PATH) -> LifecyclePolicy:
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    return LifecyclePolicy(
        lifecycle_config_version=raw["version"]["lifecycle_config_version"],
        archive_grace_days=raw["archive"]["grace_days"],
        maintenance_interval_seconds=raw["archive"][
            "maintenance_interval_seconds"
        ],
        summary_version=raw["archive"]["summary_version"],
        summary_base_tokens=raw["archive"]["summary_base_tokens"],
        memory_tokens={
            UserTier(tier): limit for tier, limit in raw["memory_tokens"].items()
        },
        cleanup_max_attempts=raw.get("cleanup", {}).get("max_attempts", 5),
        cleanup_retry_delay_seconds=raw.get("cleanup", {}).get(
            "retry_delay_seconds", 300
        ),
        orphan_min_age_seconds=raw.get("cleanup", {}).get(
            "orphan_min_age_seconds", 3600
        ),
        max_decompressed_bytes=raw["decompression"]["max_decompressed_bytes"],
    )
