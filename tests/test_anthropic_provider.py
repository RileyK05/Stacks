"""The native Anthropic path and the cloud presets' key handling."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from src.backend.common import model_profiles, provider, providers
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
        "model": "claude-haiku-5-5",
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


def test_request_sends_no_sampling_and_no_unrequested_options() -> None:
    """A model without a profile gets the API's own defaults: Stacks does
    not choose effort or fallbacks for the user's model."""
    request = provider.anthropic_request("tutor_answer", _claude(), "hi")
    assert "temperature" not in request
    assert "output_config" not in request
    assert "fallbacks" not in request and "betas" not in request
    assert request["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]}
    ]


def test_a_profile_can_pin_effort_and_opt_into_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = model_profiles.ModelProfile(
        model="claude-haiku-5-5", effort="low", refusal_fallback=True
    )
    monkeypatch.setattr(model_profiles, "profile_for", lambda model: profile)
    request = provider.anthropic_request("tutor_answer", _claude(), "hi")
    assert request["output_config"] == {"effort": "low"}
    assert request["betas"] == ["server-side-fallback-2026-07-01"]
    assert request["fallbacks"] == "default"


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
    assert client.requests[0]["model"] == "claude-haiku-5-5"


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
    providers.save_choice(
        TaskClass.INTERACTIVE,
        ProviderChoice(preset="anthropic", model="claude-haiku-5-5"),
    )
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


def test_user_chosen_models_route_per_task_class(
    _memory_keyring: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANT_KEY", "a")
    monkeypatch.setenv("OLLAMA_KEY", "o")
    providers.save_choice(
        TaskClass.INTERACTIVE,
        ProviderChoice(preset="anthropic", model="claude-haiku-5-5"),
    )
    providers.save_choice(
        TaskClass.BACKGROUND,
        ProviderChoice(preset="ollama_cloud", model="inkling-2-small"),
    )
    interactive = providers.resolve(TaskClass.INTERACTIVE)
    background = providers.resolve(TaskClass.BACKGROUND)
    assert interactive is not None and background is not None
    assert (interactive.name, interactive.model, interactive.api_key) == (
        "anthropic",
        "claude-haiku-5-5",
        "a",
    )
    assert (background.base_url, background.model, background.api_key) == (
        "https://ollama.com/v1",
        "inkling-2-small",
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


# --- model capabilities -------------------------------------------------------


def _known(monkeypatch: pytest.MonkeyPatch, **values: Any) -> None:
    from src.backend.common import model_capabilities

    caps = model_capabilities.Capabilities(**values)
    monkeypatch.setattr(model_capabilities, "capabilities_for", lambda endpoint: caps)


def test_a_known_ceiling_sizes_the_first_call_for_the_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A thinking model's quiz used ~5,000 tokens; the 2048-token first call
    for an "unknown" model was cut off and redone every time."""
    from src.backend.common import generation

    _known(monkeypatch, max_output_tokens=128000, thinks=True)
    quiz = generation.plan_call("artifact_generation", _claude(), "p")
    summary = generation.plan_call("conversation_summary", _claude(), "p")
    assert quiz.output_tokens == generation.FIRST_CALL_CAP
    assert summary.output_tokens == 1024, "reasoning off: no thinking room"
    _known(monkeypatch)
    assert (
        generation.plan_call("artifact_generation", _claude(), "p").output_tokens
        == 2048
    )


def test_tasks_without_deliberation_switch_thinking_off_where_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _known(monkeypatch, can_disable_thinking=True, thinks=True)
    assert provider.anthropic_request("conversation_summary", _claude(), "p")[
        "thinking"
    ] == {"type": "disabled"}
    assert "thinking" not in provider.anthropic_request("tutor_answer", _claude(), "p")
    _known(monkeypatch, thinks=True)
    assert "thinking" not in provider.anthropic_request(
        "conversation_summary", _claude(), "p"
    ), "a model that cannot switch it off is left alone"


def test_capabilities_are_read_from_the_models_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.backend.common import model_capabilities

    info = {
        "max_tokens": 128000,
        "capabilities": {
            "effort": {
                "supported": True,
                "low": {"supported": True},
                "max": {"supported": False},
            },
            "thinking": {"supported": True, "types": {"disabled": {"supported": True}}},
        },
    }
    fake = SimpleNamespace(
        models=SimpleNamespace(
            retrieve=lambda model: SimpleNamespace(model_dump=lambda: info)
        )
    )
    monkeypatch.setattr(provider, "anthropic_client", lambda *a, **k: fake)
    caps = model_capabilities._lookup(_claude())
    assert caps.max_output_tokens == 128000
    assert caps.efforts == frozenset({"low"})
    assert caps.can_disable_thinking and caps.thinks


# --- prompt caching ------------------------------------------------------------


def _grounded(after: str = "") -> str:
    from src.backend.common.prompt_registry import grounded_prompt

    return grounded_prompt("Instruction.", "material " * 800, after=after)


def test_a_repeated_prefix_is_cached_and_the_repair_note_stays_outside_it() -> None:
    """A quiz the checks rejected is regenerated from the same instruction and
    material: the second attempt marks that prefix so later ones read it."""
    first = provider.anthropic_request("artifact_generation", _claude(), _grounded())
    blocks = first["messages"][0]["content"]
    assert len(blocks) == 1 and "cache_control" not in blocks[0], "seen once: no write"
    again = provider.anthropic_request(
        "artifact_generation", _claude(), _grounded(after="Repair note.")
    )
    blocks = again["messages"][0]["content"]
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[0]["text"].endswith("<<<UNTRUSTED_COURSE_MATERIAL end>>>")
    assert blocks[1]["text"].strip() == "Repair note."


def test_short_or_one_off_prompts_are_never_marked() -> None:
    for _ in range(3):
        request = provider.anthropic_request("tutor_answer", _claude(), "short prompt")
        assert "cache_control" not in request["messages"][0]["content"][0]


def test_cache_tokens_reach_the_ledger(
    fake_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.backend.common.db import connection

    monkeypatch.setattr(provider, "_call_provider", REAL_CALL)
    fake_client(
        _message(
            "ok",
            usage={"cache_read_input_tokens": 900, "cache_creation_input_tokens": 0},
        )
    )
    provider._recorded_call(
        "tutor_answer",
        _claude(),
        "prompt",
        course_id=None,
        images=None,
        response_schema=None,
    )
    with connection() as conn:
        row = conn.execute(
            "SELECT input_tokens, cache_read_tokens, cache_write_tokens "
            "FROM usage_ledger ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    assert (row["input_tokens"], row["cache_read_tokens"]) == (910, 900)


def test_ollama_reports_thinking_and_its_context_as_the_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx
    from src.backend.common import model_capabilities

    shown = {
        "capabilities": ["completion", "thinking"],
        "model_info": {"inkling2.context_length": 1048576},
    }
    seen: dict[str, Any] = {}

    def post(url: str, **kwargs: Any) -> Any:
        seen["url"] = url
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: shown)

    monkeypatch.setattr(httpx, "post", post)
    caps = model_capabilities._lookup(_ollama_cloud())
    assert seen["url"] == "https://ollama.com/api/show"
    assert caps.max_output_tokens == 1048576
    assert caps.thinks and caps.can_disable_thinking
