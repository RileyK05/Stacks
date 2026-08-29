from uuid import uuid4

from fastapi.testclient import TestClient
from src.backend.common.db import connection

PASSWORD = "correct-horse-battery"


def _email() -> str:
    return f"{uuid4().hex}@test.invalid"


def test_register_then_me(client: TestClient) -> None:
    email = _email()
    r = client.post(
        "/auth/register",
        json={"name": "Ada", "email": email, "password": PASSWORD},
    )
    assert r.status_code == 200
    user = r.json()
    assert user["email"] == email
    assert "password_hash" not in user
    assert "delete_requested_at" not in user

    token_resp = client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert token_resp.status_code == 200
    token = token_resp.json()["access_token"]

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == email
    assert me.json()["tier"] == "free"
    assert "password_hash" not in me.json()
    assert "delete_requested_at" not in me.json()


def test_register_duplicate_email_conflicts(client: TestClient) -> None:
    email = _email()
    client.post(
        "/auth/register", json={"name": "A", "email": email, "password": PASSWORD}
    )
    dup = client.post(
        "/auth/register", json={"name": "B", "email": email, "password": PASSWORD}
    )
    assert dup.status_code == 409


def test_login_wrong_password_rejected(client: TestClient) -> None:
    email = _email()
    client.post(
        "/auth/register", json={"name": "A", "email": email, "password": PASSWORD}
    )
    bad = client.post("/auth/login", json={"email": email, "password": "wrong"})
    assert bad.status_code == 401


def test_login_oversized_password_does_not_error(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "x" * 1000},
    )
    assert response.status_code == 401


def test_registration_normalizes_email(client: TestClient) -> None:
    email = _email()
    response = client.post(
        "/auth/register",
        json={"name": "Ada", "email": f"  {email.upper()}  ", "password": PASSWORD},
    )
    assert response.status_code == 200
    assert response.json()["email"] == email


def test_short_registration_password_rejected(client: TestClient) -> None:
    response = client.post(
        "/auth/register",
        json={"name": "Ada", "email": _email(), "password": "short"},
    )
    assert response.status_code == 422


def test_pending_deletion_account_cannot_login(client: TestClient) -> None:
    email = _email()
    client.post(
        "/auth/register",
        json={"name": "Ada", "email": email, "password": PASSWORD},
    )
    with connection() as conn:
        conn.execute(
            "UPDATE users SET delete_requested_at = now() WHERE email = %s", (email,)
        )
        conn.commit()
    response = client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 403


def test_login_unknown_user_rejected(client: TestClient) -> None:
    bad = client.post(
        "/auth/login", json={"email": "nope@nope.test", "password": "x"}
    )
    assert bad.status_code == 401


def test_me_without_token_rejected(client: TestClient) -> None:
    me = client.get("/auth/me")
    assert me.status_code in (401, 403)


def test_me_with_bad_token_rejected(client: TestClient) -> None:
    me = client.get("/auth/me", headers={"Authorization": "Bearer not.a.real.token"})
    assert me.status_code == 401
