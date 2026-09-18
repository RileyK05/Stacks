from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import bcrypt
import jwt
from src.backend.common.config import get_settings

ALGORITHM = "HS256"
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 24
# bcrypt truncates silently past 72 bytes — the byte cap exists so a long
# multibyte password verifies the SAME bytes that were hashed, and so no
# user believes a longer password adds protection it does not.
MAX_PASSWORD_BYTES = 72
DUMMY_PASSWORD_HASH = "$2b$12$Jo5YB1lAfUoSidQaUj3pgOvWEP0Q875Y/ZYY8vwaNQ7.LcKIPo4zS"


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_password(plain: str) -> str:
    if len(plain) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"password must contain at least {MIN_PASSWORD_LENGTH} characters"
        )
    if len(plain) > MAX_PASSWORD_LENGTH:
        raise ValueError(
            f"password must contain at most {MAX_PASSWORD_LENGTH} characters"
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


def password_stamp(password_changed_at: datetime | None) -> int:
    """The invalidation stamp, in microseconds since epoch. Microsecond
    resolution matters: a second-precision stamp cannot distinguish a
    token minted before a same-second password change from one minted
    after it, so the reset race survives. A mint-then-change inside one
    microsecond is not reachable (a bcrypt hash alone costs ~100ms)."""
    if password_changed_at is None:
        return 0
    return int(password_changed_at.timestamp() * 1_000_000)


def create_access_token(user_id: UUID, password_changed_at: datetime | None) -> str:
    """Mint a token carrying the account's password stamp. A password
    change invalidates every token minted before it: current_user compares
    this claim against the live stamp. `None` (password never set) mints
    `stamp=0` so the claim is always present and always comparable."""
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "stamp": password_stamp(password_changed_at),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def token_password_stamp(token: str) -> int:
    claims = decode_access_token(token)
    stamp = claims["stamp"]
    return int(stamp) if isinstance(stamp, int) else 0


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
