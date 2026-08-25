from uuid import uuid4

from fastapi.testclient import TestClient


def _email() -> str:
    return f"{uuid4().hex}@test.invalid"


def test_register_then_me(client: TestClient) -> None:
    email = _email()
    r = client.post(
        "/auth/register",
        json={"name": "Ada", "email": email, "password": "pw123"},
    )
    assert r.status_code == 200
    user = r.json()
    assert user["email"] == email

    token_resp = client.post("/auth/login", json={"email": email, "password": "pw123"})
    assert token_resp.status_code == 200
    token = token_resp.json()["access_token"]

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == email


def test_register_duplicate_email_conflicts(client: TestClient) -> None:
    email = _email()
    client.post(
        "/auth/register", json={"name": "A", "email": email, "password": "p"}
    )
    dup = client.post(
        "/auth/register", json={"name": "B", "email": email, "password": "p"}
    )
    assert dup.status_code == 409


def test_login_wrong_password_rejected(client: TestClient) -> None:
    email = _email()
    client.post(
        "/auth/register", json={"name": "A", "email": email, "password": "right"}
    )
    bad = client.post("/auth/login", json={"email": email, "password": "wrong"})
    assert bad.status_code == 401


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
