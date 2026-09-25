"""The local model runtime: which models fit this machine, downloads with
progress, models the user adds (a Hugging Face link or a local .gguf),
and starting/stopping the bundled llama.cpp server."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from src.backend.runtime import hardware, model_store, user_models
from src.backend.runtime.config import load_runtime_config
from src.backend.runtime.server import RuntimeUnavailableError, get_server
from src.backend.runtime.user_models import AddModelError

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
    added_by_user: bool = False
    source: str = ""


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


class LinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=500)


class GgufFileView(BaseModel):
    file: str
    size_bytes: int


class LinkView(BaseModel):
    repo: str
    files: list[GgufFileView]
    # The file the link itself pointed at, if it named one.
    selected: str | None


class AddModelRequest(BaseModel):
    """Exactly one of: a Hugging Face link (+ the chosen file when the link
    names only the repository), or a path to a .gguf on this computer."""

    model_config = ConfigDict(extra="forbid")

    url: str | None = Field(default=None, max_length=500)
    file: str | None = Field(default=None, max_length=500)
    path: str | None = Field(default=None, max_length=2000)


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
    for model in user_models.all_models():
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
                added_by_user=model.added_by_user,
                source=model.local_path
                or (f"huggingface.co/{model.repo}" if model.repo else ""),
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
    if user_models.find_model(model_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown model: {model_id}")


@router.get("", response_model=RuntimeView)
def get_runtime() -> RuntimeView:
    return _overview()


@router.post("/models/{model_id}/download", response_model=RuntimeView)
def download_model(model_id: str) -> RuntimeView:
    _require_model(model_id)
    try:
        model_store.start_download(model_id)
    except KeyError as err:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "this model is a file on your computer"
        ) from err
    return _overview()


@router.delete("/models/{model_id}/download", response_model=RuntimeView)
def cancel_download(model_id: str) -> RuntimeView:
    _require_model(model_id)
    model_store.cancel_download(model_id)
    return _overview()


@router.delete("/models/{model_id}", response_model=RuntimeView)
def delete_model(model_id: str) -> RuntimeView:
    """Delete the app's own copy, and forget a model the user added. Files
    in another app's folder (LM Studio), or a .gguf the user pointed at,
    are never touched."""
    model = user_models.find_model(model_id)
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown model: {model_id}")
    if get_server().status().model_id == model_id:
        get_server().stop()
    if model.local_path is None:
        model_store.delete_model(model)
    if model.added_by_user:
        user_models.remove(model_id)
    return _overview()


@router.post("/models/inspect", response_model=LinkView)
def inspect_link(payload: LinkRequest) -> LinkView:
    """The GGUF files behind a Hugging Face link, to choose one to add."""
    try:
        link = user_models.parse_link(payload.url)
        files = user_models.gguf_files(link)
    except AddModelError as err:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(err)) from err
    if not files:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "that repository has no GGUF files (Stacks runs GGUF models)",
        )
    return LinkView(
        repo=link.repo,
        files=[GgufFileView(file=f.file, size_bytes=f.size_bytes) for f in files],
        selected=link.file,
    )


@router.post("/models", response_model=RuntimeView, status_code=status.HTTP_201_CREATED)
def add_model(payload: AddModelRequest) -> RuntimeView:
    """Add a model to the list. A Hugging Face model starts downloading
    right away; a local file is ready as soon as it has been checked."""
    try:
        if payload.path:
            user_models.add_from_file(Path(payload.path))
        elif payload.url:
            added = user_models.add_from_huggingface(payload.url, payload.file)
            model_store.start_download(added.id)
        else:
            raise AddModelError("paste a Hugging Face link or choose a .gguf file")
    except AddModelError as err:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(err)) from err
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
