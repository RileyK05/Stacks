"""End-to-end ingestion worker tests (M1 close-out).

Exercises the full loop: upload enqueues, the worker claims batches and
runs pipelines, run/source/queue states are consistent after either
terminal outcome, stale claims are released, and requeue produces a new
run.
"""

import io
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from psycopg.rows import dict_row
from src.backend.common import courses_repo, sources_repo, users_repo
from src.backend.common.auth import hash_password
from src.backend.common.db import connection
from src.backend.common.schemas.base import SourceType, UserTier
from src.backend.common.tiers import load_tier_policies
from src.backend.ingest import runs, worker

PASSWORD = "long-password"
BODY = "\n\n".join(
    f"Paragraph {i}: the mitochondria is the powerhouse of the cell {i}." * 3
    for i in range(30)
)


@pytest.fixture
def owner():
    return users_repo.create(
        "Worker Tester", f"{uuid4().hex}@test.invalid", hash_password(PASSWORD)
    )


@pytest.fixture
def course(owner):
    return courses_repo.create_course(owner.user_id, "Worker Course")


def _upload(course_id, owner_id, body: bytes = BODY.encode()):
    account = users_repo.get_by_id(owner_id)
    assert account is not None
    policy = load_tier_policies().policy_for(UserTier(account.tier))
    return sources_repo.upload_source(
        course_id,
        owner_id,
        account.tier,
        policy,
        filename="notes.txt",
        mime_type="text/plain",
        source_type=SourceType.NOTES,
        stream=io.BytesIO(body),
    )


def test_upload_enqueues_for_ingestion(owner, course) -> None:
    stored = _upload(course.course_id, owner.user_id)
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            "SELECT reason FROM pending_ingestion WHERE source_id = %s",
            (stored.source_id,),
        ).fetchone()
    assert row is not None
    assert row["reason"] == "uploaded_new_source"


def test_worker_batch_runs_and_records(owner, course) -> None:
    stored = _upload(course.course_id, owner.user_id)
    attempted, succeeded = worker.process_batch(limit=10)
    assert attempted >= 1
    assert succeeded == 0, "provider-less pipelines fail (honest state)"

    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run = runs.latest_run_for_source(conn, stored.source_id)
        assert run is not None
        source_row = cur.execute(
            "SELECT status FROM sources WHERE source_id = %s",
            (stored.source_id,),
        ).fetchone()
        assert source_row["status"] == "failed"
        queue_row = cur.execute(
            "SELECT count(*) AS n FROM pending_ingestion WHERE source_id = %s",
            (stored.source_id,),
        ).fetchone()
        assert queue_row["n"] == 0, "failed source must not leave a zombie row"


def test_worker_clears_queue_on_success(monkeypatch, owner, course) -> None:
    stored = _upload(course.course_id, owner.user_id)

    def fake_call(task, model, prompt):
        return (f"stub output for {task}", 150, 30)

    monkeypatch.setattr(
        "src.backend.common.provider._call_provider", fake_call
    )
    attempted, succeeded = worker.process_batch(limit=10)
    assert succeeded >= 1

    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        source_row = cur.execute(
            "SELECT status FROM sources WHERE source_id = %s",
            (stored.source_id,),
        ).fetchone()
        assert source_row["status"] == "indexed"
        queue_row = cur.execute(
            "SELECT count(*) AS n FROM pending_ingestion WHERE source_id = %s",
            (stored.source_id,),
        ).fetchone()
        assert queue_row["n"] == 0


def test_worker_requeue_after_failure(owner, course) -> None:
    stored = _upload(course.course_id, owner.user_id)
    worker.process_batch(limit=10)

    with connection() as conn:
        requeued = runs.requeue_failed_source(
            conn, stored.source_id, course.course_id
        )
        conn.commit()
    assert requeued
    attempted, succeeded = worker.process_batch(limit=10)
    assert attempted >= 1
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_count = cur.execute(
            "SELECT count(*) AS n FROM ingestion_runs WHERE source_id = %s",
            (stored.source_id,),
        ).fetchone()
        assert run_count["n"] >= 2, "requeue must produce a second run"


