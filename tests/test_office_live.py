from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from src.backend.common.db import connection
from src.backend.office_addin import live
from tests.factories import make_course


@pytest.fixture
def bridge(monkeypatch):
    from src.backend.office_addin.app import create_office

    clock = [0.0]
    monkeypatch.setattr(live, "BROKER", live.LiveBroker(lambda: clock[0]))
    return TestClient(create_office()), clock


def connect(bridge, host="word", text="Beginning\nLast page with current argument."):
    office, _ = bridge
    course = str(make_course("Political science").course_id)
    document = {
        "title": "My work",
        "text": text,
        "origin": "office",
        "external_id": f"office:{uuid4()}",
        "coverage": "partial",
        "warnings": ["Nontext content omitted."],
    }
    response = office.post(
        "/work-document", json={"course_id": course, "document": document}
    )
    assert response.status_code == 200, response.text
    work = response.json()
    binding = {
        "course_id": course,
        "session_id": work["session_id"],
        "host": host,
        "external_id": document["external_id"],
    }
    registered = office.post("/live", json=binding)
    assert registered.status_code == 200, registered.text
    key = registered.json()["connection_id"]
    return (
        f"/companion/courses/{course}/work/{work['session_id']}",
        key,
        binding,
        document,
        work,
    )


def complete(office, key, request, document):
    return office.post(
        f"/live/{key}/complete",
        json={
            "request_id": request["request_id"],
            "external_id": document["external_id"],
            "document": document,
        },
    )


@pytest.mark.parametrize("host", ["word", "excel", "powerpoint"])
def test_latest_document_refresh_is_shared_and_not_learning(client, bridge, host):
    path, key, _, document, original = connect(bridge, host)
    office, _ = bridge
    assert client.get(path + "/live").json()["host"] == host
    request = client.post(path + "/refresh").json()
    assert client.post(path + "/refresh").json() == request
    poll = office.post(
        f"/live/{key}/poll", json={"external_id": document["external_id"]}
    )
    assert poll.json()["command"] == {
        "request_id": request["request_id"],
        "expected_revision": 1,
    }
    assert poll.json()["policy"]["reader"]["maxChars"] == 300000
    document["text"] += "\nAn edit made after connecting, on the final page."
    result = complete(office, key, request, document)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "complete" and result.json()["revision"] == 2
    saved = client.get(path).json()
    assert saved["document"]["text"] == document["text"]
    assert saved["turns"] == [] and saved["session_id"] == original["session_id"]
    assert (
        client.get(path + f"/refresh/{request['request_id']}").json() == result.json()
    )
    assert (
        complete(office, key, request, {**document, "text": "Late retry"}).json()
        == result.json()
    )
    assert client.get(path).json()["revision"] == 2
    with connection() as conn:
        for table in (
            "learning_observations",
            "learning_experiments",
            "core_method_observations",
            "practice_runs",
            "sources",
            "retrieval_traces",
        ):
            assert (
                conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0
            )


def test_unchanged_refresh_keeps_revision_capture_time_and_update_time(client, bridge):
    path, key, _, document, work = connect(bridge)
    office, _ = bridge
    request = client.post(path + "/refresh").json()
    assert complete(office, key, request, document).json()["revision"] == 1
    assert client.get(path).json() == work


def test_manual_office_publication_deduplicates_but_checks_revision(bridge):
    _, _, binding, document, _ = connect(bridge)
    office, _ = bridge
    body = {
        "course_id": binding["course_id"],
        "session_id": binding["session_id"],
        "expected_revision": 1,
        "document": document,
    }
    assert office.post("/work-document", json=body).json()["revision"] == 1
    assert (
        office.post("/work-document", json={**body, "expected_revision": 0}).status_code
        == 409
    )


def test_pane_can_recover_latest_revision_without_overwriting_other_identity(
    client, bridge
):
    path, _, binding, document, _ = connect(bridge)
    office, _ = bridge
    client.put(
        path + "/document",
        json={**document, "text": "Updated in companion", "expected_revision": 1},
    )
    route = f"/work/{binding['session_id']}?course_id={binding['course_id']}"
    latest = office.get(route)
    assert latest.status_code == 200
    assert latest.json()["revision"] == 2
    assert latest.json()["document"]["external_id"] == document["external_id"]
    other = make_course("Other").course_id
    assert (
        office.get(f"/work/{binding['session_id']}?course_id={other}").status_code
        == 404
    )
    client.put(
        path + "/document",
        json={**document, "external_id": "another-document", "expected_revision": 2},
    )
    assert office.get(route).json()["document"]["external_id"] == "another-document"


def test_changed_snapshot_during_read_rejects_completion(client, bridge):
    path, key, _, document, _ = connect(bridge)
    office, _ = bridge
    request = client.post(path + "/refresh").json()
    other = client.put(
        path + "/document",
        json={**document, "text": "Newer manual draft", "expected_revision": 1},
    )
    assert other.status_code == 200
    result = complete(
        office, key, request, {**document, "text": "Old late host read"}
    ).json()
    assert result["status"] == "failed" and "changed" in result["error"]
    assert client.get(path).json()["document"]["text"] == "Newer manual draft"


