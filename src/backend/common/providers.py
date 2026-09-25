"""Which model endpoint serves which task (docs/plan-local-first.md §7).

Two task classes: INTERACTIVE (answers, probes, artifacts — the user is
waiting) and BACKGROUND (ingestion-time generation). The user picks a
provider preset per class in Settings; background falls back to the
interactive choice. A third slot, BIGGER, is the model behind the
per-answer "Ask a bigger model" button (plan §6 item 12): it resolves only
from the user's own saved choice — never automatically, never from the
environment. Resolution order for the first two classes:

1. the user's saved choice (app_settings `provider.<class>`), with its
   key from the OS keyring;
2. for background only: the interactive choice;
3. development fallback: LLM_BASE_URL / LLM_API_KEY / LLM_MODEL from the
   environment or `.env`;
4. nothing — the generation seam fails closed (ProviderUnavailableError).

No provider is restricted by policy: a cloud preset carries a
`disclosure` flag so the UI can tell the user once that course excerpts
leave the machine. The choice is theirs.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from src.backend.common import secrets, settings_repo
from src.backend.common.config import PROJECT_ROOT, get_settings
from src.backend.common.schemas.base import INGESTION_TASKS, KNOWN_GENERATION_TASKS

DEFAULT_MODELS_PATH = PROJECT_ROOT / "configs" / "models.toml"


class TaskClass(StrEnum):
    INTERACTIVE = "interactive"
    BACKGROUND = "background"
    BIGGER = "bigger"


def task_class(task: str) -> TaskClass:
    if task not in KNOWN_GENERATION_TASKS:
        raise ValueError(f"unknown generation task: {task}")
    return TaskClass.BACKGROUND if task in INGESTION_TASKS else TaskClass.INTERACTIVE


class ProviderPreset(BaseModel):
    name: str
    label: str
    base_url: str
    default_model: str
    requires_key: bool
    disclosure: bool


class GenerationDefaults(BaseModel):
    temperature: float = Field(ge=0.0, le=2.0)
    max_output_tokens: int = Field(ge=1)
    enable_thinking: bool
    request_timeout_seconds: float = Field(gt=0)


class ModelsConfig(BaseModel):
    models_config_version: str
    presets: dict[str, ProviderPreset]
    generation: GenerationDefaults


@cache
def _load_models_config(path: Path) -> ModelsConfig:
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    return ModelsConfig(
        models_config_version=raw["version"]["models_config_version"],
        presets={
            name: ProviderPreset(name=name, **values)
            for name, values in raw["presets"].items()
        },
        generation=GenerationDefaults(**raw["generation"]),
    )


def load_models_config(path: Path = DEFAULT_MODELS_PATH) -> ModelsConfig:
    return _load_models_config(path)


class ProviderChoice(BaseModel):
    """What the user saved for one task class. `base_url`/`model` override
    the preset's defaults (required for the custom preset)."""

    preset: str
    base_url: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class ResolvedProvider:
    """A concrete endpoint the generation seam can call."""

    name: str
    base_url: str
    model: str
    api_key: str | None
    is_local: bool


def _setting_key(cls: TaskClass) -> str:
    return f"provider.{cls.value}"


def saved_choice(cls: TaskClass) -> ProviderChoice | None:
    raw: Any = settings_repo.get_setting(_setting_key(cls))
    return ProviderChoice.model_validate(raw) if raw else None


def save_choice(cls: TaskClass, choice: ProviderChoice) -> None:
    presets = load_models_config().presets
    if choice.preset not in presets:
        raise ValueError(f"unknown provider preset: {choice.preset}")
    settings_repo.put_setting(_setting_key(cls), choice.model_dump())


def clear_choice(cls: TaskClass) -> None:
    settings_repo.delete_setting(_setting_key(cls))


def _from_choice(choice: ProviderChoice) -> ResolvedProvider | None:
    preset = load_models_config().presets.get(choice.preset)
    if preset is None:
        return None
    base_url = choice.base_url or preset.base_url
    model = choice.model or preset.default_model
    if not base_url or not model:
        return None
    # Custom endpoints may or may not need a key; look one up either way.
    needs_lookup = preset.requires_key or preset.name == "custom"
    api_key = secrets.get_api_key(preset.name) if needs_lookup else None
    if preset.requires_key and not api_key:
        return None
    return ResolvedProvider(
        name=preset.name,
        base_url=base_url,
        model=model,
        api_key=api_key,
        is_local=preset.name == "local",
    )


def _from_environment() -> ResolvedProvider | None:
    settings = get_settings()
    if not settings.llm_base_url or not settings.llm_model:
        return None
    return ResolvedProvider(
        name="environment",
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key or None,
        is_local=settings.llm_base_url.startswith(
            ("http://127.0.0.1", "http://localhost")
        ),
    )


def resolve(cls: TaskClass) -> ResolvedProvider | None:
    """The endpoint for a task class, or None when nothing is configured."""
    choice = saved_choice(cls)
    if cls == TaskClass.BIGGER:
        return _from_choice(choice) if choice is not None else None
    if choice is None and cls == TaskClass.BACKGROUND:
        choice = saved_choice(TaskClass.INTERACTIVE)
    if choice is not None:
        resolved = _from_choice(choice)
        if resolved is not None:
            return resolved
    return _from_environment()
