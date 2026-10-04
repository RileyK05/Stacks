"""Usage provenance reaches the persisted ledger and the Settings response."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from src.backend.common import (
    generation,
    model_profiles,
    provider,
    providers,
    usage_repo,
)
from src.backend.common import migrate as migrations
from src.backend.common.db import connect, connection
from src.backend.common.providers import ResolvedProvider

REAL_CALL = provider._call_provider


def _transport(monkeypatch: pytest.MonkeyPatch, payload: object) -> None:
    endpoint = ResolvedProvider(
        name="custom",
        base_url="https://example.test/v1",
        model="unknown-model",
        api_key=None,
        is_local=False,
    )
    monkeypatch.setattr(providers, "resolve", lambda *_: endpoint)
    monkeypatch.setattr(provider, "_call_provider", REAL_CALL)
    monkeypatch.setattr(model_profiles, "profile_for", lambda *_: None)
    monkeypatch.setattr(
        httpx, "post", lambda *_, **__: httpx.Response(200, json=payload)
    )


@pytest.mark.parametrize(
    ("usage", "inputs", "outputs", "reported"),
    [
        ({"prompt_tokens": 0, "completion_tokens": 0}, 0, 0, True),
        ({"prompt_tokens": "10", "completion_tokens": "5"}, 10, 5, True),
        ({"prompt_tokens": 10}, 10, 0, False),
        ({"prompt_tokens": None, "completion_tokens": 5}, 0, 5, False),
        ({"prompt_tokens": -1, "completion_tokens": 5}, 0, 5, False),
        ({"prompt_tokens": 2**64, "completion_tokens": 5}, 0, 5, False),
        ({"prompt_tokens": True, "completion_tokens": 5}, 0, 5, False),
        ({"prompt_tokens": 3.5, "completion_tokens": 5}, 0, 5, False),
        ({"prompt_tokens": "unknown", "completion_tokens": 5}, 0, 5, False),
        (None, 0, 0, False),
        ("unknown", 0, 0, False),
        ([], 0, 0, False),
    ],
)
def test_response_usage_reaches_operation_ledger_and_settings(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    usage: object,
    inputs: int,
    outputs: int,
    reported: bool,
) -> None:
    payload = {
        "choices": [{"message": {"content": "Usable answer"}, "finish_reason": "stop"}],
        "usage": usage,
    }
    _transport(monkeypatch, payload)
    with generation.operation() as operation:
        result = provider.generate("tutor_answer", "task")
    assert result.text == "Usable answer" and result.usage_reported is reported
    assert operation.reported_input_tokens == inputs
    assert operation.reported_output_tokens == outputs
    assert operation.missing_usage_calls == int(not reported)
    entry = usage_repo.ledger_page()[0]
    assert entry.usage_reported is reported
    assert entry.input_tokens == inputs and entry.output_tokens == outputs
    view = client.get("/settings/usage").json()
    assert view["recent"][0]["usage_reported"] is reported
    assert view["cloud_tokens_this_month"] == inputs + outputs
    assert view["cloud_calls_without_usage"] == int(not reported)
    assert view["totals"][0]["calls_without_usage"] == int(not reported)


def test_truncated_usage_is_saved_even_when_no_answer_can_be_delivered(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _transport(
        monkeypatch,
        {
            "choices": [
                {"message": {"content": "unfinished"}, "finish_reason": "length"}
            ],
            "usage": {"completion_tokens": 5},
        },
    )
    with pytest.raises(provider.ModelOutputTruncatedError):
        provider.generate("tutor_answer", "task")
    view = client.get("/settings/usage").json()
    assert view["recent"][0]["usage_reported"] is False
    assert view["cloud_calls_without_usage"] == 1
    assert view["cloud_tokens_this_month"] == 5
    assert view["totals"][0]["calls"] == 1


def test_monthly_reporting_excludes_local_calls_and_old_unknown_rows(
    client: TestClient,
) -> None:
    for name, local, reported, count in (
        ("cloud", False, True, 40),
        ("cloud", False, False, 7),
        ("lan-local", True, False, 300),
    ):
        usage_repo.record(
            task="tutor_answer",
            provider=name,
            model="m",
            input_tokens=count,
            output_tokens=0,
            is_local=local,
            usage_reported=reported,
        )
    old = usage_repo.record(
        task="tutor_answer",
        provider="cloud",
        model="m",
        input_tokens=500,
        output_tokens=0,
    )
    legacy = usage_repo.record(
        task="tutor_answer",
        provider="cloud",
        model="m",
        input_tokens=0,
        output_tokens=0,
    )
    with connection() as conn:
        conn.execute(
            "UPDATE usage_ledger SET created_at=?, usage_reported=NULL "
            "WHERE ledger_id=?",
            (datetime(2000, 1, 1, tzinfo=UTC), old.ledger_id),
        )
        conn.execute(
            "UPDATE usage_ledger SET usage_reported=NULL WHERE ledger_id=?",
            (legacy.ledger_id,),
        )
        conn.commit()
    view = client.get("/settings/usage").json()
    assert view["cloud_tokens_this_month"] == 47
    assert view["cloud_calls_without_usage"] == 2
    cloud_total = next(t for t in view["totals"] if t["provider"] == "cloud")
    assert cloud_total["calls"] == 3 and cloud_total["calls_without_usage"] == 2
    usage_repo.set_monthly_budget(47)
    with pytest.raises(usage_repo.BudgetExceededError):
        usage_repo.check_cloud_budget()


def test_upgrade_preserves_historical_counts_with_unknown_reporting_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "old-usage.db"
    pending = migrations._pending_migrations
    with monkeypatch.context() as scope:
        scope.setattr(
            migrations,
            "_pending_migrations",
            lambda: [
                (version, file) for version, file in pending() if int(version) <= 21
            ],
        )
        migrations.migrate(path)
    conn = connect(path)
    try:
        for inputs, outputs in ((0, 0), (10, 5)):
            conn.execute(
                "INSERT INTO usage_ledger(ledger_id,task,provider,model,"
                "input_tokens,output_tokens) "
                "VALUES(?, 'tutor_answer', 'cloud', 'm', ?, ?)",
                (uuid4(), inputs, outputs),
            )
        conn.commit()
    finally:
        conn.close()
    assert migrations.migrate(path) == ["022"]
    monkeypatch.setenv("DATABASE_PATH", str(path))
    entries = usage_repo.ledger_page()
    assert {(e.input_tokens, e.output_tokens) for e in entries} == {(0, 0), (10, 5)}
    assert all(e.usage_reported is None for e in entries)
    assert usage_repo.cloud_usage_this_month().calls_without_usage == 2
    assert usage_repo.cloud_tokens_this_month() == 15
    assert migrations.migrate(path) == []


@pytest.mark.parametrize(
    "payload", [[], None, {"choices": [None]}, {"choices": [{"message": None}]}]
)
def test_unreadable_completion_shape_raises_actionable_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    _transport(monkeypatch, payload)
    with pytest.raises(provider.ProviderUnavailableError, match="could not read"):
        provider.generate("tutor_answer", "task")
    assert usage_repo.ledger_page()[0].usage_reported is False
    assert usage_repo.cloud_usage_this_month().calls_without_usage == 1


@pytest.mark.parametrize("usage", [None, {"prompt_tokens": 10, "completion_tokens": 5}])
def test_failed_completion_envelope_keeps_usage(
    monkeypatch: pytest.MonkeyPatch,
    usage: dict | None,
) -> None:
    _transport(monkeypatch, {"error": {"message": "upstream failed"}, "usage": usage})
    with pytest.raises(provider.ProviderUnavailableError, match="could not answer"):
        provider.generate("tutor_answer", "task")
    entry = usage_repo.ledger_page()[0]
    assert entry.usage_reported is (usage is not None)
    assert usage_repo.cloud_tokens_this_month() == (15 if usage else 0)


@pytest.mark.parametrize("metadata", [["unexpected"], "unexpected"])
def test_malformed_optional_error_metadata_keeps_provider_error_actionable(
    monkeypatch: pytest.MonkeyPatch,
    metadata: object,
) -> None:
    _transport(
        monkeypatch,
        {"error": {"message": "provider returned error", "metadata": metadata}},
    )
    with pytest.raises(provider.ProviderUnavailableError, match="could not answer"):
        provider.generate("tutor_answer", "task")
