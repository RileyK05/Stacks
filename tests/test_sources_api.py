import io
import json
from uuid import UUID, uuid4

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


def test_source_viewer_returns_original_bytes_only_within_course(
    client: TestClient,
) -> None:
    owner = _course(client)
    other = _course(client, "Other")
    body = b"Original notes with a cited passage.\n" * 200
    uploaded = _upload(client, owner, "notes.txt", body).json()
    source_id = uploaded["source_id"]
    own = client.get(f"/courses/{owner}/sources/{source_id}/content")
    assert own.status_code == 200
    assert own.content == body
    assert own.headers["content-type"].startswith("text/plain")
    assert own.headers["x-content-type-options"] == "nosniff"
    assert (
        client.get(f"/courses/{other}/sources/{source_id}/content").status_code == 404
    )


def test_reindex_keeps_old_citations_readable(client: TestClient) -> None:
    course_id = _course(client)
    uploaded = _upload(client, course_id, "notes.txt", b"A useful passage.")
    source_id = UUID(uploaded.json()["source_id"])
    locator_id, chunk_id, trace_id = uuid4(), uuid4(), uuid4()
    with connection() as conn:
        conn.execute(
            "INSERT INTO locators (locator_id, source_id, locator_type, start, label) "
            "VALUES (?, ?, 'line_range', '0', 'lines 1-1')",
            (locator_id, source_id),
        )
        conn.execute(
            "INSERT INTO chunks (chunk_id, source_id, locator_id, chunk_index, text) "
            "VALUES (?, ?, ?, 0, 'A useful passage.')",
            (chunk_id, source_id, locator_id),
        )
        conn.execute(
            "INSERT INTO retrieval_traces "
            "(trace_id, course_id, query, retrieved_chunk_ids) "
            "VALUES (?, ?, 'question', ?)",
            (trace_id, course_id, json.dumps({"chunk_ids": [str(chunk_id)]})),
        )
        conn.execute("DELETE FROM pending_ingestion WHERE source_id = ?", (source_id,))
        conn.execute(
            "UPDATE sources SET status = 'indexed' WHERE source_id = ?",
            (source_id,),
        )
        conn.commit()
    response = client.post(f"/courses/{course_id}/sources/{source_id}/reindex")
    assert response.status_code == 200, response.text
    with connection() as conn:
        snapshot = conn.execute(
            "SELECT text FROM citation_snapshots WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()
        assert snapshot["text"] == "A useful passage."
        conn.execute("DELETE FROM chunks WHERE chunk_id = ?", (chunk_id,))
        conn.commit()
    citations = client.get(f"/courses/{course_id}/traces/{trace_id}/citations").json()
    assert len(citations) == 1 and citations[0]["text"] == "A useful passage."
    passage = client.get(
        f"/courses/{course_id}/sources/{source_id}/chunks/{chunk_id}"
    ).json()
    assert passage["label"] == "lines 1-1"


def test_trace_citations_preserve_chunk_order_past_ten(client: TestClient) -> None:
    course_id = _course(client)
    uploaded = _upload(client, course_id, "notes.txt", b"twelve passages")
    source_id = UUID(uploaded.json()["source_id"])
    chunk_ids: list[UUID] = []
    with connection() as conn:
        for index in range(12):
            locator_id, chunk_id = uuid4(), uuid4()
            chunk_ids.append(chunk_id)
            conn.execute(
                "INSERT INTO locators "
                "(locator_id, source_id, locator_type, start, label) "
                "VALUES (?, ?, 'line_range', '0', ?)",
                (locator_id, source_id, f"lines {index + 1}"),
            )
            conn.execute(
                "INSERT INTO chunks "
                "(chunk_id, source_id, locator_id, chunk_index, text) "
                "VALUES (?, ?, ?, ?, ?)",
                (chunk_id, source_id, locator_id, index, f"passage {index:02d}"),
            )
        conn.execute(
            "INSERT INTO retrieval_traces "
            "(trace_id, course_id, query, retrieved_chunk_ids) "
            "VALUES (?, ?, 'question', ?)",
            (
                uuid4(),
                course_id,
                json.dumps({"chunk_ids": [str(chunk_id) for chunk_id in chunk_ids]}),
            ),
        )
        trace_id = conn.execute(
            "SELECT trace_id FROM retrieval_traces WHERE course_id = ?",
            (course_id,),
        ).fetchone()["trace_id"]
        conn.commit()
    citations = client.get(f"/courses/{course_id}/traces/{trace_id}/citations").json()
    assert [citation["text"] for citation in citations] == [
        f"passage {index:02d}" for index in range(12)
    ]


def test_pdf_viewer_renders_a_scoped_page(client: TestClient) -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    buffer = io.BytesIO()
    writer.write(buffer)
    course_id = _course(client)
    other = _course(client, "Other")
    source_id = _upload(
        client, course_id, "reading.pdf", buffer.getvalue(), "application/pdf"
    ).json()["source_id"]
    page = client.get(f"/courses/{course_id}/sources/{source_id}/pages/1")
    assert page.status_code == 200, page.text if page.status_code != 200 else ""
    assert page.content.startswith(b"\x89PNG")
    assert page.headers["x-page-count"] == "1"
    assert (
        client.get(f"/courses/{course_id}/sources/{source_id}/pages/2").status_code
        == 404
    )
    assert (
        client.get(f"/courses/{other}/sources/{source_id}/pages/1").status_code == 404
    )


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


@pytest.mark.parametrize(
    ("filename", "declared", "stored"),
    [
        ("notes.md", "", "text/markdown"),
        ("notes.md", "application/octet-stream", "text/markdown"),
        ("data.csv", "application/vnd.ms-excel", "text/csv"),
        ("plain.txt", "text/plain; charset=utf-8", "text/plain"),
        ("Paper.PDF", "application/x-pdf", "application/pdf"),
        ("config.yml", "application/octet-stream", "application/yaml"),
    ],
)
def test_upload_accepts_what_the_os_mislabels(
    client: TestClient, filename: str, declared: str, stored: str
) -> None:
    """A webview reports the OS registry's guess, not the file's type: `.md`
    arrives as "" on Windows and `.csv` as an Excel type. Those used to be
    rejected as unsupported, so ordinary notes could not be uploaded."""
    course_id = _course(client)
    response = _upload(client, course_id, filename, b"# Notes\nbody text", declared)
    assert response.status_code == 201, response.text
    assert response.json()["mime_type"] == stored


def test_unsupported_upload_names_the_file_and_what_is_supported(
    client: TestClient,
) -> None:
    course_id = _course(client)
    response = _upload(
        client,
        course_id,
        "lecture.mp4",
        b"not a document",
        "video/mp4",
    )
    assert response.status_code == 415
    assert "lecture.mp4" in response.json()["detail"]
    assert "PDF" in response.json()["detail"]


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


def test_deleting_a_source_does_not_widen_a_narrowed_chat(client: TestClient) -> None:
    """Remove unavailable IDs while preserving the student's evidence scope."""
    from tests.factories import insert_source

    course_id = _course(client)
    other_course = _course(client, "Other")
    keep, drop = insert_source(course_id), insert_source(course_id)
    foreign = insert_source(other_course)

    def chat(selection: list[UUID] | None, in_course: UUID = course_id) -> str:
        created = client.post(f"/courses/{in_course}/conversations", json={})
        chat_id = created.json()["conversation_id"]
        if selection is not None:
            patched = client.patch(
                f"/courses/{in_course}/conversations/{chat_id}",
                json={"source_ids": [str(s) for s in selection]},
            )
            assert patched.status_code == 200, patched.text
        return str(chat_id)

    def selection(chat_id: str, in_course: UUID = course_id) -> list[str] | None:
        found = client.get(f"/courses/{in_course}/conversations/{chat_id}").json()
        return found["source_ids"]

    both = chat([keep, drop])
    only_dropped = chat([drop])
    everything = chat(None)
    elsewhere = chat([foreign], other_course)

    assert client.delete(f"/courses/{course_id}/sources/{drop}").status_code == 204

    assert selection(both) == [str(keep)]
    assert selection(only_dropped) == []
    assert selection(everything) is None
    assert selection(elsewhere, other_course) == [str(foreign)]


def test_omitted_source_type_is_inferred_and_can_be_changed(client: TestClient) -> None:
    course_id = _course(client)
    pptx = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    deck = client.post(
        f"/courses/{course_id}/sources",
        files={"file": ("Week1.pptx", b"PK\x03\x04 not a real deck", pptx)},
    )
    assert deck.status_code == 201, deck.text
    assert deck.json()["source_type"] == "slides"
    syllabus = client.post(
        f"/courses/{course_id}/sources",
        files={"file": ("POLS347_Syllabus.txt", b"welcome to class", "text/plain")},
    )
    assert syllabus.status_code == 201, syllabus.text
    assert syllabus.json()["source_type"] == "syllabus"
    notes = client.post(
        f"/courses/{course_id}/sources",
        files={"file": ("week2.txt", b"ordinary notes", "text/plain")},
    )
    assert notes.json()["source_type"] == "notes"
    forced = client.post(
        f"/courses/{course_id}/sources",
        data={"source_type": "textbook"},
        files={"file": ("Syllabus.txt", b"still a textbook", "text/plain")},
    )
    assert forced.json()["source_type"] == "textbook"
    changed = client.patch(
        f"/courses/{course_id}/sources/{notes.json()['source_id']}",
        json={"source_type": "exam"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["source_type"] == "exam"
    assert (
        client.patch(
            f"/courses/{course_id}/sources/{uuid4()}",
            json={"source_type": "notes"},
        ).status_code
        == 404
    )


def test_sources_list_is_oldest_first_and_reports_coverage(client: TestClient) -> None:
    from src.backend.rag.config import load_policy
    from src.backend.rag.store import EXTRACTION_VERSION

    course_id = _course(client)
    names = ("week6.txt", "week1.txt", "week3.txt")
    uploaded = [
        UUID(
            _upload(client, course_id, name, f"body {name}".encode()).json()[
                "source_id"
            ]
        )
        for name in names
    ]
    oldest = uploaded[0]
    with connection() as conn:
        for source_id, _name, stamp in zip(
            uploaded, names, ("2026-01-01", "2026-01-02", "2026-01-03"), strict=True
        ):
            conn.execute(
                "UPDATE sources SET created_at = ? WHERE source_id = ?",
                (f"{stamp}T00:00:00.000000Z", source_id),
            )
        conn.execute(
            "INSERT INTO source_indexes (source_id, revision, file_hash,"
            " extraction_version, segmentation_version, semantic_used,"
            " pages_total, pages_empty, pages_low_quality, pages_ocr)"
            " VALUES (?, 'rev', 'hash', 'legacy', 'legacy', 0, 150, 11, 2, 0)",
            (oldest,),
        )
        locator_id, chunk_id = uuid4(), uuid4()
        conn.execute(
            "INSERT INTO locators (locator_id, source_id, locator_type, start, label)"
            " VALUES (?, ?, 'page', '0', 'page 1')",
            (locator_id, oldest),
        )
        conn.execute(
            "INSERT INTO chunks (chunk_id, source_id, locator_id, chunk_index, text)"
            " VALUES (?, ?, ?, 0, 'a passage')",
            (chunk_id, oldest, locator_id),
        )
        run_id, stage_id = uuid4(), uuid4()
        conn.execute(
            "INSERT INTO ingestion_runs (run_id, source_id, pipeline_version, status)"
            " VALUES (?, ?, 'test', 'running')",
            (run_id, uploaded[1]),
        )
        conn.execute(
            "INSERT INTO ingestion_stage_runs (stage_run_id, run_id, stage, position,"
            " handler_version, status) VALUES (?, ?, 'prepare_passages', 2, 'test',"
            " 'running')",
            (stage_id, run_id),
        )
        conn.commit()

    rows = client.get(f"/courses/{course_id}/sources").json()
    assert [row["filename"] for row in rows] == ["week6.txt", "week1.txt", "week3.txt"]
    covered = rows[0]
    assert covered["pages_total"] == 150
    assert covered["pages_empty"] == 11
    assert covered["pages_low_quality"] == 2
    assert covered["chunk_count"] == 1
    assert covered["index_stale"] is True
    assert rows[1]["ingestion_stage"] == "prepare_passages"
    assert rows[1]["index_stale"] is False

    with connection() as conn:
        conn.execute(
            "UPDATE source_indexes SET extraction_version = ?, segmentation_version = ?"
            " WHERE source_id = ?",
            (EXTRACTION_VERSION, load_policy().version, oldest),
        )
        conn.commit()
    refreshed = client.get(f"/courses/{course_id}/sources").json()[0]
    assert refreshed["index_stale"] is False
