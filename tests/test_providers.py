"""The generation seam and provider resolution (plan §7)."""

from typing import Any

import httpx
import pytest
from src.backend.common import model_profiles, provider, providers, usage_repo
from src.backend.common.providers import ProviderChoice, ResolvedProvider, TaskClass
from tests.conftest import configure_test_provider

# Captured at import, before the autouse fixture stubs the transport, so
# the HTTP-level tests exercise the real request/response handling.
REAL_CALL = provider._call_provider


def _endpoint(**overrides: Any) -> ResolvedProvider:
    values: dict[str, Any] = {
        "name": "local",
        "base_url": "http://127.0.0.1:8081/v1",
        "model": "minicpm5-2b",
        "api_key": None,
        "is_local": True,
    }
    values.update(overrides)
    return ResolvedProvider(**values)


# --- resolution -----------------------------------------------------------------


def test_nothing_configured_resolves_to_none_and_generate_fails_closed() -> None:
    assert providers.resolve(TaskClass.INTERACTIVE) is None
    with pytest.raises(provider.ProviderUnavailableError, match="Settings"):
        provider.generate("tutor_answer", "prompt")


def test_saved_local_choice_resolves_to_preset_defaults() -> None:
    providers.save_choice(TaskClass.INTERACTIVE, ProviderChoice(preset="local"))
    resolved = providers.resolve(TaskClass.INTERACTIVE)
    assert resolved == _endpoint()


def test_background_falls_back_to_interactive_choice() -> None:
    providers.save_choice(TaskClass.INTERACTIVE, ProviderChoice(preset="local"))
    assert providers.resolve(TaskClass.BACKGROUND) == _endpoint()
    providers.save_choice(
        TaskClass.BACKGROUND, ProviderChoice(preset="local", model="bigger-model")
    )
    background = providers.resolve(TaskClass.BACKGROUND)
    assert background is not None and background.model == "bigger-model"
    interactive = providers.resolve(TaskClass.INTERACTIVE)
    assert interactive is not None and interactive.model == "minicpm5-2b"


