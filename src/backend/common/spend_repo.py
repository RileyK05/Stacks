from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from psycopg.connection import Connection
from psycopg.rows import dict_row
from src.backend.common.db import connection
from src.backend.common.queries import get
from src.backend.common.schemas.base import KNOWN_GENERATION_TASKS, UserTier
from src.backend.common.schemas.spend import GenerationLedgerEntry, UserSubscription

_FILE = "spend"

WEEK_LENGTH = timedelta(days=7)


def week_start(now: datetime | None = None) -> datetime:
    """Start of the current rolling weekly window (UTC, last Monday 00:00)."""
    reference = now or datetime.now(UTC)
    monday = reference - timedelta(days=reference.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def _to_subscription(row: dict[str, Any]) -> UserSubscription:
    return UserSubscription(
        subscription_id=row["subscription_id"],
        user_id=row["user_id"],
        tier=row["tier"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
    )


def active_subscription(user_id: UUID) -> UserSubscription | None:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "active_subscription"), {"user_id": user_id}
        ).fetchone()
    if row is None:
        return None
    return _to_subscription(row)


def active_subscription_on(
    conn: Connection, user_id: UUID
) -> UserSubscription | None:
    """active_subscription on a caller-supplied connection: participates in
    the caller's transaction and row locks instead of opening a second one.
    Money-path checks (premium redemption) must use this variant — reading
    subscription state on a second connection while holding locks elsewhere
    is a lock-ordering invariant that is easy to break silently."""
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "active_subscription"), {"user_id": user_id}
        ).fetchone()
    if row is None:
        return None
    return _to_subscription(row)


def insert_subscription(
    conn: Connection, user_id: UUID, tier: UserTier
) -> UserSubscription:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "start_subscription"),
            {"user_id": user_id, "tier": tier.value},
        ).fetchone()
    assert row is not None
    return _to_subscription(row)


def start_subscription(user_id: UUID, tier: UserTier) -> UserSubscription:
    with connection() as conn:
        subscription = insert_subscription(conn, user_id, tier)
        conn.commit()
    return subscription


def end_active_subscription(user_id: UUID) -> UserSubscription | None:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "end_active_subscription"), {"user_id": user_id}
        ).fetchone()
        conn.commit()
    if row is None:
        return None
    return _to_subscription(row)


def weekly_spend(user_id: UUID, now: datetime | None = None) -> int:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "weekly_spend"),
            {"user_id": user_id, "week_start": week_start(now)},
        ).fetchone()
    assert row is not None
    return int(row["spent"])


def record_generation(
    user_id: UUID,
    task: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    course_id: UUID | None = None,
    course_label: str | None = None,
    overhead_tokens: int = 0,
) -> GenerationLedgerEntry:
    if task not in KNOWN_GENERATION_TASKS:
        raise ValueError(f"unknown generation task: {task}")
    if input_tokens < 0 or output_tokens < 0 or overhead_tokens < 0:
        raise ValueError("token counts cannot be negative")
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "record"),
            {
                "user_id": user_id,
                "course_id": course_id,
                "course_label": course_label,
                "task": task,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "overhead_tokens": overhead_tokens,
            },
        ).fetchone()
        conn.commit()
    assert row is not None
    return _to_entry(row)


def _to_entry(row: dict[str, Any]) -> GenerationLedgerEntry:
    return GenerationLedgerEntry(
        ledger_id=row["ledger_id"],
        user_id=row["user_id"],
        course_id=row["course_id"],
        course_label=row["course_label"],
        task=row["task"],
        model=row["model"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        overhead_tokens=row["overhead_tokens"],
        created_at=row["created_at"],
    )


def ledger_page(user_id: UUID, limit: int = 50) -> list[GenerationLedgerEntry]:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            get(_FILE, "ledger_page"), {"user_id": user_id, "limit": limit}
        ).fetchall()
    return [_to_entry(row) for row in rows]
