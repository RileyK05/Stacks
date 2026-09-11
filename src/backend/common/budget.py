from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from src.backend.common import courses_repo, spend_repo, users_repo
from src.backend.common.schemas.base import SpendKind, UserTier
from src.backend.common.tiers import TierPolicy


class BudgetExceededError(RuntimeError):
    def __init__(self, tier: UserTier, spent: int, budget: int) -> None:
        self.tier = tier
        self.spent = spent
        self.budget = budget
        super().__init__(
            f"{tier.value} tier weekly budget exceeded: {spent}/{budget} tokens"
        )


class CourseLimitExceededError(RuntimeError):
    def __init__(self, tier: UserTier, owned: int, limit: int) -> None:
        self.tier = tier
        self.owned = owned
        self.limit = limit
        super().__init__(
            f"{tier.value} tier allows at most {limit} owned courses "
            f"(currently {owned})"
        )


class StorageLimitExceededError(RuntimeError):
    def __init__(
        self,
        tier: UserTier,
        stored_bytes: int,
        incoming_bytes: int,
        limit: int,
        scope: str,
    ) -> None:
        self.tier = tier
        self.stored_bytes = stored_bytes
        self.incoming_bytes = incoming_bytes
        self.limit = limit
        self.scope = scope
        super().__init__(
            f"{tier.value} tier allows at most {limit} bytes {scope} "
            f"(stored {stored_bytes}, incoming {incoming_bytes})"
        )


class TierMismatchError(RuntimeError):
    def __init__(self, expected: UserTier, actual: UserTier) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"tier mismatch: caller supplied {expected.value} "
            f"but the account is {actual.value}"
        )


@dataclass(frozen=True)
class BudgetState:
    tier: UserTier
    spent: int
    budget: int
    remaining: int
    week_start: datetime


def verify_tier(user_id: UUID, tier: UserTier) -> None:
    """Double-verify the caller-supplied tier against the account record so a
    stale or spoofed tier can never unlock paid limits. Endpoints resolve the
    tier from the authenticated account and pass it here."""
    account = users_repo.get_by_id(user_id)
    if account is None:
        raise ValueError(f"unknown user: {user_id}")
    if account.tier != tier:
        raise TierMismatchError(tier, account.tier)


def check_budget(
    user_id: UUID,
    tier: UserTier,
    policy: TierPolicy,
    *,
    now: datetime | None = None,
    spent: int | None = None,
    spend_kind: SpendKind,
) -> BudgetState:
    """Inspectable budget check. Callers gate model compute on this, then
    record spend via `spend_repo.record_generation` after the call completes.
    In-flight generations are never cut off mid-answer; the gate applies to
    the *next* request only. `spend_kind` selects the pool: generation
    (interactive) or ingestion (bulk upload work) — the two budgets are
    independent weekly pools."""
    reference = now or datetime.now(UTC)
    current_week_start = spend_repo.week_start(reference)
    budget = (
        policy.ingestion_token_budget
        if spend_kind == SpendKind.INGESTION
        else policy.weekly_token_budget
    )
    current_spent = (
        spend_repo.weekly_spend(user_id, reference, spend_kind=spend_kind)
        if spent is None
        else spent
    )
    if current_spent > budget:
        raise BudgetExceededError(tier, current_spent, budget)
    return BudgetState(
        tier=tier,
        spent=current_spent,
        budget=budget,
        remaining=budget - current_spent,
        week_start=current_week_start,
    )


def check_course_limit(
    owner_user_id: UUID, tier: UserTier, policy: TierPolicy
) -> None:
    """Gate course creation: raise if the owner already holds their tier's
    maximum of courses. Enrollment does not count; ownership does. Course
    deletion frees the slot."""
    owned = courses_repo.count_owned_courses(owner_user_id)
    if owned >= policy.max_owned_courses:
        raise CourseLimitExceededError(tier, owned, policy.max_owned_courses)


def check_course_storage(
    course_id: UUID,
    tier: UserTier,
    policy: TierPolicy,
    incoming_bytes: int,
) -> int:
    """Gate source upload against the per-course cap. Returns the projected
    course total. Call before writing the file. In-course dedup by file_hash
    happens upstream, so re-uploads of stored bytes are free."""
    if incoming_bytes < 0:
        raise ValueError("incoming_bytes cannot be negative")
    stored = courses_repo.course_storage_bytes(course_id)
    projected = stored + incoming_bytes
    if projected > policy.max_course_storage_bytes:
        raise StorageLimitExceededError(
            tier, stored, incoming_bytes, policy.max_course_storage_bytes, "per course"
        )
    return projected


def check_total_storage(
    owner_user_id: UUID,
    tier: UserTier,
    policy: TierPolicy,
    incoming_bytes: int,
) -> int:
    """Gate source upload against the owner's aggregate storage cap across all
    owned courses, so storage cannot be multiplied by making more courses."""
    if incoming_bytes < 0:
        raise ValueError("incoming_bytes cannot be negative")
    stored = courses_repo.total_storage_bytes(owner_user_id)
    projected = stored + incoming_bytes
    if projected > policy.max_total_storage_bytes:
        raise StorageLimitExceededError(
            tier, stored, incoming_bytes, policy.max_total_storage_bytes, "total"
        )
    return projected


def free_tier_overhead(policy: TierPolicy, base_tokens: int) -> int:
    """Extra tokens charged to free-tier users per generation, per
    `free_tier_overhead_percent` in tier policy. Paid tiers carry 0. Applied
    when recording spend, not when gating: an in-flight answer is never
    truncated, the overhead only tightens the *next* budget check."""
    if base_tokens < 0:
        raise ValueError("base_tokens cannot be negative")
    return (base_tokens * policy.free_tier_overhead_percent) // 100