from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from src.backend.common.auth import normalize_email
from src.backend.common.db import connection
from src.backend.common.queries import get
from src.backend.common.schemas.identity import User, UserAccount

_FILE = "users"


def create(name: str, email: str, password_hash: str) -> User:
    email = normalize_email(email)
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "create"),
            {"name": name, "email": email, "password_hash": password_hash},
        ).fetchone()
        conn.commit()
    assert row is not None
    return User(
        user_id=row["user_id"],
        name=row["name"],
        email=row["email"],
        tier=row["tier"],
        created_at=row["created_at"],
    )


def _to_account(row: dict[str, Any]) -> UserAccount:
    return UserAccount(
        user_id=row["user_id"],
        name=row["name"],
        email=row["email"],
        tier=row["tier"],
        password_hash=row["password_hash"],
        delete_requested_at=row["delete_requested_at"],
        created_at=row["created_at"],
    )


def get_by_email(email: str) -> UserAccount | None:
    email = normalize_email(email)
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(get(_FILE, "get_by_email"), {"email": email}).fetchone()
    if row is None:
        return None
    return _to_account(row)


def get_by_id(user_id: UUID) -> UserAccount | None:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(get(_FILE, "get_by_id"), {"user_id": user_id}).fetchone()
    if row is None:
        return None
    return _to_account(row)
