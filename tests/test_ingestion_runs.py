"""End-to-end ingestion pipeline tests.

Text sources index with no model at all: extract → locators → chunks →
embeddings run locally, and the enrichment stages (TOC, knowledge) record
an honest skip until their local-first implementations land. Only scanned
PDFs need a model (OCR); without one they fail loudly, never falsely
indexed.
"""

import io
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from src.backend.common import courses_repo, storage, usage_repo
from src.backend.common.db import connection
from src.backend.common.schemas.base import IngestionStatus
from src.backend.ingest import runs
from src.backend.ingest.orchestrator import run_ingestion
from src.backend.ingest.pipeline import IngestionPipelineError
from tests.conftest import configure_test_provider

TEXT_BODY = "\n\n".join(
    f"Paragraph {i}: the mitochondria is the powerhouse of the cell {i}." * 3
    for i in range(30)
)


@pytest.fixture
def course_id() -> UUID:
    return courses_repo.create_course("Ingestion Course").course_id


def _make_source(course_id: UUID, mime_type: str, body: bytes) -> UUID:
    """A source row + stored file (identity encoding), enqueued in the same
    transaction like the real upload path."""
    source_id = uuid4()
    path = storage.write_stored(course_id, source_id, body)
    with connection() as conn:
        conn.execute(
            "INSERT INTO sources (source_id, course_id, filename, mime_type,"
            " source_type, uri, status, file_hash, size_bytes, stored_encoding)"
            " VALUES (?, ?, 'notes.txt', ?, 'notes', ?, 'uploaded', ?, ?,"
            " 'identity')",
            (source_id, course_id, mime_type, str(path), uuid4().hex, len(body)),
        )
        runs.enqueue_pending(conn, source_id, course_id, "uploaded_new_source")
        conn.commit()
    return source_id


def _pdf(pages: int) -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _stage_rows(run_id: UUID) -> list[dict]:
    with connection() as conn:
        return conn.execute(
            "SELECT stage, status, error_message, attempt_count"
            " FROM ingestion_stage_runs WHERE run_id = ? ORDER BY position",
            (run_id,),
        ).fetchall()


def _one(sql: str, *params) -> dict:
    with connection() as conn:
        return conn.execute(sql, params).fetchone()