def test_cloud_preset_needs_its_key(
    _memory_keyring: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://dev-endpoint.test/v1")
    monkeypatch.setenv("LLM_MODEL", "dev-model")
    providers.save_choice(TaskClass.INTERACTIVE, ProviderChoice(preset="openrouter"))
    assert providers.resolve(TaskClass.INTERACTIVE) is None, (
        "an unavailable explicit choice must not silently switch providers"
    )
    _memory_keyring["openrouter"] = "sk-or-test"
    resolved = providers.resolve(TaskClass.INTERACTIVE)
    assert resolved is not None
    assert resolved.api_key == "sk-or-test" and resolved.is_local is False
    assert resolved.base_url == "https://openrouter.ai/api/v1"


def test_openai_preset_requires_a_model_choice(_memory_keyring: dict[str, str]) -> None:
    _memory_keyring["openai"] = "sk-test"
    providers.save_choice(TaskClass.INTERACTIVE, ProviderChoice(preset="openai"))
    assert providers.resolve(TaskClass.INTERACTIVE) is None
    providers.save_choice(
        TaskClass.INTERACTIVE, ProviderChoice(preset="openai", model="some-model")
    )
    resolved = providers.resolve(TaskClass.INTERACTIVE)
    assert resolved is not None and resolved.model == "some-model"


def test_custom_preset_uses_given_url_and_optional_key() -> None:
    providers.save_choice(
        TaskClass.INTERACTIVE,
        ProviderChoice(
            preset="custom", base_url="http://localhost:11434/v1", model="m"
        ),
    )
    resolved = providers.resolve(TaskClass.INTERACTIVE)
    assert resolved is not None
    assert (resolved.base_url, resolved.model, resolved.api_key) == (
        "http://localhost:11434/v1",
        "m",
        None,
    )


def test_environment_fallback_for_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("LLM_MODEL", "dev-model")
    monkeypatch.setenv("LLM_API_KEY", "dev-key")
    resolved = providers.resolve(TaskClass.INTERACTIVE)
    assert resolved is not None
    assert (resolved.name, resolved.model, resolved.api_key, resolved.is_local) == (
        "environment",
        "dev-model",
        "dev-key",
        False,
    )
    # A saved choice always wins over the environment.
    providers.save_choice(TaskClass.INTERACTIVE, ProviderChoice(preset="local"))
    assert providers.resolve(TaskClass.INTERACTIVE) == _endpoint()


def test_unknown_preset_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown provider preset"):
        providers.save_choice(TaskClass.INTERACTIVE, ProviderChoice(preset="nope"))


# --- generate: routing, ledger, budget, fallback ---------------------------------


def test_generate_routes_by_task_class_and_records_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = configure_test_provider(monkeypatch, "answer")
    providers.save_choice(
        TaskClass.BACKGROUND, ProviderChoice(preset="local", model="background-model")
    )
    provider.generate("tutor_answer", "prompt")
    provider.generate("conversation_summary", "prompt")
    assert [call["endpoint"].model for call in calls] == [
        "minicpm5-2b",
        "background-model",
    ]
    ledger = usage_repo.ledger_page()
    assert {(entry.task, entry.model) for entry in ledger} == {
        ("tutor_answer", "minicpm5-2b"),
        ("conversation_summary", "background-model"),
    }
    assert all(e.input_tokens == 10 and e.output_tokens == 5 for e in ledger)


def test_unknown_task_rejected_before_anything() -> None:
    with pytest.raises(ValueError, match="unknown generation task"):
        provider.generate("not_a_task", "prompt")


def test_empty_provider_output_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_test_provider(monkeypatch, "   ")
    with pytest.raises(provider.EmptyModelError):
        provider.generate("tutor_answer", "prompt")
    assert len(usage_repo.ledger_page()) == 2
    assert usage_repo.ledger_page()[0].output_tokens == 5


def test_cloud_budget_blocks_before_the_call_local_is_exempt(
    monkeypatch: pytest.MonkeyPatch, _memory_keyring: dict[str, str]
) -> None:
    usage_repo.set_monthly_budget(100)
    usage_repo.record(
        task="tutor_answer",
        provider="openrouter",
        model="m",
        input_tokens=80,
        output_tokens=20,
    )
    calls = configure_test_provider(monkeypatch, "ok", preset="openrouter")
    _memory_keyring["openrouter"] = "sk-or-test"
    with pytest.raises(usage_repo.BudgetExceededError):
        provider.generate("tutor_answer", "prompt")
    assert calls == [], "the provider must not be called past the budget"

    # Local calls cost nothing and are never blocked by the cloud budget.
    providers.save_choice(TaskClass.INTERACTIVE, ProviderChoice(preset="local"))
    assert provider.generate("tutor_answer", "prompt").text == "ok"
    usage_repo.set_monthly_budget(None)
    assert usage_repo.monthly_budget() is None


def test_rate_limited_cloud_call_falls_back_to_local(
    monkeypatch: pytest.MonkeyPatch, _memory_keyring: dict[str, str]
) -> None:
    _memory_keyring["openrouter"] = "sk-or-test"
    providers.save_choice(TaskClass.INTERACTIVE, ProviderChoice(preset="openrouter"))
    seen: list[str] = []

    def transport(task, endpoint, prompt, *, images=None, response_schema=None):
        seen.append(endpoint.name)
        if endpoint.name == "openrouter":
            raise provider.ProviderRateLimitedError("429")
        return "local answer", 7, 3

    monkeypatch.setattr(provider, "_call_provider", transport)
    result = provider.generate("tutor_answer", "prompt")
    assert seen == ["openrouter", "local"]
    assert result.fell_back_to_local and result.provider == "local"
    assert usage_repo.ledger_page()[0].provider == "local"


def test_bigger_slot_resolves_only_from_its_own_choice(
    monkeypatch: pytest.MonkeyPatch, _memory_keyring: dict[str, str]
) -> None:
    """Never automatic: no interactive or environment fallback."""
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    providers.save_choice(TaskClass.INTERACTIVE, ProviderChoice(preset="local"))
    assert providers.resolve(TaskClass.BIGGER) is None
    with pytest.raises(provider.ProviderUnavailableError, match="bigger model"):
        provider.generate("tutor_answer", "prompt", bigger=True)

    _memory_keyring["openrouter"] = "sk-or-test"
    providers.save_choice(TaskClass.BIGGER, ProviderChoice(preset="openrouter"))
    bigger = providers.resolve(TaskClass.BIGGER)
    assert bigger is not None and bigger.name == "openrouter"
    assert providers.resolve(TaskClass.INTERACTIVE) == _endpoint()


def test_bigger_env_fills_only_an_empty_slot(
    monkeypatch: pytest.MonkeyPatch, _memory_keyring: dict[str, str]
) -> None:
    assert providers.resolve(TaskClass.BIGGER) is None
    monkeypatch.setenv("LLM_BIGGER_MODEL", "env-bigger")
    assert providers.resolve(TaskClass.BIGGER) is None
    monkeypatch.setenv("LLM_BIGGER_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("LLM_BIGGER_API_KEY", "test-key")
    bigger = providers.resolve(TaskClass.BIGGER)
    assert bigger is not None
    assert bigger.model == "env-bigger"
    assert bigger.base_url == "http://127.0.0.1:9/v1"
    assert bigger.api_key == "test-key"
    providers.save_choice(TaskClass.BIGGER, ProviderChoice(preset="local"))
    chosen = providers.resolve(TaskClass.BIGGER)
    assert chosen is not None and chosen.name == "local"
    assert chosen.model != "env-bigger"


def test_bigger_model_routes_and_never_falls_back(
    monkeypatch: pytest.MonkeyPatch, _memory_keyring: dict[str, str]
) -> None:
    _memory_keyring["openrouter"] = "sk-or-test"
    providers.save_choice(TaskClass.INTERACTIVE, ProviderChoice(preset="local"))
    providers.save_choice(TaskClass.BIGGER, ProviderChoice(preset="openrouter"))
    seen: list[str] = []
    limited = False

    def transport(task, endpoint, prompt, *, images=None, response_schema=None):
        seen.append(endpoint.name)
        if limited and endpoint.name == "openrouter":
            raise provider.ProviderRateLimitedError("429")
        return "answer", 7, 3

    monkeypatch.setattr(provider, "_call_provider", transport)
    assert provider.generate("tutor_answer", "p", bigger=True).provider == "openrouter"
    limited = True
    with pytest.raises(provider.ProviderRateLimitedError):
        provider.generate("tutor_answer", "p", bigger=True)
    assert seen == ["openrouter", "openrouter"], "no silent local substitute"
    with pytest.raises(ValueError):
        provider.generate("ocr", "p", bigger=True)


# --- the HTTP transport -----------------------------------------------------------


class _Response:
    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        self.status_code = status
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://test")
            raise httpx.HTTPStatusError(
                "error", request=request, response=httpx.Response(self.status_code)
            )

    def json(self) -> dict[str, Any]:
        return self._payload


def _capture_post(monkeypatch: pytest.MonkeyPatch, response: _Response) -> list[dict]:
    captured: list[dict] = []

    def fake_post(url, headers=None, json=None, timeout=None, follow_redirects=False):
        captured.append({"url": url, "headers": headers, "json": json})
        return response

    monkeypatch.setattr(httpx, "post", fake_post)
    return captured


OK_BODY = {
    "choices": [{"message": {"content": "hello"}}],
    "usage": {"prompt_tokens": 12, "completion_tokens": 4},
}


def test_local_request_disables_thinking_and_sends_no_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_post(monkeypatch, _Response(200, OK_BODY))
    text, prompt_tokens, completion_tokens = REAL_CALL(
        "tutor_answer",
        _endpoint(),
        "prompt",
        response_schema={"type": "object"},
    )
    assert (text, prompt_tokens, completion_tokens) == ("hello", 12, 4)
    request = captured[0]
    assert request["url"] == "http://127.0.0.1:8081/v1/chat/completions"
    assert request["headers"] == {}
    body = request["json"]
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["reasoning_effort"] == "none"
    assert body["response_format"]["type"] == "json_schema"
    assert body["model"] == "minicpm5-2b" and body["max_tokens"] > 0


def test_cloud_request_sends_key_and_no_llama_cpp_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_post(monkeypatch, _Response(200, OK_BODY))
    REAL_CALL(
        "tutor_answer",
        _endpoint(
            name="openai",
            base_url="https://api.openai.com/v1/",
            api_key="sk",
            is_local=False,
            model="m",
        ),
        "prompt",
    )
    request = captured[0]
    assert request["url"] == "https://api.openai.com/v1/chat/completions"
    assert request["headers"] == {"Authorization": "Bearer sk"}
    assert "chat_template_kwargs" not in request["json"]
    assert "reasoning_effort" not in request["json"]


def test_http_429_raises_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_post(monkeypatch, _Response(429, {}))
    with pytest.raises(provider.ProviderRateLimitedError):
        REAL_CALL("tutor_answer", _endpoint(), "prompt")


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("<think>private reasoning</think>final answer", "final answer"),
        ([{"type": "text", "text": "final answer"}], "final answer"),
    ],
)
def test_transport_returns_only_visible_text(
    monkeypatch: pytest.MonkeyPatch, content: Any, expected: str
) -> None:
    payload = {"choices": [{"message": {"content": content}}], "usage": {}}
    _capture_post(monkeypatch, _Response(200, payload))
    assert REAL_CALL("tutor_answer", _endpoint(), "prompt")[0] == expected


