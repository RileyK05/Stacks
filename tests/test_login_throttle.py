"""Login throttling (carried security item): failed logins lock the
targeted account and the source IP independently, a locked key gets 429
with Retry-After, and a successful login clears the account counter so a
legitimate user who mistyped is not punished."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from src.backend.common import login_throttle, users_repo
from src.backend.common.auth import hash_password
from src.backend.common.auth_config import LoginThrottlePolicy
from src.backend.common.db import connection

PASSWORD = "correct-horse-battery"
IP = "203.0.113.7"


@pytest.fixture
def policy() -> LoginThrottlePolicy:
    return LoginThrottlePolicy(
        auth_config_version="test",
        max_failures=3,
        window_seconds=900,
        lockout_seconds=900,
        trust_forwarded_for=False,
    )


def _account() -> str:
    email = f"{uuid4().hex}@test.invalid"
    users_repo.create("Throttle", email, hash_password(PASSWORD))
    return email


def test_email_key_locks_after_max_failures(policy) -> None:
    email = _account()
    assert not login_throttle.check_locked(email, IP).locked
    for _ in range(policy.max_failures):
        login_throttle.record_failure(email, IP, policy)
    state = login_throttle.check_locked(email, IP)
    assert state.locked
    assert state.retry_after_seconds > 0


def test_ip_key_locks_independently_of_email(policy) -> None:
    """Spraying many accounts from one host must lock the host even though
    no single email hit the cap."""
    for _ in range(policy.max_failures):
        login_throttle.record_failure(f"{uuid4().hex}@test.invalid", IP, policy)
    victim = _account()
    assert login_throttle.check_locked(victim, IP).locked
    other_ip = login_throttle.check_locked(victim, "198.51.100.9")
    assert not other_ip.locked, "a fresh IP key must not inherit the lock"


def test_window_reset_forgets_old_failures(policy) -> None:
    email = _account()
    stale = datetime.now(UTC) - timedelta(seconds=policy.window_seconds + 60)
    # Two old failures, then a fresh window starts: the count resets.
    login_throttle.record_failure(email, IP, policy, now=stale)
    login_throttle.record_failure(email, IP, policy, now=stale)
    login_throttle.record_failure(email, IP, policy)
    state = login_throttle.check_locked(email, IP)
    assert not state.locked, "stale failures must not count toward the cap"


def test_successful_login_clears_email_counter(policy) -> None:
    email = _account()
    # A unique IP keeps the shared-IP key out of this email-focused test.
    ip = f"198.51.100.{uuid4().int % 200 + 1}"
    for _ in range(policy.max_failures - 1):
        login_throttle.record_failure(email, ip, policy)
    login_throttle.clear_email(email)
    with connection() as conn:
        row = conn.execute(
            "SELECT count(*) FROM login_throttle"
            " WHERE scope = 'email' AND key_hash = %s",
            (login_throttle.email_key(email),),
        ).fetchone()
    assert row[0] == 0, "successful login must clear the account counter"
    # The IP counter is intentionally left intact (spray defense).
    with connection() as conn:
        ip_row = conn.execute(
            "SELECT count(*) FROM login_throttle"
            " WHERE scope = 'ip' AND key_hash = %s",
            (login_throttle.ip_key(ip),),
        ).fetchone()
    assert ip_row[0] == 1


def test_login_endpoint_returns_429_when_locked(client: TestClient) -> None:
    email = _account()
    # The key locks when the Nth failure is RECORDED; the request that
    # records it still gets 401. The next request sees the lock.
    for _ in range(5):
        first_response = client.post(
            "/auth/login", json={"email": email, "password": "wrong-password"}
        )
    assert first_response.status_code == 401
    response = client.post(
        "/auth/login", json={"email": email, "password": "wrong-password"}
    )
    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert response.json()["detail"]
    # A correct password is still refused while the key is locked.
    locked_out = client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert locked_out.status_code == 429


def test_login_endpoint_records_failure_and_throttles(client: TestClient) -> None:
    email = _account()
    first = client.post(
        "/auth/login", json={"email": email, "password": "wrong-password"}
    )
    assert first.status_code == 401
    with connection() as conn:
        count = conn.execute(
            "SELECT count(*) FROM login_throttle WHERE scope = 'email'"
        ).fetchone()[0]
    assert count == 1


def test_successful_login_resets_email_key(client: TestClient) -> None:
    email = _account()
    for _ in range(2):
        client.post(
            "/auth/login", json={"email": email, "password": "wrong-password"}
        )
    ok = client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert ok.status_code == 200
    with connection() as conn:
        rows = conn.execute(
            "SELECT count(*) FROM login_throttle WHERE scope = 'email'"
        ).fetchone()[0]
    assert rows == 0
