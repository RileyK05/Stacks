import secrets
from uuid import uuid4

import pytest
from src.backend.common import auth, codes, premium_codes_repo, spend_repo, users_repo
from src.backend.common.schemas import UserTier


def _user() -> object:
    return users_repo.create(
        "Code Tester",
        f"{uuid4().hex}@test.invalid",
        auth.hash_password("long-password"),
    )


def test_generate_code_shape_and_normalization() -> None:
    code = codes.generate_code()
    assert len(code) == 16
    assert codes.is_valid(code)
    assert "-" not in code
    grouped = codes.display_code(code)
    assert grouped == f"{code[:4]}-{code[4:8]}-{code[8:12]}-{code[12:16]}"
    assert codes.normalize_code(grouped) == code
    assert codes.normalize_code(" abcd-EFGH-JKMN-PQRS ") == (
        "ABCDEFGHJKMNPQRS"
    )
    assert not codes.is_valid("NO-SUCH-CODE-0000")


def test_issue_and_lookup_roundtrip() -> None:
    record, plaintext = premium_codes_repo.issue_code(
        grants_premium=True, note="test code"
    )
    assert record.claimed_at is None
    assert record.grants_premium is True
    found = premium_codes_repo.lookup(plaintext)
    assert found is not None
    assert found.code_id == record.code_id
    assert premium_codes_repo.lookup("NO-SUCH-CODE-0000") is None
    found_loose = premium_codes_repo.lookup(
        plaintext[:4] + "-" + plaintext[4:].lower()
    )
    assert found_loose is not None


def test_support_code_is_issued_and_bound() -> None:
    account = _user()
    record, plaintext = premium_codes_repo.issue_code(
        issued_for_user_id=account.user_id, note="customer support code"
    )
    assert record.issued_for_user_id == account.user_id
    other = _user()
    with pytest.raises(ValueError, match="bound to a different account"):
        premium_codes_repo.redeem(plaintext, other.user_id)
    premium_codes_repo.redeem(plaintext, account.user_id)
    fetched = users_repo.get_by_id(account.user_id)
    assert fetched is not None
    assert fetched.tier == UserTier.FREE


def test_premium_code_redeem_starts_subscription() -> None:
    account = _user()
    record, plaintext = premium_codes_repo.issue_code(grants_premium=True)
    premium_codes_repo.redeem(plaintext, account.user_id)
    fetched = users_repo.get_by_id(account.user_id)
    assert fetched is not None
    assert fetched.tier == UserTier.PAID
    with pytest.raises(ValueError, match="already claimed"):
        premium_codes_repo.redeem(plaintext, _user().user_id)


def test_redeem_while_subscribed_is_rejected_not_500() -> None:
    account = _user()
    _, first_code = premium_codes_repo.issue_code(
        issued_for_user_id=account.user_id, grants_premium=True
    )
    premium_codes_repo.redeem(first_code, account.user_id)
    renewal, plaintext = premium_codes_repo.issue_code(
        issued_for_user_id=account.user_id, grants_premium=True
    )
    assert renewal.grants_premium is True
    with pytest.raises(ValueError, match="already has an active subscription"):
        premium_codes_repo.redeem(plaintext, account.user_id)
    code_state = premium_codes_repo.lookup(plaintext)
    assert code_state is not None
    assert code_state.claimed_at is None


def test_rotation_does_not_grant_premium_by_default() -> None:
    account = _user()
    record, plaintext = premium_codes_repo.rotate_support_code(account.user_id)
    assert record.grants_premium is False
    premium_codes_repo.redeem(plaintext, account.user_id)
    fetched = users_repo.get_by_id(account.user_id)
    assert fetched is not None
    assert fetched.tier == UserTier.FREE


def test_non_premium_code_claimed_but_no_tier_change() -> None:
    account = _user()
    record, plaintext = premium_codes_repo.issue_code(grants_premium=False)
    premium_codes_repo.redeem(plaintext, account.user_id)
    fetched = users_repo.get_by_id(account.user_id)
    assert fetched is not None
    assert fetched.tier == UserTier.FREE


def test_revoked_code_cannot_redeem() -> None:
    account = _user()
    record, plaintext = premium_codes_repo.issue_code(grants_premium=True)
    premium_codes_repo.revoke(record.code_id)
    with pytest.raises(ValueError, match="revoked"):
        premium_codes_repo.redeem(plaintext, account.user_id)


def test_wrong_user_cannot_claim_bound_code() -> None:
    owner = _user()
    stranger = _user()
    record, plaintext = premium_codes_repo.issue_code(
        issued_for_user_id=owner.user_id
    )
    with pytest.raises(ValueError, match="bound to a different account"):
        premium_codes_repo.redeem(plaintext, stranger.user_id)
    premium_codes_repo.redeem(plaintext, owner.user_id)
    fetched = users_repo.get_by_id(owner.user_id)
    assert fetched is not None


def test_issue_with_supplied_code_is_deterministic() -> None:
    suffix = "".join(
        secrets.choice(codes.CODE_ALPHABET) for _ in range(12)
    )
    record, plaintext = premium_codes_repo.issue_code(
        code=f"TEST-{suffix}", note="supplied"
    )
    assert plaintext == f"TEST-{suffix[:4]}-{suffix[4:8]}-{suffix[8:]}"
    again = premium_codes_repo.lookup(f"test {suffix[:4]} {suffix[4:]}")
    assert again is not None
    assert again.code_id == record.code_id
    with pytest.raises(ValueError, match="already exists"):
        premium_codes_repo.issue_code(code=f"TEST-{suffix}")


def test_concurrent_double_redeem_admits_only_one() -> None:
    """Two threads race to redeem the same premium code for different
    accounts. The row lock (get_by_hash_for_update) makes the loser see the
    winner's claim and reject; exactly one subscription exists."""
    import threading

    _, plaintext = premium_codes_repo.issue_code(grants_premium=True)
    winner = _user()
    loser = _user()
    results: dict[str, object] = {}

    def redeem_thread(name: str, account: object, barrier: threading.Barrier) -> None:
        barrier.wait()
        try:
            premium_codes_repo.redeem(plaintext, account.user_id)  # type: ignore[attr-defined]
            results[name] = "ok"
        except ValueError as err:
            results[name] = str(err)

    barrier = threading.Barrier(2)
    threads = [
        threading.Thread(target=redeem_thread, args=("winner", winner, barrier)),
        threading.Thread(target=redeem_thread, args=("loser", loser, barrier)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    outcomes = list(results.values())
    assert outcomes.count("ok") == 1, outcomes
    assert all("claimed" in o or "subscription" in o for o in outcomes if o != "ok"), (
        outcomes
    )
    winner_sub = spend_repo.active_subscription(winner.user_id)  # type: ignore[attr-defined]
    loser_sub = spend_repo.active_subscription(loser.user_id)  # type: ignore[attr-defined]
    assert (winner_sub is None) != (loser_sub is None)
