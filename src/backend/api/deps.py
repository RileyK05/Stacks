from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from src.backend.common import auth, users_repo
from src.backend.common.schemas.identity import UserAccount

bearer = HTTPBearer()


def current_user(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
) -> UserAccount:
    """Resolve the bearer token to the internal account. Accounts pending
    deletion are blocked; tier is already resolved by the users lookup.
    Tokens minted before the last password change are rejected — a reset
    (the compromise response) must not leave the pre-reset session live."""
    try:
        claims = auth.decode_access_token(creds.credentials)
        token_user_id = UUID(str(claims["sub"]))
        raw_stamp = claims["stamp"]
        token_stamp = raw_stamp if isinstance(raw_stamp, int) else 0
    except Exception as err:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from err
    user = users_repo.get_by_id(token_user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    if token_stamp < auth.password_stamp(user.password_changed_at):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "session invalidated by password change",
        )
    if user.delete_requested_at is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account pending deletion")
    return user


def require_verified_email(user: UserAccount) -> None:
    """Gate for endpoints that create resources or spend operator storage.
    Login stays open to unverified accounts (existing accounts are never
    locked out); new resource creation does not."""
    if not user.email_verified:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "email address not verified; request a verification email "
            "via POST /auth/verify-email/request",
        )