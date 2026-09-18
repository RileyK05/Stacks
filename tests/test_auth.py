from datetime import UTC, datetime
from uuid import uuid4

import jwt
import pytest
from src.backend.common.auth import (
    ALGORITHM,
    create_access_token,
    decode_access_token,
    hash_password,
    token_user_id,
    verify_password,
)


def test_hash_and_verify_password() -> None:
    hashed = hash_password("correct-horse-battery")
    assert hashed != "correct-horse-batterz"
    assert verify_password("huntere2", hashed) is False
    assert verify_password("correct-horse-battery", hashed) is True


def test_hash_is_salt_random() -> None:
    a = hash_password("same-password-value")
    b = hash_password("same-password-value")
    assert a != b
    assert verify_password("same-password-value", a)
    assert verify_password("same-password-value", b)


def test_short_password_rejected() -> None:
    with pytest.raises(ValueError, match="at least 12"):
        hash_password("too-short")


def test_oversized_password_candidate_is_rejected_without_bcrypt_error() -> None:
    hashed = hash_password("correct-horse-battery")
    assert verify_password("x" * 1000, hashed) is False


def test_token_roundtrip() -> None:
    user_id = uuid4()
    changed_at = datetime.now(UTC)
    token = create_access_token(user_id, changed_at)
    claims = decode_access_token(token)
    assert claims["sub"] == str(user_id)
    assert claims["stamp"] == int(changed_at.timestamp() * 1_000_000)


def test_token_stamp_none_becomes_zero() -> None:
    user_id = uuid4()
    token = create_access_token(user_id, None)
    claims = decode_access_token(token)
    assert claims["stamp"] == 0


def test_token_user_id_extracts_subject() -> None:
    user_id = uuid4()
    assert (
        token_user_id(create_access_token(user_id, datetime.now(UTC)))
        == user_id
    )


def test_expired_token_rejected() -> None:
    from datetime import UTC, datetime, timedelta

    from src.backend.common.config import get_settings

    settings = get_settings()
    now = datetime.now(UTC)
    expired_payload = {
        "sub": str(uuid4()),
        "iat": int((now - timedelta(minutes=10)).timestamp()),
        "nbf": int((now - timedelta(minutes=10)).timestamp()),
        "exp": int((now - timedelta(minutes=1)).timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    expired = jwt.encode(expired_payload, settings.jwt_secret, algorithm=ALGORITHM)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired)
