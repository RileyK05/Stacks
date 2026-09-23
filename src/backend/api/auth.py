from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, ConfigDict, Field, field_validator
from src.backend.api.deps import bearer, current_user  # noqa: F401
from src.backend.common import (
    auth,
    codes,
    email_repo,
    login_throttle,
    premium_codes_repo,
    users_repo,
)
from src.backend.common.auth_config import load_login_throttle_policy
from src.backend.common.db import connection
from src.backend.common.schemas.identity import User, UserAccount

router = APIRouter(prefix="/auth", tags=["auth"])

UNKNOWN_CLIENT_IP = "unknown"


def _client_ip(request: Request) -> str:
    """The source IP used as the throttle key. `request.client` is the
    socket peer; when a reverse proxy fronts the app that peer is the
    proxy, so per-IP throttling would lock out everyone at once. Only when
    the operator opts in (configs/auth.toml `trust_forwarded_for`) is the
    left-most X-Forwarded-For entry treated as the client — that header is
    trivially spoofable if the app is directly reachable, which is why it
    is off by default."""
    if load_login_throttle_policy().trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first
    return request.client.host if request.client else UNKNOWN_CLIENT_IP



class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    email: str = Field(max_length=254)
    password: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        normalized = auth.normalize_email(value)
        if "@" not in normalized or normalized.startswith("@"):
            raise ValueError("invalid email address")
        return normalized

    @field_validator("password")
    @classmethod
    def _validate_password(cls, value: str) -> str:
        return auth.validate_password(value)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254)
    password: str = Field(max_length=1024)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return auth.normalize_email(value)


class SupportCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=128)

    @field_validator("code")
    @classmethod
    def _code_format(cls, value: str) -> str:
        try:
            return codes.require_valid(value)
        except ValueError as err:
            raise ValueError(
                "support code must be 16 characters from the code alphabet "
                "(display form: XXXX-XXXX-XXXX-XXXX)"
            ) from err


@router.post(
    "/register",
    response_model=User,
    status_code=status.HTTP_201_CREATED,
)
def register(payload: RegisterRequest) -> User:
    existing = users_repo.get_by_email(payload.email)
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")
    hashed = auth.hash_password(payload.password)
    try:
        with connection() as conn:
            user = users_repo.insert(
                conn, name=payload.name, email=payload.email, password_hash=hashed
            )
            premium_codes_repo.insert_code(
                conn,
                issued_for_user_id=user.user_id,
                note="customer support code",
            )
            conn.commit()
    except UniqueViolation as err:
        constraint = getattr(err.diag, "constraint_name", None) or ""
        if "email" in constraint:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "email already registered"
            ) from err
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "registration is temporarily unavailable; retry",
        ) from err
    return User.model_validate(user)


@router.post("/support-code/redeem", response_model=User)
def redeem_support_code(
    payload: SupportCodeRequest,
    user: Annotated[UserAccount, Depends(current_user)],
) -> User:
    try:
        premium_codes_repo.redeem(payload.code, user.user_id)
    except ValueError as err:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(err)) from err
    refreshed = users_repo.get_by_id(user.user_id)
    if refreshed is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    return User.model_validate(refreshed)


@router.post("/login")
def login(payload: LoginRequest, request: Request) -> dict[str, str]:
    ip = _client_ip(request)
    lock = login_throttle.check_locked(payload.email, ip)
    if lock.locked:
        # 429 with the remaining seconds: the client is told to back off,
        # but not whether the address exists or the password was close.
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too many failed login attempts; try again later",
            headers={"Retry-After": str(lock.retry_after_seconds)},
        )
    policy = load_login_throttle_policy()
    user = users_repo.get_by_email(payload.email)
    if user is None or user.password_hash is None:
        auth.verify_password(payload.password, auth.DUMMY_PASSWORD_HASH)
        login_throttle.record_failure(payload.email, ip, policy)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    password_hash = user.password_hash.get_secret_value()
    if not auth.verify_password(payload.password, password_hash):
        login_throttle.record_failure(payload.email, ip, policy)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    if user.delete_requested_at is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account pending deletion")
    login_throttle.clear_email(payload.email)
    token = auth.create_access_token(user.user_id, user.password_changed_at)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/verify-email/request", status_code=status.HTTP_202_ACCEPTED)
