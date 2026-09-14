"""DB-backed run ledger for ingestion pipelines.

`RunObserver` implements the pipeline executor's `TransitionObserver` so
every stage attempt is persisted as it happens: `ingestion_runs` holds the
run, `ingestion_stage_runs` one row per stage (unique per run+stage).
Attempts and handler versions are recorded per the house rule that stage
attempts and versions are inspectable — the DB is the log, no opaque
scores. The observer writes on the pipeline driver's connection so run
rows and derived rows commit together.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from src.backend.common.queries import get
from src.backend.common.schemas.base import IngestionStage, IngestionStatus
from src.backend.common.schemas.ingestion import IngestionRun, IngestionStageRun

if TYPE_CHECKING:
    from src.backend.ingest.pipeline import IngestionPipelineError

_FILE = "ingestion"


def _to_run(row: dict[str, Any]) -> IngestionRun:
    return IngestionRun(
        run_id=row["run_id"],
        source_id=row["source_id"],
        pipeline_version=row["pipeline_version"],
        status=IngestionStatus(row["status"]),
        configuration=row["configuration"],
        error_message=row["error_message"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
    )


def _to_stage_run(row: dict[str, Any]) -> IngestionStageRun:
    return IngestionStageRun(
        stage_run_id=row["stage_run_id"],
        run_id=row["run_id"],
        stage=IngestionStage(row["stage"]),
        position=row["position"],
        depends_on_stage_id=row["depends_on_stage_id"],
        status=IngestionStatus(row["status"]),
        attempt_count=row["attempt_count"],
        max_attempts=row["max_attempts"],
        handler_version=row["handler_version"],
        configuration=row["configuration"],
        error_message=row["error_message"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
    )


def create_run(
    conn: Connection,
    source_id: UUID,
    pipeline_version: str,
    configuration: dict[str, Any],
    stage_versions: list[tuple[IngestionStage, str]],
    max_attempts: int,
) -> tuple[IngestionRun, list[IngestionStageRun]]:
    """Create the run row plus one pending stage row per pipeline stage,
    ordered with depends_on chains, inside the caller's transaction."""
    with conn.cursor(row_factory=dict_row) as cur:
        run_row = cur.execute(
            get(_FILE, "insert_run"),
            {
                "source_id": source_id,
                "pipeline_version": pipeline_version,
                "configuration": _dumps(configuration),
            },
        ).fetchone()
        assert run_row is not None
        run = _to_run(run_row)
        stage_runs: list[IngestionStageRun] = []
        previous_stage_run_id: UUID | None = None
        for position, (stage, handler_version) in enumerate(stage_versions):
            stage_row = cur.execute(
                get(_FILE, "insert_stage_run"),
                {
                    "run_id": run.run_id,
                    "stage": stage.value,
                    "position": position,
                    "depends_on_stage_id": previous_stage_run_id,
                    "max_attempts": max_attempts,
                    "handler_version": handler_version,
                    "configuration": _dumps({}),
                },
            ).fetchone()
            assert stage_row is not None
            stage_run = _to_stage_run(stage_row)
            stage_runs.append(stage_run)
            previous_stage_run_id = stage_run.stage_run_id
    return run, stage_runs


def get_run(conn: Connection, run_id: UUID) -> IngestionRun | None:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(get(_FILE, "get_run"), {"run_id": run_id}).fetchone()
    return _to_run(row) if row else None


def latest_run_for_source(conn: Connection, source_id: UUID) -> IngestionRun | None:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "latest_run_for_source"), {"source_id": source_id}
        ).fetchone()
    return _to_run(row) if row else None


def stage_run(
    conn: Connection, run_id: UUID, stage: IngestionStage
) -> IngestionStageRun | None:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "get_stage_run"),
            {"run_id": run_id, "stage": stage.value},
        ).fetchone()
    return _to_stage_run(row) if row else None


