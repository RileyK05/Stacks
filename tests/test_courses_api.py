from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from src.backend.common.db import connection

PASSWORD = "correct-horse-battery"


def _user(client: TestClient) -> tuple[str, dict]:
    email = f"{uuid4().hex}@test.invalid"
    response = client.post(
        "/auth/register",
        json={"name": "Course User", "email": email, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    token = login.json()["access_token"]
    return token, body


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_register_keeps_support_code_out_of_api(client: TestClient) -> None:
    _, body = _user(client)
    assert "support_code" not in body
    with connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM premium_codes WHERE issued_for_user_id = %s",
            (body["user_id"],),
        ).fetchone()[0]
    assert count == 1


def test_create_course_returns_owner_view(client: TestClient) -> None:
    token, _ = _user(client)
    response = client.post(
        "/courses", json={"name": "Calculus"}, headers=_headers(token)
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["join_code"] is None
    assert body["role"] == "owner"
    assert body["visibility"] == "private"
    assert body["source_count"] == 0
    assert body["stored_bytes"] == 0
    assert "support_code" not in body
    memory_bank = client.get("/memory-bank", headers=_headers(token))
    assert memory_bank.status_code == 200
    assert memory_bank.json()[0]["course_id"] == body["course_id"]
    assert "Course: Calculus" in memory_bank.json()[0]["summary"]


def _post_course(client: TestClient, token: str, name: str) -> object:
    return client.post(
        "/courses",
        json={"name": name},
        headers=_headers(token),
    )


def test_client_cannot_choose_join_code(client: TestClient) -> None:
    token, _ = _user(client)
    response = client.post(
        "/courses",
        json={"code": "PHYS", "name": "Physics"},
        headers=_headers(token),
    )
    assert response.status_code == 422


def test_random_join_codes_are_unique_and_visibility_scoped(
    client: TestClient,
) -> None:
    token, _ = _user(client)
    first = client.post(
        "/courses",
        json={"name": "A", "visibility": "invite_only"},
        headers=_headers(token),
    ).json()
    second = client.post(
        "/courses",
        json={"name": "B", "visibility": "public"},
        headers=_headers(token),
    ).json()
    assert len(first["join_code"]) == 19
    assert len(second["join_code"]) == 19
    assert first["join_code"] != second["join_code"]


def test_free_course_limit_enforced(client: TestClient) -> None:
    token, _ = _user(client)
    statuses = [
        client.post(
            "/courses",
            json={"name": name},
            headers=_headers(token),
        ).status_code
        for name in ("A1", "A2", "A3")
    ]
    assert statuses == [201, 201, 403]


def test_course_list_includes_owned(client: TestClient) -> None:
    token, _ = _user(client)
    client.post(
        "/courses", json={"name": "Listed"}, headers=_headers(token)
    )
    listing = client.get("/courses", headers=_headers(token))
    assert listing.status_code == 200
    assert any(course["role"] == "owner" for course in listing.json())


def test_course_requires_auth(client: TestClient) -> None:
    response = client.get("/courses")
    assert response.status_code in (401, 403)


def test_patch_course_visibility(client: TestClient) -> None:
    token, _ = _user(client)
    created = client.post(
        "/courses", json={"name": "Public"}, headers=_headers(token)
    )
    course_id = created.json()["course_id"]
    patched = client.patch(
        f"/courses/{course_id}",
        json={"visibility": "public"},
        headers=_headers(token),
    )
    assert patched.status_code == 200
    assert patched.json()["visibility"] == "public"


def test_delete_course_requires_owner(client: TestClient) -> None:
    owner_token, _ = _user(client)
    stranger_token, _ = _user(client)
    created = client.post(
        "/courses",
        json={"name": "Doomed"},
        headers=_headers(owner_token),
    )
    course_id = created.json()["course_id"]
    forbidden = client.delete(
        f"/courses/{course_id}", headers=_headers(stranger_token)
    )
    assert forbidden.status_code == 404
    deleted = client.delete(f"/courses/{course_id}", headers=_headers(owner_token))
    assert deleted.status_code == 204
    gone = client.get(f"/courses/{course_id}", headers=_headers(owner_token))
    assert gone.status_code == 404


def test_self_enroll_public_course(client: TestClient) -> None:
    owner_token, _ = _user(client)
    learner_token, _ = _user(client)
    created = client.post(
        "/courses",
        json={"name": "Open", "visibility": "public"},
        headers=_headers(owner_token),
    )
    course_id = created.json()["course_id"]
    enrolled = client.post(
        f"/courses/{course_id}/enroll", headers=_headers(learner_token)
    )
    assert enrolled.status_code == 201, enrolled.text
    duplicate = client.post(
        f"/courses/{course_id}/enroll", headers=_headers(learner_token)
    )
    assert duplicate.status_code == 409


def test_self_enroll_private_course_is_404(client: TestClient) -> None:
    owner_token, _ = _user(client)
    learner_token, _ = _user(client)
    created = client.post(
        "/courses",
        json={"name": "Private"},
        headers=_headers(owner_token),
    )
    course_id = created.json()["course_id"]
    enrolled = client.post(
        f"/courses/{course_id}/enroll", headers=_headers(learner_token)
    )
    assert enrolled.status_code == 404


def test_self_enroll_invite_only_course_signals_join_code(client: TestClient) -> None:
    owner_token, _ = _user(client)
    learner_token, _ = _user(client)
    created = client.post(
        "/courses",
        json={"name": "Gated", "visibility": "invite_only"},
        headers=_headers(owner_token),
    )
    course_id = created.json()["course_id"]
    enrolled = client.post(
        f"/courses/{course_id}/enroll", headers=_headers(learner_token)
    )
    assert enrolled.status_code == 409
    assert "join code" in enrolled.json()["detail"]


def test_revoke_then_self_reenroll(client: TestClient) -> None:
    owner_token, _ = _user(client)
    learner_token, learner_body = _user(client)
    created = client.post(
        "/courses",
        json={"name": "Revocation", "visibility": "public"},
        headers=_headers(owner_token),
    )
    course_id = created.json()["course_id"]
    client.post(f"/courses/{course_id}/enroll", headers=_headers(learner_token))
    learner_id = learner_body["user_id"]
    revoked = client.delete(
        f"/courses/{course_id}/enrollments/{learner_id}",
        headers=_headers(owner_token),
    )
    assert revoked.status_code == 204
    denied = client.get(f"/courses/{course_id}", headers=_headers(learner_token))
    assert denied.status_code == 404
    reenrolled = client.post(
        f"/courses/{course_id}/enroll", headers=_headers(learner_token)
    )
    assert reenrolled.status_code == 201


def test_invite_and_member_visibility(client: TestClient) -> None:
    owner_token, owner_body = _user(client)
    learner_token, learner_body = _user(client)
    created = client.post(
        "/courses",
        json={"name": "Invited"},
        headers=_headers(owner_token),
    )
    course_id = created.json()["course_id"]
    invited = client.post(
        f"/courses/{course_id}/invitations",
        json={"user_id": learner_body["user_id"]},
        headers=_headers(owner_token),
    )
    assert invited.status_code == 201, invited.text
    assert invited.json()["status"] == "invited"
    assert client.get(
        "/memory-bank", headers=_headers(learner_token)
    ).json() == []
    before_acceptance = client.get(
        f"/courses/{course_id}", headers=_headers(learner_token)
    )
    assert before_acceptance.status_code == 404
    accepted = client.post(
        f"/courses/{course_id}/invitations/accept",
        headers=_headers(learner_token),
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "active"
    learner_memory = client.get(
        "/memory-bank", headers=_headers(learner_token)
    ).json()
    assert learner_memory[0]["course_id"] == course_id
    members = client.get(
        f"/courses/{course_id}/members", headers=_headers(owner_token)
    )
    assert members.status_code == 200
    assert any(
        member["user_id"] == learner_body["user_id"] for member in members.json()
    )
    learner_members = client.get(
        f"/courses/{course_id}/members", headers=_headers(learner_token)
    )
    assert learner_members.status_code == 404


def test_inviting_unknown_user_is_404(client: TestClient) -> None:
    owner_token, _ = _user(client)
    created = client.post(
        "/courses",
        json={"name": "Unknown invite"},
        headers=_headers(owner_token),
    )
    response = client.post(
        f"/courses/{created.json()['course_id']}/invitations",
        json={"user_id": str(uuid4())},
        headers=_headers(owner_token),
    )
    assert response.status_code == 404


def test_owner_cannot_self_enroll_own_course(client: TestClient) -> None:
    owner_token, _ = _user(client)
    created = client.post(
        "/courses",
        json={"name": "Owned", "visibility": "public"},
        headers=_headers(owner_token),
    )
    course_id = created.json()["course_id"]
    response = client.post(
        f"/courses/{course_id}/enroll", headers=_headers(owner_token)
    )
    assert response.status_code == 404


def test_invite_only_join_code_is_owner_visible_and_joinable(
    client: TestClient,
) -> None:
    owner_token, _ = _user(client)
    learner_token, _ = _user(client)
    created = client.post(
        "/courses",
        json={"name": "Joinable", "visibility": "invite_only"},
        headers=_headers(owner_token),
    )
    join_code = created.json()["join_code"]
    assert join_code is not None

    joined = client.post(
        "/courses/join",
        json={"join_code": join_code},
        headers=_headers(learner_token),
    )
    assert joined.status_code == 201
    learner_view = client.get(
        f"/courses/{created.json()['course_id']}",
        headers=_headers(learner_token),
    )
    assert learner_view.status_code == 200
    assert learner_view.json()["join_code"] is None


def test_owner_can_rotate_shareable_join_code(client: TestClient) -> None:
    owner_token, _ = _user(client)
    learner_token, _ = _user(client)
    created = client.post(
        "/courses",
        json={"name": "Rotating", "visibility": "invite_only"},
        headers=_headers(owner_token),
    ).json()
    old_code = created["join_code"]
    rotated = client.post(
        f"/courses/{created['course_id']}/join-code/rotate",
        headers=_headers(owner_token),
    )
    assert rotated.status_code == 200
    new_code = rotated.json()["join_code"]
    assert new_code != old_code
    assert client.post(
        "/courses/join",
        json={"join_code": old_code},
        headers=_headers(learner_token),
    ).status_code == 404
    assert client.post(
        "/courses/join",
        json={"join_code": new_code},
        headers=_headers(learner_token),
    ).status_code == 201


def test_public_catalog_exposes_public_join_code(client: TestClient) -> None:
    owner_token, _ = _user(client)
    created = client.post(
        "/courses",
        json={"name": "Catalog", "visibility": "public"},
        headers=_headers(owner_token),
    ).json()
    catalog = client.get("/courses/public")
    assert catalog.status_code == 200
    public_course = next(
        row for row in catalog.json() if row["course_id"] == created["course_id"]
    )
    assert public_course["join_code"] == created["join_code"]


def test_public_to_private_creates_learner_archive_and_owner_successor(
    client: TestClient,
) -> None:
    owner_token, _ = _user(client)
    learner_token, _ = _user(client)
    created = client.post(
        "/courses",
        json={"name": "Shared", "visibility": "public"},
        headers=_headers(owner_token),
    )
    original_id = created.json()["course_id"]
    client.post(
        f"/courses/{original_id}/enroll", headers=_headers(learner_token)
    )

    restricted = client.patch(
        f"/courses/{original_id}",
        json={"visibility": "private"},
        headers=_headers(owner_token),
    )
    assert restricted.status_code == 200, restricted.text
    successor_id = restricted.json()["course_id"]
    assert successor_id != original_id
    assert restricted.json()["visibility"] == "private"
    assert restricted.json()["join_code"] is None

    learner_archives = client.get(
        "/course-archives", headers=_headers(learner_token)
    )
    assert learner_archives.status_code == 200
    assert learner_archives.json()[0]["course_id"] == original_id
    copied = client.post(
        f"/course-archives/{original_id}/copy",
        json={},
        headers=_headers(learner_token),
    )
    assert copied.status_code == 201, copied.text
    assert copied.json()["course_id"] not in {original_id, successor_id}

    second_copy = client.post(
        f"/course-archives/{original_id}/copy",
        json={},
        headers=_headers(learner_token),
    )
    assert second_copy.status_code == 201


def test_leaving_declines_pending_invitation_instead_of_revoking(
    client: TestClient,
) -> None:
    owner_token, owner_body = _user(client)
    learner_token, learner_body = _user(client)
    created = client.post(
        "/courses",
        json={"name": "Leaving"},
        headers=_headers(owner_token),
    )
    course_id = created.json()["course_id"]
    invited = client.post(
        f"/courses/{course_id}/invitations",
        json={"user_id": learner_body["user_id"]},
        headers=_headers(owner_token),
    )
    assert invited.status_code == 201
    left = client.delete(
        f"/courses/{course_id}/enrollment", headers=_headers(learner_token)
    )
    assert left.status_code == 204
    with connection() as conn:
        state = conn.execute(
            "SELECT status, revoked_at, responded_at "
            "FROM course_enrollments WHERE course_id = %s AND user_id = %s",
            (UUID(course_id), UUID(learner_body["user_id"])),
        ).fetchone()
    assert state[0] == "declined"
    assert state[1] is None
    assert state[2] is not None


def test_owner_revoke_of_pending_invitation_stays_revoked(
    client: TestClient,
) -> None:
    owner_token, owner_body = _user(client)
    learner_token, learner_body = _user(client)
    created = client.post(
        "/courses",
        json={"name": "Rescinding"},
        headers=_headers(owner_token),
    )
    course_id = created.json()["course_id"]
    client.post(
        f"/courses/{course_id}/invitations",
        json={"user_id": learner_body["user_id"]},
        headers=_headers(owner_token),
    )
    revoked = client.delete(
        f"/courses/{course_id}/enrollments/{learner_body['user_id']}",
        headers=_headers(owner_token),
    )
    assert revoked.status_code == 204
    with connection() as conn:
        state = conn.execute(
            "SELECT status, revoked_at, responded_at "
            "FROM course_enrollments WHERE course_id = %s AND user_id = %s",
            (UUID(course_id), UUID(learner_body["user_id"])),
        ).fetchone()
    assert state[0] == "revoked"
    assert state[1] is not None


def test_register_rejects_unknown_fields(client: TestClient) -> None:
    response = client.post(
        "/auth/register",
        json={
            "name": "Strict",
            "email": f"{uuid4().hex}@test.invalid",
            "password": "long-password",
            "support_code": "please",
        },
    )
    assert response.status_code == 422