def request_email_verification(
    user: Annotated[UserAccount, Depends(current_user)],
) -> dict[str, str]:
    """Queue a verification email. Always 202, even when already verified:
    account state must not be probeable through response differences."""
    if user.email is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "account has no email address"
        )
    with connection() as conn:
        email_repo.issue_token(
            conn,
            user_id=user.user_id,
            kind=email_repo.VERIFICATION_KIND,
            to_email=user.email,
            subject="Verify your email",
            body_template=(
                "Use this token to verify your email address: {token}\n"
                "The token expires in "
                f"{email_repo.TOKEN_TTL_MINUTES} minutes."
            ),
        )
        conn.commit()
    return {"status": "verification email queued"}


@router.post("/verify-email/{token}", response_model=User)
def verify_email(
    token: str,
    user: Annotated[UserAccount, Depends(current_user)],
) -> User:
    """Consume a verification token. The token must belong to the
    authenticated caller — one account can never verify another's email."""
    try:
        with connection() as conn:
            token_user_id = email_repo.consume_token(
                conn, kind=email_repo.VERIFICATION_KIND, plaintext=token
            )
            if token_user_id != user.user_id:
                raise email_repo.TokenRejectedError("token does not match account")
            email_repo.mark_email_verified(conn, user.user_id)
            conn.commit()
    except email_repo.TokenRejectedError as err:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "invalid or expired verification token"
        ) from err
    refreshed = users_repo.get_by_id(user.user_id)
    assert refreshed is not None
    return User.model_validate(refreshed)


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return auth.normalize_email(value)


class PasswordResetConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=16, max_length=128)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _validate_password(cls, value: str) -> str:
        return auth.validate_password(value)


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
def request_password_reset(payload: PasswordResetRequest) -> dict[str, str]:
    """Queue a reset email. Always 202 whether or not the account exists:
    the response must not disclose registered addresses."""
    user = users_repo.get_by_email(payload.email)
    if (
        user is not None
        and user.password_hash is not None
        and user.delete_requested_at is None
        and user.email is not None
    ):
        with connection() as conn:
            email_repo.issue_token(
                conn,
                user_id=user.user_id,
                kind=email_repo.RESET_KIND,
                to_email=user.email,
                subject="Reset your password",
                body_template=(
                    "Use this token to reset your password: {token}\n"
                    "The token expires in "
                    f"{email_repo.TOKEN_TTL_MINUTES} minutes. If you did "
                    "not request this, ignore this email."
                ),
            )
            conn.commit()
    return {"status": "password reset email queued if account exists"}


@router.post("/password-reset/confirm", response_model=User)
def confirm_password_reset(payload: PasswordResetConfirm) -> User:
    """Consume a reset token and set the new password. The account must not
    be pending deletion; a successful reset also marks the email verified
    (proving control of the mailbox proves the address)."""
    try:
        with connection() as conn:
            user_id = email_repo.consume_token(
                conn, kind=email_repo.RESET_KIND, plaintext=payload.token
            )
            account = users_repo.get_by_id(user_id)
            if (
                account is None
                or account.delete_requested_at is not None
            ):
                raise email_repo.TokenRejectedError("account unavailable")
            users_repo.update_password(
                conn, user_id, auth.hash_password(payload.new_password)
            )
            email_repo.mark_email_verified(conn, user_id)
            conn.commit()
            refreshed = users_repo.get_by_id(user_id)
    except email_repo.TokenRejectedError as err:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "invalid or expired reset token"
        ) from err
    assert refreshed is not None
    return User.model_validate(refreshed)


@router.get("/me", response_model=User)
def me(user: Annotated[UserAccount, Depends(current_user)]) -> User:
    return User.model_validate(user)
