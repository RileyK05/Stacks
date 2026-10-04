from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field
from src.backend.common.schemas.base import BaseRecord, _new_id, _now


class UsageLedgerEntry(BaseRecord):
    """One model call's supplied token counts and reporting completeness.
    Missing counts contribute zero but are not measurements. Append-only:
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
    usage_reported: bool | None = None
    created_at: datetime = Field(default_factory=_now)


class CloudUsage(BaseRecord):
    reported_tokens: int = Field(ge=0)
    calls_without_usage: int = Field(ge=0)
