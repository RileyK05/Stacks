"""Email verification and password reset tokens, plus the outbox seam.

Tokens are random 32-byte secrets, stored only as SHA-256 hashes (a DB
leak reveals nothing usable) and single-use with an expiry. The plaintext
exists in exactly one place: the email body written to `email_outbox`,
which is an operator/worker seam — no delivery happens in-process. A
future SMTP worker drains the outbox; tests read it through this repo.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from psycopg.connection import Connection
from psycopg.rows import dict_row
from src.backend.common.db import connection
from src.backend.common.queries import get

_FILE = "email_tokens"

VERIFICATION_KIND = "email_verification"
RESET_KIND = "password_reset"
TOKEN_TTL_MINUTES = 60
_TOKEN_BYTES = 32


@dataclass(frozen=True)
class OutboxEmail:
    message_id: UUID
    user_id: UUID | None
    to_email: str
    kind: str
    subject: str
    body: str
    created_at: datetime


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _expiry(now: datetime) -> datetime:
    return now + timedelta(minutes=TOKEN_TTL_MINUTES)


def issue_token(
    conn: Connection,
    *,
    user_id: UUID,
    kind: str,
    to_email: str,
    subject: str,
    body_template: str,
    now: datetime | None = None,
) -> str:
    """Create (replacing any open token of the same kind) and queue the
    email carrying the plaintext token. Returns nothing user-visible; the
    plaintext lives only in the outbox row."""
    reference = now or datetime.now(UTC)
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            get(_FILE, "revoke_open_tokens"),
            {"user_id": user_id, "kind": kind},
        )
        row = cur.execute(
            get(_FILE, "create_token"),
            {
                "user_id": user_id,
                "kind": kind,
                "token_hash": _hash(token),
                "expires_at": _expiry(reference),
            },
        ).fetchone()
        assert row is not None
        cur.execute(
            get(_FILE, "enqueue_email"),
            {
                "user_id": user_id,
                "to_email": to_email,
                "kind": kind,
                "subject": subject,
                "body": body_template.format(token=token),
            },
        )
    return token


def latest_outbox_email(user_id: UUID, kind: str) -> OutboxEmail | None:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "latest_outbox_email"),
            {"user_id": user_id, "kind": kind},
        ).fetchone()
    return _to_email(row) if row is not None else None


def _to_email(row: dict[str, Any]) -> OutboxEmail:
    return OutboxEmail(
        message_id=row["message_id"],
        user_id=row["user_id"],
        to_email=row["to_email"],
        kind=row["kind"],
        subject=row["subject"],
        body=row["body"],
        created_at=row["created_at"],
    )


class TokenRejectedError(RuntimeError):
    pass


def consume_token(
    conn: Connection, *, kind: str, plaintext: str, now: datetime | None = None
) -> UUID:
    """Mark a valid, unexpired, unused token of this kind as used and
    return its user. Raises TokenRejectedError otherwise — unknown token,
    wrong kind, already used, or expired all look identical to the caller
    so nothing about token state leaks."""
    reference = now or datetime.now(UTC)
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "token_by_hash"), {"token_hash": _hash(plaintext)}
        ).fetchone()
        if (
            row is None
            or row["kind"] != kind
            or row["used_at"] is not None
            or row["expires_at"] <= reference
        ):
            raise TokenRejectedError("invalid or expired token")
        used = cur.execute(
            get(_FILE, "mark_token_used"), {"token_id": row["token_id"]}
        ).fetchone()
        if used is None:
            # mark_token_used is guarded by `used_at IS NULL`, so it matches
            # nothing when a concurrent request claimed the token between
            # this transaction's SELECT and its UPDATE. That is a normal
            # lost race (double-clicked reset link, mail scanner prefetching
            # the URL), not an invariant breach — it must read as a rejected
            # token, not an AssertionError 500.
            raise TokenRejectedError("invalid or expired token")
    user_id: UUID = used["user_id"]
    return user_id


def mark_email_verified(conn: Connection, user_id: UUID) -> None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(get(_FILE, "verify_user_email"), {"user_id": user_id})


def is_verified(user_id: UUID) -> bool:
    with connection() as conn:
        row = conn.execute(
            "SELECT email_verified_at FROM users WHERE user_id = %s",
            (user_id,),
        ).fetchone()
    return row is not None and row[0] is not None