"""Claim codes for customer-support entitlement workflows.

Every account receives a support code at registration. It is not an
authentication factor. Support can use it to identify an account and coordinate
entitlements paid through another avenue. The operator may mark a code as
premium-granting; redemption then starts a paid subscription through the
standard subscription machinery, so tier state stays single-sourced in
`users.tier` via the existing trigger.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from psycopg.connection import Connection
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from src.backend.common import codes, spend_repo
from src.backend.common.db import connection
from src.backend.common.queries import get
from src.backend.common.schemas.base import UserTier
from src.backend.common.schemas.spend import PremiumCode

_FILE = "premium_codes"


def hash_code(code: str) -> str:
    normalized = codes.require_valid(code)
    return hashlib.sha256(normalized.encode()).hexdigest()


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


def insert_code(
    conn: Connection,
    *,
    issued_for_user_id: UUID | None = None,
    grants_premium: bool = False,
    note: str | None = None,
    code: str | None = None,
) -> tuple[PremiumCode, str]:
    plaintext = code or codes.generate_code()
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "insert_code"),
            {
                "code_hash": hash_code(plaintext),
                "issued_for_user_id": issued_for_user_id,
                "grants_premium": grants_premium,
                "note": note,
            },
        ).fetchone()
    assert row is not None
    return _to_record(row), codes.display_code(plaintext)


def issue_code(
    *,
    issued_for_user_id: UUID | None = None,
    grants_premium: bool = False,
    note: str | None = None,
    code: str | None = None,
) -> tuple[PremiumCode, str]:
    """Operator: mint a code. Returns (record, plaintext); plaintext is shown
    once because only the hash is stored."""
    with connection() as conn:
        try:
            result = insert_code(
                conn,
                issued_for_user_id=issued_for_user_id,
                grants_premium=grants_premium,
                note=note,
                code=code,
            )
        except UniqueViolation as err:
            raise ValueError("code already exists") from err
        conn.commit()
    return result


def rotate_support_code(
    user_id: UUID, *, grants_premium: bool = False
) -> tuple[PremiumCode, str]:
    """Internal customer-support operation. The returned plaintext must be
    delivered out of band and is never exposed by a read API. Premium
    granting is opt-in so a pure re-identification rotation can never mint
    an entitlement by accident. The user-row lock serializes concurrent
    rotations so two open codes cannot both survive (READ COMMITTED would
    otherwise let a racing second revoke miss the first's replacement)."""
    with connection() as conn:
        conn.execute(
            "SELECT user_id FROM users WHERE user_id = %s FOR UPDATE", (user_id,)
        ).fetchone()
        conn.execute(get(_FILE, "revoke_open_for_user"), {"user_id": user_id})
        result = insert_code(
            conn,
            issued_for_user_id=user_id,
            grants_premium=grants_premium,
            note="customer support replacement code",
        )
        conn.commit()
    return result


def lookup(code: str) -> PremiumCode | None:
    normalized = codes.normalize_code(code)
    if not codes.is_valid(normalized):
        return None
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "get_by_hash"), {"code_hash": hash_code(normalized)}
        ).fetchone()
    if row is None:
        return None
    return _to_record(row)


def redeem(code: str, user_id: UUID) -> PremiumCode:
    """Claim an unclaimed, unrevoked code for user_id and, if it grants
    premium, start the paid subscription. A code bound to another account
    is rejected without consuming it. Raises ValueError on any unusable
    code or state, including an existing active subscription, so callers
    can always map the failure to a 4xx response."""
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "get_by_hash_for_update"),
            {"code_hash": hash_code(code)},
        ).fetchone()
        if row is None:
            raise ValueError("invalid code")
        existing = _to_record(row)
        if existing.claimed_at is not None or existing.revoked_at is not None:
            raise ValueError("code already claimed or revoked")
        if (
            existing.issued_for_user_id is not None
            and existing.issued_for_user_id != user_id
        ):
            raise ValueError("code is bound to a different account")
        if existing.grants_premium:
            conn.execute(
                "SELECT user_id FROM users WHERE user_id = %s FOR UPDATE",
                (user_id,),
            ).fetchone()
            if spend_repo.active_subscription_on(conn, user_id) is not None:
                raise ValueError(
                    "account already has an active subscription; "
                    "redeem after it ends or through normal billing"
                )
        claimed_row = cur.execute(
            get(_FILE, "claim_code"),
            {"code_hash": hash_code(code), "claimed_by_user_id": user_id},
        ).fetchone()
        if claimed_row is None:
            raise ValueError("code is invalid, already claimed, or revoked")
        record = _to_record(claimed_row)
        if record.grants_premium:
            spend_repo.insert_subscription(conn, user_id, UserTier.PAID)
        conn.commit()
    return record


def revoke(code_id: UUID) -> PremiumCode | None:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "set_revoked"), {"code_id": code_id}
        ).fetchone()
        conn.commit()
    if row is None:
        return None
    return _to_record(row)
