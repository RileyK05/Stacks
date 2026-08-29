from uuid import uuid4

import pytest
from src.backend.common import auth, premium_codes_repo, users_repo
from src.backend.common.schemas import UserTier


def _user() -> object:
    return users_repo.create(
        "Code Tester",
        f"{uuid4().hex}@test.invalid",
        auth.hash_password("long-password"),
    )


def test_generate_code_shape_and_normalization() -> None:
    code = premium_codes_repo.generate_code()
    assert len(code.replace("-", "")) == 16
    assert code.count("-") == 3
    assert premium_codes_repo.normalize_code(code) == code.replace("-", "")
    assert premium_codes_repo.normalize_code(" abcd-EFGH-1234-5678 ") == (
        "ABCDEFGH12345678"
    )


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


def test_personal_code_is_issued_and_bound() -> None:
    account = _user()
    record, plaintext = premium_codes_repo.issue_code(
        issued_for_user_id=account.user_id, note="registration code"
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
    suffix = uuid4().hex[:12].upper()
    record, plaintext = premium_codes_repo.issue_code(
        code=f"TEST-{suffix}", note="supplied"
    )
    assert plaintext == f"TEST{suffix}"
    again = premium_codes_repo.lookup(f"test {suffix[:4]} {suffix[4:]}")
    assert again is not None
    assert again.code_id == record.code_id
    with pytest.raises(ValueError, match="already exists"):
        premium_codes_repo.issue_code(code=f"TEST-{suffix}")