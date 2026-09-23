"""Failed-login throttling (carried security item; docs/notes.md).

Two keys are counted on every failed login — the normalized account email
and the source IP — because they defend different attacks: per-email
slows guessing against one account, per-IP slows spraying across many
accounts from one host. Only SHA-256 hashes of the keys are stored, so a
database leak does not hand over probed addresses or source IPs.

The counters are inspectable and bounded (one row per distinct key); a
key self-resets in place once its counting window has passed. A
successful login clears the email key so a legitimate user who
mis-typed a few times is not locked out after they get it right. The IP
key is deliberately NOT cleared on success: an attacker who knows one
valid credential must not be able to reset the spray counter for the
whole host.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from psycopg import Connection
from psycopg.rows import dict_row
from src.backend.common.auth import normalize_email
from src.backend.common.auth_config import LoginThrottlePolicy
from src.backend.common.db import connection
from src.backend.common.queries import get

_FILE = "auth"

EMAIL_SCOPE = "email"
IP_SCOPE = "ip"


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def email_key(email: str) -> str:
    return _hash(normalize_email(email))


def ip_key(ip: str) -> str:
    return _hash(ip)


@dataclass(frozen=True)
class LockState:
    locked: bool
    retry_after_seconds: int


@dataclass(frozen=True)
class ThrottleKeys:
    email_hash: str
    ip_hash: str


def _keys(email: str, ip: str) -> list[tuple[str, str]]:
    return [
        (EMAIL_SCOPE, email_key(email)),
        (IP_SCOPE, ip_key(ip)),
    ]


def check_locked(
    email: str,
    ip: str,
    *,
    now: datetime | None = None,
) -> LockState:
    """Whether either key is locked, and the longest remaining lock."""
    reference = now or datetime.now(UTC)
    pairs = _keys(email, ip)
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            get(_FILE, "locked_keys"),
            {
                "scopes": [scope for scope, _ in pairs],
                "key_hashes": [key_hash for _, key_hash in pairs],
                "now": reference,
            },
        ).fetchall()
    if not rows:
        return LockState(locked=False, retry_after_seconds=0)
    remaining = max(
        int((row["locked_until"] - reference).total_seconds()) for row in rows
    )
    return LockState(locked=True, retry_after_seconds=max(remaining, 0))


def record_failure(
    email: str,
    ip: str,
    policy: LoginThrottlePolicy,
    *,
    now: datetime | None = None,
) -> None:
    """Increment both failure keys and lock a key once it hits the cap."""
    reference = now or datetime.now(UTC)
    with connection() as conn:
        for scope, key_hash in _keys(email, ip):
            _bump(conn, scope, key_hash, policy, reference)
        conn.commit()


def _bump(
    conn: Connection,
    scope: str,
    key_hash: str,
    policy: LoginThrottlePolicy,
    reference: datetime,
) -> None:
    window_start = reference - timedelta(seconds=policy.window_seconds)
    conn.execute(
        get(_FILE, "ensure_throttle_row"),
        {"scope": scope, "key_hash": key_hash, "now": reference},
    )
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "lock_throttle_row"),
            {"scope": scope, "key_hash": key_hash},
        ).fetchone()
    assert row is not None
    window_expired = (
        row["first_failure_at"] is None or row["first_failure_at"] < window_start
    )
    if window_expired:
        failure_count = 1
        first_failure_at = reference
    else:
        failure_count = int(row["failure_count"]) + 1
        first_failure_at = row["first_failure_at"]
    locked_until = (
        reference + timedelta(seconds=policy.lockout_seconds)
        if failure_count >= policy.max_failures
        else None
    )
    conn.execute(
        get(_FILE, "update_throttle_after_failure"),
        {
            "scope": scope,
            "key_hash": key_hash,
            "failure_count": failure_count,
            "first_failure_at": first_failure_at,
            "locked_until": locked_until,
            "now": reference,
        },
    )


def clear_email(email: str) -> None:
    """Successful login: forget this account's failures. The IP counter is
    intentionally left alone (see module docstring)."""
    with connection() as conn:
        conn.execute(
            get(_FILE, "clear_throttle_key"),
            {"scope": EMAIL_SCOPE, "key_hash": email_key(email)},
        )
        conn.commit()
