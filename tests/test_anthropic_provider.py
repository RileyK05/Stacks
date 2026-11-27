"""The native Anthropic path and the cloud presets' key handling."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from src.backend.common import provider, providers
from src.backend.common.providers import (
    Connection,
    ProviderChoice,
    ResolvedProvider,
    TaskClass,
)

REAL_CALL = provider._call_provider


def _claude(**overrides: Any) -> ResolvedProvider:
    values: dict[str, Any] = {
        "name": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "claude-opus-5-5",
        "api_key": "sk-ant-test",
        "is_local": False,
        "label": "Anthropic",
    }
    values.update(overrides)
    return ResolvedProvider(**values)


def _message(
    text: str = "answer",
    *,
    stop_reason: str = "end_turn",
    thinking: bool = False,
    usage: dict[str, int] | None = None,
) -> SimpleNamespace:
    blocks = [SimpleNamespace(type="thinking", thinking="")] if thinking else []
    if text:
        blocks.append(SimpleNamespace(type="text", text=text))
    counts = {
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    counts.update(usage or {})
    return SimpleNamespace(
        content=blocks, stop_reason=stop_reason, usage=SimpleNamespace(**counts)
    )


class _FakeClient:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.requests: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    @contextmanager
    def _stream(self, **request: Any) -> Any:
        self.requests.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        yield SimpleNamespace(get_final_message=lambda: self.result)


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> Any:
    holder: dict[str, _FakeClient] = {}

    def install(result: Any) -> _FakeClient:
        client = _FakeClient(result)
        holder["client"] = client
        monkeypatch.setattr(
            provider, "anthropic_client", lambda *args, **kwargs: client
        )
        return client

    return install


def _status_error(cls: type[anthropic.APIStatusError], code: int) -> Exception:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("nope", response=httpx2.Response(code, request=request), body=None)


# --- request shape -----------------------------------------------------------


def test_request_pins_effort_and_fallback_and_sends_no_sampling() -> None:
    request = provider.anthropic_request("tutor_answer", _claude(), "hi")
    assert "temperature" not in request
    assert request["output_config"] == {"effort": "medium"}
    assert request["betas"] == ["server-side-fallback-2026-07-01"]
    assert request["fallbacks"] == "default"
    assert request["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]}
    ]


def test_model_without_profile_gets_no_fallback_or_effort() -> None:
    request = provider.anthropic_request(
        "tutor_answer", _claude(model="claude-haiku-5-5"), "hi"
    )
    assert "fallbacks" not in request and "betas" not in request
    assert "output_config" not in request


def test_schema_and_images_use_messages_api_shapes() -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string", "minLength": 1}},
        "required": ["a"],
    }
    request = provider.anthropic_request(
        "ocr", _claude(), "read", images=[b"\x89PNG"], response_schema=schema
    )
    content = request["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/png"
    assert content[-1] == {"type": "text", "text": "read"}
    output_format = request["output_config"]["format"]
    assert output_format["type"] == "json_schema"
    assert output_format["schema"]["additionalProperties"] is False


def test_client_is_pinned_to_the_connection_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://elsewhere.invalid")
    client = provider.anthropic_client(
        "https://api.anthropic.com/v1/", "k", timeout=5.0
    )
    assert str(client.base_url).rstrip("/") == "https://api.anthropic.com"
    assert client.max_retries == 0


# --- reply handling ----------------------------------------------------------


def test_call_provider_dispatches_anthropic_and_bills_cached_input(
    fake_client: Any,
) -> None:
    client = fake_client(
        _message(
            "Paris",
            usage={"cache_creation_input_tokens": 100, "cache_read_input_tokens": 7},
        )
    )
    text, inputs, outputs = REAL_CALL("tutor_answer", _claude(), "capital?")
    assert (text, inputs, outputs) == ("Paris", 117, 5)
    assert client.requests[0]["model"] == "claude-opus-5-5"


def test_refusal_stop_reason_is_a_refusal(fake_client: Any) -> None:
    fake_client(_message("", stop_reason="refusal"))
    with pytest.raises(provider.ModelRefusalError):
        provider._call_anthropic("tutor_answer", _claude(), "x")


def test_max_tokens_is_truncation_with_partial_text(fake_client: Any) -> None:
    fake_client(_message("half", stop_reason="max_tokens"))
    with pytest.raises(provider.ModelOutputTruncatedError) as caught:
        provider._call_anthropic("tutor_answer", _claude(), "x")
    assert caught.value.partial_text == "half"


def test_thinking_without_text_is_reasoning_only(fake_client: Any) -> None:
    fake_client(_message("", thinking=True))
    with pytest.raises(provider.ModelReasoningOnlyError):
        provider._call_anthropic("tutor_answer", _claude(), "x")


@pytest.mark.parametrize(
    ("error", "expected", "transient"),
    [
        (
            _status_error(anthropic.RateLimitError, 429),
            provider.ProviderRateLimitedError,
            False,
        ),
        (
            _status_error(anthropic.AuthenticationError, 401),
            provider.ProviderRequestRejectedError,
            False,
        ),
        (
            _status_error(anthropic.InternalServerError, 529),
            provider.ProviderUnavailableError,
            True,
        ),
    ],
)
def test_sdk_errors_map_to_the_seam_errors(
    fake_client: Any, error: Exception, expected: type[Exception], transient: bool
) -> None:
    fake_client(error)
    with pytest.raises(expected) as caught:
        provider._call_anthropic("tutor_answer", _claude(), "x")
    assert getattr(caught.value, "transient", False) is transient


# --- keys and routing --------------------------------------------------------


def test_missing_key_fails_closed(_memory_keyring: dict[str, str]) -> None:
    providers.save_choice(TaskClass.INTERACTIVE, ProviderChoice(preset="anthropic"))
    assert providers.resolve(TaskClass.INTERACTIVE) is None
    with pytest.raises(provider.ProviderUnavailableError, match="Settings"):
        provider.generate("tutor_answer", "prompt")


def test_env_key_fallback_and_keychain_precedence(
    _memory_keyring: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = Connection(id="anthropic", preset="anthropic", name="Anthropic")
    monkeypatch.setenv("ANT_KEY", "from-ant-key")
    assert providers.api_key_for(connection) == "from-ant-key"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-standard-name")
    assert providers.api_key_for(connection) == "from-standard-name"
    _memory_keyring["anthropic"] = "from-keychain"
    assert providers.api_key_for(connection) == "from-keychain"


def test_env_keys_do_not_cross_presets(
    _memory_keyring: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANT_KEY", "anthropic-only")
    for preset in ("ollama_cloud", "openai"):
        connection = Connection(id=preset, preset=preset, name=preset)
        assert providers.api_key_for(connection) is None


def test_interactive_claude_and_background_ollama_cloud(
    _memory_keyring: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANT_KEY", "a")
    monkeypatch.setenv("OLLAMA_KEY", "o")
    providers.save_choice(TaskClass.INTERACTIVE, ProviderChoice(preset="anthropic"))
    providers.save_choice(TaskClass.BACKGROUND, ProviderChoice(preset="ollama_cloud"))
    interactive = providers.resolve(TaskClass.INTERACTIVE)
    background = providers.resolve(TaskClass.BACKGROUND)
    assert interactive is not None and background is not None
    assert (interactive.name, interactive.model, interactive.api_key) == (
        "anthropic",
        "claude-opus-5-5",
        "a",
    )
    assert (background.base_url, background.model, background.api_key) == (
        "https://ollama.com/v1",
        "mimo-v2.6-flash",
        "o",
    )
    assert providers.task_class("ocr") == TaskClass.BACKGROUND


# --- Ollama Cloud thinking switch -------------------------------------------


def _ollama_cloud() -> ResolvedProvider:
    return ResolvedProvider(
        name="ollama_cloud",
        base_url="https://ollama.com/v1",
        model="mimo-v2.6-flash",
        api_key="k",
        is_local=False,
    )


def test_ocr_turns_thinking_off_on_ollama_cloud() -> None:
    body = provider.request_body("ocr", _ollama_cloud(), "read", images=[b"x"])
    assert body["reasoning_effort"] == "none"
    assert "chat_template_kwargs" not in body


def test_answers_keep_the_reasoning_profile_on_ollama_cloud() -> None:
    body = provider.request_body("tutor_answer", _ollama_cloud(), "q")
    assert "reasoning_effort" not in body


def test_ocr_budget_is_not_sized_for_reasoning() -> None:
    from src.backend.common import generation

    ocr = generation.plan_call("ocr", _ollama_cloud(), "read")
    answer = generation.plan_call("tutor_answer", _ollama_cloud(), "q")
    assert ocr.output_tokens == 2048
    assert answer.output_tokens > ocr.output_tokens