def test_stale_claims_are_released(owner, course) -> None:
    stored = _upload(course.course_id, owner.user_id)
    with connection() as conn:
        claimed = runs.claim_pending_sources(conn, limit=1)
        conn.commit()
    assert len(claimed) == 1

    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE pending_ingestion SET claimed_at = %s"
            " WHERE source_id = %s",
            (
                datetime.now(UTC)
                - worker.STALE_CLAIM_AFTER
                - timedelta(minutes=5),
                stored.source_id,
            ),
        )
        conn.commit()

    with connection() as conn:
        worker._release_stale_claims(conn)
        conn.commit()

    with connection() as conn:
        reclaimed = runs.claim_pending_sources(conn, limit=1)
        conn.commit()
    assert len(reclaimed) == 1

def test_batch_refreshes_course_memory_once(monkeypatch, owner, course) -> None:
    """Fix #9 ratified: the course-memory summary is rebuilt once per
    successful batch (not per upload, not per source). Two uploads to the
    same course -> one refresh call covering both."""
    calls: list = []
    monkeypatch.setattr(
        "src.backend.ingest.worker._refresh_course_memory",
        lambda course_id: calls.append(course_id),
    )

    def fake_call(task, model, prompt):
        return (f"stub output for {task}", 100, 20)

    monkeypatch.setattr(
        "src.backend.common.provider._call_provider", fake_call
    )
    _upload(course.course_id, owner.user_id, body=b"first upload body " * 50)
    _upload(course.course_id, owner.user_id, body=b"second upload body " * 50)
    attempted, succeeded = worker.process_batch(limit=10)
    assert succeeded == 2
    assert calls == [course.course_id], (
        "one refresh per touched course per batch, not per source"
    )


def test_live_run_is_never_reclaimed(owner, course) -> None:
    """Fix #5 (ratified): the heartbeat fence. A claim whose heartbeat is
    fresh is NOT stale even if its claim time is ancient — a
    slow-but-alive run is never re-claimed out from under a live worker
    (two pipelines racing delete-then-insert was the failure mode)."""
    stored = _upload(course.course_id, owner.user_id)
    with connection() as conn:
        claimed = runs.claim_pending_sources(conn, limit=1)
        conn.commit()
    assert len(claimed) == 1
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE pending_ingestion SET claimed_at = %s,"
            " heartbeat_at = now() WHERE source_id = %s",
            (
                datetime.now(UTC)
                - worker.STALE_CLAIM_AFTER
                - timedelta(minutes=5),
                stored.source_id,
            ),
        )
        conn.commit()
    with connection() as conn:
        worker._release_stale_claims(conn)
        conn.commit()
    with connection() as conn:
        still_claimed = runs.claim_pending_sources(conn, limit=1)
        conn.commit()
    assert still_claimed == [], "fresh heartbeat must fence the re-claim"


def test_dead_run_without_heartbeat_is_reclaimed(owner, course) -> None:
    """The other half of the fence: a claim with NO heartbeat yet (worker
    died before its first stage transition) still ages out on claimed_at
    — the original 30-minute budget bounds the pre-stage crash window."""
    stored = _upload(course.course_id, owner.user_id)
    with connection() as conn:
        claimed = runs.claim_pending_sources(conn, limit=1)
        conn.commit()
    assert len(claimed) == 1
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE pending_ingestion SET claimed_at = %s,"
            " heartbeat_at = NULL WHERE source_id = %s",
            (
                datetime.now(UTC)
                - worker.STALE_CLAIM_AFTER
                - timedelta(minutes=5),
                stored.source_id,
            ),
        )
        conn.commit()
    with connection() as conn:
        worker._release_stale_claims(conn)
        conn.commit()
    with connection() as conn:
        reclaimed = runs.claim_pending_sources(conn, limit=1)
        conn.commit()
    assert len(reclaimed) == 1


def test_stale_sweep_clears_heartbeat(owner, course) -> None:
    """A released claim loses its stale heartbeat too: the next claim
    starts a fresh liveness budget."""
    stored = _upload(course.course_id, owner.user_id)
    with connection() as conn:
        runs.claim_pending_sources(conn, limit=1)
        conn.commit()
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE pending_ingestion SET claimed_at = %s,"
            " heartbeat_at = %s WHERE source_id = %s",
            (
                datetime.now(UTC)
                - worker.STALE_CLAIM_AFTER
                - timedelta(minutes=5),
                datetime.now(UTC) - timedelta(hours=2),
                stored.source_id,
            ),
        )
        conn.commit()
    with connection() as conn:
        worker._release_stale_claims(conn)
        conn.commit()
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            "SELECT claimed_at, heartbeat_at FROM pending_ingestion"
            " WHERE source_id = %s",
            (stored.source_id,),
        ).fetchone()
    assert row["claimed_at"] is None
    assert row["heartbeat_at"] is None