class RunObserver:
    """TransitionObserver persisting every stage transition on the caller's
    connection. Commits after each SUCCEEDED transition so completed stage
    output survives a later stage's failure — a retry does not redo
    committed stages. Failed/pending transitions are written but not
    committed (the driver's failure-audit commit covers them)."""

    def __init__(self, conn: Connection, run_id: UUID) -> None:
        self._conn = conn
        self._run_id = run_id
        self._run_started = False

    def observe(
        self,
        stage: IngestionStage,
        attempt: int,
        status: IngestionStatus,
        error_message: str | None,
    ) -> None:
        with self._conn.cursor(row_factory=dict_row) as cur:
            if not self._run_started:
                cur.execute(
                    get(_FILE, "mark_run_started"), {"run_id": self._run_id}
                )
                self._run_started = True
            cur.execute(
                get(_FILE, "mark_stage_transition"),
                {
                    "run_id": self._run_id,
                    "stage": stage.value,
                    "status": status.value,
                    "attempt_count": attempt,
                    "error_message": error_message,
                },
            )
        if status == IngestionStatus.SUCCEEDED:
            self._conn.commit()

    def finish(self, status: IngestionStatus, error_message: str | None) -> None:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                get(_FILE, "mark_run_terminal"),
                {
                    "run_id": self._run_id,
                    "status": status.value,
                    "error_message": error_message,
                },
            )


def mark_run_failed_direct(
    conn: Connection,
    run_id: UUID,
    message: str,
    *,
    failed_stage: IngestionPipelineError | None = None,
) -> None:
    """Terminal failure write used by the failure-audit path (post-rollback,
    fresh transaction); bypasses the observer on purpose. `failed_stage`,
    when given, is the pipeline's IngestionPipelineError — it carries the
    failing stage and final attempt count, which the rolled-back
    transaction may have erased. The stage row gets the underlying cause
    (e.g. the provider error); the run row keeps the pipeline summary."""
    cause = ""
    if failed_stage is not None and failed_stage.__cause__ is not None:
        cause = str(failed_stage.__cause__)
    stage_message = f"{message} ({cause})"[:500] if cause else message
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            get(_FILE, "mark_run_terminal"),
            {
                "run_id": run_id,
                "status": IngestionStatus.FAILED.value,
                "error_message": message,
            },
        )
        if failed_stage is not None:
            cur.execute(
                get(_FILE, "mark_stage_transition"),
                {
                    "run_id": run_id,
                    "stage": failed_stage.stage.value,
                    "status": IngestionStatus.FAILED.value,
                    "attempt_count": failed_stage.attempts,
                    "error_message": stage_message,
                },
            )


def claim_pending_sources(
    conn: Connection, limit: int
) -> list[dict[str, Any]]:
    """Claim queued sources by a persistent state transition
    (claimed_at set, skipped for future claims) — not by a row lock,
    which evaporates at the pipeline's first commit. Only never-claimed
    rows with status 'uploaded' are claimable. Caller commits."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            get(_FILE, "claim_pending_sources"), {"limit": limit}
        ).fetchall()
    return list(rows)


def clear_pending_source(conn: Connection, source_id: UUID) -> None:
    """Remove the queue row; the caller must have written ingestion_history
    first (queued_at is passed explicitly, not subselected)."""
    with conn.cursor() as cur:
        cur.execute(get(_FILE, "clear_pending_source"), {"source_id": source_id})


def record_history(
    conn: Connection,
    source_id: UUID,
    course_id: UUID,
    reason: str,
    queued_at: Any,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            get(_FILE, "record_ingestion_history"),
            {
                "source_id": source_id,
                "course_id": course_id,
                "reason": reason,
                "queued_at": queued_at,
            },
        )


def requeue_failed_source(conn: Connection, source_id: UUID, course_id: UUID) -> bool:
    """failed → uploaded + re-enqueue. The deliberate retry path for failed
    sources; ingestion attempts themselves do not auto-requeue. Returns
    False if the source was not in a failed state."""
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "requeue_failed_source"), {"source_id": source_id}
        ).fetchone()
    if row is None:
        return False
    with conn.cursor() as cur:
        cur.execute(
            get(_FILE, "requeue_row"),
            {"source_id": source_id, "course_id": course_id},
        )
    return True


def enqueue_pending(
    conn: Connection, source_id: UUID, course_id: UUID, reason: str
) -> None:
    """Queue a source for ingestion (upload handoff, copy seam). Idempotent
    on source_id. Caller commits."""
    with conn.cursor() as cur:
        cur.execute(
            get(_FILE, "enqueue_pending"),
            {
                "source_id": source_id,
                "course_id": course_id,
                "reason": reason,
            },
        )


def mark_source_indexed(conn: Connection, source_id: UUID) -> None:
    with conn.cursor() as cur:
        cur.execute(get(_FILE, "mark_source_indexed"), {"source_id": source_id})


def mark_source_failed(conn: Connection, source_id: UUID, error_message: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            get(_FILE, "mark_source_failed"),
            {"source_id": source_id, "error_message": error_message},
        )


def _dumps(value: dict[str, Any]) -> str:
    return json.dumps(value)