from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field
from src.backend.common.schemas.base import BaseRecord, _new_id, _now


class UsageLedgerEntry(BaseRecord):
    """One model call's real token counts (from the provider's usage
    response, never estimated). Append-only and informational: locally
    there is no operator to bill, only a user who may want to see — or
    cap — what their own cloud keys spend."""

    ledger_id: UUID = Field(default_factory=_new_id)
    course_id: UUID | None = None
    course_label: str | None = None
    task: str
    provider: str
    model: str
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=_now)
