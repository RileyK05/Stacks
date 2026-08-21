from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from src.backend.common import auth, users_repo
from src.backend.common.schemas.identity import User

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer()


async def current_user(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
) -> User:
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
def register(name: str, email: str, password: str) -> User:
    existing = users_repo.get_by_email(email)
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")
    hashed = auth.hash_password(password)
    return users_repo.create(name=name, email=email, password_hash=hashed)


@router.post("/login")
def login(email: str, password: str) -> dict[str, str]:
    user = users_repo.get_by_email(email)
    if user is None or user.password_hash is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    if not auth.verify_password(password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    token = auth.create_access_token(user.user_id)
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=User)
def me(user: Annotated[User, Depends(current_user)]) -> User:
    return user
