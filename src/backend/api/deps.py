from __future__ import annotations

import hmac
from typing import Annotated
from uuid import UUID

from fastapi import Header, HTTPException, status
from src.backend.common import courses_repo
from src.backend.common.config import get_settings
from src.backend.common.schemas.identity import Course

APP_TOKEN_HEADER = "X-App-Token"


def require_course(course_id: UUID) -> Course:
    course = courses_repo.get_course(course_id)
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")
    return course


def require_app_token(
    x_app_token: Annotated[str | None, Header(alias=APP_TOKEN_HEADER)] = None,
) -> None:
    """The only auth a local tool needs (plan §4). The desktop shell starts
    the backend with a per-launch secret and hands it to its own webview;
    every API request must echo it. Other local programs and web pages
    can reach 127.0.0.1 but cannot read the secret, so they cannot drive
    the API (DNS-rebinding / CSRF protection). Disabled when no token is
    configured (development, tests)."""
    settings = get_settings()
    expected = settings.api_token
    if not expected:
        if settings.app_env == "production":
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "the desktop API token is not configured",
            )
        return
    if x_app_token is None or not hmac.compare_digest(
        x_app_token.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "missing or invalid app token"
        )
