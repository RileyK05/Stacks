"""Which model endpoint serves which task (docs/plan-local-first.md §7,
docs/plan-notebook.md §4.8).

**Connections.** The user adds as many endpoints as they like — OpenAI,
Anthropic, OpenRouter, a custom server, their LM Studio — each a
*connection* made from a *preset* (a template in configs/models.toml) with
its own name, URL, default model and API key (in the OS keychain, stored
under the connection's id). The bundled local model is the built-in
`local` connection.

**Choices.** A choice is a connection + model. The user saves one per task
class in Settings; a chat can pin its own (the model picker), and
"Ask a bigger model" uses the BIGGER slot.

Task classes: INTERACTIVE (answers, artifacts — the user is waiting),
BACKGROUND (ingestion-time work, chat summaries), and BIGGER (the per-answer
"Ask a bigger model" button — it resolves only from the user's own saved
choice, never automatically, never from the environment). Resolution order
for the first two:

1. the user's saved choice for the class;
2. for background only: the interactive choice;
3. development fallback: LLM_BASE_URL / LLM_API_KEY / LLM_MODEL from the
   environment or `.env`;
4. nothing — the generation seam fails closed (ProviderUnavailableError).

No provider is restricted by policy: a cloud preset carries a `disclosure`
flag so the UI can tell the user once that course excerpts leave the
machine. The choice is theirs.

A choice written as `ProviderChoice(preset="openai")` (the pre-connection
form, still accepted) means the connection whose id is the preset name,
created from that preset on first use — which is also how keys saved
before connections existed carry over: they were stored under the preset
name.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from src.backend.common import secrets, settings_repo
from src.backend.common.config import PROJECT_ROOT, get_settings
from src.backend.common.schemas.base import INGESTION_TASKS, KNOWN_GENERATION_TASKS

DEFAULT_MODELS_PATH = PROJECT_ROOT / "configs" / "models.toml"
LOCAL = "local"
_CONNECTIONS_KEY = "provider.connections"
_SLUG = re.compile(r"[^a-z0-9]+")
CONNECTION_ID_MAX = 40


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
    # Optional key: some endpoints (custom servers) take one, some don't.
    accepts_key: bool = False


class GenerationDefaults(BaseModel):
    temperature: float = Field(ge=0.0, le=2.0)
    max_output_tokens: int = Field(ge=1)
    enable_thinking: bool
    request_timeout_seconds: float = Field(gt=0)
    answer_mode: Literal["plain", "quotes"] = "plain"


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


class Connection(BaseModel):
    """One endpoint the user has set up. `base_url` / `default_model`
    override the preset's; the API key lives in the keychain under `id`."""

    id: str = Field(min_length=1, max_length=CONNECTION_ID_MAX)
    preset: str
    name: str = Field(min_length=1, max_length=80)
    base_url: str | None = None
    default_model: str | None = None


class ProviderChoice(BaseModel):
    """A connection + model. `model` None means the connection's default.
    `preset` / `base_url` are the pre-connection form (see module doc)."""

    connection: str | None = None
    model: str | None = None
    preset: str | None = None
    base_url: str | None = None

    @model_validator(mode="after")
    def _names_an_endpoint(self) -> ProviderChoice:
        if not self.connection and not self.preset:
            raise ValueError("a choice names a connection")
        return self

    @property
    def connection_id(self) -> str:
        return self.connection or self.preset or ""


@dataclass(frozen=True)
class ResolvedProvider:
    """A concrete endpoint the generation seam can call. `name` is the
    preset (what kind of endpoint); `connection` is which one."""

    name: str
    base_url: str
    model: str
    api_key: str | None
    is_local: bool
    # Which connection this came from and its display name: descriptive,
    # not part of what is called, so not part of equality.
    connection: str = field(default="", compare=False)
    label: str = field(default="", compare=False)


class UnknownConnectionError(ValueError):
    pass


# --- connections -------------------------------------------------------


def _preset(name: str) -> ProviderPreset:
    preset = load_models_config().presets.get(name)
    if preset is None:
        raise UnknownConnectionError(f"unknown provider preset: {name}")
    return preset


def _builtin_local() -> Connection:
    return Connection(id=LOCAL, preset=LOCAL, name=_preset(LOCAL).label)


def _saved_connections() -> list[Connection]:
    raw: Any = settings_repo.get_setting(_CONNECTIONS_KEY) or []
    return [Connection.model_validate(item) for item in raw]


def _store_connections(connections: list[Connection]) -> None:
    settings_repo.put_setting(
        _CONNECTIONS_KEY,
        [c.model_dump() for c in connections if c.id != LOCAL],
    )


def list_connections() -> list[Connection]:
    """The built-in local connection first, then the user's, in the order
    they were added."""
    return [_builtin_local(), *(c for c in _saved_connections() if c.id != LOCAL)]


def get_connection(connection_id: str) -> Connection | None:
    return next((c for c in list_connections() if c.id == connection_id), None)


def _slug(text: str) -> str:
    return _SLUG.sub("-", text.lower()).strip("-")[:CONNECTION_ID_MAX] or "connection"


