"""Settings API: connections (endpoints + keys), which model serves which
task, the chat model picker's options, and usage.

Keys are write-only through this API: they go straight to the OS
keyring and are never returned — the UI only learns whether one is set.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from src.backend.common import providers, secrets, usage_repo
from src.backend.common.providers import (
    Connection,
    ProviderChoice,
    TaskClass,
    UnknownConnectionError,
)
from src.backend.common.schemas.usage import UsageLedgerEntry
from src.backend.runtime import model_store, user_models
from src.backend.runtime.config import CatalogModel

router = APIRouter(prefix="/settings", tags=["settings"])


class PresetView(BaseModel):
    name: str
    label: str
    base_url: str
    default_model: str
    requires_key: bool
    accepts_key: bool
    disclosure: bool
    # Kept for the pre-connection UI: whether the connection named after
    # this preset has a key.
    has_key: bool


class ConnectionView(BaseModel):
    id: str
    preset: str
    name: str
    # What the user set (None: the preset's) and what is actually used.
    base_url: str | None
    default_model: str | None
    effective_base_url: str
    effective_default_model: str
    requires_key: bool
    accepts_key: bool
    has_key: bool
    disclosure: bool
    is_local: bool
    builtin: bool


class ResolvedView(BaseModel):
    name: str
    base_url: str
    model: str
    is_local: bool
    connection: str
    label: str


class ProvidersView(BaseModel):
    presets: list[PresetView]
    connections: list[ConnectionView]
    choices: dict[TaskClass, ProviderChoice | None]
    resolved: dict[TaskClass, ResolvedView | None]


class ConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: str = Field(min_length=1, max_length=40)
    name: str | None = Field(default=None, max_length=80)
    base_url: str | None = Field(default=None, max_length=500)
    default_model: str | None = Field(default=None, max_length=200)
    key: str | None = Field(default=None, max_length=500)


class ConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    base_url: str | None = Field(default=None, max_length=500)
    default_model: str | None = Field(default=None, max_length=200)


class KeyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=500)


class ConnectionTest(BaseModel):
    ok: bool
    models: list[str] = Field(default_factory=list)
    error: str | None = None


class ModelOption(BaseModel):
    """One entry in the chat's model picker."""

    connection: str
    connection_name: str
    model: str
    label: str
    is_local: bool
    # False: listed, but it can't answer yet (not downloaded, no key).
    available: bool
    note: str = ""


class BudgetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monthly_cloud_token_budget: int | None = Field(default=None, ge=1)


class UsageTotal(BaseModel):
    provider: str
    model: str
    task: str
    calls: int
    input_tokens: int
    output_tokens: int


class UsageView(BaseModel):
    month_start: datetime
    cloud_tokens_this_month: int
    monthly_cloud_token_budget: int | None
    totals: list[UsageTotal]
    recent: list[UsageLedgerEntry]


def _connection_view(connection: Connection) -> ConnectionView:
    preset = providers.load_models_config().presets[connection.preset]
    wants_key = preset.requires_key or preset.accepts_key
    return ConnectionView(
        id=connection.id,
        preset=connection.preset,
        name=connection.name,
        base_url=connection.base_url,
        default_model=connection.default_model,
        effective_base_url=connection.base_url or preset.base_url,
        effective_default_model=connection.default_model or preset.default_model,
        requires_key=preset.requires_key,
        accepts_key=preset.accepts_key,
        has_key=providers.has_key(connection) if wants_key else False,
        disclosure=preset.disclosure,
        is_local=connection.preset == providers.LOCAL,
        builtin=connection.id == providers.LOCAL,
    )


