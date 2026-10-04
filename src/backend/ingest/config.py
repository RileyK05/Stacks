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


class OcrConfig(BaseModel):
    """Rasterization bounds for the OCR stage (vision model does the
    recognition; these cap how much we render per source)."""

    max_pages: int = Field(ge=1)
    scale: float = Field(gt=0)
    batch_pages: int = Field(default=4, ge=1)
    max_image_pixels: int = Field(default=8_000_000, ge=1)
    max_request_image_bytes: int = Field(default=12_000_000, ge=1)


class TextConfig(BaseModel):
    """When a PDF page is blank or its text layer is not readable prose."""

    min_page_chars: int = Field(default=20, ge=1)
    quality_floor: float = Field(default=0.35, ge=0, le=1)
    max_decode_bytes: int = Field(default=64 * 1024 * 1024, ge=1)


class IngestionConfig(BaseModel):
    pipeline_version: str
    max_attempts: int = Field(ge=1)
    retry_backoff_seconds: float = Field(default=0.5, ge=0)
    retry_backoff_multiplier: float = Field(default=2, ge=1)
    poll_interval_seconds: int = Field(ge=1)
    ocr: OcrConfig
    text: TextConfig = Field(default_factory=TextConfig)
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
