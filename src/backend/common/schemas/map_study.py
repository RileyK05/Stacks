from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MapOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: UUID | None = None
    item_index: int = Field(default=0, ge=0)
    artifact_id: UUID | None = None
    artifact_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _one_origin(self) -> MapOrigin:
        if bool(self.message_id) == bool(self.artifact_id):
            raise ValueError("choose a saved message or map artifact")
        if self.artifact_id and self.artifact_version is None:
            raise ValueError("a saved map needs its version")
        return self


class MapStudyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: MapOrigin
    node_id: str = Field(min_length=1, max_length=40)
    action: Literal["explain", "quiz"]
    request_id: UUID
