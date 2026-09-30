import tomllib
from functools import cache

from pydantic import BaseModel, Field
from src.backend.common.config import PROJECT_ROOT


class CompanionPolicy(BaseModel):
    version: int
    max_document_chars: int = Field(gt=0)
    max_upload_bytes: int = Field(gt=0)
    document_context_chars: int = Field(gt=0)
    history_context_chars: int = Field(gt=0)
    source_context_chars: int = Field(gt=0)
    section_chars: int = Field(gt=0)
    capture_timeout_seconds: int = Field(gt=0)


@cache
def load_companion_policy() -> CompanionPolicy:
    with (PROJECT_ROOT / "configs/companion.toml").open("rb") as handle:
        return CompanionPolicy.model_validate(tomllib.load(handle))
