import pytest
from src.backend.common.schemas import IngestionStage, IngestionStatus
from src.backend.ingest.pipeline import (
    PIPELINE_STAGES,
    IngestionPipelineError,
    StageSkipped,
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


def test_failed_attempt_is_rolled_back_recorded_and_retried() -> None:
    """A failed attempt's partial writes are rolled back before the
    failure is recorded, so the retry starts clean and the ledger never
    commits half a stage (review catch #3's invariant, SQLite edition:
    the observer commits every transition, so the attempt's own writes
    are the only uncommitted work)."""
    calls: list[IngestionStage] = []
    attempts: dict[str, int] = {"extract": 0}

    def flaky() -> None:
        attempts["extract"] += 1
        calls.append(IngestionStage.EXTRACT_TEXT)
        if attempts["extract"] == 1:
            raise RuntimeError("temporary parser failure")

    events: list[str] = []

    class _FakeConn:
        def rollback(self) -> None:
            events.append("rollback")

    def observe(stage, attempt, status, error):
        events.append(f"{stage.value}:{attempt}:{status.value}")

    handlers = _handlers(calls)
    handlers[IngestionStage.EXTRACT_TEXT] = flaky
    result = execute_pipeline(
        handlers, max_attempts=2, observe=observe, conn=_FakeConn()
    )
    extract_stage = next(
        s for s in result.stages if s.stage == IngestionStage.EXTRACT_TEXT
    )
    assert extract_stage.attempts == 2, "first attempt failed, second clean"
    assert events[:5] == [
        "extract_text:1:running",
        "rollback",
        "extract_text:1:failed",
        "extract_text:2:running",
        "extract_text:2:succeeded",
    ]


def test_skipped_stage_is_recorded_as_succeeded_with_reason() -> None:
    """A stage that does not apply records WHY in the ledger instead of
    pretending it did work (or failing the whole source)."""
    calls: list[IngestionStage] = []
    recorded: list[tuple[IngestionStage, IngestionStatus, str | None]] = []

    def skip() -> None:
        raise StageSkipped("no table of contents yet")

    handlers = _handlers(calls)
    handlers[IngestionStage.UPDATE_TOC] = skip
    result = execute_pipeline(
        handlers,
        max_attempts=2,
        observe=lambda stage, attempt, status, error: recorded.append(
            (stage, status, error)
        ),
    )
    assert IngestionStage.UPDATE_TOC in {s.stage for s in result.stages}
    assert (
        IngestionStage.UPDATE_TOC,
        IngestionStatus.SUCCEEDED,
        "skipped: no table of contents yet",
    ) in recorded
