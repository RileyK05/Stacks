from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from src.backend.common.config import PROJECT_ROOT

DEFAULT_BACKUPS_PATH = PROJECT_ROOT / "configs" / "backups.toml"


class BackupPolicy(BaseModel):
    backup_config_version: str
    default_enabled: bool
    default_tier: Literal["full", "partial", "heavy"]
    default_compression: Literal["fast", "balanced", "maximum"]
    default_interval_hours: int = Field(ge=1, le=720)
    default_keep_count: int = Field(ge=1, le=100)
    max_archive_bytes: int = Field(ge=1)
    max_members: int = Field(ge=1)


def load_backup_policy(path: Path = DEFAULT_BACKUPS_PATH) -> BackupPolicy:
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    return BackupPolicy(
        backup_config_version=raw["version"]["backup_config_version"],
        default_enabled=raw["defaults"]["enabled"],
        default_tier=raw["defaults"]["tier"],
        default_compression=raw["defaults"]["compression"],
        default_interval_hours=raw["defaults"]["interval_hours"],
        default_keep_count=raw["defaults"]["keep_count"],
        max_archive_bytes=raw["limits"]["max_archive_bytes"],
        max_members=raw["limits"]["max_members"],
    )
