"""End-to-end ingestion worker tests.

Exercises the full loop: upload enqueues, the worker claims batches and
runs pipelines, run/source/queue states are consistent after either
terminal outcome, stale claims are released (the laptop-slept-mid-run
case), live claims are fenced by their heartbeat, and requeue produces a
new run.
"""

import asyncio
import io
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from src.backend.common import courses_repo, sources_repo
from src.backend.common.db import connection
from src.backend.common.schemas.base import SourceType
from src.backend.ingest import runs, worker

BODY = "\n\n".join(
    f"Paragraph {i}: the mitochondria is the powerhouse of the cell {i}." * 3
    for i in range(30)
)
LONG_AGO = datetime.now(UTC) - worker.STALE_CLAIM_AFTER - timedelta(minutes=5)


@pytest.fixture
def course_id() -> UUID:
    return courses_repo.create_course("Worker Course").course_id


def _upload(
    course_id: UUID,
    body: bytes = BODY.encode(),
    *,
    mime_type: str = "text/plain",
) -> sources_repo.StoredSource:
    return sources_repo.upload_source(
        course_id,
        filename="notes.txt",
        mime_type=mime_type,
        source_type=SourceType.NOTES,
        stream=io.BytesIO(body),
    )


def _queue_row(source_id: UUID) -> dict | None:
    with connection() as conn:
        return conn.execute(
            "SELECT reason, claimed_at, heartbeat_at FROM pending_ingestion"
            " WHERE source_id = ?",
            (source_id,),
        ).fetchone()


def _set_claim(source_id: UUID, claimed_at, heartbeat_at) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE pending_ingestion SET claimed_at = ?, heartbeat_at = ?"
            " WHERE source_id = ?",
            (claimed_at, heartbeat_at, source_id),
        )
        conn.commit()


def _release_and_claim() -> list[dict]:
    with connection() as conn:
        worker._release_stale_claims(conn)
        conn.commit()
    with connection() as conn:
        claimed = runs.claim_pending_sources(conn, limit=1)
        conn.commit()
    return claimed


def _source_status(source_id: UUID) -> str:
    with connection() as conn:
        return conn.execute(
            "SELECT status FROM sources WHERE source_id = ?", (source_id,)
        ).fetchone()["status"]


def test_upload_enqueues_for_ingestion(course_id: UUID) -> None:
    stored = _upload(course_id)
    assert _queue_row(stored.source_id)["reason"] == "uploaded_new_source"


def test_worker_indexes_text_sources_and_clears_the_queue(course_id: UUID) -> None:
    stored = _upload(course_id)
    attempted, succeeded = worker.process_batch(limit=10)
    assert (attempted, succeeded) == (1, 1)
    assert _source_status(stored.source_id) == "indexed"
    assert _queue_row(stored.source_id) is None
    with connection() as conn:
        assert (
            conn.execute("SELECT COUNT(*) AS n FROM chunk_embeddings").fetchone()["n"]
            >= 1
        )


def test_worker_records_failures_without_zombies(course_id: UUID) -> None:
    stored = _upload(course_id, b"PK\x03\x04junk", mime_type="application/zip")
    attempted, succeeded = worker.process_batch(limit=10)
    assert (attempted, succeeded) == (1, 0)
    assert _source_status(stored.source_id) == "failed"
    assert _queue_row(stored.source_id) is None


def test_worker_requeue_after_failure(course_id: UUID) -> None:
    stored = _upload(course_id, b"PK\x03\x04junk", mime_type="application/zip")
    worker.process_batch(limit=10)
    with connection() as conn:
        assert runs.requeue_failed_source(conn, stored.source_id, course_id)
        conn.commit()
    attempted, _succeeded = worker.process_batch(limit=10)
    assert attempted == 1
    with connection() as conn:
        run_count = conn.execute(
            "SELECT COUNT(*) AS n FROM ingestion_runs WHERE source_id = ?",
            (stored.source_id,),
        ).fetchone()["n"]
    assert run_count == 2, "requeue must produce a second run"


def test_batch_refreshes_course_memory_once(
    monkeypatch: pytest.MonkeyPatch, course_id: UUID
) -> None:
    """The course-memory summary is rebuilt once per successful batch (not
    per upload, not per source): two uploads to one course -> one refresh."""
    calls: list[UUID] = []
    monkeypatch.setattr(
        "src.backend.ingest.worker._refresh_course_memory",
        lambda refreshed: calls.append(refreshed),
    )
    _upload(course_id, body=b"first upload body " * 50)
    _upload(course_id, body=b"second upload body " * 50)
    attempted, succeeded = worker.process_batch(limit=10)
    assert (attempted, succeeded) == (2, 2)
    assert calls == [course_id]


def test_batch_refresh_writes_the_summary(course_id: UUID) -> None:
    _upload(course_id, body=b"memory refresh body " * 50)
    worker.process_batch(limit=10)
    with connection() as conn:
        summary = conn.execute(
            "SELECT summary FROM course_memories WHERE course_id = ?", (course_id,)
        ).fetchone()["summary"]
    assert "notes.txt" in summary


def test_stale_claims_are_released(course_id: UUID) -> None:
    """A laptop that slept or crashed mid-run: the claim ages out and the
    source becomes claimable again."""
    stored = _upload(course_id)
    with connection() as conn:
        assert len(runs.claim_pending_sources(conn, limit=1)) == 1
        conn.commit()
    _set_claim(stored.source_id, LONG_AGO, None)
    assert len(_release_and_claim()) == 1


def test_live_run_is_never_reclaimed(course_id: UUID) -> None:
    """The heartbeat fence: a fresh heartbeat protects a claim however old
    the claim itself is — a slow-but-alive run is never re-claimed."""
    stored = _upload(course_id)
    with connection() as conn:
        runs.claim_pending_sources(conn, limit=1)
        conn.commit()
    _set_claim(stored.source_id, LONG_AGO, datetime.now(UTC))
    assert _release_and_claim() == []


def test_stale_sweep_clears_heartbeat(course_id: UUID) -> None:
    stored = _upload(course_id)
    with connection() as conn:
        runs.claim_pending_sources(conn, limit=1)
        conn.commit()
    _set_claim(stored.source_id, LONG_AGO, datetime.now(UTC) - timedelta(hours=2))
    with connection() as conn:
        worker._release_stale_claims(conn)
        conn.commit()
    row = _queue_row(stored.source_id)
    assert row["claimed_at"] is None and row["heartbeat_at"] is None


def test_upload_wakes_the_worker_immediately() -> None:
    """wakeup() is called from API threads; it must reach the worker's
    loop (thread-safely) and end its sleep well before the poll interval."""

    async def scenario() -> float:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        passes: list[float] = []
        original = worker.process_batch

        def counting_batch(*args, **kwargs):
            passes.append(loop.time())
            return original(*args, **kwargs)

        worker.process_batch = counting_batch
        try:
            task = asyncio.create_task(worker.run_forever(stop))
            while len(passes) < 1:
                await asyncio.sleep(0.01)
            started = loop.time()
            await asyncio.to_thread(worker.wakeup)
            while len(passes) < 2:
                await asyncio.sleep(0.01)
            elapsed = passes[1] - started
            stop.set()
            await asyncio.wait_for(task, timeout=5)
            return elapsed
        finally:
            worker.process_batch = original

    assert asyncio.run(scenario()) < 2.0
