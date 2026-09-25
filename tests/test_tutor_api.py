"""Tutor answer endpoint tests.

Covers what makes the endpoint trustworthy: strict refusal when
retrieval finds nothing (Fork B lean), an honest 503 while no model is
configured, a 402 once the user's cloud budget is spent, and the happy
path where the answer, its citations, and the retrieval trace agree.
"""

import pytest
from fastapi.testclient import TestClient
from src.backend.common import usage_repo
from src.backend.common.db import connection
from tests.conftest import configure_test_provider
from tests.factories import add_chunk

GROUNDED_ANSWER = "linearity preserves structure [1]."


def _course(client: TestClient, name: str = "Tutor Course") -> str:
    created = client.post("/courses", json={"name": name})
    assert created.status_code == 201, created.text
    return created.json()["course_id"]


def _seeded_course(client: TestClient) -> str:
    course_id = _course(client)
    add_chunk(
        course_id,
        "linearity means preserving vector addition and scalar multiplication"
        " under transformation.",
    )
    return course_id


def _ask(client: TestClient, course_id: str, question: str = "what is linearity"):
    return client.post(f"/courses/{course_id}/ask", json={"question": question})


def _trace_count(course_id: str) -> int:
    with connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM retrieval_traces WHERE course_id = ?",
            (course_id,),
        ).fetchone()["n"]


def test_ask_unknown_or_trashed_course_is_404(client: TestClient) -> None:
    course_id = _seeded_course(client)
    client.delete(f"/courses/{course_id}")
    assert _ask(client, course_id).status_code == 404


def test_ask_refuses_when_nothing_found(client: TestClient) -> None:
    """Fork B lean, enforced: empty retrieval is a refusal (404 with the
    reason), never an ungrounded answer."""
    response = _ask(client, _course(client))
    assert response.status_code == 404
    assert "nothing" in response.json()["detail"].lower()


def test_ask_is_honest_about_missing_provider(client: TestClient) -> None:
    """No model configured: 503 with the real reason, and no trace for an
    answer that never happened."""
    course_id = _seeded_course(client)
    response = _ask(client, course_id)
    assert response.status_code == 503, response.text
    assert "settings" in response.json()["detail"].lower()
    assert _trace_count(course_id) == 0


def test_ask_is_blocked_by_spent_cloud_budget(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    _memory_keyring: dict[str, str],
) -> None:
    course_id = _seeded_course(client)
    configure_test_provider(monkeypatch, GROUNDED_ANSWER, preset="openrouter")
    _memory_keyring["openrouter"] = "sk-or-test"
    usage_repo.set_monthly_budget(10)
    usage_repo.record(
        task="tutor_answer",
        provider="openrouter",
        model="m",
        input_tokens=10,
        output_tokens=0,
    )
    response = _ask(client, course_id)
    assert response.status_code == 402
    assert "budget" in response.json()["detail"]
    assert _trace_count(course_id) == 0


def test_ask_happy_path_stubbed_provider(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retrieval finds the chunk, the answer comes back with citations,
    and the trace records the same chunk set."""
    course_id = _seeded_course(client)
    calls = configure_test_provider(monkeypatch, GROUNDED_ANSWER)
    response = _ask(client, course_id)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "[1]" in payload["text"]
    assert len(payload["chunk_ids"]) == 1
    assert payload["workspace"] == [] and payload["withheld"] == []
    assert payload["model"] == "minicpm5-2b"
    assert payload["fell_back_to_local"] is False
    assert "linearity means preserving" in calls[0]["prompt"]

    with connection() as conn:
        row = conn.execute(
            "SELECT retrieved_chunk_ids FROM retrieval_traces WHERE trace_id = ?",
            (payload["trace_id"],),
        ).fetchone()
    assert row["retrieved_chunk_ids"]["chunk_ids"] == payload["chunk_ids"], (
        "the trace and the answer must cite the same evidence"
    )


def test_ask_a_bigger_model(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    _memory_keyring: dict[str, str],
) -> None:
    """The per-answer button: 503 until a bigger model is chosen, then the
    same question is answered by that endpoint."""
    from src.backend.common import providers
    from src.backend.common.providers import ProviderChoice, TaskClass

    course_id = _seeded_course(client)
    calls = configure_test_provider(monkeypatch, GROUNDED_ANSWER)
    body = {"question": "what is linearity", "bigger_model": True}
    refused = client.post(f"/courses/{course_id}/ask", json=body)
    assert refused.status_code == 503
    assert "bigger model" in refused.json()["detail"]

    _memory_keyring["openai"] = "sk-test"
    providers.save_choice(
        TaskClass.BIGGER, ProviderChoice(preset="openai", model="big-model")
    )
    response = client.post(f"/courses/{course_id}/ask", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["model"] == "big-model"
    assert [c["endpoint"].name for c in calls] == ["openai"]


def test_ask_lifts_cited_workspace_items_and_withholds_uncited(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Workspace blocks leave the chat body; a cited quiz is returned
    structured, an uncited document is withheld with its reason
    (decision 009 hard gate at the endpoint)."""
    course_id = _seeded_course(client)
    answer = (
        "Linearity preserves structure [1].\n\n"
        "```workspace\n"
        '{"type": "quiz", "questions": [{"prompt": "Preserved?", "options":'
        ' ["Sums", "Nothing"], "answer": 0, "sources": [1]}]}\n'
        "```\n"
        "```workspace\n"
        '{"type": "document", "content": "Uncited notes", "sources": [5]}\n'
        "```"
    )
    configure_test_provider(monkeypatch, answer)
    payload = _ask(client, course_id).json()
    assert payload["text"] == "Linearity preserves structure [1]."
    assert [item["type"] for item in payload["workspace"]] == ["quiz"]
    assert payload["workspace"][0]["questions"][0]["sources"] == [1]
    assert len(payload["withheld"]) == 1
    assert "document cites [5]" in payload["withheld"][0]


def test_trace_citations_happy_path(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chunk ids resolve into readable evidence: text + locator label +
    filename (golden rule 1)."""
    course_id = _seeded_course(client)
    configure_test_provider(monkeypatch, GROUNDED_ANSWER)
    trace_id = _ask(client, course_id).json()["trace_id"]
    response = client.get(f"/courses/{course_id}/traces/{trace_id}/citations")
    assert response.status_code == 200, response.text
    [citation] = response.json()
    assert citation["filename"] == "notes.txt"
    assert (citation["label"], citation["locator_type"]) == ("page 1", "page")
    assert "linearity" in citation["text"].lower()
    assert citation["chunk_index"] == 0


def test_trace_citations_rejects_foreign_trace(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A trace id from another course 404s — the WHERE pins trace to
    course, so guessing ids reads nothing."""
    course_id = _seeded_course(client)
    configure_test_provider(monkeypatch, GROUNDED_ANSWER)
    trace_id = _ask(client, course_id).json()["trace_id"]
    other = _course(client, "Other")
    response = client.get(f"/courses/{other}/traces/{trace_id}/citations")
    assert response.status_code == 404
