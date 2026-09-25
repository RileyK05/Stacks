from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# The developer's .env must never leak into the suite: get_settings()
# only loads .env keys that are ABSENT from the environment, so pinning
# these here (before any settings read) keeps a configured LLM key or a
# real data directory out of every test.
for _name in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "APP_API_TOKEN"):
    os.environ[_name] = ""
os.environ["APP_ENV"] = "test"


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """A passing run leaves no scratch files behind; a failing one keeps
    them (--basetemp, pyproject.toml) so the failure can be inspected."""
    basetemp = session.config.option.basetemp
    if exitstatus == 0 and basetemp:
        shutil.rmtree(basetemp, ignore_errors=True)


@pytest.fixture(autouse=True)
def _isolated_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    """Every test gets its own freshly migrated SQLite file and upload
    directory. Migration is a single small script, so per-test isolation
    costs milliseconds and no test can see another's rows."""
    from src.backend.common.migrate import migrate

    data_dir = tmp_path / "app-data"
    monkeypatch.setenv("APP_DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_PATH", str(data_dir / "test.db"))
    monkeypatch.setenv("STORAGE_ROOT", str(data_dir / "raw"))
    monkeypatch.setenv("APP_EXPORT_DIR", str(tmp_path / "exports"))
    migrate()
    yield data_dir


@pytest.fixture
def client() -> TestClient:
    """The API app (what the desktop shell mounts at /api)."""
    from src.backend.main import create_api

    return TestClient(create_api())


@pytest.fixture(autouse=True)
def _memory_keyring(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    """Tests never touch the OS credential store."""
    from src.backend.common import secrets

    store: dict[str, str] = {}
    monkeypatch.setattr(secrets, "get_api_key", lambda provider: store.get(provider))
    monkeypatch.setattr(
        secrets, "set_api_key", lambda provider, key: store.__setitem__(provider, key)
    )
    monkeypatch.setattr(
        secrets, "delete_api_key", lambda provider: store.pop(provider, None)
    )
    yield store


@pytest.fixture(autouse=True)
def _no_local_runtime(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Tests never start llama-server or read other apps' model folders
    (LM Studio, the Hugging Face cache). Records which catalog models the
    generation seam asked to have running."""
    from src.backend.common import provider
    from src.backend.runtime import model_store

    started: list[str] = []
    monkeypatch.setattr(provider, "_ensure_local_runtime", started.append)
    monkeypatch.setattr(model_store, "_external_roots", lambda: [])
    yield started


@pytest.fixture(autouse=True)
def _fake_reranker(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No test downloads the cross-encoder. The stub scores by word
    overlap with the question, so ordering is deterministic and sensible."""
    from src.backend.common import provider

    def overlap(model_name, query, texts):
        words = set(query.lower().split())
        return [float(len(words & set(text.lower().split()))) for text in texts]

    monkeypatch.setattr(provider, "rerank_scores", overlap)
    yield


@pytest.fixture(autouse=True)
def _no_live_provider(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No test makes a live HTTP model call: the transport is stubbed
    fail-closed. Tests that need a working provider monkeypatch
    `_call_provider` themselves (and configure an endpoint)."""
    from src.backend.common import provider

    def _unavailable(task, endpoint, prompt, *, images=None, response_schema=None):
        raise provider.ProviderUnavailableError(
            f"no live provider in tests (task={task}, model={endpoint.model})"
        )

    monkeypatch.setattr(provider, "_call_provider", _unavailable)
    yield


@pytest.fixture(autouse=True)
def _no_live_model_hub(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No test asks Hugging Face about a model. Tests that add one stub
    `user_models._http_get` themselves."""
    from src.backend.runtime import user_models

    def _offline(url: str) -> object:
        raise AssertionError(f"a test tried to reach {url}")

    monkeypatch.setattr(user_models, "_http_get", _offline)
    yield


@pytest.fixture(autouse=True)
def _fake_embedding_backend(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No test loads the real embedding model (hundreds of MB, seconds per
    load). The stub's dimension matches the configured contract — the seam
    enforces the config's dimension per call, so the fake must satisfy it,
    not dodge it."""
    from src.backend.common import provider
    from src.backend.common.embeddings_config import load_embedding_policy

    class _FakeBackend:
        def __init__(self, dimension: int) -> None:
            self._dimension = dimension

        def get_embedding_dimension(self) -> int:
            return self._dimension

        def encode(
            self,
            texts,
            batch_size=32,
            normalize_embeddings=True,
            show_progress_bar=False,
        ):
            return [
                [1.0 / (len(text) or 1) for _ in range(self._dimension)]
                for text in texts
            ]

    policy = load_embedding_policy()
    monkeypatch.setattr(
        provider,
        "_EMBEDDING_BACKEND",
        provider._EmbedBackend(model=_FakeBackend(policy.dimension), policy=policy),
    )
    yield
    provider.reset_embedding_backend()


def configure_test_provider(
    monkeypatch: pytest.MonkeyPatch,
    reply: str | None = "stub answer",
    *,
    preset: str = "local",
) -> list[dict[str, object]]:
    """Point both task classes at `preset` and stub the transport to return
    `reply`. Returns the list of recorded calls for assertions."""
    from src.backend.common import provider, providers
    from src.backend.common.providers import ProviderChoice, TaskClass

    providers.save_choice(TaskClass.INTERACTIVE, ProviderChoice(preset=preset))
    calls: list[dict[str, object]] = []

    def _reply(task, endpoint, prompt, *, images=None, response_schema=None):
        calls.append(
            {"task": task, "endpoint": endpoint, "prompt": prompt, "images": images}
        )
        if reply is None:
            raise provider.ProviderUnavailableError("stubbed failure")
        return reply, 10, 5

    monkeypatch.setattr(provider, "_call_provider", _reply)
    return calls
