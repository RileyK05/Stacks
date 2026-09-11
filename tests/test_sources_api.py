from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from src.backend.common import storage
from src.backend.common.db import connection
from src.backend.common.lifecycle_config import load_lifecycle_policy
from src.backend.common.schemas.base import UserTier
from src.backend.common.tiers import load_tier_policies
from tests.conftest import verify_email

PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _storage_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(
        "src.backend.common.storage.get_settings",
        lambda: type("S", (), {"storage_root": str(tmp_path)})(),
    )
    return tmp_path


def _user(client: TestClient) -> tuple[str, UUID]:
    email = f"{uuid4().hex}@test.invalid"
    registered = client.post(
        "/auth/register",
        json={"name": "Uploader", "email": email, "password": PASSWORD},
    )
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    token = login.json()["access_token"]
    verify_email(client, token)
    return token, UUID(registered.json()["user_id"])


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _course(client: TestClient, token: str) -> UUID:
    response = client.post(
        "/courses", json={"name": "Uploads"}, headers=_headers(token)
    )
    return UUID(response.json()["course_id"])


def test_upload_streams_compresses_and_accounts_stored_bytes(
    client: TestClient,
) -> None:
    token, _ = _user(client)
    course_id = _course(client, token)
    raw = b"source-grounded notes " * 10_000
    uploaded = client.post(
        f"/courses/{course_id}/sources",
        data={"source_type": "notes"},
        files={"file": ("../week-1.txt", raw, "text/plain")},
        headers=_headers(token),
    )

    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["filename"] == "week-1.txt"
    assert body["raw_size_bytes"] == len(raw)
    assert body["stored_encoding"] == "gzip"
    assert body["stored_size_bytes"] < len(raw)
    source_id = UUID(body["source_id"])
    assert (
        storage.read_stored(
            course_id,
            source_id,
            "gzip",
            max_decompressed_bytes=load_lifecycle_policy().max_decompressed_bytes,
        )
        == raw
    )
    with connection() as conn:
        recorded = conn.execute(
            "SELECT size_bytes, stored_encoding FROM sources WHERE source_id = %s",
            (source_id,),
        ).fetchone()
    assert recorded == (body["stored_size_bytes"], "gzip")

    view = client.get(f"/courses/{course_id}", headers=_headers(token)).json()
    assert view["source_count"] == 1
    assert view["stored_bytes"] == body["stored_size_bytes"]
    memory = client.get("/course-memories", headers=_headers(token)).json()[0]
    assert "week-1.txt" in memory["summary"]
    assert body["file_hash"] in memory["summary"]


def test_duplicate_content_is_rejected_without_double_charge(
    client: TestClient,
) -> None:
    token, _ = _user(client)
    course_id = _course(client, token)
    payload = b"same content" * 100
    first = client.post(
        f"/courses/{course_id}/sources",
        data={"source_type": "notes"},
        files={"file": ("one.txt", payload, "text/plain")},
        headers=_headers(token),
    )
    second = client.post(
        f"/courses/{course_id}/sources",
        data={"source_type": "notes"},
        files={"file": ("two.txt", payload, "text/plain")},
        headers=_headers(token),
    )
    assert first.status_code == 201
    assert second.status_code == 409
    with connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM sources WHERE course_id = %s", (course_id,)
        ).fetchone()[0] == 1


def test_only_owner_can_upload(client: TestClient) -> None:
    owner_token, _ = _user(client)
    stranger_token, _ = _user(client)
    course_id = _course(client, owner_token)
    response = client.post(
        f"/courses/{course_id}/sources",
        data={"source_type": "notes"},
        files={"file": ("notes.txt", b"notes", "text/plain")},
        headers=_headers(stranger_token),
    )
    assert response.status_code == 404


def test_raw_body_ceiling_is_separate_from_stored_quota(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, _ = _user(client)
    course_id = _course(client, token)
    base = load_tier_policies().policy_for(UserTier.FREE)
    small_raw_policy = base.model_copy(update={"max_raw_upload_bytes": 10})
    policies = type(
        "Policies",
        (),
        {"policy_for": lambda self, tier: small_raw_policy},
    )()
    monkeypatch.setattr(
        "src.backend.api.sources.tier_config.load_tier_policies",
        lambda: policies,
    )

    response = client.post(
        f"/courses/{course_id}/sources",
        data={"source_type": "notes"},
        files={"file": ("large.txt", b"x" * 11, "text/plain")},
        headers=_headers(token),
    )
    assert response.status_code == 413
    with connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM sources WHERE course_id = %s", (course_id,)
        ).fetchone()[0] == 0


def test_archived_course_copy_recreates_stored_sources(
    client: TestClient,
) -> None:
    token, _ = _user(client)
    course_id = _course(client, token)
    raw = b"copy this grounded source" * 500
    uploaded = client.post(
        f"/courses/{course_id}/sources",
        data={"source_type": "notes"},
        files={"file": ("copy.txt", raw, "text/plain")},
        headers=_headers(token),
    )
    assert uploaded.status_code == 201
    assert client.delete(
        f"/courses/{course_id}", headers=_headers(token)
    ).status_code == 204

    copied = client.post(
        f"/course-archives/{course_id}/copy",
        json={"name": "Recovered"},
        headers=_headers(token),
    )
    assert copied.status_code == 201, copied.text
    copied_id = UUID(copied.json()["course_id"])
    copied_view = client.get(
        f"/courses/{copied_id}", headers=_headers(token)
    ).json()
    assert copied_view["source_count"] == 1
    with connection() as conn:
        source_id, encoding = conn.execute(
            "SELECT source_id, stored_encoding FROM sources WHERE course_id = %s",
            (copied_id,),
        ).fetchone()
    assert (
        storage.read_stored(
            copied_id,
            source_id,
            encoding,
            max_decompressed_bytes=load_lifecycle_policy().max_decompressed_bytes,
        )
        == raw
    )
