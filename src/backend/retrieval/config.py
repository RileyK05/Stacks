from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from src.backend.common.config import PROJECT_ROOT

DEFAULT_RETRIEVAL_PATH = PROJECT_ROOT / "configs" / "retrieval.toml"


class RetrievalPolicy(BaseModel):
    """Funnel tunables. All values are config-owned (never hardcoded in
    the funnel), versioned in configs/retrieval.toml."""

    retrieval_config_version: str
    keyword_limit: int = Field(ge=1)
    graph_limit: int = Field(ge=0)
    generated_lookup_weight: float = Field(ge=0, le=1)
    embedding_limit: int = Field(ge=1)
    final_k: int = Field(ge=1)
    embedding_only_quota: int = Field(ge=0)


class RerankPolicy(BaseModel):
    enabled: bool
    model: str
    generation_k: int = Field(ge=1)
    # "top_k" (fused order, generation_k cut) or "score" (score the whole
    # pool, keep what clears the floor). Ships "top_k" until the user
    # calibrates the floor (plan-score-retrieval.md Phase 3/4).
    mode: Literal["top_k", "score"] = "top_k"
    pool_limit: int = Field(default=60, ge=1)
    min_score: float = -1000.0
    max_drop: float = Field(default=1000.0, ge=0)


class ScorePolicy(BaseModel):
    """Wide seam limits for score mode (plan-score-retrieval.md Phase 3)."""

    keyword_limit: int = Field(ge=1)
    embedding_limit: int = Field(ge=1)
    graph_limit: int = Field(ge=0)


def load_score_policy(path: Path = DEFAULT_RETRIEVAL_PATH) -> ScorePolicy:
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    return ScorePolicy.model_validate(raw["score"])


class RoutePolicy(BaseModel):
    """Explicit-address routing (plan-score-retrieval.md Phase 1): a question
    that names a numbered thing ("Table 2.2") or a week ("Week 3") is routed
    to that passage or source instead of a generic keyword match."""

    enabled: bool
    label_kinds: tuple[str, ...]
    label_limit: int = Field(ge=1)


def load_route_policy(path: Path = DEFAULT_RETRIEVAL_PATH) -> RoutePolicy:
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    return RoutePolicy.model_validate(raw["route"])


def load_rerank_policy(path: Path = DEFAULT_RETRIEVAL_PATH) -> RerankPolicy:
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    return RerankPolicy.model_validate(raw["rerank"])


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
