"""Bounded model recovery: actual request bodies and shared feature operations."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import httpx
import pytest
from src.backend.common import (
    generation,
    model_profiles,
    provider,
    providers,
    usage_repo,
)
from src.backend.common.generation_config import load_generation_policy
from src.backend.common.providers import ResolvedProvider
from src.backend.retrieval.funnel import Candidate
from src.backend.tutor.compose import compose_answer

REAL_CALL = provider._call_provider


def _endpoint(**kwargs: Any) -> ResolvedProvider:
    return ResolvedProvider(
        **{
            "name": "custom",
            "base_url": "https://example.test/v1",
            "model": "test-model",
            "api_key": None,
            "is_local": False,
        }
        | kwargs
    )


def _payload(text: str | None, finish: str = "stop", **kwargs: Any) -> dict:
    return {
        "choices": [{"message": {"content": text}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    } | kwargs


def _http(
    monkeypatch: pytest.MonkeyPatch,
    replies: list[tuple[int, dict]],
    *,
    on_post: Callable[[], None] | None = None,
) -> list[dict]:
    requests: list[dict] = []

    def post(url, **kwargs):
        requests.append(json.loads(json.dumps(kwargs["json"])))
        if on_post:
            on_post()
        assert replies, "unexpected extra HTTP attempt"
        status, body = replies.pop(0)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(provider, "_call_provider", REAL_CALL)
    monkeypatch.setattr(provider, "_ADAPTATIONS", {})
    monkeypatch.setattr(providers, "resolve", lambda *_: _endpoint())
    monkeypatch.setattr(httpx, "post", post)
    return requests


def _profile(monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> None:
    profile = model_profiles.ModelProfile(
        model="test-model", max_output_tokens=2048, **kwargs
    )
    monkeypatch.setattr(model_profiles, "profile_for", lambda *_: profile)


@pytest.mark.parametrize("finish", ["length", "max_tokens"])
def test_cutoff_recovers_entire_unit_with_same_prompt_and_counts_every_attempt(
    monkeypatch: pytest.MonkeyPatch, finish: str
) -> None:
    _profile(monkeypatch, output_token_limit=8192, context_window_tokens=32768)
    calls = _http(
        monkeypatch,
        [(200, _payload("unsafe partial", finish)), (200, _payload("complete"))],
    )
    with generation.operation() as operation:
        result = provider.generate("artifact_generation", "Original task and evidence")
    assert result.text == "complete"
    assert [c["max_tokens"] for c in calls] == [2048, 4096]
    assert calls[0]["messages"] == calls[1]["messages"]
    assert operation.calls == 2 and operation.http_requests == 2
    assert operation.reported_input_tokens == 20
    assert operation.reported_output_tokens == 10
    assert usage_repo.cloud_tokens_this_month() == 30


def test_unknown_capacity_does_not_invent_a_larger_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_profiles, "profile_for", lambda *_: None)
    calls = _http(monkeypatch, [(200, _payload("secret partial", "length"))])
    with pytest.raises(provider.ModelOutputTruncatedError) as error:
        provider.generate("artifact_generation", "task")
    assert len(calls) == 1 and calls[0]["max_tokens"] == 2048
    assert error.value.partial_text == "secret partial"
    assert "secret partial" not in str(error.value)


def test_context_estimate_includes_utf8_schema_and_leaves_output_space(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _profile(monkeypatch, output_token_limit=8192, context_window_tokens=2048)
    prompt = "学" * 1000
    schema = {"properties": {"answer": {"type": "string"}}}
    plan = generation.plan_call(
        "tutor_answer", _endpoint(), prompt, response_schema=schema
    )
    assert plan.input_tokens_estimate > 1000
    assert plan.output_tokens + plan.input_tokens_estimate + 512 == 2048
    assert plan.wider() is None
    with pytest.raises(generation.GenerationLimitError, match="too much material"):
        generation.plan_call("tutor_answer", _endpoint(), prompt * 2)


def test_bundled_context_allocation_overrides_a_larger_model_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.backend.runtime import user_models

    _profile(monkeypatch, context_window_tokens=131072)
    monkeypatch.setattr(user_models, "find_model", lambda *_: object())
    limits = generation.plan_call(
        "artifact_generation", _endpoint(name="local"), "task"
    )
    assert limits.context_tokens == 8192
    assert limits.output_tokens == 2048
    assert limits.output_ceiling == 8192
    assert limits.wider().output_tokens == 4096
    visual = generation.plan_call("ocr", _endpoint(name="local"), "task", images=True)
    assert visual.wider() is None, "image costs must not be guessed from PNG bytes"


def test_profile_reasoning_allowance_is_preserved_for_short_tasks() -> None:
    plan = generation.plan_call(
        "tutor_answer", _endpoint(model="mimo-v2.6-flash"), "task"
    )
    assert plan.output_tokens == 16384
    assert plan.context_tokens is None and plan.wider() is None


def test_empty_is_retried_only_once_and_background_summary_does_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reasoning = _payload(None)
    reasoning["choices"][0]["message"]["reasoning_content"] = "private thoughts"
    calls = _http(monkeypatch, [(200, reasoning)])
    with pytest.raises(provider.ModelReasoningOnlyError):
        # Known reasoning with an unknown output ceiling cannot be widened.
        provider.generate("tutor_answer", "task")
    assert len(calls) == 1
    calls = _http(monkeypatch, [(200, _payload("")), (200, _payload(""))])
    with pytest.raises(provider.EmptyModelError):
        provider.generate("tutor_answer", "task")
    assert len(calls) == 2
    calls = _http(monkeypatch, [(200, _payload(""))])
    with pytest.raises(provider.EmptyModelError):
        provider.generate("conversation_summary", "task")
    assert len(calls) == 1


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": 10}])
def test_missing_usage_is_explicit_and_estimates_do_not_become_measured_counts(
    monkeypatch: pytest.MonkeyPatch, usage: dict | None
) -> None:
    _http(monkeypatch, [(200, _payload("answer", usage=usage))])
    with generation.operation() as operation:
        result = provider.generate("tutor_answer", "task")
    assert not result.usage_reported
    assert operation.missing_usage_calls == 1
    assert operation.reported_output_tokens == 0
    assert operation.requested_tokens > 0
    assert result.output_tokens == 0


def test_cloud_budget_is_checked_again_after_a_billed_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _profile(monkeypatch, output_token_limit=8192)
    calls = _http(monkeypatch, [(200, _payload("partial", "length"))])
    usage_repo.set_monthly_budget(15)
    with pytest.raises(usage_repo.BudgetExceededError):
        provider.generate("tutor_answer", "task")
    assert len(calls) == 1 and usage_repo.cloud_tokens_this_month() == 15


def test_parameter_adaptations_consume_shared_http_and_requested_token_allowances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _http(
        monkeypatch,
        [
            (400, {"error": {"message": "use max_completion_tokens"}}),
            (400, {"error": {"message": "temperature is unsupported"}}),
        ],
    )
    policy = load_generation_policy().model_copy(update={"max_http_requests": 2})
    with (
        generation.operation(policy) as operation,
        pytest.raises(provider.ProviderUnavailableError, match="several requests"),
    ):
        provider.generate("tutor_answer", "task")
    assert len(calls) == 2 and operation.calls == 1
    assert operation.http_requests == 2
    assert operation.requested_tokens > 4096
    assert "max_completion_tokens" in calls[1] and "max_tokens" not in calls[1]


def test_nested_content_and_schema_repair_share_one_call_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _http(
        monkeypatch,
        [
            (400, {"error": {"message": "schema unsupported"}}),
            (200, _payload('{"item":{"type":"document","content":"# Only title"}}')),
            (400, {"error": {"message": "schema unsupported"}}),
        ],
    )
    policy = load_generation_policy().model_copy(update={"max_calls": 3})
    candidates = (
        Candidate(
            chunk_id=uuid4(),
            source_id=uuid4(),
            locator_id=uuid4(),
            chunk_index=0,
            text="Linearity preserves addition and scaling.",
            layers=frozenset({"keyword"}),
            rank=1.0,
        ),
    )

    def generate(task, prompt, *, response_schema=None):
        return provider.generate(task, prompt, response_schema=response_schema).text

    with (
        generation.operation(policy) as operation,
        pytest.raises(provider.ProviderUnavailableError, match="several attempts"),
    ):
        compose_answer(
            "Make a study guide",
            candidates,
            generate,
            on_schema_rejected=lambda e: isinstance(
                e, provider.ProviderRequestRejectedError
            ),
        )
    assert len(calls) == operation.calls == 3


def test_requested_token_limit_stops_retry_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _profile(monkeypatch, output_token_limit=8192)
    calls = _http(monkeypatch, [(200, _payload("partial", "length"))])
    policy = load_generation_policy().model_copy(update={"max_requested_tokens": 3000})
    with (
        generation.operation(policy),
        pytest.raises(provider.ProviderUnavailableError, match="generation allowance"),
    ):
        provider.generate("tutor_answer", "task")
    assert len(calls) == 1


def test_late_complete_reply_is_not_published_and_usage_is_still_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [0.0]
    calls = _http(
        monkeypatch,
        [(200, _payload("late complete answer"))],
        on_post=lambda: now.__setitem__(0, 11.0),
    )
    policy = load_generation_policy().model_copy(update={"max_elapsed_seconds": 10})
    with (
        generation.operation(policy, clock=lambda: now[0]),
        pytest.raises(provider.ProviderUnavailableError, match="took too long"),
    ):
        provider.generate("tutor_answer", "task")
    assert len(calls) == 1 and usage_repo.cloud_tokens_this_month() == 15


def test_cancellation_is_not_recovered(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def cancel(*args, **kwargs):
        calls.append(True)
        raise asyncio.CancelledError

    monkeypatch.setattr(providers, "resolve", lambda *_: _endpoint())
    monkeypatch.setattr(provider, "_call_provider", cancel)
    with pytest.raises(asyncio.CancelledError):
        provider.generate("tutor_answer", "task")
    assert len(calls) == 1


def test_request_timeout_is_clamped_to_remaining_operation_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _http(monkeypatch, [])
    now = [0.0]
    timeouts = []

    def post(url, **kwargs):
        timeouts.append(kwargs["timeout"])
        return httpx.Response(200, json=_payload("answer"))

    monkeypatch.setattr(httpx, "post", post)
    policy = load_generation_policy().model_copy(update={"max_elapsed_seconds": 30})
    with generation.operation(policy, clock=lambda: now[0]):
        now[0] = 25
        assert provider.generate("tutor_answer", "task").text == "answer"
        now[0] = 31
        with pytest.raises(provider.ProviderUnavailableError, match="took too long"):
            provider.generate("tutor_answer", "task")
    assert len(timeouts) == 1
    assert timeouts[0].read == timeouts[0].connect == 5


def test_reasoning_only_response_can_recover_with_known_headroom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _profile(monkeypatch, output_token_limit=8192)
    reasoning = _payload(None)
    reasoning["choices"][0]["message"]["reasoning_content"] = "private thoughts"
    calls = _http(monkeypatch, [(200, reasoning), (200, _payload("answer"))])
    assert provider.generate("tutor_answer", "task").text == "answer"
    assert [call["max_tokens"] for call in calls] == [2048, 4096]
    assert "private thoughts" not in json.dumps(calls[1])


def test_provider_choice_is_pinned_for_repairs_but_new_operation_reads_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    choices = iter([_endpoint(model="first"), _endpoint(model="next")])
    seen = []
    monkeypatch.setattr(providers, "resolve", lambda *_: next(choices))

    def transport(task, endpoint, prompt, **kwargs):
        seen.append(endpoint.model)
        return "answer", 10, 5

    monkeypatch.setattr(provider, "_call_provider", transport)
    with generation.operation():
        provider.generate("tutor_answer", "task")
        provider.generate("artifact_generation", "repair")
    provider.generate("tutor_answer", "next task")
    assert seen == ["first", "first", "next"]


def test_successful_rate_limit_fallback_remains_visible_on_subsequent_repairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(providers, "resolve", lambda *_: _endpoint())
    monkeypatch.setattr(
        provider, "_local_fallback", lambda *_: _endpoint(name="local", is_local=True)
    )
    seen = []

    def transport(task, endpoint, prompt, **kwargs):
        seen.append(endpoint.name)
        if endpoint.name == "custom":
            raise provider.ProviderRateLimitedError("limited")
        return "answer", 10, 5

    monkeypatch.setattr(provider, "_call_provider", transport)
    with generation.operation() as operation:
        first = provider.generate("tutor_answer", "task")
        repair = provider.generate("artifact_generation", "repair")
    assert first.fell_back_to_local and repair.fell_back_to_local
    assert seen == ["custom", "local", "local"] and operation.calls == 3