def test_replaced_pane_cannot_finish_old_read(client, bridge):
    path, key, binding, document, _ = connect(bridge)
    office, _ = bridge
    request = client.post(path + "/refresh").json()
    replacement = office.post("/live", json=binding).json()["connection_id"]
    assert replacement != key
    assert complete(office, key, request, document).status_code == 409
    assert (
        client.get(path + f"/refresh/{request['request_id']}").json()["status"]
        == "failed"
    )
    assert (
        office.post(
            f"/live/{key}/poll", json={"external_id": document["external_id"]}
        ).status_code
        == 409
    )


def test_expired_connection_preserves_work_and_requires_reconnection(client, bridge):
    path, key, _, document, work = connect(bridge)
    office, clock = bridge
    clock[0] = 16
    assert client.get(path + "/live").json()["connected"] is False
    assert client.post(path + "/refresh").status_code == 409
    assert client.get(path).json() == work
    assert (
        office.post(
            f"/live/{key}/poll", json={"external_id": document["external_id"]}
        ).status_code
        == 409
    )


def test_slow_read_can_outlive_heartbeat_lease_but_not_read_deadline(client, bridge):
    path, key, _, document, _ = connect(bridge)
    office, clock = bridge
    request = client.post(path + "/refresh").json()
    clock[0] = 20
    assert client.get(path + "/live").json()["connected"] is True
    assert complete(office, key, request, document).json()["status"] == "complete"
    request = client.post(path + "/refresh").json()
    clock[0] = 46
    assert (
        client.get(path + f"/refresh/{request['request_id']}").json()["status"]
        == "failed"
    )
    assert complete(office, key, request, document).status_code == 409


def test_read_error_keeps_snapshot_and_next_refresh_can_succeed(client, bridge):
    path, key, _, document, work = connect(bridge)
    office, _ = bridge
    request = client.post(path + "/refresh").json()
    result = office.post(
        f"/live/{key}/complete",
        json={
            "request_id": request["request_id"],
            "external_id": document["external_id"],
            "error": "Workbook is protected",
        },
    )
    assert result.json()["status"] == "failed"
    assert client.get(path).json() == work
    retry = client.post(path + "/refresh").json()
    assert retry["request_id"] != request["request_id"]
    assert complete(office, key, retry, document).json()["status"] == "complete"


def test_wrong_document_identity_disconnects_without_reading_other_file(client, bridge):
    path, key, binding, document, _ = connect(bridge)
    office, _ = bridge
    request = client.post(path + "/refresh").json()
    result = complete(office, key, request, {**document, "external_id": "different"})
    assert result.status_code == 409
    assert (
        office.post(f"/live/{key}/poll", json={"external_id": "different"}).status_code
        == 409
    )
    assert client.get(path + "/live").json()["connected"] is False
    assert (
        office.post("/live", json={**binding, "external_id": "different"}).status_code
        == 409
    )
    assert client.get(path).json()["revision"] == 1


def test_snapshot_replacement_invalidates_old_live_binding(client, bridge):
    path, _, _, document, _ = connect(bridge)
    client.put(
        path + "/document",
        json={**document, "external_id": "new-doc", "expected_revision": 1},
    )
    assert client.get(path + "/live").json()["connected"] is False
    assert client.post(path + "/refresh").status_code == 409


def test_refresh_results_and_registration_are_scoped_to_course_session(client, bridge):
    path, key, binding, document, _ = connect(bridge)
    office, _ = bridge
    request = client.post(path + "/refresh").json()
    course = str(make_course("Other course").course_id)
    other = path.replace(binding["course_id"], course)
    assert client.get(other + "/live").status_code == 404
    assert client.get(other + f"/refresh/{request['request_id']}").status_code == 404
    assert (
        office.post("/live", json={**binding, "course_id": course}).status_code == 404
    )
    assert complete(office, str(uuid4()), request, document).status_code == 409
    assert client.get(path + f"/refresh/{uuid4()}").status_code == 404
    assert live.BROKER.status(
        UUID(binding["course_id"]), UUID(binding["session_id"])
    ).connection_id == UUID(key)


def test_disconnect_and_backend_restart_clear_live_identity(client, bridge):
    path, key, _, _, work = connect(bridge)
    office, _ = bridge
    request = client.post(path + "/refresh").json()
    assert office.delete(f"/live/{key}").status_code == 204
    assert (
        client.get(path + f"/refresh/{request['request_id']}").json()["status"]
        == "failed"
    )
    live.BROKER.clear()
    assert client.get(path + "/live").json()["connected"] is False
    assert client.get(path).json() == work


def test_live_routes_require_office_token_and_desktop_token(
    monkeypatch, client, bridge
):
    office, _ = bridge
    monkeypatch.setenv("APP_OFFICE_TOKEN", "office-secret")
    assert office.get("/live-policy").status_code == 401
    assert (
        office.get(
            "/live-policy", headers={"X-Office-Token": "office-secret"}
        ).status_code
        == 200
    )
    monkeypatch.setenv("APP_API_TOKEN", "desktop-secret")
    assert client.get("/companion/live-policy").status_code == 401
    assert (
        client.get(
            "/companion/live-policy", headers={"X-App-Token": "desktop-secret"}
        ).status_code
        == 200
    )
