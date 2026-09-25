from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from src.backend.common import storage
from src.backend.common.db import connection
from src.backend.common.lifecycle_config import load_lifecycle_policy


def _course(client: TestClient, name: str = "Uploads") -> UUID:
    response = client.post("/courses", json={"name": name})
    return UUID(response.json()["course_id"])


def _upload(
    client: TestClient,
    course_id: UUID,
    filename: str,
    body: bytes,
    mime: str = "text/plain",
):
    return client.post(
        f"/courses/{course_id}/sources",
        data={"source_type": "notes"},
        files={"file": (filename, body, mime)},
    )


def _count_sources(course_id: UUID) -> int:
    with connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM sources WHERE course_id = ?", (course_id,)
        ).fetchone()["n"]


def test_upload_streams_compresses_and_accounts_stored_bytes(
    client: TestClient,
) -> None:
    course_id = _course(client)
    raw = b"source-grounded notes " * 10_000
    uploaded = _upload(client, course_id, "../week-1.txt", raw)

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
            "SELECT size_bytes, stored_encoding FROM sources WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        queued = conn.execute(
            "SELECT reason FROM pending_ingestion WHERE source_id = ?", (source_id,)
        ).fetchone()
    assert (recorded["size_bytes"], recorded["stored_encoding"]) == (
        body["stored_size_bytes"],
        "gzip",
    )
    assert queued["reason"] == "uploaded_new_source"

    view = client.get(f"/courses/{course_id}").json()
    assert view["source_count"] == 1
    assert view["stored_bytes"] == body["stored_size_bytes"]
    # Course-memory refresh is per worker BATCH (fix #9), not per upload.
    memory = client.get("/course-memories").json()[0]
    assert "week-1.txt" not in memory["summary"]


def test_duplicate_content_is_rejected(client: TestClient) -> None:
    course_id = _course(client)
    payload = b"same content" * 100
    assert _upload(client, course_id, "one.txt", payload).status_code == 201
    assert _upload(client, course_id, "two.txt", payload).status_code == 409
    assert _count_sources(course_id) == 1


def test_upload_into_unknown_or_trashed_course_is_404(client: TestClient) -> None:
    course_id = _course(client)
    client.delete(f"/courses/{course_id}")
    assert _upload(client, course_id, "late.txt", b"text").status_code == 404
    assert client.get(f"/courses/{course_id}/sources").status_code == 404
    assert not (storage.storage_root() / str(course_id)).exists() or not any(
        (storage.storage_root() / str(course_id)).iterdir()
    ), "a rejected upload must leave no file behind"


def test_raw_body_ceiling_rejects_oversized_uploads(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _course(client)
    small = load_lifecycle_policy().model_copy(
        update={"max_raw_upload_bytes": 10, "max_decompressed_bytes": 10}
    )
    monkeypatch.setattr(
        "src.backend.common.sources_repo.load_lifecycle_policy", lambda: small
    )
    response = _upload(client, course_id, "large.txt", b"x" * 11)
    assert response.status_code == 413
    assert _count_sources(course_id) == 0


def test_upload_rejects_uningestable_mime_before_storing(client: TestClient) -> None:
    """Review catch #12: an un-ingestable file used to be stored, then
    failed at extract_text. The boundary rejects before any write."""
    course_id = _course(client)
    response = _upload(
        client, course_id, "archive.zip", b"PK\x03\x04 fake zip", "application/zip"
    )
    assert response.status_code == 415, response.text
    assert _count_sources(course_id) == 0


def test_source_list_shows_status(client: TestClient) -> None:
    course_id = _course(client)
    assert _upload(client, course_id, "good.txt", b"readable text").status_code == 201
    rows = client.get(f"/courses/{course_id}/sources").json()
    assert [(row["filename"], row["status"]) for row in rows] == [
        ("good.txt", "uploaded")
    ]


def test_requeue_failed_source_roundtrip(client: TestClient) -> None:
    course_id = _course(client)
    source_id = _upload(client, course_id, "retry.txt", b"some text").json()[
        "source_id"
    ]
    with connection() as conn:
        conn.execute(
            "UPDATE sources SET status = 'failed', error_message = 'boom'"
            " WHERE source_id = ?",
            (source_id,),
        )
        conn.execute("DELETE FROM pending_ingestion WHERE source_id = ?", (source_id,))
        conn.commit()

    listed = client.get(f"/courses/{course_id}/sources").json()
    assert listed[0]["error_message"] == "boom"

    requeued = client.post(f"/courses/{course_id}/sources/{source_id}/requeue")
    assert requeued.status_code == 200, requeued.text
    with connection() as conn:
        status_row = conn.execute(
            "SELECT status, error_message FROM sources WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        queue_row = conn.execute(
            "SELECT reason FROM pending_ingestion WHERE source_id = ?", (source_id,)
        ).fetchone()
    assert status_row["status"] == "uploaded" and status_row["error_message"] is None
    assert queue_row["reason"] == "requeue_after_failure"


def test_requeue_rejects_non_failed_source(client: TestClient) -> None:
    course_id = _course(client)
    source_id = _upload(client, course_id, "fine.txt", b"some text").json()["source_id"]
    response = client.post(f"/courses/{course_id}/sources/{source_id}/requeue")
    assert response.status_code == 409


def test_delete_source_removes_row_queue_and_file(client: TestClient) -> None:
    course_id = _course(client)
    source_id = UUID(
        _upload(client, course_id, "drop.txt", b"delete me").json()["source_id"]
    )
    path = storage.source_disk_path(course_id, source_id)
    assert path.exists()

    assert client.delete(f"/courses/{course_id}/sources/{source_id}").status_code == 204
    assert not path.exists()
    assert _count_sources(course_id) == 0
    with connection() as conn:
        assert (
            conn.execute("SELECT COUNT(*) AS n FROM pending_ingestion").fetchone()["n"]
            == 0
        )
    assert client.delete(f"/courses/{course_id}/sources/{source_id}").status_code == 404
    # The same bytes can be uploaded again once the old copy is gone.
    assert _upload(client, course_id, "drop.txt", b"delete me").status_code == 201
