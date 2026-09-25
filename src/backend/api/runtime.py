"""The local model runtime: which models fit this machine, downloads with
progress, and starting/stopping the bundled llama.cpp server."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from src.backend.runtime import hardware, model_store
from src.backend.runtime.config import load_runtime_config
from src.backend.runtime.server import RuntimeUnavailableError, get_server

router = APIRouter(prefix="/runtime", tags=["runtime"])


class HardwareView(BaseModel):
    os: str
    arch: str
    ram_gb: float
    logical_cores: int


class DownloadView(BaseModel):
    status: str
    done_bytes: int
    total_bytes: int
    error: str | None


class ModelView(BaseModel):
    id: str
    label: str
    tier: Literal["starter", "standard", "large"]
    size_bytes: int
    min_ram_gb: int
    license: str
    notes: str
    fits: bool
    recommended: bool
    location: str  # app | external | external-unverified | missing
    download: DownloadView | None


class ServerView(BaseModel):
    state: str
    model_id: str | None
    backend: str | None
    port: int
    error: str | None


class RuntimeView(BaseModel):
    hardware: HardwareView
    server: ServerView
    models: list[ModelView]


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str


def _server_view() -> ServerView:
    current = get_server().status()
    return ServerView(
        state=current.state,
        model_id=current.model_id,
        backend=current.backend,
        port=current.port,
        error=current.error,
    )


def _overview() -> RuntimeView:
    config = load_runtime_config()
    machine = hardware.detect()
    recommended = hardware.recommended_model(config, machine)
    models: list[ModelView] = []
    for model in config.models:
        _path, location = model_store.locate(model, verify=False)
        state = model_store.download_status(model.id)
        models.append(
            ModelView(
                id=model.id,
                label=model.label,
                tier=model.tier,
                size_bytes=model.size_bytes,
                min_ram_gb=model.min_ram_gb,
                license=model.license,
                notes=model.notes,
                fits=hardware.fits(model, machine),
                recommended=model.id == recommended.id,
                location=location,
                download=DownloadView(
                    status=state.status,
                    done_bytes=state.done,
                    total_bytes=state.total,
                    error=state.error,
                )
                if state is not None
                else None,
            )
        )
    return RuntimeView(
        hardware=HardwareView(
            os=machine.os,
            arch=machine.arch,
            ram_gb=round(machine.ram_gb, 1),
            logical_cores=machine.logical_cores,
        ),
        server=_server_view(),
        models=models,
    )


def _require_model(model_id: str) -> None:
    if load_runtime_config().model(model_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown model: {model_id}")


@router.get("", response_model=RuntimeView)
def get_runtime() -> RuntimeView:
    return _overview()


@router.post("/models/{model_id}/download", response_model=RuntimeView)
def download_model(model_id: str) -> RuntimeView:
    _require_model(model_id)
    model_store.start_download(model_id)
    return _overview()


@router.delete("/models/{model_id}/download", response_model=RuntimeView)
def cancel_download(model_id: str) -> RuntimeView:
    _require_model(model_id)
    model_store.cancel_download(model_id)
    return _overview()


@router.delete("/models/{model_id}", response_model=RuntimeView)
def delete_model(model_id: str) -> RuntimeView:
    """Delete the app's own copy. Files in another app's folder (LM
    Studio) are never touched."""
    model = load_runtime_config().model(model_id)
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown model: {model_id}")
    if get_server().status().model_id == model_id:
        get_server().stop()
    model_store.delete_model(model)
    return _overview()


@router.post("/start", response_model=ServerView)
def start_server(payload: StartRequest) -> ServerView:
    """Start (or switch) the local model. Blocks until it answers health
    checks — seconds for a small model."""
    _require_model(payload.model_id)
    try:
        get_server().start(payload.model_id)
    except RuntimeUnavailableError as err:
        raise HTTPException(status.HTTP_409_CONFLICT, str(err)) from err
    return _server_view()


@router.post("/stop", response_model=ServerView)
def stop_server() -> ServerView:
    get_server().stop()
    return _server_view()
