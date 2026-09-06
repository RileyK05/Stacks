from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, ConfigDict, Field, field_validator
from src.backend.api.deps import bearer, current_user  # noqa: F401
from src.backend.common import auth, codes, premium_codes_repo, users_repo
from src.backend.common.db import connection
from src.backend.common.schemas.identity import User, UserAccount

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    email: str
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

    email: str
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
def login(payload: LoginRequest) -> dict[str, str]:
    user = users_repo.get_by_email(payload.email)
    if user is None or user.password_hash is None:
        auth.verify_password(payload.password, auth.DUMMY_PASSWORD_HASH)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    password_hash = user.password_hash.get_secret_value()
    if not auth.verify_password(payload.password, password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    if user.delete_requested_at is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account pending deletion")
    token = auth.create_access_token(user.user_id)
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=User)
def me(user: Annotated[UserAccount, Depends(current_user)]) -> User:
    return User.model_validate(user)
