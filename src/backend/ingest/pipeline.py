from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.backend.common.schemas.base import IngestionStage, IngestionStatus

PIPELINE_STAGES = (
    IngestionStage.EXTRACT_TEXT,
    IngestionStage.BUILD_LOCATORS,
    IngestionStage.BUILD_CHUNKS,
    IngestionStage.UPDATE_TOC,
    IngestionStage.EXTRACT_MEMORY,
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
) -> PipelineExecution:
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
            except Exception as err:
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