def test_text_source_indexes_with_no_model_configured(
    course_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.backend.common import provider

    def no_model_calls(*args, **kwargs):
        raise AssertionError("a text source must not need a model")

    monkeypatch.setattr(provider, "_call_provider", no_model_calls)
    source_id = _make_source(course_id, "text/plain", TEXT_BODY.encode())
    queued_at = _one(
        "SELECT created_at FROM pending_ingestion WHERE source_id = ?", source_id
    )["created_at"]

    with connection() as conn:
        run_id = run_ingestion(conn, source_id)

    with connection() as conn:
        run = runs.get_run(conn, run_id)
    assert run is not None and run.status == IngestionStatus.SUCCEEDED
    assert (
        _one("SELECT status FROM sources WHERE source_id = ?", source_id)["status"]
        == "indexed"
    )

    stages = _stage_rows(run_id)
    assert [row["stage"] for row in stages] == [
        "extract_text",
        "ocr",
        "build_locators",
        "build_chunks",
        "embed_chunks",
        "update_toc",
        "extract_knowledge",
    ]
    assert {row["status"] for row in stages} == {"succeeded"}
    by_stage = {row["stage"]: row for row in stages}
    assert by_stage["update_toc"]["error_message"].startswith("skipped:")
    assert by_stage["extract_knowledge"]["error_message"].startswith("skipped:")
    assert by_stage["extract_text"]["error_message"] is None

    counts = _one(
        "SELECT (SELECT COUNT(*) FROM chunks WHERE source_id = ?) AS chunks,"
        " (SELECT COUNT(*) FROM chunk_embeddings AS e JOIN chunks AS c"
        "  ON c.chunk_id = e.chunk_id WHERE c.source_id = ?) AS embeddings,"
        " (SELECT COUNT(*) FROM chunk_locators AS l JOIN chunks AS c"
        "  ON c.chunk_id = l.chunk_id WHERE c.source_id = ?) AS links,"
        " (SELECT COUNT(*) FROM pending_ingestion WHERE source_id = ?) AS queued",
        source_id,
        source_id,
        source_id,
        source_id,
    )
    assert counts["chunks"] > 1
    assert counts["embeddings"] == counts["chunks"]
    assert counts["links"] >= counts["chunks"], "every chunk maps to its locators"
    assert counts["queued"] == 0

    history = _one(
        "SELECT reason, queued_at FROM ingestion_history WHERE source_id = ?",
        source_id,
    )
    assert history["reason"] == "ingested"
    assert history["queued_at"] == queued_at, "history keeps the ORIGINAL enqueue time"

    hits = _one(
        "SELECT COUNT(*) AS n FROM chunks_fts WHERE chunks_fts MATCH 'mitochondria'"
    )
    assert hits["n"] == counts["chunks"], "every chunk is keyword-searchable"
    assert usage_repo.ledger_page() == [], "nothing was sent to any model"


def test_unsupported_mime_fails_loudly_and_records_history(course_id: UUID) -> None:
    source_id = _make_source(course_id, "application/zip", b"PK\x03\x04junk")
    queued_at = _one(
        "SELECT created_at FROM pending_ingestion WHERE source_id = ?", source_id
    )["created_at"]

    with pytest.raises(IngestionPipelineError), connection() as conn:
        run_ingestion(conn, source_id)

    with connection() as conn:
        run = runs.latest_run_for_source(conn, source_id)
    assert run is not None and run.status == IngestionStatus.FAILED
    extract_row = _stage_rows(run.run_id)[0]
    assert extract_row["status"] == "failed"
    assert extract_row["attempt_count"] == 2
    assert "no text extraction handler" in (extract_row["error_message"] or "")
    source_row = _one(
        "SELECT status, error_message FROM sources WHERE source_id = ?", source_id
    )
    assert source_row["status"] == "failed" and source_row["error_message"]
    assert (
        _one(
            "SELECT COUNT(*) AS n FROM pending_ingestion WHERE source_id = ?", source_id
        )["n"]
        == 0
    ), "a failed source must not leave a zombie queue row"
    history = _one(
        "SELECT reason, queued_at FROM ingestion_history WHERE source_id = ?",
        source_id,
    )
    assert history["reason"] == "failed" and history["queued_at"] == queued_at


def test_failed_source_can_be_requeued(course_id: UUID) -> None:
    source_id = _make_source(course_id, "application/zip", b"PK\x03\x04junk")
    with pytest.raises(IngestionPipelineError), connection() as conn:
        run_ingestion(conn, source_id)

    with connection() as conn:
        assert runs.requeue_failed_source(conn, source_id, course_id)
        conn.commit()
        assert not runs.requeue_failed_source(conn, source_id, course_id)

    assert (
        _one("SELECT status FROM sources WHERE source_id = ?", source_id)["status"]
        == "uploaded"
    )
    assert (
        _one("SELECT reason FROM pending_ingestion WHERE source_id = ?", source_id)[
            "reason"
        ]
        == "requeue_after_failure"
    )


def test_claim_persists_and_excludes_claimed(course_id: UUID) -> None:
    _make_source(course_id, "text/plain", b"one")
    _make_source(course_id, "text/plain", b"two")

    with connection() as conn:
        first_claim = runs.claim_pending_sources(conn, limit=1)
        conn.commit()
    assert len(first_claim) == 1

    with connection() as conn:
        second_claim = runs.claim_pending_sources(conn, limit=10)
        conn.commit()
    assert len(second_claim) == 1
    assert second_claim[0]["source_id"] != first_claim[0]["source_id"]
    with connection() as conn:
        assert runs.claim_pending_sources(conn, limit=10) == []


def test_trashed_course_sources_are_not_claimed(course_id: UUID) -> None:
    """A course in the trash must not keep the laptop busy ingesting it;
    restoring it makes its queue claimable again."""
    _make_source(course_id, "text/plain", b"queued before delete")
    courses_repo.move_to_trash(course_id)
    with connection() as conn:
        assert runs.claim_pending_sources(conn, limit=10) == []
    courses_repo.restore_from_trash(course_id)
    with connection() as conn:
        assert len(runs.claim_pending_sources(conn, limit=10)) == 1


def test_scanned_pdf_is_ocrd_and_recorded(
    course_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An image-only PDF routes through OCR: pages rasterize, the model
    reads them, and the source indexes with page locators intact."""
    calls = configure_test_provider(
        monkeypatch, "page one transcription\n\n---\n\npage two transcription"
    )
    source_id = _make_source(course_id, "application/pdf", _pdf(2))

    with connection() as conn:
        run_id = run_ingestion(conn, source_id)

    assert [call["task"] for call in calls] == ["ocr"]
    assert len(calls[0]["images"]) == 2, "both rendered pages reach the model"
    statuses = {row["stage"]: row["status"] for row in _stage_rows(run_id)}
    assert statuses["ocr"] == "succeeded"
    with connection() as conn:
        text = " ".join(
            row["text"]
            for row in conn.execute(
                "SELECT text FROM chunks WHERE source_id = ?", (source_id,)
            ).fetchall()
        )
        labels = {
            row["label"]
            for row in conn.execute(
                "SELECT label FROM locators WHERE source_id = ?", (source_id,)
            ).fetchall()
        }
    assert "page one transcription" in text
    assert {"page 1", "page 2"} <= labels, "OCR pages keep page locators"
    entry = usage_repo.ledger_page()[0]
    assert (entry.task, entry.provider, entry.course_id) == ("ocr", "local", course_id)


def test_scanned_pdf_without_a_model_fails_loudly(course_id: UUID) -> None:
    """No model configured: the OCR stage fails with an actionable error
    and the source is 'failed' — never a falsely indexed, empty source."""
    source_id = _make_source(course_id, "application/pdf", _pdf(1))

    with pytest.raises(IngestionPipelineError), connection() as conn:
        run_ingestion(conn, source_id)

    with connection() as conn:
        run = runs.latest_run_for_source(conn, source_id)
    assert run is not None and run.status == IngestionStatus.FAILED
    ocr_row = next(row for row in _stage_rows(run.run_id) if row["stage"] == "ocr")
    assert ocr_row["status"] == "failed"
    assert "provider" in (ocr_row["error_message"] or "")
    assert (
        _one("SELECT status FROM sources WHERE source_id = ?", source_id)["status"]
        == "failed"
    )


def test_observer_heartbeats_the_claim(course_id: UUID) -> None:
    source_id = _make_source(course_id, "text/plain", TEXT_BODY.encode())
    before = datetime.now(UTC)
    with connection() as conn:
        claimed = runs.claim_pending_sources(conn, limit=1)
        conn.commit()
        assert claimed[0]["source_id"] == source_id
        run, _stages = runs.create_run(conn, source_id, "1", {}, [], max_attempts=1)
        conn.commit()
        observer = runs.RunObserver(conn, run.run_id, source_id=source_id)
        from src.backend.common.schemas.base import IngestionStage

        observer.observe(IngestionStage.EXTRACT_TEXT, 1, IngestionStatus.RUNNING, None)
    heartbeat = _one(
        "SELECT heartbeat_at FROM pending_ingestion WHERE source_id = ?", source_id
    )["heartbeat_at"]
    assert heartbeat is not None and heartbeat >= before
