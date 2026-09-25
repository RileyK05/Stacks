"""Answer cache (common/answer_cache.py, migration 002) through the API."""

import pytest
from fastapi.testclient import TestClient
from src.backend.common import answer_cache
from src.backend.common.db import connection
from tests.conftest import configure_test_provider
from tests.factories import add_chunk

ANSWER = "linearity preserves structure [1]."


def _course(client: TestClient) -> str:
    course_id: str = client.post("/courses", json={"name": "Cache"}).json()[
        "course_id"
    ]
    add_chunk(course_id, "linearity means preserving addition and scaling.")
    return course_id


def _ask(client: TestClient, course_id: str, question: str, **extra: object):
    response = client.post(
        f"/courses/{course_id}/ask", json={"question": question, **extra}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _rows() -> int:
    with connection() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM answer_cache").fetchone()["n"]


def test_normalised_question() -> None:
    assert answer_cache.normalise_question("  What is  Linearity?? ") == (
        "what is linearity"
    )


def test_same_question_is_answered_from_the_cache(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _course(client)
    calls = configure_test_provider(monkeypatch, ANSWER)
    first = _ask(client, course_id, "What is linearity?")
    second = _ask(client, course_id, "what is   linearity")
    assert len(calls) == 1, "the second ask must not call the model"
    assert (first["cached"], second["cached"]) == (False, True)
    assert second["text"] == first["text"]
    assert second["trace_id"] == first["trace_id"]
    assert second["chunk_ids"] == first["chunk_ids"]
    citations = client.get(
        f"/courses/{course_id}/traces/{second['trace_id']}/citations"
    )
    assert citations.status_code == 200 and len(citations.json()) == 1


def test_changed_material_or_model_misses(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    _memory_keyring: dict[str, str],
) -> None:
    from src.backend.common import providers
    from src.backend.common.providers import ProviderChoice, TaskClass

    course_id = _course(client)
    calls = configure_test_provider(monkeypatch, ANSWER)
    _ask(client, course_id, "What is linearity?")

    _memory_keyring["openai"] = "sk-test"
    providers.save_choice(
        TaskClass.BIGGER, ProviderChoice(preset="openai", model="big-model")
    )
    bigger = _ask(client, course_id, "What is linearity?", bigger_model=True)
    assert bigger["cached"] is False and len(calls) == 2

    add_chunk(course_id, "linearity also appears in chapter two.")
    after = _ask(client, course_id, "What is linearity?")
    assert after["cached"] is False and len(calls) == 3
    with connection() as conn:
        fingerprints = {
            row["fingerprint"]
            for row in conn.execute("SELECT fingerprint FROM answer_cache").fetchall()
        }
    assert len(fingerprints) == 1, "entries for the old material were dropped"


def test_workspace_requests_are_never_cached(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _course(client)
    configure_test_provider(monkeypatch, "Here you go.")
    _ask(client, course_id, "Quiz me on linearity")
    assert _rows() == 0


def test_deleting_the_course_removes_its_cache(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _course(client)
    configure_test_provider(monkeypatch, ANSWER)
    _ask(client, course_id, "What is linearity?")
    assert _rows() == 1
    client.delete(f"/courses/{course_id}")
    assert client.delete(f"/trash/{course_id}").status_code == 204
    assert _rows() == 0
