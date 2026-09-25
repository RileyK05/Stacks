from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field, model_validator
from src.backend.common.config import PROJECT_ROOT

DEFAULT_LIFECYCLE_PATH = PROJECT_ROOT / "configs" / "lifecycle.toml"


class LifecyclePolicy(BaseModel):
    lifecycle_config_version: str
    trash_retention_days: int = Field(ge=1)
    maintenance_interval_seconds: int = Field(ge=60)
    summary_version: str
    summary_base_tokens: int = Field(ge=1)
    memory_max_tokens: int = Field(ge=1)
    max_raw_upload_bytes: int = Field(ge=1)
    max_decompressed_bytes: int = Field(ge=1)
    orphan_min_age_seconds: int = Field(default=3600, ge=60)

    @model_validator(mode="after")
    def _decompression_covers_uploads(self) -> LifecyclePolicy:
        if self.max_decompressed_bytes < self.max_raw_upload_bytes:
            raise ValueError(
                "max_decompressed_bytes must be >= max_raw_upload_bytes"
            )
        return self


def load_lifecycle_policy(path: Path = DEFAULT_LIFECYCLE_PATH) -> LifecyclePolicy:
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    return LifecyclePolicy(
        lifecycle_config_version=raw["version"]["lifecycle_config_version"],
        trash_retention_days=raw["trash"]["retention_days"],
        maintenance_interval_seconds=raw["trash"]["maintenance_interval_seconds"],
        summary_version=raw["memory"]["summary_version"],
        summary_base_tokens=raw["memory"]["summary_base_tokens"],
        memory_max_tokens=raw["memory"]["max_tokens"],
        max_raw_upload_bytes=raw["uploads"]["max_raw_upload_bytes"],
        max_decompressed_bytes=raw["decompression"]["max_decompressed_bytes"],
        orphan_min_age_seconds=raw.get("cleanup", {}).get(
            "orphan_min_age_seconds", 3600
        ),
    )
