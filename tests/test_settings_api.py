from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from src.backend.common import provider, usage_repo

REAL_CALL = provider._call_provider


def test_providers_overview_starts_unconfigured(client: TestClient) -> None:
    overview = client.get("/settings/providers").json()
    names = [preset["name"] for preset in overview["presets"]]
    assert names[0] == "local"
    assert {"openai", "anthropic", "google", "openrouter", "groq"} <= set(names)
    assert {"lmstudio", "ollama", "custom"} <= set(names)
    assert [c["id"] for c in overview["connections"]] == ["local"]
    unset = {"interactive": None, "background": None, "bigger": None}
    assert overview["choices"] == unset
    assert overview["resolved"] == unset
    disclosed = {p["name"]: p["disclosure"] for p in overview["presets"]}
    assert disclosed["local"] is False and disclosed["openrouter"] is True


def test_choosing_local_resolves_both_task_classes(client: TestClient) -> None:
    response = client.put("/settings/providers/interactive", json={"preset": "local"})
    assert response.status_code == 200
    resolved = response.json()["resolved"]
    assert resolved["interactive"]["model"] == "minicpm5-2b"
    assert resolved["background"]["model"] == "minicpm5-2b", (
        "background follows the interactive choice until set separately"
    )
    cleared = client.delete("/settings/providers/interactive").json()
    assert cleared["resolved"]["interactive"] is None


def test_keys_are_write_only_and_live_in_the_keyring(
    client: TestClient, _memory_keyring: dict[str, str]
) -> None:
    client.put("/settings/providers/interactive", json={"preset": "openrouter"})
    assert client.get("/settings/providers").json()["resolved"]["interactive"] is None

    response = client.put("/settings/keys/openrouter", json={"key": "  sk-or-secret "})
    assert response.status_code == 204
    assert _memory_keyring == {"openrouter": "sk-or-secret"}
    overview = client.get("/settings/providers")
    assert "sk-or-secret" not in overview.text, "keys are never echoed back"
    presets = {p["name"]: p for p in overview.json()["presets"]}
    assert presets["openrouter"]["has_key"] is True
    assert overview.json()["resolved"]["interactive"]["name"] == "openrouter"

    assert client.delete("/settings/keys/openrouter").status_code == 204
    assert _memory_keyring == {}


def test_unknown_provider_and_task_class_are_rejected(client: TestClient) -> None:
    assert client.put("/settings/keys/nope", json={"key": "x"}).status_code == 404
    assert (
        client.put(
            "/settings/providers/interactive", json={"preset": "nope"}
        ).status_code
        == 404
    )
    assert (
        client.put(
            "/settings/providers/sometimes", json={"preset": "local"}
        ).status_code
        == 422
    )


def test_connection_test_lists_models_without_spending_tokens(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    unconfigured = client.post("/settings/providers/interactive/test").json()
    assert unconfigured["ok"] is False and unconfigured["models"] == []
    assert unconfigured["error"] == "no provider configured"
    assert unconfigured["model_ok"] is None, "nothing to try"
    client.put("/settings/providers/interactive", json={"preset": "local"})
    seen: list[str] = []

    def fake_get(url: str, headers: Any = None, timeout: Any = None) -> httpx.Response:
        seen.append(url)
        return httpx.Response(
            200,
            json={"data": [{"id": "minicpm5-2b"}, {"id": "k2-horizon-3.7b"}]},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    result = client.post("/settings/providers/interactive/test").json()
    assert result["ok"] is True and result["error"] is None
    assert result["models"] == ["k2-horizon-3.7b", "minicpm5-2b"]
    assert seen == ["http://127.0.0.1:8081/v1/models"]
    assert usage_repo.ledger_page() == []


def test_connection_test_reports_failures(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.put("/settings/providers/interactive", json={"preset": "local"})

    def refuse(url: str, headers: Any = None, timeout: Any = None) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", refuse)
    result = client.post("/settings/providers/interactive/test").json()
    assert result["ok"] is False
    assert result["error"] == (
        "nothing is answering at http://127.0.0.1:8081/v1. Is the server running?"
    )


def test_usage_and_budget(client: TestClient) -> None:
    usage_repo.record(
        task="tutor_answer",
        provider="local",
        model="m",
        input_tokens=100,
        output_tokens=50,
    )
    usage_repo.record(
        task="tutor_answer",
        provider="openrouter",
        model="free",
        input_tokens=30,
        output_tokens=10,
    )
    usage = client.get("/settings/usage").json()
    assert usage["cloud_tokens_this_month"] == 40, "local tokens are not cloud spend"
    assert usage["monthly_cloud_token_budget"] is None
    assert {(t["provider"], t["calls"]) for t in usage["totals"]} == {
        ("local", 1),
        ("openrouter", 1),
    }
    assert len(usage["recent"]) == 2

    updated = client.put(
        "/settings/usage/budget", json={"monthly_cloud_token_budget": 5000}
    ).json()
    assert updated["monthly_cloud_token_budget"] == 5000
    assert (
        client.put(
            "/settings/usage/budget", json={"monthly_cloud_token_budget": 0}
        ).status_code
        == 422
    )
    cleared = client.put("/settings/usage/budget", json={}).json()
    assert cleared["monthly_cloud_token_budget"] is None


def test_connection_test_tries_the_default_model(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Listing models only proves the URL and key: a mistyped default model
    passed Test and then failed every chat."""
    offered = {"data": [{"id": "mimo-v2.6-flash"}, {"id": "mimo-v2.6-pro"}]}
    monkeypatch.setattr(
        httpx,
        "get",
        lambda url, **k: httpx.Response(
            200, json=offered, request=httpx.Request("GET", url)
        ),
    )
    monkeypatch.setattr(provider, "_call_provider", REAL_CALL)
    posts: list[str] = []

    def fake_post(
        url: str,
        headers: Any = None,
        json: Any = None,
        timeout: Any = None,
        follow_redirects: bool = False,
    ):
        posts.append(json["model"])
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}}
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    created = client.post(
        "/settings/connections",
        json={
            "preset": "custom",
            "name": "Xiaomi",
            "base_url": "https://mimo.example/v1",
            "default_model": "mimo-2.6-flash",
        },
    ).json()
    wrong = client.post(f"/settings/connections/{created['id']}/test").json()
    assert wrong["ok"] is True and wrong["model_ok"] is False
    assert wrong["suggested_models"][0] == "mimo-v2.6-flash"
    assert posts == [], "an unlisted name fails without spending tokens"

    client.patch(
        f"/settings/connections/{created['id']}",
        json={"default_model": "mimo-v2.6-flash"},
    )
    right = client.post(f"/settings/connections/{created['id']}/test").json()
    assert right["model_ok"] is True and right["model"] == "mimo-v2.6-flash"
    assert posts == ["mimo-v2.6-flash"]


def test_connection_models_lists_names_without_a_completion(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    offered = {"data": [{"id": "b-model"}, {"id": "a-model"}]}
    monkeypatch.setattr(
        httpx,
        "get",
        lambda url, **k: httpx.Response(
            200, json=offered, request=httpx.Request("GET", url)
        ),
    )

    def no_post(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("listing models must not send a completion")

    monkeypatch.setattr(httpx, "post", no_post)
    created = client.post(
        "/settings/connections",
        json={"preset": "custom", "base_url": "https://llm.example/v1"},
    ).json()
    listed = client.get(f"/settings/connections/{created['id']}/models").json()
    assert listed["ok"] is True and listed["models"] == ["a-model", "b-model"]
    assert client.get("/settings/connections/local/models").json()["ok"] is False
