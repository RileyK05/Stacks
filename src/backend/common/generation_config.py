"""Versioned bounds for model generation work."""

from __future__ import annotations

import tomllib
from functools import cache
from pathlib import Path

from pydantic import BaseModel, Field, model_validator
from src.backend.common.config import PROJECT_ROOT
from src.backend.common.schemas.base import KNOWN_GENERATION_TASKS

DEFAULT_GENERATION_POLICY_PATH = PROJECT_ROOT / "configs" / "generation.toml"


class GenerationTask(BaseModel):
    desired_output_tokens: int = Field(ge=1)
    max_recoveries: int = Field(ge=0, le=3)
    # A reasoning model spends part of its output budget thinking, so the
    # allowance is a multiple of the answer size. Interactive answers set a
    # higher multiple: a truncated answer is thrown away and re-asked, which
    # costs the student the whole wait (R4-NEW-q). The multiple must still
    # leave a widening step below the model's ceiling.
    reasoning_multiplier: int = Field(default=4, ge=1, le=16)


class GenerationPolicy(BaseModel):
    version: str
    max_calls: int = Field(ge=1)
    max_http_requests: int = Field(ge=1)
    max_elapsed_seconds: float = Field(gt=0)
    max_requested_tokens: int = Field(ge=1)
    input_bytes_per_token: float = Field(ge=1, le=4)
    context_margin_tokens: int = Field(ge=0)
    framing_tokens: int = Field(ge=0)
    min_output_tokens: int = Field(ge=1)
    tasks: dict[str, GenerationTask]

    @model_validator(mode="after")
    def tasks_match_known_generation_tasks(self) -> GenerationPolicy:
        missing = KNOWN_GENERATION_TASKS - self.tasks.keys()
        unknown = self.tasks.keys() - KNOWN_GENERATION_TASKS
        if missing or unknown:
            details = []
            if missing:
                details.append(f"missing tasks: {', '.join(sorted(missing))}")
            if unknown:
                details.append(f"unknown tasks: {', '.join(sorted(unknown))}")
            raise ValueError("; ".join(details))
        return self


@cache
def _load(path: Path) -> GenerationPolicy:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    return GenerationPolicy(
        version=raw["version"]["generation_policy_version"],
        **raw["operation"],
        tasks=raw["tasks"],
    )


def load_generation_policy(
    path: Path = DEFAULT_GENERATION_POLICY_PATH,
) -> GenerationPolicy:
    return _load(path)
