"""End-to-end ingestion pipeline tests (Milestone 1 wiring).

Provider-less state: the three deterministic stages run and persist their
rows, then the model stage fails the run — inspectably, with the provider
error visible in the stage row and the queue row cleared. Budget gating
and ledger recording are asserted against a stubbed provider.
"""

from uuid import uuid4

import pytest
from psycopg.rows import dict_row
from src.backend.common import courses_repo, storage, users_repo
from src.backend.common.db import connection
from src.backend.common.schemas.base import IngestionStatus
from src.backend.ingest import runs
from src.backend.ingest.orchestrator import run_ingestion
from src.backend.ingest.pipeline import IngestionPipelineError

TEXT_BODY = "\n\n".join(
    f"Paragraph {i}: the mitochondria is the powerhouse of the cell {i}." * 3
    for i in range(30)
)


@pytest.fixture
def source_pair():
    """(user, course) fresh pair for one test."""
    user = users_repo.create(
        "Ingest Tester", f"{uuid4().hex}@test.invalid", "not-a-hash"
    )
    course = courses_repo.create_course(user.user_id, "Ingestion Course")
    return user, course


def _make_source(course_id, owner_id, mime_type: str, body: bytes):
    """Insert a source row + stored file (identity encoding). Mirrors the
    upload repo's row shape; kept minimal deliberately so a column change
    in the upload path shows up here as a failure, not silent drift."""
    source_id = uuid4()
    path = storage.write_stored(course_id, source_id, body)
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        object_id = cur.execute(
            "INSERT INTO course_objects (course_id, created_by_user_id, kind,"
            " content_type, content, access_scope) VALUES (%s, %s, 'source',"
            " %s, '{}', 'enrolled') RETURNING object_id",
            (course_id, owner_id, mime_type),
        ).fetchone()["object_id"]
        cur.execute(
            "INSERT INTO sources (source_id, object_id, uploaded_by_user_id,"
            " course_id, filename, mime_type, source_type, uri, status,"
            " file_hash, size_bytes, stored_encoding)"
            " VALUES (%s, %s, %s, %s, 'notes.txt', %s, 'notes', %s,"
            " 'uploaded', %s, %s, 'identity')",
            (
                source_id,
                object_id,
                owner_id,
                course_id,
                mime_type,
                str(path),
                f"hash-{uuid4().hex}",
                len(body),
            ),
        )
        conn.commit()
    return source_id


def _run_and_fail(user, course, source_id):
    policy_tier = user.tier
    with pytest.raises(IngestionPipelineError), connection() as conn:
        run_ingestion(conn, source_id, user.user_id, policy_tier)


def test_full_pipeline_deterministic_stages_and_honest_failure(
    source_pair,
) -> None:
    user, course = source_pair
    source_id = _make_source(
        course.course_id, user.user_id, "text/plain", TEXT_BODY.encode()
    )
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO pending_ingestion (source_id, course_id, reason)"
                " VALUES (%s, %s, 'test_queue')",
                (source_id, course.course_id),
            )
        conn.commit()

    _run_and_fail(user, course, source_id)

    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run = runs.latest_run_for_source(conn, source_id)
        assert run is not None
        assert run.status == IngestionStatus.FAILED
        source_row = cur.execute(
            "SELECT status FROM sources WHERE source_id = %s",
            (source_id,),
        ).fetchone()
        assert source_row["status"] == "failed"
        locator_rows = cur.execute(
            "SELECT count(*) AS n FROM locators WHERE source_id = %s",
            (source_id,),
        ).fetchone()
        assert locator_rows["n"] >= 1
        chunk_rows = cur.execute(
            "SELECT chunk_index, count(*) AS n FROM chunks"
            " WHERE source_id = %s GROUP BY chunk_index ORDER BY chunk_index",
            (source_id,),
        ).fetchall()
        assert [row["chunk_index"] for row in chunk_rows] == list(
            range(len(chunk_rows))
        )
        stage_rows = cur.execute(
            "SELECT stage, status, error_message, attempt_count"
            " FROM ingestion_stage_runs"
            " WHERE run_id = %s ORDER BY position",
            (run.run_id,),
        ).fetchall()
        assert [row["stage"] for row in stage_rows] == [
            "extract_text",
            "build_locators",
            "build_chunks",
            "update_toc",
            "extract_knowledge",
        ]
        statuses = {row["stage"]: row["status"] for row in stage_rows}
        assert statuses["extract_text"] == "succeeded"
        assert statuses["build_locators"] == "succeeded"
        assert statuses["build_chunks"] == "succeeded"
        assert statuses["update_toc"] == "failed"
        assert statuses["extract_knowledge"] == "pending"
        toc_row = next(row for row in stage_rows if row["stage"] == "update_toc")
        assert "provider" in (toc_row["error_message"] or "")
        assert toc_row["attempt_count"] == 2
        zombie = cur.execute(
            "SELECT count(*) AS n FROM pending_ingestion"
            " WHERE source_id = %s",
            (source_id,),
        ).fetchone()
        assert zombie["n"] == 0, "failed source must not leave a zombie queue row"


