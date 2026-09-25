"""The generation seam and provider resolution (plan §7)."""

from typing import Any

import httpx
import pytest
from src.backend.common import provider, providers, usage_repo
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


def test_cloud_preset_needs_its_key(_memory_keyring: dict[str, str]) -> None:
    providers.save_choice(TaskClass.INTERACTIVE, ProviderChoice(preset="openrouter"))
    assert providers.resolve(TaskClass.INTERACTIVE) is None, "no key yet"
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
    provider.generate("course_knowledge_extraction", "prompt")
    assert [call["endpoint"].model for call in calls] == [
        "minicpm5-2b",
        "background-model",
    ]
    ledger = usage_repo.ledger_page()
    assert {(entry.task, entry.model) for entry in ledger} == {
        ("tutor_answer", "minicpm5-2b"),
        ("course_knowledge_extraction", "background-model"),
    }
    assert all(e.input_tokens == 10 and e.output_tokens == 5 for e in ledger)


def test_unknown_task_rejected_before_anything() -> None:
    with pytest.raises(ValueError, match="unknown generation task"):
        provider.generate("not_a_task", "prompt")


def test_empty_provider_output_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_test_provider(monkeypatch, "   ")
    with pytest.raises(provider.EmptyModelError):
        provider.generate("tutor_answer", "prompt")
    assert usage_repo.ledger_page() == []


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

    def fake_post(url, headers=None, json=None, timeout=None):
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
    "response",
    [_Response(500, {}), _Response(200, {"choices": []}), _Response(200, {"x": 1})],
)
def test_transport_failures_fail_closed(
    monkeypatch: pytest.MonkeyPatch, response: _Response
) -> None:
    _capture_post(monkeypatch, response)
    with pytest.raises(provider.ProviderUnavailableError):
        REAL_CALL("tutor_answer", _endpoint(), "prompt")
