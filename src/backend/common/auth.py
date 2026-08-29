from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import bcrypt
import jwt
from src.backend.common.config import get_settings

ALGORITHM = "HS256"
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_BYTES = 72
DUMMY_PASSWORD_HASH = "$2b$12$Jo5YB1lAfUoSidQaUj3pgOvWEP0Q875Y/ZYY8vwaNQ7.LcKIPo4zS"


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_password(plain: str) -> str:
    if len(plain) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"password must contain at least {MIN_PASSWORD_LENGTH} characters"
        )
    if len(plain.encode()) > MAX_PASSWORD_BYTES:
        raise ValueError(f"password must be at most {MAX_PASSWORD_BYTES} UTF-8 bytes")
    return plain


def hash_password(plain: str) -> str:
    validate_password(plain)
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain.encode(), salt).decode()


def verify_password(plain: str, hashed: str) -> bool:
    if len(plain.encode()) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


def create_access_token(user_id: UUID) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, object]:
    settings = get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[ALGORITHM],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
        options={"require": ["sub", "iat", "nbf", "exp", "iss", "aud"]},
    )


def token_user_id(token: str) -> UUID:
    claims = decode_access_token(token)
    return UUID(str(claims["sub"]))