def _overview() -> ProvidersView:
    config = providers.load_models_config()
    presets = [
        PresetView(
            **preset.model_dump(),
            has_key=bool(secrets.get_api_key(preset.name))
            if preset.requires_key or preset.accepts_key
            else False,
        )
        for preset in config.presets.values()
    ]
    choices = {cls: providers.saved_choice(cls) for cls in TaskClass}
    resolved: dict[TaskClass, ResolvedView | None] = {}
    for cls in TaskClass:
        endpoint = providers.resolve(cls)
        resolved[cls] = (
            ResolvedView(
                name=endpoint.name,
                base_url=endpoint.base_url,
                model=endpoint.model,
                is_local=endpoint.is_local,
                connection=endpoint.connection,
                label=endpoint.label,
            )
            if endpoint is not None
            else None
        )
    return ProvidersView(
        presets=presets,
        connections=[_connection_view(c) for c in providers.list_connections()],
        choices=choices,
        resolved=resolved,
    )


def _require_connection(connection_id: str) -> Connection:
    connection = providers.get_connection(connection_id)
    if connection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown connection")
    return connection


def _connection_for_key(name: str) -> Connection:
    """Keys are set per connection. A preset name is accepted too (the
    pre-connection form): it names — and on first use creates — the
    connection of the same id."""
    found = providers.get_connection(name)
    if found is not None:
        return found
    if name in providers.load_models_config().presets and name != providers.LOCAL:
        return providers.add_connection(name, connection_id=name)
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown connection: {name}")


@router.get("/providers", response_model=ProvidersView)
def get_providers() -> ProvidersView:
    return _overview()


@router.put("/providers/{task_class}", response_model=ProvidersView)
def set_provider(task_class: TaskClass, choice: ProviderChoice) -> ProvidersView:
    try:
        providers.save_choice(task_class, choice)
    except UnknownConnectionError as err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(err)) from err
    return _overview()


@router.delete("/providers/{task_class}", response_model=ProvidersView)
def clear_provider(task_class: TaskClass) -> ProvidersView:
    providers.clear_choice(task_class)
    return _overview()


@router.post(
    "/connections", response_model=ConnectionView, status_code=status.HTTP_201_CREATED
)
def add_connection(payload: ConnectionCreate) -> ConnectionView:
    try:
        connection = providers.add_connection(
            payload.preset,
            name=payload.name,
            base_url=payload.base_url,
            default_model=payload.default_model,
        )
    except UnknownConnectionError as err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(err)) from err
    except ValueError as err:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(err)) from err
    if payload.key and payload.key.strip():
        secrets.set_api_key(connection.id, payload.key.strip())
    return _connection_view(connection)


@router.patch("/connections/{connection_id}", response_model=ConnectionView)
def update_connection(connection_id: str, payload: ConnectionUpdate) -> ConnectionView:
    _require_connection(connection_id)
    try:
        updated = providers.update_connection(
            connection_id,
            name=payload.name,
            base_url=payload.base_url,
            default_model=payload.default_model,
        )
    except UnknownConnectionError as err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(err)) from err
    except ValueError as err:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(err)) from err
    return _connection_view(updated)


@router.delete("/connections/{connection_id}", response_model=ProvidersView)
def remove_connection(connection_id: str) -> ProvidersView:
    _require_connection(connection_id)
    try:
        providers.remove_connection(connection_id)
    except ValueError as err:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(err)) from err
    return _overview()


