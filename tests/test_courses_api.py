from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


def _create(client: TestClient, name: str) -> dict:
    response = client.post("/courses", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def test_create_list_get_and_rename(client: TestClient) -> None:
    algebra = _create(client, "Linear Algebra")
    _create(client, "analysis")
    assert algebra["source_count"] == 0 and algebra["stored_bytes"] == 0

    names = [course["name"] for course in client.get("/courses").json()]
    assert names == ["analysis", "Linear Algebra"]  # case-insensitive order

    fetched = client.get(f"/courses/{algebra['course_id']}").json()
    assert fetched["name"] == "Linear Algebra"

    renamed = client.patch(
        f"/courses/{algebra['course_id']}", json={"name": "Linear Algebra II"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Linear Algebra II"


@pytest.mark.parametrize("payload", [{"name": ""}, {"name": "x" * 201}, {}])
def test_create_validates_name(client: TestClient, payload: dict) -> None:
    assert client.post("/courses", json=payload).status_code == 422


def test_create_rejects_unknown_fields(client: TestClient) -> None:
    response = client.post("/courses", json={"name": "A", "visibility": "public"})
    assert response.status_code == 422


def test_unknown_course_is_404(client: TestClient) -> None:
    missing = uuid4()
    assert client.get(f"/courses/{missing}").status_code == 404
    assert client.patch(f"/courses/{missing}", json={"name": "x"}).status_code == 404
    assert client.delete(f"/courses/{missing}").status_code == 404


def test_delete_moves_to_trash_then_restore(client: TestClient) -> None:
    course = _create(client, "Topology")
    deleted = client.delete(f"/courses/{course['course_id']}")
    assert deleted.status_code == 200
    assert deleted.json()["purge_after"] > deleted.json()["deleted_at"]

    assert client.get("/courses").json() == []
    assert client.get(f"/courses/{course['course_id']}").status_code == 404
    trash = client.get("/trash").json()
    assert [entry["course_id"] for entry in trash] == [course["course_id"]]

    restored = client.post(f"/trash/{course['course_id']}/restore")
    assert restored.status_code == 200
    assert client.get("/trash").json() == []
    assert [c["course_id"] for c in client.get("/courses").json()] == [
        course["course_id"]
    ]


def test_trashed_course_cannot_be_renamed_or_deleted_again(client: TestClient) -> None:
    course = _create(client, "Gone")
    client.delete(f"/courses/{course['course_id']}")
    assert (
        client.patch(f"/courses/{course['course_id']}", json={"name": "x"}).status_code
        == 404
    )
    assert client.delete(f"/courses/{course['course_id']}").status_code == 404


def test_purge_from_trash_keeps_course_memory(client: TestClient) -> None:
    course = _create(client, "Keepsake")
    assert client.delete(f"/trash/{course['course_id']}").status_code == 404
    client.delete(f"/courses/{course['course_id']}")
    assert client.delete(f"/trash/{course['course_id']}").status_code == 204
    assert client.get("/trash").json() == []
    assert client.post(f"/trash/{course['course_id']}/restore").status_code == 404
    memories = client.get("/course-memories").json()
    assert [m["name"] for m in memories] == ["Keepsake"]


def test_app_token_is_required_when_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_API_TOKEN", "launch-secret")
    assert client.get("/courses").status_code == 401
    assert client.get("/courses", headers={"X-App-Token": "wrong"}).status_code == 401
    ok = client.get("/courses", headers={"X-App-Token": "launch-secret"})
    assert ok.status_code == 200