def add_connection(
    preset: str,
    *,
    name: str | None = None,
    base_url: str | None = None,
    default_model: str | None = None,
    connection_id: str | None = None,
) -> Connection:
    template = _preset(preset)
    if preset == LOCAL:
        raise ValueError("the local model is built in")
    existing = {c.id for c in list_connections()}
    base = connection_id or _slug(name or template.name)
    candidate, counter = base, 2
    while candidate in existing:
        suffix = f"-{counter}"
        candidate = f"{base[: CONNECTION_ID_MAX - len(suffix)]}{suffix}"
        counter += 1
    connection = Connection(
        id=candidate,
        preset=preset,
        name=(name or template.label).strip(),
        base_url=(base_url or "").strip() or None,
        default_model=(default_model or "").strip() or None,
    )
    _store_connections([*_saved_connections(), connection])
    return connection


def update_connection(
    connection_id: str,
    *,
    name: str | None = None,
    base_url: str | None = None,
    default_model: str | None = None,
) -> Connection:
    if connection_id == LOCAL:
        raise ValueError("the local model is built in")
    saved = _saved_connections()
    for index, current in enumerate(saved):
        if current.id == connection_id:
            updated = current.model_copy(
                update={
                    "name": (name if name is not None else current.name).strip(),
                    "base_url": (
                        (base_url.strip() or None)
                        if base_url is not None
                        else current.base_url
                    ),
                    "default_model": (
                        (default_model.strip() or None)
                        if default_model is not None
                        else current.default_model
                    ),
                }
            )
            saved[index] = updated
            _store_connections(saved)
            return updated
    raise UnknownConnectionError(f"unknown connection: {connection_id}")


def remove_connection(connection_id: str) -> None:
    """Delete a connection, its key, and every saved choice that used it."""
    if connection_id == LOCAL:
        raise ValueError("the local model is built in")
    saved = _saved_connections()
    if not any(c.id == connection_id for c in saved):
        raise UnknownConnectionError(f"unknown connection: {connection_id}")
    _store_connections([c for c in saved if c.id != connection_id])
    secrets.delete_api_key(connection_id)
    for cls in TaskClass:
        choice = saved_choice(cls)
        if choice is not None and choice.connection_id == connection_id:
            clear_choice(cls)


def has_key(connection: Connection) -> bool:
    return bool(secrets.get_api_key(connection.id))


def _ensure_connection(choice: ProviderChoice) -> Connection:
    """The connection a choice names, creating it from a preset for the
    pre-connection form."""
    found = get_connection(choice.connection_id)
    if found is not None:
        return found
    if choice.connection is None and choice.preset is not None:
        _preset(choice.preset)
        return add_connection(
            choice.preset, base_url=choice.base_url, connection_id=choice.preset
        )
    raise UnknownConnectionError(f"unknown connection: {choice.connection_id}")


# --- choices -----------------------------------------------------------


def _setting_key(cls: TaskClass) -> str:
    return f"provider.{cls.value}"


def saved_choice(cls: TaskClass) -> ProviderChoice | None:
    raw: Any = settings_repo.get_setting(_setting_key(cls))
    return ProviderChoice.model_validate(raw) if raw else None


def save_choice(cls: TaskClass, choice: ProviderChoice) -> None:
    connection = _ensure_connection(choice)
    normalised = ProviderChoice(connection=connection.id, model=choice.model or None)
    settings_repo.put_setting(
        _setting_key(cls), normalised.model_dump(exclude_none=True)
    )


def clear_choice(cls: TaskClass) -> None:
    settings_repo.delete_setting(_setting_key(cls))


def resolve_choice(choice: ProviderChoice) -> ResolvedProvider | None:
    """The endpoint a choice names, or None when it is incomplete (no URL,
    no model, or a required key missing)."""
    connection = get_connection(choice.connection_id)
    if connection is None:
        if choice.connection is not None or choice.preset is None:
            return None
        preset_config = load_models_config().presets.get(choice.preset)
        if preset_config is None:
            return None
        connection = Connection(
            id=choice.preset, preset=choice.preset, name=preset_config.label
        )
    preset = load_models_config().presets.get(connection.preset)
    if preset is None:
        return None
    base_url = choice.base_url or connection.base_url or preset.base_url
    model = choice.model or connection.default_model or preset.default_model
    if not base_url or not model:
        return None
    wants_key = preset.requires_key or preset.accepts_key
    api_key = secrets.get_api_key(connection.id) if wants_key else None
    if preset.requires_key and not api_key:
        return None
    return ResolvedProvider(
        name=preset.name,
        base_url=base_url,
        model=model,
        api_key=api_key,
        is_local=preset.name == LOCAL,
        connection=connection.id,
        label=connection.name,
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
        connection="environment",
        label="Development endpoint",
    )


def resolve(cls: TaskClass) -> ResolvedProvider | None:
    """The endpoint for a task class, or None when nothing is configured."""
    choice = saved_choice(cls)
    if cls == TaskClass.BIGGER:
        return resolve_choice(choice) if choice is not None else None
    if choice is None and cls == TaskClass.BACKGROUND:
        choice = saved_choice(TaskClass.INTERACTIVE)
    if choice is not None:
        resolved = resolve_choice(choice)
        if resolved is not None:
            return resolved
    return _from_environment()
