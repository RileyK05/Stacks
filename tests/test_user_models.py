"""Adding a model (docs/plan-notebook.md §4.8): a Hugging Face GGUF link
or a .gguf file on this computer becomes one more catalog entry."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from src.backend.runtime import model_store, user_models
from src.backend.runtime.user_models import AddModelError, HuggingFaceLink

SHA = "8203991019c36dd618145aa76246097252e45283a4f75c0991a0ce902a0ad7d3"
TREE: list[dict[str, Any]] = [
    {"type": "file", "path": "README.md", "size": 10},
    {
        "type": "file",
        "path": "K2-Horizon-4B-Q8_0.gguf",
        "size": 5386404224,
        "lfs": {"oid": SHA, "size": 5386404224},
    },
    {
        "type": "file",
        "path": "K2-Horizon-4B-Q4_K_M.gguf",
        "size": 3156598144,
        "lfs": {"oid": "0" * 64, "size": 3156598144},
    },
]


@pytest.fixture
def fake_hub(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    requested: list[str] = []

    def get(url: str) -> Any:
        requested.append(url)
        return TREE

    monkeypatch.setattr(user_models, "_http_get", get)
    monkeypatch.setattr(model_store, "start_download", lambda model_id: None)
    return requested


def test_links_to_a_repo_or_a_file() -> None:
    assert user_models.parse_link(
        "https://huggingface.co/IFM/K2-Horizon-3.7B-GGUF"
    ) == (HuggingFaceLink(repo="IFM/K2-Horizon-3.7B-GGUF", revision="main", file=None))
    assert user_models.parse_link(
        "huggingface.co/org/repo/blob/main/sub/model-Q8_0.gguf?download=true"
    ) == HuggingFaceLink(repo="org/repo", revision="main", file="sub/model-Q8_0.gguf")
    for bad in (
        "https://example.com/org/repo",
        "https://huggingface.co/org",
        "https://huggingface.co/org/repo/blob/main/weights.safetensors",
    ):
        with pytest.raises(AddModelError):
            user_models.parse_link(bad)


def test_inspecting_a_repo_lists_its_ggufs_smallest_first(
    client: TestClient, fake_hub: list[str]
) -> None:
    view = client.post(
        "/runtime/models/inspect",
        json={"url": "https://huggingface.co/IFM/K2-Horizon-3.7B-GGUF"},
    ).json()
    assert [f["file"] for f in view["files"]] == [
        "K2-Horizon-4B-Q4_K_M.gguf",
        "K2-Horizon-4B-Q8_0.gguf",
    ]
    assert view["selected"] is None
    assert fake_hub == [
        "https://huggingface.co/api/models/IFM/K2-Horizon-3.7B-GGUF/tree/main"
    ]


def test_adding_from_huggingface_uses_the_published_checksum(
    client: TestClient, fake_hub: list[str]
) -> None:
    response = client.post(
        "/runtime/models",
        json={
            "url": "https://huggingface.co/IFM/K2-Horizon-3.7B-GGUF",
            "file": "K2-Horizon-4B-Q8_0.gguf",
        },
    )
    assert response.status_code == 201, response.text
    added = [m for m in response.json()["models"] if m["added_by_user"]]
    assert [(m["id"], m["label"], m["tier"]) for m in added] == [
        ("k2-horizon-4b-q8-0", "K2-Horizon-4B-Q8_0", "standard")
    ]
    model = user_models.find_model("k2-horizon-4b-q8-0")
    assert model is not None and model.sha256 == SHA
    assert model.download_url == (
        "https://huggingface.co/IFM/K2-Horizon-3.7B-GGUF/resolve/main/"
        "K2-Horizon-4B-Q8_0.gguf"
    )
    again = client.post(
        "/runtime/models",
        json={
            "url": "https://huggingface.co/IFM/K2-Horizon-3.7B-GGUF/blob/main/"
            "K2-Horizon-4B-Q8_0.gguf"
        },
    )
    assert again.status_code == 422 and "already" in again.json()["detail"]


def test_a_link_without_a_file_asks_which_one(
    client: TestClient, fake_hub: list[str]
) -> None:
    response = client.post(
        "/runtime/models",
        json={"url": "https://huggingface.co/IFM/K2-Horizon-3.7B-GGUF"},
    )
    assert response.status_code == 422
    assert "choose which GGUF" in response.json()["detail"]


def test_adding_a_local_file_uses_it_in_place(
    client: TestClient, tmp_path: Path
) -> None:
    gguf = tmp_path / "My-Model-Q4.gguf"
    gguf.write_bytes(b"GGUF" + b"\0" * 100)
    response = client.post("/runtime/models", json={"path": str(gguf)})
    assert response.status_code == 201, response.text
    view = next(m for m in response.json()["models"] if m["added_by_user"])
    assert view["location"] == "external" and view["source"] == str(gguf)
    model = user_models.find_model(view["id"])
    assert model is not None
    assert model.sha256 == hashlib.sha256(gguf.read_bytes()).hexdigest()
    assert model_store.installed_path(model) == gguf

    gguf.write_bytes(b"changed")
    assert model_store.installed_path(model) is None, "a changed file is not used"

    removed = client.delete(f"/runtime/models/{view['id']}")
    assert removed.status_code == 200
    assert gguf.exists(), "a file the user pointed at is never deleted"
    assert user_models.find_model(view["id"]) is None


def test_only_gguf_files_are_accepted(client: TestClient, tmp_path: Path) -> None:
    other = tmp_path / "weights.bin"
    other.write_bytes(b"x")
    assert client.post("/runtime/models", json={"path": str(other)}).status_code == 422
    assert client.post("/runtime/models", json={}).status_code == 422


def test_catalog_models_cannot_be_forgotten(client: TestClient) -> None:
    client.delete("/runtime/models/minicpm5-2b")
    assert user_models.find_model("minicpm5-2b") is not None
