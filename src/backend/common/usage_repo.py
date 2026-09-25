"""The usage ledger (plan §7.4): one row per model call with the real
token counts from the provider's usage response. Informational for local
calls; for cloud providers an optional user-set monthly token budget
blocks the NEXT call once reached (never cuts off one in flight)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from src.backend.common import settings_repo
from src.backend.common.db import connection, utc_now
from src.backend.common.queries import get
from src.backend.common.schemas.usage import UsageLedgerEntry

_FILE = "usage"
BUDGET_SETTING = "usage.monthly_cloud_token_budget"


class BudgetExceededError(RuntimeError):
    def __init__(self, spent: int, budget: int) -> None:
        self.spent = spent
        self.budget = budget
        super().__init__(
            f"monthly cloud token budget reached ({spent}/{budget}); "
            "raise it in Settings or switch to the local model"
        )


def _to_entry(row: dict[str, Any]) -> UsageLedgerEntry:
    return UsageLedgerEntry(**row)


def record(
    *,
    task: str,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    course_id: UUID | None = None,
) -> UsageLedgerEntry:
    with connection() as conn:
        row = conn.execute(
            get(_FILE, "record"),
            {
                "ledger_id": uuid4(),
                "course_id": course_id,
                "task": task,
                "provider": provider,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
        ).fetchone()
        conn.commit()
    assert row is not None
    return _to_entry(row)


def ledger_page(limit: int = 50) -> list[UsageLedgerEntry]:
    with connection() as conn:
        rows = conn.execute(get(_FILE, "ledger_page"), {"limit": limit}).fetchall()
    return [_to_entry(row) for row in rows]


def month_start(now: datetime | None = None) -> datetime:
    reference = now or utc_now()
    return reference.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def cloud_tokens_this_month(now: datetime | None = None) -> int:
    with connection() as conn:
        row = conn.execute(
            get(_FILE, "cloud_tokens_since"), {"since": month_start(now)}
        ).fetchone()
    return int(row["spent"]) if row else 0


def totals_since(since: datetime) -> list[dict[str, Any]]:
    with connection() as conn:
        return conn.execute(get(_FILE, "totals_since"), {"since": since}).fetchall()


def monthly_budget() -> int | None:
    value = settings_repo.get_setting(BUDGET_SETTING)
    return int(value) if value is not None else None


def set_monthly_budget(budget: int | None) -> None:
    if budget is None:
        settings_repo.delete_setting(BUDGET_SETTING)
    else:
        settings_repo.put_setting(BUDGET_SETTING, int(budget))


def check_cloud_budget(now: datetime | None = None) -> None:
    """Raise when a cloud budget is set and already reached."""
    budget = monthly_budget()
    if budget is None:
        return
    spent = cloud_tokens_this_month(now)
    if spent >= budget:
        raise BudgetExceededError(spent, budget)
