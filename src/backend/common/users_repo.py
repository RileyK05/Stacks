from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.connection import Connection
from psycopg.rows import dict_row
from src.backend.common.auth import normalize_email
from src.backend.common.db import connection
from src.backend.common.queries import get
from src.backend.common.schemas.identity import User, UserAccount

_FILE = "users"


def insert(
    conn: Connection, name: str, email: str, password_hash: str
) -> User:
    email = normalize_email(email)
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "create"),
            {"name": name, "email": email, "password_hash": password_hash},
        ).fetchone()
    assert row is not None
    return User(
        user_id=row["user_id"],
        name=row["name"],
        email=row["email"],
        tier=row["tier"],
        email_verified=row["email_verified_at"] is not None,
        created_at=row["created_at"],
    )


def create(name: str, email: str, password_hash: str) -> User:
    with connection() as conn:
        user = insert(conn, name, email, password_hash)
        conn.commit()
    return user


def _to_account(row: dict[str, Any]) -> UserAccount:
    return UserAccount(
        user_id=row["user_id"],
        name=row["name"],
        email=row["email"],
        tier=row["tier"],
        email_verified=row["email_verified_at"] is not None,
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


def update_password(
    conn: Connection, user_id: UUID, password_hash: str
) -> UserAccount | None:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "update_password"),
            {"user_id": user_id, "password_hash": password_hash},
        ).fetchone()
    return _to_account(row) if row is not None else None