@router.put("/keys/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def set_key(connection_id: str, payload: KeyUpdate) -> None:
    connection = _connection_for_key(connection_id)
    secrets.set_api_key(connection.id, payload.key.strip())


@router.delete("/keys/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_key(connection_id: str) -> None:
    connection = _connection_for_key(connection_id)
    secrets.delete_api_key(connection.id)


def _list_models(base_url: str, api_key: str | None) -> ConnectionTest:
    """GET /models on an OpenAI-compatible endpoint: proves the URL and key
    work without spending any tokens."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        response = httpx.get(
            base_url.rstrip("/") + "/models",
            headers=headers,
            timeout=httpx.Timeout(15.0),
        )
        if response.status_code in (401, 403):
            return ConnectionTest(ok=False, error="the key was not accepted")
        response.raise_for_status()
        body: Any = response.json()
        models = sorted(
            str(item["id"]) for item in body.get("data", []) if "id" in item
        )
    except httpx.ConnectError:
        return ConnectionTest(
            ok=False,
            error=f"nothing is answering at {base_url}. Is the server running?",
        )
    except httpx.TimeoutException:
        return ConnectionTest(ok=False, error=f"{base_url} did not answer in time")
    except httpx.HTTPStatusError as err:
        return ConnectionTest(
            ok=False, error=f"the server answered {err.response.status_code}"
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as err:
        return ConnectionTest(ok=False, error=str(err))
    return ConnectionTest(ok=True, models=models)


@router.post("/providers/{task_class}/test", response_model=ConnectionTest)
def test_provider(task_class: TaskClass) -> ConnectionTest:
    endpoint = providers.resolve(task_class)
    if endpoint is None:
        return ConnectionTest(ok=False, error="no provider configured")
    return _list_models(endpoint.base_url, endpoint.api_key)


def _local_models() -> list[CatalogModel]:
    return user_models.all_models()


@router.post("/connections/{connection_id}/test", response_model=ConnectionTest)
def test_connection(connection_id: str) -> ConnectionTest:
    """The models a connection offers. The built-in local connection lists
    the models downloaded on this computer (its server may be stopped)."""
    connection = _require_connection(connection_id)
    if connection.id == providers.LOCAL:
        installed = [
            m.id
            for m in _local_models()
            if model_store.locate(m, verify=False)[1] in ("app", "external")
        ]
        return ConnectionTest(ok=True, models=installed)
    view = _connection_view(connection)
    if not view.effective_base_url:
        return ConnectionTest(ok=False, error="this connection has no URL yet")
    if view.requires_key and not view.has_key:
        return ConnectionTest(ok=False, error="add an API key first")
    return _list_models(view.effective_base_url, secrets.get_api_key(connection.id))


@router.get("/model-options", response_model=list[ModelOption])
def model_options() -> list[ModelOption]:
    """What the chat's model picker offers: every local model (downloaded
    ones available), then each connection's default model. Any other
    model a connection serves can be typed in the picker."""
    options: list[ModelOption] = []
    local = providers.get_connection(providers.LOCAL)
    assert local is not None
    for model in _local_models():
        _path, where = model_store.locate(model, verify=False)
        installed = where in ("app", "external")
        options.append(
            ModelOption(
                connection=local.id,
                connection_name="On this computer",
                model=model.id,
                label=model.label,
                is_local=True,
                available=installed,
                note="" if installed else "Download it in Settings",
            )
        )
    for connection in providers.list_connections():
        if connection.id == providers.LOCAL:
            continue
        view = _connection_view(connection)
        default_model = view.effective_default_model
        if not default_model:
            continue
        ready = bool(view.effective_base_url) and (
            view.has_key or not view.requires_key
        )
        options.append(
            ModelOption(
                connection=connection.id,
                connection_name=connection.name,
                model=default_model,
                label=default_model,
                is_local=False,
                available=ready,
                note="" if ready else "Add its API key in Settings",
            )
        )
    return options


@router.get("/usage", response_model=UsageView)
def get_usage() -> UsageView:
    start = usage_repo.month_start()
    return UsageView(
        month_start=start,
        cloud_tokens_this_month=usage_repo.cloud_tokens_this_month(),
        monthly_cloud_token_budget=usage_repo.monthly_budget(),
        totals=[UsageTotal(**row) for row in usage_repo.totals_since(start)],
        recent=usage_repo.ledger_page(limit=50),
    )


@router.put("/usage/budget", response_model=UsageView)
def set_budget(payload: BudgetUpdate) -> UsageView:
    usage_repo.set_monthly_budget(payload.monthly_cloud_token_budget)
    return get_usage()