def test_longcat_profile_requests_a_reasoning_budget() -> None:
    body = provider.request_body(
        "tutor_answer",
        _endpoint(name="custom", is_local=False, model="LongCat-2.5-Preview"),
        "prompt",
    )
    assert body["max_tokens"] == 16384


def test_null_content_with_stop_is_reasoning_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "choices": [
            {
                "message": {"content": None, "reasoning_content": "private thoughts"},
                "finish_reason": "stop",
            }
        ]
    }
    _capture_post(monkeypatch, _Response(200, payload))
    with pytest.raises(provider.ModelReasoningOnlyError, match="only reasoning"):
        REAL_CALL("tutor_answer", _endpoint(), "prompt")


def test_transport_cutoff_has_no_hidden_retry_and_keeps_private_partial_internal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    length = {
        "choices": [
            {
                "message": {"content": "<think>private</think>unfinished"},
                "finish_reason": "length",
            }
        ],
        "usage": {"completion_tokens_details": {"reasoning_tokens": 1800}},
    }
    captured = _sequence_post(monkeypatch, _Response(200, length))
    with pytest.raises(provider.ModelOutputTruncatedError) as error:
        REAL_CALL("tutor_answer", _endpoint(), "prompt")
    assert len(captured) == 1
    assert error.value.partial_text == "unfinished"
    assert "unfinished" not in str(error.value) and "private" not in str(error.value)
    assert captured[0]["max_tokens"] == 2048


