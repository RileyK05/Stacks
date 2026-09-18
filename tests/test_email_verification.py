"""Email verification and password reset: token lifecycle, the outbox
seam, anti-enumeration on reset requests, resource-creation gating, and
the verify-email side effect of a successful password reset."""

import time
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from src.backend.common import email_repo, users_repo
from src.backend.common.db import connection
from tests.conftest import verify_email

PASSWORD = "correct-horse-battery"
NEW_PASSWORD = "different-long-pass"


def _register(client: TestClient) -> tuple[str, str, dict]:
    email = f"{uuid4().hex}@test.invalid"
    response = client.post(
        "/auth/register",
        json={"name": "Email User", "email": email, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return login.json()["access_token"], email, response.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _outbox_token(user_id, kind: str) -> str:
    email = email_repo.latest_outbox_email(user_id, kind)
    assert email is not None
    return email.body.split(": ", 1)[1].splitlines()[0]


def test_verification_flow_marks_account_and_lifts_gate(client: TestClient) -> None:
    token, email, body = _register(client)
    user_id = UUID(body["user_id"])

    assert client.get("/auth/me", headers=_headers(token)).json()[
        "email_verified"
    ] is False
    blocked = client.post("/courses", json={"name": "Nope"}, headers=_headers(token))
    assert blocked.status_code == 403
    assert "not verified" in blocked.json()["detail"]

    request = client.post("/auth/verify-email/request", headers=_headers(token))
    assert request.status_code == 202
    plaintext = _outbox_token(user_id, email_repo.VERIFICATION_KIND)
    confirmed = client.post(
        f"/auth/verify-email/{plaintext}", headers=_headers(token)
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["email_verified"] is True

    created = client.post(
        "/courses", json={"name": "Now Fine"}, headers=_headers(token))
    assert created.status_code == 201, created.text


def test_reissued_verification_token_invalidates_previous(
    client: TestClient,
) -> None:
    token, _, body = _register(client)
    user_id = UUID(body["user_id"])
    client.post("/auth/verify-email/request", headers=_headers(token))
    first = _outbox_token(user_id, email_repo.VERIFICATION_KIND)
    client.post("/auth/verify-email/request", headers=_headers(token))
    second = _outbox_token(user_id, email_repo.VERIFICATION_KIND)
    assert first != second

    stale = client.post(f"/auth/verify-email/{first}", headers=_headers(token))
    assert stale.status_code == 400
    fresh = client.post(f"/auth/verify-email/{second}", headers=_headers(token))
    assert fresh.status_code == 200, fresh.text


def test_verification_token_is_single_use_and_bound(
    client: TestClient,
) -> None:
    token, _, body = _register(client)
    user_id = UUID(body["user_id"])
    client.post("/auth/verify-email/request", headers=_headers(token))
    plaintext = _outbox_token(user_id, email_repo.VERIFICATION_KIND)

    assert (
        client.post(
            f"/auth/verify-email/{plaintext}", headers=_headers(token)
        ).status_code
        == 200
    )
    replay = client.post(
        f"/auth/verify-email/{plaintext}", headers=_headers(token)
    )
    assert replay.status_code == 400

    other_token, _, other_body = _register(client)
    other_id = UUID(other_body["user_id"])
    client.post("/auth/verify-email/request", headers=_headers(other_token))
    other_plaintext = _outbox_token(other_id, email_repo.VERIFICATION_KIND)
    crossed = client.post(
        f"/auth/verify-email/{other_plaintext}", headers=_headers(token)
    )
    assert crossed.status_code == 400
    assert client.get("/auth/me", headers=_headers(other_token)).json()[
        "email_verified"
    ] is False


def test_password_reset_full_flow(client: TestClient) -> None:
    token, email, body = _register(client)
    user_id = UUID(body["user_id"])

    request = client.post(
        "/auth/password-reset/request", json={"email": email}
    )
    assert request.status_code == 202
    plaintext = _outbox_token(user_id, email_repo.RESET_KIND)

    confirm = client.post(
        "/auth/password-reset/confirm",
        json={"token": plaintext, "new_password": NEW_PASSWORD},
    )
    assert confirm.status_code == 200, confirm.text

    old_login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert old_login.status_code == 401
    new_login = client.post(
        "/auth/login", json={"email": email, "password": NEW_PASSWORD}
    )
    assert new_login.status_code == 200


def test_password_reset_also_verifies_email(client: TestClient) -> None:
    token, email, body = _register(client)
    user_id = UUID(body["user_id"])
    client.post("/auth/password-reset/request", json={"email": email})
    plaintext = _outbox_token(user_id, email_repo.RESET_KIND)
    confirm = client.post(
        "/auth/password-reset/confirm",
        json={"token": plaintext, "new_password": NEW_PASSWORD},
    )
    assert confirm.status_code == 200
    assert confirm.json()["email_verified"] is True


def test_password_reset_request_does_not_reveal_accounts(
    client: TestClient,
) -> None:
    unknown = client.post(
        "/auth/password-reset/request", json={"email": "nobody@test.invalid"}
    )
    assert unknown.status_code == 202
    with connection() as conn:
        queued = conn.execute(
            "SELECT COUNT(*) FROM email_outbox WHERE to_email = %s",
            ("nobody@test.invalid",),
        ).fetchone()[0]
    assert queued == 0


def test_expired_reset_token_is_rejected(client: TestClient) -> None:
    from datetime import UTC, datetime, timedelta

    token, email, body = _register(client)
    user_id = UUID(body["user_id"])
    client.post("/auth/password-reset/request", json={"email": email})
    plaintext = _outbox_token(user_id, email_repo.RESET_KIND)

    with connection() as conn:
        conn.execute(
            "UPDATE email_tokens SET expires_at = %s "
            "WHERE user_id = %s AND kind = 'password_reset'",
            (datetime.now(UTC) - timedelta(minutes=1), user_id),
        )
        conn.commit()
    confirm = client.post(
        "/auth/password-reset/confirm",
        json={"token": plaintext, "new_password": NEW_PASSWORD},
    )
    assert confirm.status_code == 400
    still_old = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert still_old.status_code == 200


def test_reset_token_single_use(client: TestClient) -> None:
    token, email, body = _register(client)
    user_id = UUID(body["user_id"])
    client.post("/auth/password-reset/request", json={"email": email})
    plaintext = _outbox_token(user_id, email_repo.RESET_KIND)
    first = client.post(
        "/auth/password-reset/confirm",
        json={"token": plaintext, "new_password": NEW_PASSWORD},
    )
    assert first.status_code == 200
    replay = client.post(
        "/auth/password-reset/confirm",
        json={"token": plaintext, "new_password": "yet-another-password"},
    )
    assert replay.status_code == 400


def test_upload_blocked_until_verified(client: TestClient) -> None:
    token, _, _ = _register(client)
    created = client.post("/courses", json={"name": "Gated"}, headers=_headers(token))
    assert created.status_code == 403
    verify_email(client, token)
    created = client.post("/courses", json={"name": "Gated"}, headers=_headers(token))
    assert created.status_code == 201
    course_id = created.json()["course_id"]
    upload = client.post(
        f"/courses/{course_id}/sources",
        data={"source_type": "notes"},
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers=_headers(token),
    )
    assert upload.status_code == 201, upload.text

def test_consume_token_lost_race_is_rejected_not_asserted() -> None:
    """Two requests redeeming the same token concurrently (double-clicked
    reset link, mail scanner prefetching the URL) both pass the SELECT; the
    loser's guarded UPDATE matches nothing. That is a rejected token, not a
    broken invariant — it must not surface as an AssertionError 500."""
    import threading

    from src.backend.common.db import connect

    user = users_repo.create("Race", f"{uuid4().hex}@test.invalid", "x")
    with connection() as conn:
        token = email_repo.issue_token(
            conn,
            user_id=user.user_id,
            kind=email_repo.RESET_KIND,
            to_email="a@b.invalid",
            subject="s",
            body_template="{token}",
        )
        conn.commit()

    winner = connect()
    email_repo.consume_token(
        winner, kind=email_repo.RESET_KIND, plaintext=token
    )
    outcome: dict[str, str] = {}

    def loser() -> None:
        conn = connect()
        try:
            email_repo.consume_token(
                conn, kind=email_repo.RESET_KIND, plaintext=token
            )
            outcome["result"] = "double-consumed"
        except email_repo.TokenRejectedError:
            outcome["result"] = "rejected"
        except AssertionError:
            outcome["result"] = "assertion-error"
        finally:
            conn.close()

    thread = threading.Thread(target=loser)
    thread.start()
    time.sleep(1.0)
    winner.commit()
    winner.close()
    thread.join(timeout=20)
    assert outcome.get("result") == "rejected"


def test_password_reset_invalidates_sessions_minted_before_it(
    client: TestClient,
) -> None:
    """The compromise response: if the reset happened because someone else
    may hold the password, the attacker's pre-reset session must die at
    the next request. current_user rejects tokens whose stamp predates
    the live password_changed_at."""
    token, email, body = _register(client)
    user_id = UUID(body["user_id"])
    assert client.get("/auth/me", headers=_headers(token)).status_code == 200

    client.post("/auth/password-reset/request", json={"email": email})
    plaintext = _outbox_token(user_id, email_repo.RESET_KIND)
    confirm = client.post(
        "/auth/password-reset/confirm",
        json={"token": plaintext, "new_password": NEW_PASSWORD},
    )
    assert confirm.status_code == 200, confirm.text

    stale = client.get("/auth/me", headers=_headers(token))
    assert stale.status_code == 401, "pre-reset session must be dead"
    assert "password change" in stale.json()["detail"]

    fresh_login = client.post(
        "/auth/login", json={"email": email, "password": NEW_PASSWORD}
    )
    assert fresh_login.status_code == 200
    assert (
        client.get(
            "/auth/me", headers=_headers(fresh_login.json()["access_token"])
        ).status_code
        == 200
    )


def test_password_max_length_rejected_at_register(client: TestClient) -> None:
    """24 chars pass, 25 fail — the boundary is the policy, not an
    accident of fixture choice."""
    email = f"{uuid4().hex}@test.invalid"
    ok = client.post(
        "/auth/register",
        json={
            "name": "Boundary",
            "email": email,
            "password": "x" * 24,
        },
    )
    assert ok.status_code == 201, ok.text
    over = client.post(
        "/auth/register",
        json={
            "name": "Boundary",
            "email": f"{uuid4().hex}@test.invalid",
            "password": "x" * 25,
        },
    )
    assert over.status_code == 422
