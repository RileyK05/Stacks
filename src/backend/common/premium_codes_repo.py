"""Claim codes: operator-issued premium activation and account recovery.

Every account receives a personal code at registration. Codes are stored as
SHA-256 hashes — a database leak never reveals a usable code. Most codes grant
nothing (they are account recovery keys); the operator flips `grants_premium`
on a code to make it a premium activation code. Claiming a premium code starts
a paid subscription through the standard subscription machinery, so tier state
stays single-sourced in `users.tier` via the existing trigger.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any
from uuid import UUID

from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from src.backend.common import spend_repo
from src.backend.common.db import connection
from src.backend.common.queries import get
from src.backend.common.schemas.base import UserTier
from src.backend.common.schemas.spend import PremiumCode

_FILE = "premium_codes"

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 16


def normalize_code(code: str) -> str:
    """Canonical form: uppercase, separators and whitespace removed."""
    return "".join(char for char in code.strip().upper() if char.isalnum())


def hash_code(code: str) -> str:
    return hashlib.sha256(normalize_code(code).encode()).hexdigest()


def generate_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    return "-".join(raw[i : i + 4] for i in range(0, CODE_LENGTH, 4))


def _to_record(row: dict[str, Any]) -> PremiumCode:
    return PremiumCode(
        code_id=row["code_id"],
        issued_for_user_id=row["issued_for_user_id"],
        grants_premium=row["grants_premium"],
        claimed_by_user_id=row["claimed_by_user_id"],
        claimed_at=row["claimed_at"],
        revoked_at=row["revoked_at"],
        note=row["note"],
        created_at=row["created_at"],
    )


def issue_code(
    *,
    issued_for_user_id: UUID | None = None,
    grants_premium: bool = False,
    note: str | None = None,
    code: str | None = None,
) -> tuple[PremiumCode, str]:
    """Operator: mint a code. Returns (record, plaintext); plaintext is shown
    once because only the hash is stored."""
    plaintext = code or generate_code()
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        try:
            row = cur.execute(
                get(_FILE, "insert_code"),
                {
                    "code_hash": hash_code(plaintext),
                    "issued_for_user_id": issued_for_user_id,
                    "grants_premium": grants_premium,
                    "note": note,
                },
            ).fetchone()
        except UniqueViolation as err:
            raise ValueError("code already exists") from err
        conn.commit()
    assert row is not None
    return _to_record(row), normalize_code(plaintext)


def lookup(code: str) -> PremiumCode | None:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "get_by_hash"), {"code_hash": hash_code(code)}
        ).fetchone()
    if row is None:
        return None
    return _to_record(row)


def _claim(code: str, user_id: UUID) -> PremiumCode:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "mark_claimed"),
            {"code_hash": hash_code(code), "claimed_by_user_id": user_id},
        ).fetchone()
        conn.commit()
    if row is None:
        raise ValueError("code is invalid, already claimed, or revoked")
    return _to_record(row)


def redeem(code: str, user_id: UUID) -> PremiumCode:
    """Claim an unclaimed, unrevoked code for user_id and, if it grants
    premium, start the paid subscription. A code bound to another account
    is rejected. Raises ValueError on any unusable code."""
    record = lookup(code)
    if record is None:
        raise ValueError("invalid code")
    if record.claimed_at is not None or record.revoked_at is not None:
        raise ValueError("code already claimed or revoked")
    if (
        record.issued_for_user_id is not None
        and record.issued_for_user_id != user_id
    ):
        raise ValueError("code is bound to a different account")
    claimed = _claim(code, user_id)
    if claimed.grants_premium:
        spend_repo.start_subscription(user_id, UserTier.PAID)
    return claimed


def revoke(code_id: UUID) -> PremiumCode | None:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "set_revoked"), {"code_id": code_id}
        ).fetchone()
        conn.commit()
    if row is None:
        return None
    return _to_record(row)