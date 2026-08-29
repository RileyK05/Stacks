import pytest
from src.backend.common.schemas import IngestionStage, IngestionStatus
from src.backend.ingest.pipeline import (
    PIPELINE_STAGES,
    IngestionPipelineError,
    execute_pipeline,
)


def _handlers(calls):
    return {stage: lambda stage=stage: calls.append(stage) for stage in PIPELINE_STAGES}


def test_pipeline_runs_stages_in_dependency_order() -> None:
    calls = []
    result = execute_pipeline(_handlers(calls), max_attempts=2)
    assert calls == list(PIPELINE_STAGES)
    assert [stage.stage for stage in result.stages] == list(PIPELINE_STAGES)


def test_pipeline_retries_failed_stage_then_continues() -> None:
    calls = []
    handlers = _handlers(calls)
    attempts = 0

    def flaky_extract() -> None:
        nonlocal attempts
        attempts += 1
        calls.append(IngestionStage.EXTRACT_TEXT)
        if attempts == 1:
            raise RuntimeError("temporary parser failure")

    handlers[IngestionStage.EXTRACT_TEXT] = flaky_extract
    result = execute_pipeline(handlers, max_attempts=2)
    assert attempts == 2
    assert result.stages[0].attempts == 2
    assert calls[:2] == [IngestionStage.EXTRACT_TEXT, IngestionStage.EXTRACT_TEXT]


def test_pipeline_stops_after_second_failure() -> None:
    calls = []
    handlers = _handlers(calls)

    def broken_extract() -> None:
        calls.append(IngestionStage.EXTRACT_TEXT)
        raise RuntimeError("parser unavailable")

    handlers[IngestionStage.EXTRACT_TEXT] = broken_extract
    transitions = []
    with pytest.raises(IngestionPipelineError) as caught:
        execute_pipeline(
            handlers,
            max_attempts=2,
            observe=lambda *transition: transitions.append(transition),
        )
    assert caught.value.stage == IngestionStage.EXTRACT_TEXT
    assert caught.value.attempts == 2
    assert calls == [IngestionStage.EXTRACT_TEXT, IngestionStage.EXTRACT_TEXT]
    assert transitions[-1][2] == IngestionStatus.FAILED
