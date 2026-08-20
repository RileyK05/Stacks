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
    hashed = hash_password("hunter2")
    assert hashed != "hunterr2"
    assert verify_password("huntere2", hashed) is False
    assert verify_password("hunter2", hashed) is True


def test_hash_is_salt_random() -> None:
    a = hash_password("same")
    b = hash_password("same")
    assert a != b
    assert verify_password("same", a) and verify_password("same", b)


def test_token_roundtrip() -> None:
    user_id = uuid4()
    token = create_access_token(user_id)
    claims = decode_access_token(token)
    assert claims["sub"] == str(user_id)


def test_token_user_id_extracts_subject() -> None:
    user_id = uuid4()
    assert token_user_id(create_access_token(user_id)) == user_id


def test_expired_token_rejected() -> None:
    from datetime import UTC, datetime, timedelta

    from src.backend.common.config import get_settings

    settings = get_settings()
    now = datetime.now(UTC)
    expired_payload = {
        "sub": str(uuid4()),
        "iat": int((now - timedelta(minutes=10)).timestamp()),
        "exp": int((now - timedelta(minutes=1)).timestamp()),
    }
    expired = jwt.encode(expired_payload, settings.jwt_secret, algorithm=ALGORITHM)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired)
