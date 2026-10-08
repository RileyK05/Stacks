import tomllib
from functools import cache

from pydantic import BaseModel, Field
from src.backend.common.config import PROJECT_ROOT


class OfficeLivePolicy(BaseModel):
    poll_interval_ms: int = Field(gt=0)
    lease_seconds: int = Field(gt=0)
    refresh_timeout_seconds: int = Field(gt=0)
    result_retention_seconds: int = Field(gt=0)
    max_connections: int = Field(gt=0)
    max_cells: int = Field(gt=0)
    max_sheets: int = Field(gt=0)
    max_slides: int = Field(gt=0)
    max_shapes: int = Field(gt=0)
    chunk_rows: int = Field(gt=0)
    chunk_columns: int = Field(gt=0)


class CritiquePolicy(BaseModel):
    score_min: int = Field(default=10, ge=1)
    score_max: int = Field(default=100, gt=1)
    default_score: int = Field(default=50, ge=1)
    cap_base: int = Field(default=2, ge=0)
    cap_rise: int = Field(default=6, ge=0)
    cap_span: int = Field(default=90, gt=0)
    strong_from: int = Field(default=30, ge=1)
    severe_from: int = Field(default=75, ge=1)
    edge_sections_from: int = Field(default=50, ge=1)
    low_context_chars: int = Field(default=4000, gt=0)
    syllabus_chunks: int = Field(default=2, ge=0)
    syllabus_chars: int = Field(default=1800, gt=0)


class CompanionPolicy(BaseModel):
    version: int
    max_document_chars: int = Field(gt=0)
    max_upload_bytes: int = Field(gt=0)
    document_context_chars: int = Field(gt=0)
    history_context_chars: int = Field(gt=0)
    source_context_chars: int = Field(gt=0)
    section_chars: int = Field(gt=0)
    capture_timeout_seconds: int = Field(gt=0)
    max_screenshot_pixels: int = Field(gt=0)
    critique: CritiquePolicy = Field(default_factory=CritiquePolicy)
    office_live: OfficeLivePolicy


@cache
def load_companion_policy() -> CompanionPolicy:
    with (PROJECT_ROOT / "configs/companion.toml").open("rb") as handle:
        return CompanionPolicy.model_validate(tomllib.load(handle))
