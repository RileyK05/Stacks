from __future__ import annotations

import tomllib
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from src.backend.common.config import PROJECT_ROOT

DEFAULT_RUNTIME_PATH = PROJECT_ROOT / "configs" / "runtime.toml"

Tier = Literal["starter", "standard", "large"]


class Asset(BaseModel):
    file: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)


class LlamaCppConfig(BaseModel):
    build: str
    port: int = Field(ge=1024, le=65535)
    context_size: int = Field(ge=512)
    reasoning_budget: int
    startup_timeout_seconds: float = Field(gt=0)
    assets: dict[str, Asset]

    def download_url(self, asset: Asset) -> str:
        return (
            "https://github.com/ggml-org/llama.cpp/releases/download/"
            f"{self.build}/{asset.file}"
        )


class CatalogModel(BaseModel):
    id: str
    label: str
    tier: Tier
    repo: str
    file: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)
    min_ram_gb: int = Field(ge=1)
    license: str
    notes: str = ""
    revision: str = "main"
    # Models the user added (runtime/user_models.py). `local_path` is a
    # .gguf they pointed at on this computer: used in place, never copied.
    added_by_user: bool = False
    local_path: str | None = None

    @property
    def download_url(self) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{self.file}"


class RuntimeConfig(BaseModel):
    runtime_config_version: str
    llama_cpp: LlamaCppConfig
    models: list[CatalogModel]

    def model(self, model_id: str) -> CatalogModel | None:
        return next((m for m in self.models if m.id == model_id), None)


@cache
def _load(path: Path) -> RuntimeConfig:
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    return RuntimeConfig(
        runtime_config_version=raw["version"]["runtime_config_version"],
        llama_cpp=LlamaCppConfig(**raw["llama_cpp"]),
        models=[CatalogModel(**entry) for entry in raw["models"]],
    )


def load_runtime_config(path: Path = DEFAULT_RUNTIME_PATH) -> RuntimeConfig:
    return _load(path)
