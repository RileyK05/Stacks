from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator
from src.backend.common.schemas.base import (
    BaseRecord,
    UserTier,
    _new_id,
    _now,
)


class UserSubscription(BaseRecord):
    subscription_id: UUID = Field(default_factory=_new_id)
    user_id: UUID
    tier: UserTier
    started_at: datetime = Field(default_factory=_now)
    ended_at: datetime | None = None

    @model_validator(mode="after")
    def _period_consistency(self) -> UserSubscription:
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("subscription cannot end before it starts")
        return self


class GenerationLedgerEntry(BaseRecord):
    """One billed model call. Append-only: spend is inspectable, never edited."""

    ledger_id: UUID = Field(default_factory=_new_id)
    user_id: UUID
    course_id: UUID | None = None
    course_label: str | None = None
    task: str
    model: str
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    overhead_tokens: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=_now)