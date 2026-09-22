from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from src.backend.common.schemas.base import IngestionStage, IngestionStatus

PIPELINE_STAGES = (
    IngestionStage.EXTRACT_TEXT,
    IngestionStage.BUILD_LOCATORS,
    IngestionStage.BUILD_CHUNKS,
    IngestionStage.EMBED_CHUNKS,
    IngestionStage.UPDATE_TOC,
    IngestionStage.EXTRACT_KNOWLEDGE,
)

StageHandler = Callable[[], None]
TransitionObserver = Callable[[IngestionStage, int, IngestionStatus, str | None], None]


@dataclass(frozen=True)
class StageExecution:
    stage: IngestionStage
    attempts: int


@dataclass(frozen=True)
class PipelineExecution:
    stages: tuple[StageExecution, ...]


class IngestionPipelineError(RuntimeError):
    def __init__(self, stage: IngestionStage, attempts: int) -> None:
        self.stage = stage
        self.attempts = attempts
        super().__init__(f"ingestion stage {stage} failed after {attempts} attempts")


def execute_pipeline(
    handlers: Mapping[IngestionStage, StageHandler],
    *,
    max_attempts: int,
    observe: TransitionObserver | None = None,
    conn: Any | None = None,
) -> PipelineExecution:
    """`conn` is the pipeline's connection (typed loosely to avoid an
    import cycle). When given, each attempt runs inside a SAVEPOINT so a
    DB-level stage failure cannot abort the surrounding transaction —
    the retry loop and the failure ledger keep working for every
    failure mode, not just non-DB ones (review catch #3)."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    missing = [stage for stage in PIPELINE_STAGES if stage not in handlers]
    if missing:
        names = ", ".join(stage.value for stage in missing)
        raise ValueError(f"missing ingestion handlers: {names}")

    completed: list[StageExecution] = []
    for stage in PIPELINE_STAGES:
        for attempt in range(1, max_attempts + 1):
            if observe is not None:
                observe(stage, attempt, IngestionStatus.RUNNING, None)
            # Each attempt runs inside a SAVEPOINT: a DB-level failure
            # (aborted transaction) must not poison the observer's own
            # ledger write or the retry. The handler's partial work rolls
            # back to the savepoint; the transaction stays usable. The
            # savepoint is released on success so later failures roll
            # back only their own attempt. (Review catch #3: without
            # this, the first psycopg error escaped as
            # InFailedSqlTransaction — uncatchable by the orchestrator's
            # IngestionPipelineError handler — leaving the run 'running'
            # forever with an empty stage ledger: the false state the
            # ledger exists to prevent.)
            savepoint_id = f"ingest_stage_{stage.value}_{attempt}"
            if conn is not None:
                with conn.cursor() as cur:
                    cur.execute(f"SAVEPOINT {savepoint_id}")
            try:
                handlers[stage]()
            except Exception as err:
                if conn is not None:
                    with conn.cursor() as cur:
                        cur.execute(f"ROLLBACK TO SAVEPOINT {savepoint_id}")
                if observe is not None:
                    observe(stage, attempt, IngestionStatus.FAILED, str(err))
                if attempt == max_attempts:
                    raise IngestionPipelineError(stage, attempt) from err
            else:
                if conn is not None:
                    with conn.cursor() as cur:
                        cur.execute(f"RELEASE SAVEPOINT {savepoint_id}")
                if observe is not None:
                    observe(stage, attempt, IngestionStatus.SUCCEEDED, None)
                completed.append(StageExecution(stage=stage, attempts=attempt))
                break
    return PipelineExecution(stages=tuple(completed))
