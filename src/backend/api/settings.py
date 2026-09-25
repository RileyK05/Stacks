"""Settings API: which model serves which task, API keys, and usage.

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
from src.backend.common.providers import ProviderChoice, TaskClass
from src.backend.common.schemas.usage import UsageLedgerEntry

router = APIRouter(prefix="/settings", tags=["settings"])


class PresetView(BaseModel):
    name: str
    label: str
    base_url: str
    default_model: str
    requires_key: bool
    disclosure: bool
    has_key: bool


class ResolvedView(BaseModel):
    name: str
    base_url: str
    model: str
    is_local: bool


class ProvidersView(BaseModel):
    presets: list[PresetView]
    choices: dict[TaskClass, ProviderChoice | None]
    resolved: dict[TaskClass, ResolvedView | None]


class KeyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=500)


class ConnectionTest(BaseModel):
    ok: bool
    models: list[str] = Field(default_factory=list)
    error: str | None = None


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


def _overview() -> ProvidersView:
    config = providers.load_models_config()
    presets = [
        PresetView(
            **preset.model_dump(),
            has_key=bool(secrets.get_api_key(preset.name))
            if preset.requires_key or preset.name == "custom"
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
            )
            if endpoint is not None
            else None
        )
    return ProvidersView(presets=presets, choices=choices, resolved=resolved)


def _require_preset(name: str) -> None:
    if name not in providers.load_models_config().presets:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown provider: {name}")


@router.get("/providers", response_model=ProvidersView)
def get_providers() -> ProvidersView:
    return _overview()


@router.put("/providers/{task_class}", response_model=ProvidersView)
def set_provider(task_class: TaskClass, choice: ProviderChoice) -> ProvidersView:
    _require_preset(choice.preset)
    providers.save_choice(task_class, choice)
    return _overview()


@router.delete("/providers/{task_class}", response_model=ProvidersView)
def clear_provider(task_class: TaskClass) -> ProvidersView:
    providers.clear_choice(task_class)
    return _overview()


@router.put("/keys/{preset}", status_code=status.HTTP_204_NO_CONTENT)
def set_key(preset: str, payload: KeyUpdate) -> None:
    _require_preset(preset)
    secrets.set_api_key(preset, payload.key.strip())


@router.delete("/keys/{preset}", status_code=status.HTTP_204_NO_CONTENT)
def delete_key(preset: str) -> None:
    _require_preset(preset)
    secrets.delete_api_key(preset)


@router.post("/providers/{task_class}/test", response_model=ConnectionTest)
def test_provider(task_class: TaskClass) -> ConnectionTest:
    """Check the resolved endpoint by listing its models (GET /models):
    proves the URL and key work without spending any tokens."""
    endpoint = providers.resolve(task_class)
    if endpoint is None:
        return ConnectionTest(ok=False, error="no provider configured")
    headers = (
        {"Authorization": f"Bearer {endpoint.api_key}"} if endpoint.api_key else {}
    )
    try:
        response = httpx.get(
            endpoint.base_url.rstrip("/") + "/models",
            headers=headers,
            timeout=httpx.Timeout(15.0),
        )
        response.raise_for_status()
        body: Any = response.json()
        models = sorted(
            str(item["id"]) for item in body.get("data", []) if "id" in item
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as err:
        return ConnectionTest(ok=False, error=str(err))
    return ConnectionTest(ok=True, models=models)


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
