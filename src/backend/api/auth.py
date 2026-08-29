from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field, field_validator
from src.backend.common import auth, users_repo
from src.backend.common.schemas.identity import User, UserAccount

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer()


class RegisterRequest(BaseModel):
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
    email: str
    password: str = Field(max_length=1024)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return auth.normalize_email(value)


def current_user(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
) -> UserAccount:
    try:
        user_id = auth.token_user_id(creds.credentials)
    except Exception as err:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from err
    user = users_repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    if user.delete_requested_at is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account pending deletion")
    return user


@router.post("/register", response_model=User)
def register(payload: RegisterRequest) -> User:
    existing = users_repo.get_by_email(payload.email)
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")
    hashed = auth.hash_password(payload.password)
    try:
        return users_repo.create(
            name=payload.name, email=payload.email, password_hash=hashed
        )
    except UniqueViolation as err:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "email already registered"
        ) from err


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
