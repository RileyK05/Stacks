"""The single hosted-model seam.

Every model call in the backend goes through `generate`: task + prompt
in, text out — gated, routed, billed. Providers are an implementation
detail behind this one function; swapping providers never touches
ingestion/tutor code.

Contract (enforced here, not by callers remembering):
- the tier is resolved and verified from the account inside this seam —
  no caller-supplied TierPolicy, so a stale/spoofed tier can never route
  ingestion to paid models;
- the budget gate runs BEFORE the provider call (in-flight calls are
  never cut off; the gate tightens the next request only);
- the ledger row is recorded AFTER the call with the call's real token
  counts, even if the caller's access lapsed mid-flight — spend must be
  visible;
- task-to-pool routing is symmetric: ingestion tasks must bill the
  ingestion pool, interactive tasks must bill the generation pool. The
  task classification lives in `schemas/base.py` next to the task list
  (single source of truth).

Milestone-1 status: everything above is wired and tested except the
provider HTTP call itself — `_call_provider` raises ProviderUnavailable
until the operator picks a provider and the no-retention check passes.
When it lands, the token counts must come from the provider response, not
from the caller. Only `_call_provider` + `_parse_usage` change.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.backend.common import budget, spend_repo
from src.backend.common.schemas.base import (
    INGESTION_TASKS,
    KNOWN_GENERATION_TASKS,
    SpendKind,
    UserTier,
)
from src.backend.common.tiers import load_tier_policies


@dataclass(frozen=True)
class GenerationResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


class ProviderUnavailableError(RuntimeError):
    """Raised when no provider client is configured. Callers surface this
    as a retryable stage failure, not a crash."""


class EmptyModelError(RuntimeError):
    """The provider returned no usable text. Stages must fail on this —
    a model stage that 'succeeds' while writing no rows is a false
    success that empties the course knowledge base."""


def generate(
    task: str,
    prompt: str,
    user_id: UUID,
    tier: UserTier,
    *,
    course_id: UUID | None = None,
) -> GenerationResult:
    """One gated, routed, billed model call. `tier` is verified against
    the account inside; the pool is derived from the task, never passed
    in."""
    if task not in KNOWN_GENERATION_TASKS:
        raise ValueError(f"unknown generation task: {task}")
    spend_kind = (
        SpendKind.INGESTION if task in INGESTION_TASKS else SpendKind.GENERATION
    )
    budget.verify_tier(user_id, tier)
    policy = load_tier_policies().policy_for(tier)
    budget.check_budget(
        user_id,
        tier,
        policy,
        spend_kind=spend_kind,
    )
    model = policy.model_for(task)
    raw_text, input_tokens, output_tokens = _call_provider(task, model, prompt)
    if not raw_text.strip():
        raise EmptyModelError(task)
    result = GenerationResult(
        text=raw_text,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    spend_repo.record_generation(
        user_id,
        task,
        result.model,
        result.input_tokens,
        result.output_tokens,
        course_id=course_id,
        spend_kind=spend_kind,
        overhead_tokens=budget.free_tier_overhead(
            policy, result.input_tokens + result.output_tokens
        ),
    )
    return result


def _call_provider(
    task: str, model: str, prompt: str
) -> tuple[str, int, int]:
    """The provider HTTP call. Intentionally unimplemented until the
    operator picks a provider and the no-retention policy is verified.
    Returns (text, input_tokens, output_tokens) — token counts come from
    the provider's usage response, never estimated by the caller."""
    raise ProviderUnavailableError(
        f"no provider client configured yet (task={task}, model={model})"
    )