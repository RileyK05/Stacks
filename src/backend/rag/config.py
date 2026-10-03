from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field, model_validator
from src.backend.common.config import PROJECT_ROOT


class PassagePolicy(BaseModel):
    version: str
    semantic_enabled: bool
    target_tokens: int = Field(ge=32)
    boundary_similarity: float = Field(ge=-1, le=1)
    search_window_tokens: int = Field(ge=32)
    retrieved_passage_tokens: int = Field(ge=32)
    generation_material_tokens: int = Field(ge=32)
    window_overlap_tokens: int = Field(ge=0)
    context_neighbors: int = Field(ge=0)
    context_similarity: float = Field(ge=-1, le=1)
    similarity_neighbors: int = Field(ge=0)
    similarity_floor: float = Field(ge=-1, le=1)
    similarity_block_rows: int = Field(ge=1)

    @model_validator(mode="after")
    def valid_sizes(self) -> PassagePolicy:
        if self.generation_material_tokens < self.retrieved_passage_tokens:
            raise ValueError("material budget is smaller than one retrieved passage")
        if self.window_overlap_tokens >= self.search_window_tokens:
            raise ValueError("window overlap must be smaller than its window")
        return self


def load_policy(path: Path | None = None) -> PassagePolicy:
    with (path or PROJECT_ROOT / "configs" / "passages.toml").open("rb") as handle:
        return PassagePolicy.model_validate(tomllib.load(handle))
