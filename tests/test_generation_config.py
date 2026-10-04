from pathlib import Path

import pytest
from pydantic import ValidationError
from src.backend.common.generation_config import (
    GenerationPolicy,
    GenerationTask,
    load_generation_policy,
)
from src.backend.common.model_profiles import ModelProfile, profile_for
from src.backend.common.schemas.base import KNOWN_GENERATION_TASKS


def test_generation_policy_loads_all_known_tasks_and_operation_bounds() -> None:
    policy = load_generation_policy()

    assert policy.version == "1"
    assert policy.max_calls == 8
    assert policy.max_http_requests == 16
    assert policy.max_elapsed_seconds == 600
    assert policy.max_requested_tokens == 262144
    assert set(policy.tasks) == KNOWN_GENERATION_TASKS
    assert policy.tasks["tutor_answer"] == GenerationTask(
        desired_output_tokens=2048, max_recoveries=2
    )
    assert policy.tasks["artifact_generation"].desired_output_tokens == 16384
    assert policy.tasks["ocr"].max_recoveries == 1
    assert policy.tasks["conversation_summary"].max_recoveries == 0
    assert policy.tasks["learning_research"].desired_output_tokens == 2048
    assert policy.tasks["answer_eval_judge"].desired_output_tokens == 4096


@pytest.mark.parametrize(
    "field,value",
    [
        ("desired_output_tokens", 0),
        ("max_recoveries", -1),
        ("max_recoveries", 4),
    ],
)
def test_generation_task_rejects_invalid_bounds(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        GenerationTask(**{field: value})


def test_generation_policy_rejects_unknown_and_missing_tasks() -> None:
    base = load_generation_policy().model_dump()
    with_unknown = {
        **base,
        "tasks": {
            **base["tasks"],
            "other": {"desired_output_tokens": 1, "max_recoveries": 0},
        },
    }
    with pytest.raises(ValidationError, match="unknown tasks"):
        GenerationPolicy(**with_unknown)

    missing = {**base, "tasks": dict(base["tasks"])}
    missing["tasks"].pop(next(iter(KNOWN_GENERATION_TASKS)))
    with pytest.raises(ValidationError, match="missing tasks"):
        GenerationPolicy(**missing)


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_calls", 0),
        ("max_http_requests", 0),
        ("max_elapsed_seconds", 0),
        ("max_requested_tokens", 0),
        ("input_bytes_per_token", 0.9),
        ("input_bytes_per_token", 4.1),
        ("context_margin_tokens", -1),
        ("framing_tokens", -1),
        ("min_output_tokens", 0),
    ],
)
def test_generation_policy_rejects_invalid_operation_fields(
    field: str, value: int | float
) -> None:
    fields = load_generation_policy().model_dump()
    fields[field] = value
    with pytest.raises(ValidationError):
        GenerationPolicy(**fields)


def test_model_profile_token_bounds_and_optional_fields() -> None:
    valid = ModelProfile(
        model="bounded",
        max_output_tokens=1024,
        output_token_limit=2048,
        context_window_tokens=8192,
    )
    assert valid.max_output_tokens == 1024
    assert valid.output_token_limit == 2048
    assert valid.context_window_tokens == 8192
    with pytest.raises(ValidationError, match="max_output_tokens"):
        ModelProfile(model="invalid", max_output_tokens=2049, output_token_limit=2048)
    for field in ("output_token_limit", "context_window_tokens"):
        with pytest.raises(ValidationError):
            ModelProfile(model="invalid", **{field: 0})


def test_model_profile_alias_load_semantics_remain_case_insensitive(
    tmp_path: Path,
) -> None:
    (tmp_path / "demo.toml").write_text(
        'model = "demo-1b"\naliases = ["Demo-1B-Q4"]\nreasoning = true\n',
        encoding="utf-8",
    )
    found = profile_for("demo-1b-q4", tmp_path)
    assert found is not None and found.reasoning is True
    assert profile_for("other", tmp_path) is None


def test_mimo_profile_has_empirical_allowance_without_claimed_ceilings() -> None:
    profile = profile_for("mimo-v2.6-flash")
    assert profile is not None
    assert profile.model == "mimo-v2.6-flash"
    assert profile.reasoning is True
    assert profile.max_output_tokens == 16384
    assert profile.output_token_limit is None
    assert profile.context_window_tokens is None
    assert profile.aliases == ()
    assert "empirically used allowance" in profile.notes.casefold()
    assert "not an advertised model ceiling" in profile.notes.casefold()
