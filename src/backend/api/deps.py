from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Header, HTTPException, status
from src.backend.common.config import get_settings

APP_TOKEN_HEADER = "X-App-Token"


def require_app_token(
    x_app_token: Annotated[str | None, Header(alias=APP_TOKEN_HEADER)] = None,
) -> None:
    """The only auth a local tool needs (plan §4). The desktop shell starts
    the backend with a per-launch secret and hands it to its own webview;
    every API request must echo it. Other local programs and web pages
    can reach 127.0.0.1 but cannot read the secret, so they cannot drive
    the API (DNS-rebinding / CSRF protection). Disabled when no token is
    configured (development, tests)."""
    expected = get_settings().api_token
    if not expected:
        return
    if x_app_token is None or not hmac.compare_digest(x_app_token, expected):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "missing or invalid app token"
        )
