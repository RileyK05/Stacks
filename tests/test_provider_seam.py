from uuid import uuid4

import pytest
from src.backend.common import provider, spend_repo, users_repo
from src.backend.common.auth import hash_password
from src.backend.common.schemas.base import SpendKind, UserTier
from src.backend.common.tiers import load_tier_policies


def _user():
    return users_repo.create(
        "Provider Tester",
        f"{uuid4().hex}@test.invalid",
        hash_password("long-password"),
    )


def test_ingestion_task_bills_ingestion_pool(monkeypatch) -> None:
    account = _user()

    def fake_call(task, model, prompt, *, images=None):
        return ("structured toc", 100, 20)

    monkeypatch.setattr(provider, "_call_provider", fake_call)
    result = provider.generate(
        "toc_update", "prompt", account.user_id, account.tier
    )
    assert result.text == "structured toc"
    spent_ingestion = spend_repo.weekly_spend(
        account.user_id, spend_kind=SpendKind.INGESTION
    )
    spent_generation = spend_repo.weekly_spend(
        account.user_id, spend_kind=SpendKind.GENERATION
    )
    assert spent_ingestion == 126, (
        "120 base + 5% free-tier overhead (decision 004)"
    )
    assert spent_generation == 0


def test_interactive_task_bills_generation_pool(monkeypatch) -> None:
    account = _user()

    def fake_call(task, model, prompt, *, images=None):
        return ("answer", 50, 10)

    monkeypatch.setattr(provider, "_call_provider", fake_call)
    provider.generate(
        "tutor_answer", "prompt", account.user_id, account.tier
    )
    assert (
        spend_repo.weekly_spend(account.user_id, spend_kind=SpendKind.GENERATION)
        == 63
    ), "60 base + 5% free-tier overhead (decision 004)"
    assert (
        spend_repo.weekly_spend(account.user_id, spend_kind=SpendKind.INGESTION)
        == 0
    )


def test_unknown_task_rejected_before_anything() -> None:
    account = _user()
    with pytest.raises(ValueError, match="unknown generation task"):
        provider.generate(
            "not_a_task", "prompt", account.user_id, account.tier
        )


def test_paid_tier_carries_no_overhead(monkeypatch) -> None:
    account = _user()
    spend_repo.start_subscription(account.user_id, UserTier.PAID)
    paid = users_repo.get_by_id(account.user_id)
    assert paid is not None and paid.tier == UserTier.PAID

    def fake_call(task, model, prompt, *, images=None):
        return ("answer", 100, 20)

    monkeypatch.setattr(provider, "_call_provider", fake_call)
    provider.generate("tutor_answer", "prompt", paid.user_id, paid.tier)
    assert (
        spend_repo.weekly_spend(account.user_id, spend_kind=SpendKind.GENERATION)
        == 120
    ), "paid tiers carry free_tier_overhead_percent=0"


def test_tier_mismatch_rejected_inside_seam() -> None:
    from src.backend.common.budget import TierMismatchError
    from src.backend.common.schemas.base import UserTier

    account = _user()
    with pytest.raises(TierMismatchError):
        provider.generate(
            "tutor_answer", "prompt", account.user_id, UserTier.PAID
        )


def test_drained_pool_blocks_before_provider_call(monkeypatch) -> None:
    account = _user()
    policy = load_tier_policies().policy_for(account.tier)
    spend_repo.record_generation(
        account.user_id,
        "tutor_answer",
        "test-model",
        policy.weekly_token_budget + 1,
        0,
        spend_kind=SpendKind.GENERATION,
    )

    def explode(task, model, prompt, *, images=None):
        raise AssertionError("provider must not be called past the gate")

    monkeypatch.setattr(provider, "_call_provider", explode)
    from src.backend.common.budget import BudgetExceededError

    with pytest.raises(BudgetExceededError):
        provider.generate(
            "tutor_answer", "prompt", account.user_id, account.tier
        )


def test_empty_provider_output_fails_closed(monkeypatch) -> None:
    account = _user()

    def fake_call(task, model, prompt, *, images=None):
        return ("", 100, 20)

    monkeypatch.setattr(provider, "_call_provider", fake_call)
    with pytest.raises(provider.EmptyModelError):
        provider.generate(
            "toc_update", "prompt", account.user_id, account.tier
        )