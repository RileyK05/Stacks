"""Per-model generation profiles (docs/plan-local-first.md §6.10,
plan-notebook §4.8).

One TOML file per model in `configs/models/`: whether the model reasons
before answering, how long it may write, and its sampling temperature.
A model without a profile uses `[generation]` in configs/models.toml.
Profiles are matched by the model name the endpoint is called with —
the catalog id for the bundled runtime, the provider's model id for a
connection — or any of the profile's `aliases`.

Reasoning is off by default because small models spend most of their
budget thinking when allowed (decision 012); a reasoning-first model
(K2 Horizon) gets it on, with room to finish.
"""

from __future__ import annotations

import tomllib
from functools import cache
from pathlib import Path

from pydantic import BaseModel, Field
from src.backend.common.config import PROJECT_ROOT

PROFILES_DIR = PROJECT_ROOT / "configs" / "models"


class ModelProfile(BaseModel):
    model: str
    aliases: tuple[str, ...] = ()
    reasoning: bool = False
    max_output_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    notes: str = ""


@cache
def _load(directory: Path) -> dict[str, ModelProfile]:
    profiles: dict[str, ModelProfile] = {}
    if not directory.is_dir():
        return profiles
    for path in sorted(directory.glob("*.toml")):
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        profile = ModelProfile(
            model=raw.get("model", path.stem),
            **{key: value for key, value in raw.items() if key != "model"},
        )
        for name in (profile.model, *profile.aliases):
            profiles[name.casefold()] = profile
    return profiles


def profile_for(model: str, directory: Path = PROFILES_DIR) -> ModelProfile | None:
    return _load(directory).get(model.casefold())