def test_failed_source_can_be_requeued(source_pair) -> None:
    user, course = source_pair
    source_id = _make_source(
        course.course_id, user.user_id, "text/plain", TEXT_BODY.encode()
    )
    _run_and_fail(user, course, source_id)

    with connection() as conn:
        requeued = runs.requeue_failed_source(
            conn, source_id, course.course_id
        )
        conn.commit()
    assert requeued

    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        source_row = cur.execute(
            "SELECT status FROM sources WHERE source_id = %s",
            (source_id,),
        ).fetchone()
        assert source_row["status"] == "uploaded"
        queued = cur.execute(
            "SELECT reason FROM pending_ingestion WHERE source_id = %s",
            (source_id,),
        ).fetchone()
        assert queued is not None
        assert queued["reason"] == "requeue_after_failure"


def test_claim_persists_and_excludes_claimed(source_pair) -> None:
    user, course = source_pair
    first = _make_source(course.course_id, user.user_id, "text/plain", b"one")
    second = _make_source(course.course_id, user.user_id, "text/plain", b"two")
    for sid in (first, second):
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO pending_ingestion (source_id, course_id,"
                    " reason) VALUES (%s, %s, 'test_claim')",
                    (sid, course.course_id),
                )
            conn.commit()

    with connection() as conn:
        first_claim = runs.claim_pending_sources(conn, limit=1)
        conn.commit()
    assert len(first_claim) == 1
    first_claimed_id = str(first_claim[0]["source_id"])

    with connection() as conn:
        second_claim = runs.claim_pending_sources(conn, limit=10)
        conn.commit()
    claimed_ids = {str(row["source_id"]) for row in second_claim}
    assert first_claimed_id not in claimed_ids
    assert len(second_claim) >= 1


def test_unsupported_mime_fails_the_stage(source_pair) -> None:
    user, course = source_pair
    source_id = _make_source(
        course.course_id, user.user_id, "application/zip", b"PK\x03\x04junk"
    )
    with pytest.raises(IngestionPipelineError), connection() as conn:
        run_ingestion(conn, source_id, user.user_id, user.tier)
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run = runs.latest_run_for_source(conn, source_id)
        assert run is not None
        assert run.status == IngestionStatus.FAILED
        stage = cur.execute(
            "SELECT error_message FROM ingestion_stage_runs"
            " WHERE run_id = %s AND stage = 'extract_text'",
            (run.run_id,),
        ).fetchone()
        assert "no text extraction handler" in (stage["error_message"] or "")


def test_budget_gate_and_ledger_with_stubbed_provider(
    monkeypatch, source_pair
) -> None:
    """With only the HTTP layer stubbed, a full pipeline must go green and
    the ledger must show ingestion-pool rows with real token counts —
    proving the gate + billing inside the seam are actually wired."""
    user, course = source_pair
    source_id = _make_source(
        course.course_id, user.user_id, "text/plain", TEXT_BODY.encode()
    )

    def fake_call(task, model, prompt):
        return (f"stub output for {task}", 150, 30)

    monkeypatch.setattr(
        "src.backend.common.provider._call_provider", fake_call
    )

    with connection() as conn:
        run_id = run_ingestion(conn, source_id, user.user_id, user.tier)
        conn.commit()

    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run = runs.get_run(conn, run_id)
        assert run is not None
        assert run.status == IngestionStatus.SUCCEEDED
        source_row = cur.execute(
            "SELECT status FROM sources WHERE source_id = %s",
            (source_id,),
        ).fetchone()
        assert source_row["status"] == "indexed"
        ledger_rows = cur.execute(
            "SELECT task, spend_kind, input_tokens, output_tokens"
            " FROM generation_ledger WHERE user_id = %s"
            " AND created_at >= now() - interval '1 minute'",
            (user.user_id,),
        ).fetchall()
        assert ledger_rows, "successful ingestion must record ledger rows"
        for row in ledger_rows:
            assert row["spend_kind"] == "ingestion"
            assert row["task"] in ("toc_update", "course_knowledge_extraction")
            assert row["input_tokens"] + row["output_tokens"] > 0


def test_budget_exhaustion_fails_ingestion_before_call(
    monkeypatch, source_pair
) -> None:
    """An owner with a drained ingestion pool must fail before any provider
    call — the gate is real, not decorative."""
    from src.backend.common import provider as provider_module
    from src.backend.common import spend_repo
    from src.backend.common.schemas.base import SpendKind

    user, course = source_pair
    source_id = _make_source(
        course.course_id, user.user_id, "text/plain", TEXT_BODY.encode()
    )
    from src.backend.common.tiers import load_tier_policies

    policy = load_tier_policies().policy_for(user.tier)
    for _ in range(3):
        spend_repo.record_generation(
            user.user_id,
            "toc_update",
            "test-model",
            policy.ingestion_token_budget,
            0,
            spend_kind=SpendKind.INGESTION,
        )

    def explode(task, model, prompt):
        raise AssertionError("provider must not be called with a drained pool")

    monkeypatch.setattr(provider_module, "_call_provider", explode)

    with pytest.raises(IngestionPipelineError), connection() as conn:
        run_ingestion(conn, source_id, user.user_id, user.tier)