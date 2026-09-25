from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from src.backend.common.schemas.base import IngestionStage, IngestionStatus

PIPELINE_STAGES = (
    IngestionStage.EXTRACT_TEXT,
    IngestionStage.OCR,
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


class StageSkipped(Exception):  # noqa: N818 - a signal, not an error
    """Raised by a handler whose stage does not apply to this source (or
    is not implemented yet). The executor records the stage as succeeded
    WITH the reason in its error_message column, so the ledger shows the
    stage was skipped rather than pretending it did work."""


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
    import cycle). When given, a failed attempt's partial writes are rolled
    back before the failure is recorded, so a retry starts clean and the
    failure ledger never commits half a stage. This relies on the
    observer committing every transition: the attempt's writes are then
    the only uncommitted work when the handler raises."""
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
            try:
                handlers[stage]()
            except StageSkipped as skipped:
                if observe is not None:
                    observe(
                        stage, attempt, IngestionStatus.SUCCEEDED, f"skipped: {skipped}"
                    )
                completed.append(StageExecution(stage=stage, attempts=attempt))
                break
            except Exception as err:
                if conn is not None:
                    conn.rollback()
                if observe is not None:
                    observe(stage, attempt, IngestionStatus.FAILED, str(err))
                if attempt == max_attempts:
                    raise IngestionPipelineError(stage, attempt) from err
            else:
                if observe is not None:
                    observe(stage, attempt, IngestionStatus.SUCCEEDED, None)
                completed.append(StageExecution(stage=stage, attempts=attempt))
                break
    return PipelineExecution(stages=tuple(completed))
