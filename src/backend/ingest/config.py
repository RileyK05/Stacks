from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field, model_validator
from src.backend.common.config import PROJECT_ROOT
from src.backend.common.schemas.base import IngestionStage
from src.backend.ingest.pipeline import PIPELINE_STAGES

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "ingestion.toml"


class StageConfig(BaseModel):
    name: IngestionStage
    handler_version: str


class IngestionConfig(BaseModel):
    pipeline_version: str
    max_attempts: int = Field(ge=1)
    chunk_max_tokens: int = Field(ge=1)
    prompt_window_chars: int = Field(ge=1)
    stages: list[StageConfig]

    @model_validator(mode="after")
    def _ordered_complete_pipeline(self) -> IngestionConfig:
        configured = tuple(stage.name for stage in self.stages)
        if configured != PIPELINE_STAGES:
            raise ValueError("ingestion stages must match the supported pipeline order")
        return self


def load_ingestion_config(path: Path = DEFAULT_CONFIG_PATH) -> IngestionConfig:
    with path.open("rb") as config_file:
        return IngestionConfig.model_validate(tomllib.load(config_file))