def test_transport_rejects_truncated_output(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "choices": [{"message": {"content": '{"partial":'}, "finish_reason": "length"}]
    }
    _capture_post(monkeypatch, _Response(200, payload))
    with pytest.raises(provider.ModelOutputTruncatedError, match="output limit"):
        REAL_CALL("tutor_answer", _endpoint(), "prompt")


def test_generate_records_truncated_and_reasoning_retry_usage(monkeypatch) -> None:
    endpoint = _endpoint(name="custom", is_local=False)
    monkeypatch.setattr(provider, "_call_provider", REAL_CALL)
    monkeypatch.setattr(providers, "resolve", lambda *_: endpoint)
    profile = model_profiles.ModelProfile(
        model=endpoint.model, max_output_tokens=2048, output_token_limit=8192
    )
    monkeypatch.setattr(model_profiles, "profile_for", lambda *_: profile)
    cut_off = {
        "choices": [{"message": {"content": None}, "finish_reason": "length"}],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "completion_tokens_details": {"reasoning_tokens": 20},
        },
    }
    completed = {
        "choices": [{"message": {"content": "Answer"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    calls = _sequence_post(
        monkeypatch, _Response(200, cut_off), _Response(200, completed)
    )
    assert provider.generate("tutor_answer", "prompt").text == "Answer"
    assert len(calls) == 2
    assert [call["max_tokens"] for call in calls] == [2048, 4096]
    assert usage_repo.cloud_tokens_this_month() == 45
    monkeypatch.setattr(
        model_profiles,
        "profile_for",
        lambda *_: profile.model_copy(update={"output_token_limit": 2048}),
    )
    _sequence_post(
        monkeypatch,
        _Response(
            200,
            completed
            | {
                "choices": [
                    {"message": {"content": "Partial"}, "finish_reason": "length"}
                ]
            },
        ),
    )
    with pytest.raises(provider.ModelOutputTruncatedError):
        provider.generate("tutor_answer", "prompt")
    assert usage_repo.cloud_tokens_this_month() == 60


@pytest.mark.parametrize(
    "response",
    [_Response(500, {}), _Response(200, {"choices": []}), _Response(200, {"x": 1})],
)
def test_transport_failures_fail_closed(
    monkeypatch: pytest.MonkeyPatch, response: _Response
) -> None:
    _capture_post(monkeypatch, response)
    with pytest.raises(provider.ProviderUnavailableError):
        REAL_CALL("tutor_answer", _endpoint(), "prompt")


def _sequence_post(monkeypatch: pytest.MonkeyPatch, *responses: Any) -> list[dict]:
    """Serve `responses` in order; record a copy of each request body (the
    call adjusts its body in place between attempts)."""
    captured: list[dict] = []
    queue = list(responses)

    def fake_post(url, headers=None, json=None, timeout=None, follow_redirects=False):
        captured.append(dict(json))
        return queue.pop(0)

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(provider, "_ADAPTATIONS", {})
    return captured


def test_rejection_carries_the_providers_own_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare "custom rejected the request (400)" is undiagnosable: the
    student sees the endpoint's words and which setting to change."""
    body = {"error": {"code": "400", "message": "Unsupported model mimo-2.6-flash"}}
    _sequence_post(monkeypatch, _Response(400, body))
    endpoint = _endpoint(name="custom", label="Xiaomi", is_local=False, model="m")
    with pytest.raises(provider.ProviderRequestRejectedError) as caught:
        REAL_CALL("tutor_answer", endpoint, "prompt")
    message = str(caught.value)
    assert message.startswith("Xiaomi rejected the request (400)")
    assert "Unsupported model mimo-2.6-flash" in message
    assert "model name in Settings" in message


def test_openrouter_upstream_error_prefers_the_raw_reason() -> None:
    body = {
        "error": {
            "message": "Provider returned error",
            "metadata": {"raw": "context length exceeded"},
        }
    }
    assert provider.provider_error_detail(_Response(400, body)) == (
        "context length exceeded"
    )


def test_named_unsupported_parameters_are_adapted_and_remembered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Newer OpenAI models refuse `max_tokens` and custom temperatures."""
    tokens = {
        "error": {
            "message": "Unsupported parameter: 'max_tokens'. "
            "Use 'max_completion_tokens' instead."
        }
    }
    temperature = {
        "error": {
            "message": "Unsupported value: 'temperature' does "
            "not support 0.2 with this model."
        }
    }
    captured = _sequence_post(
        monkeypatch,
        _Response(400, tokens),
        _Response(400, temperature),
        _Response(200, OK_BODY),
        _Response(200, OK_BODY),
    )
    endpoint = _endpoint(name="openai", is_local=False, model="gpt-x", api_key="sk")
    assert REAL_CALL("tutor_answer", endpoint, "p")[0] == "hello"
    assert "max_tokens" in captured[0] and "temperature" in captured[0]
    assert "max_completion_tokens" in captured[2] and "temperature" not in captured[2]
    REAL_CALL("tutor_answer", endpoint, "p")
    assert len(captured) == 4, "the second call goes straight through"
    assert "max_tokens" not in captured[3] and "temperature" not in captured[3]


def test_unfixable_rejection_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _sequence_post(
        monkeypatch, _Response(403, {"error": {"message": "not for you"}})
    )
    with pytest.raises(provider.ProviderRequestRejectedError, match="not for you"):
        REAL_CALL("tutor_answer", _endpoint(), "p")
    assert len(captured) == 1


def test_error_inside_a_200_is_reported_not_a_parse_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _sequence_post(
        monkeypatch, _Response(200, {"error": {"message": "upstream overloaded"}})
    )
    with pytest.raises(provider.ProviderUnavailableError, match="upstream overloaded"):
        REAL_CALL("tutor_answer", _endpoint(), "p")


def test_probe_accepts_a_reply_cut_short_by_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    truncated = {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}
    _sequence_post(monkeypatch, _Response(200, truncated))
    monkeypatch.setattr(provider, "_call_provider", REAL_CALL)
    provider.probe(_endpoint())


def test_refusal_text_is_rejected_not_shown_as_an_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refusal = {
        "choices": [
            {
                "message": {
                    "content": (
                        "The request was rejected because it was considered high risk"
                    ),
                    "reasoning_content": "private",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 8},
    }
    _capture_post(monkeypatch, _Response(200, refusal))
    with pytest.raises(provider.ModelRefusalError, match="refused to answer"):
        REAL_CALL("tutor_answer", _endpoint(), "prompt")


def test_failed_local_fallback_keeps_the_rate_limit_message(
    monkeypatch: pytest.MonkeyPatch, _memory_keyring: dict[str, str]
) -> None:
    _memory_keyring["openrouter"] = "sk-or-test"
    providers.save_choice(TaskClass.INTERACTIVE, ProviderChoice(preset="openrouter"))

    def fake_call(task, endpoint, prompt, **kwargs):
        if endpoint.is_local:
            raise provider.ProviderUnavailableError("the local model could not start")
        raise provider.ProviderRateLimitedError("OpenRouter is rate-limiting requests")

    monkeypatch.setattr(provider, "_call_provider", fake_call)
    with pytest.raises(provider.ProviderRateLimitedError, match="rate-limiting"):
        provider.generate("tutor_answer", "prompt")
