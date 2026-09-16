from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field
from src.backend.common.config import PROJECT_ROOT

DEFAULT_RETRIEVAL_PATH = PROJECT_ROOT / "configs" / "retrieval.toml"


class RetrievalPolicy(BaseModel):
    """Funnel tunables. All values are config-owned (never hardcoded in
    the funnel), versioned in configs/retrieval.toml."""

    retrieval_config_version: str
    keyword_limit: int = Field(ge=1)
    toc_limit: int = Field(ge=1)
    dependency_limit: int = Field(ge=1)
    embedding_limit: int = Field(ge=1)
    final_k: int = Field(ge=1)
    per_source_cap: int = Field(ge=1)
    embedding_only_quota: int = Field(ge=0)


def load_retrieval_policy(
    path: Path = DEFAULT_RETRIEVAL_PATH,
) -> RetrievalPolicy:
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    return RetrievalPolicy.model_validate(
        {
            "retrieval_config_version": raw["version"]["retrieval_config_version"],
            **raw["funnel"],
        }
    )