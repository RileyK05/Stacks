"""Connections (docs/plan-notebook.md §4.8): many endpoints, one key each,
the pre-connection form still working, per-model profiles, and the chat
model picker's options."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from src.backend.common import model_profiles, provider, providers
from src.backend.common.providers import ProviderChoice, ResolvedProvider, TaskClass


def test_many_connections_of_one_kind_each_with_its_own_key(
    client: TestClient, _memory_keyring: dict[str, str]
) -> None:
    personal = client.post(
        "/settings/connections",
        json={"preset": "openai", "name": "Personal", "key": " sk-personal "},
    ).json()
    work = client.post(
        "/settings/connections",
        json={"preset": "openai", "name": "Work", "default_model": "gpt-work"},
    ).json()
    assert personal["id"] != work["id"]
    assert _memory_keyring == {personal["id"]: "sk-personal"}
    assert personal["has_key"] is True and work["has_key"] is False
    assert work["effective_base_url"] == "https://api.openai.com/v1"

    client.put(f"/settings/keys/{work['id']}", json={"key": "sk-work"})
    client.put(
        "/settings/providers/interactive",
        json={"connection": work["id"]},
    )
    resolved = client.get("/settings/providers").json()["resolved"]["interactive"]
    assert (resolved["connection"], resolved["model"]) == (work["id"], "gpt-work")
    assert resolved["label"] == "Work"
    endpoint = providers.resolve(TaskClass.INTERACTIVE)
    assert endpoint is not None and endpoint.api_key == "sk-work"


def test_removing_a_connection_clears_its_key_and_choices(
    client: TestClient, _memory_keyring: dict[str, str]
) -> None:
    made = client.post(
        "/settings/connections", json={"preset": "groq", "key": "gsk"}
    ).json()
    client.put(
        "/settings/providers/bigger",
        json={"connection": made["id"], "model": "llama-big"},
    )
    overview = client.delete(f"/settings/connections/{made['id']}").json()
    assert [c["id"] for c in overview["connections"]] == ["local"]
    assert overview["choices"]["bigger"] is None
    assert made["id"] not in _memory_keyring


def test_the_local_connection_is_built_in(client: TestClient) -> None:
    assert client.delete("/settings/connections/local").status_code == 422
    assert (
        client.patch("/settings/connections/local", json={"name": "x"}).status_code
        == 422
    )
    assert (
        client.post("/settings/connections", json={"preset": "local"}).status_code
        == 422
    )


def test_connections_can_be_renamed_and_repointed(client: TestClient) -> None:
    made = client.post(
        "/settings/connections",
        json={
            "preset": "custom",
            "name": "Lab server",
            "base_url": "http://lab:8000/v1",
        },
    ).json()
    assert made["accepts_key"] is True and made["disclosure"] is True
    updated = client.patch(
        f"/settings/connections/{made['id']}",
        json={
            "name": "Lab GPU",
            "base_url": "http://gpu:8000/v1",
            "default_model": "m",
        },
    ).json()
    assert (
        updated["name"],
        updated["effective_base_url"],
        updated["default_model"],
    ) == (
        "Lab GPU",
        "http://gpu:8000/v1",
        "m",
    )
    unknown = client.post("/settings/connections", json={"preset": "nope"})
    assert unknown.status_code == 404


def test_keys_saved_before_connections_still_work(
    _memory_keyring: dict[str, str],
) -> None:
    """Keys used to live under the preset name; the connection created for
    a pre-connection choice has that same id, so they carry over."""
    _memory_keyring["openrouter"] = "sk-or-old"
    providers.save_choice(TaskClass.INTERACTIVE, ProviderChoice(preset="openrouter"))
    endpoint = providers.resolve(TaskClass.INTERACTIVE)
    assert endpoint is not None
    assert (endpoint.connection, endpoint.api_key) == ("openrouter", "sk-or-old")
    assert providers.saved_choice(TaskClass.INTERACTIVE) == ProviderChoice(
        connection="openrouter"
    )


def test_model_options_list_local_models_and_connection_defaults(
    client: TestClient, _memory_keyring: dict[str, str]
) -> None:
    client.post(
        "/settings/connections",
        json={"preset": "openai", "name": "Mine", "default_model": "gpt-x", "key": "k"},
    )
    client.post("/settings/connections", json={"preset": "anthropic"})
    options = client.get("/settings/model-options").json()
    local = [o for o in options if o["is_local"]]
    assert local and all(o["connection"] == "local" for o in local)
    assert not any(o["available"] for o in local), "nothing is downloaded in tests"
    cloud = [o for o in options if not o["is_local"]]
    assert [(o["connection_name"], o["model"], o["available"]) for o in cloud] == [
        ("Mine", "gpt-x", True)
    ], "a connection without a default model is typed in, not listed"


def _endpoint(preset: str, model: str) -> ResolvedProvider:
    return ResolvedProvider(
        name=preset,
        base_url="http://127.0.0.1:1234/v1",
        model=model,
        api_key=None,
        is_local=preset == "local",
    )


def test_profiles_switch_reasoning_per_model() -> None:
    minicpm, k2, plain = (
        provider.request_body("tutor_answer", _endpoint("lmstudio", model), "p")
        for model in ("minicpm5-2b", "K2-Horizon-4B-Q8_0", "unprofiled-model")
    )
    assert minicpm["reasoning_effort"] == "none"
    assert minicpm["chat_template_kwargs"] == {"enable_thinking": False}
    assert k2["reasoning_effort"] == "high" and k2["max_tokens"] == 8192
    assert k2["temperature"] == 1.0
    assert plain["reasoning_effort"] == "none", "no profile: thinking off"


def test_cloud_requests_never_carry_runtime_switches() -> None:
    body = provider.request_body(
        "tutor_answer", _endpoint("anthropic", "claude-x"), "p"
    )
    assert "reasoning_effort" not in body and "chat_template_kwargs" not in body


def test_profiles_load_by_name_or_alias(tmp_path: Path) -> None:
    (tmp_path / "demo.toml").write_text(
        'model = "demo-1b"\naliases = ["Demo-1B-Q4"]\nreasoning = true\n',
        encoding="utf-8",
    )
    found = model_profiles.profile_for("demo-1b-q4", tmp_path)
    assert found is not None and found.reasoning is True
    assert model_profiles.profile_for("other", tmp_path) is None
