"""Tutor answer endpoint tests (M1 close-out).

Covers the four behaviors that make the endpoint trustworthy:
enrollment gating (the retrieval-caller check), strict refusal when
retrieval finds nothing (Fork B lean), honest 503 while no provider is
configured, and the stubbed-provider happy path where the answer, its
citations, and the retrieval trace are consistent.
"""

import uuid as uuid_module
from uuid import uuid4

from fastapi.testclient import TestClient
from src.backend.common import provider
from src.backend.common.db import connection
from tests.conftest import verify_email

PASSWORD = "correct-horse-battery"


def _register(client: TestClient) -> tuple[str, str, dict]:
    email = f"{uuid4().hex}@test.invalid"
    response = client.post(
        "/auth/register",
        json={"name": "Tutor User", "email": email, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    token = login.json()["access_token"]
    verify_email(client, token)
    return token, email, response.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _verified_course(client: TestClient, token: str) -> str:
    created = client.post(
        "/courses", json={"name": "Tutor Course"}, headers=_headers(token)
    )
    assert created.status_code == 201, created.text
    return created.json()["course_id"]


def _seed_chunks(course_id: str, user_id) -> None:
    """Insert indexed chunks + locators directly so retrieval has
    material without a provider (the ingestion model stages fail closed;
    deterministic chunking of a text source is what the tutor tests
    need)."""
    locator_id = uuid_module.uuid4()
    chunk_id = uuid_module.uuid4()
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO course_objects (course_id, created_by_user_id,"
            " kind, content_type, content, access_scope)"
            " VALUES (%s, %s, 'source', 'text/plain', '{}', 'enrolled')"
            " RETURNING object_id",
            (course_id, user_id),
        )
        object_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO sources (source_id, object_id, uploaded_by_user_id,"
            " course_id, filename, mime_type, source_type, uri, status,"
            " file_hash, size_bytes, stored_encoding)"
            " VALUES (%s, %s, %s, %s, 'notes.txt', 'text/plain', 'notes',"
            " 'disk://x', 'indexed', %s, 10, 'identity')",
            (
                uuid_module.uuid4(),
                object_id,
                user_id,
                course_id,
                f"hash-{uuid_module.uuid4().hex}",
            ),
        )
        cur.execute(
            "INSERT INTO locators (locator_id, source_id, locator_type,"
            " start, end_value, label)"
            " VALUES (%s, (SELECT source_id FROM sources WHERE"
            " course_id = %s LIMIT 1), 'page', '0', '100', 'page 1')",
            (locator_id, course_id),
        )
        cur.execute(
            "INSERT INTO chunks (chunk_id, source_id, locator_id,"
            " chunk_index, text)"
            " VALUES (%s, (SELECT source_id FROM sources WHERE"
            " course_id = %s LIMIT 1), %s, 0,"
            " 'linearity means preserving vector addition and scalar"
            " multiplication under transformation.')",
            (chunk_id, course_id, locator_id),
        )
        conn.commit()


def test_ask_requires_enrollment(client: TestClient) -> None:
    """The retrieval-caller check the review demanded: a user with no
    relationship to the course gets 404 (not 403 — existence is not
    disclosed), even though the course exists."""
    token, _, _ = _register(client)
    stranger_token, _, _ = _register(client)
    course_id = _verified_course(client, token)
    response = client.post(
        f"/courses/{course_id}/ask",
        json={"question": "what is linearity?"},
        headers=_headers(stranger_token),
    )
    assert response.status_code == 404


def test_ask_refuses_when_nothing_found(client: TestClient) -> None:
    """Fork B lean, enforced: empty retrieval is a refusal (404 with the
    reason), never an ungrounded answer. True for an owned course with
    no material."""
    token, _, _ = _register(client)
    course_id = _verified_course(client, token)
    response = client.post(
        f"/courses/{course_id}/ask",
        json={"question": "what is linearity"},
        headers=_headers(token),
    )
    assert response.status_code == 404
    assert "nothing" in response.json()["detail"].lower()


def test_ask_is_honest_about_missing_provider(client: TestClient) -> None:
    """No provider picked yet: an answer attempt must 503 with the real
    reason, never pretend. The retrieval trace must NOT survive a failed
    generation (same transaction)."""
    token, _, body = _register(client)
    course_id = _verified_course(client, token)
    _seed_chunks(course_id, body["user_id"])
    response = client.post(
        f"/courses/{course_id}/ask",
        json={"question": "what is linearity"},
        headers=_headers(token),
    )
    assert response.status_code == 503, response.text
    assert "provider" in response.json()["detail"].lower()

    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM retrieval_traces WHERE course_id = %s",
            (course_id,),
        )
        assert cur.fetchone()[0] == 0, "failed generation must roll back the trace"


def test_ask_happy_path_stubbed_provider(client: TestClient, monkeypatch) -> None:
    """With the provider stubbed, the full flow works: retrieval finds
    the chunk, the answer comes back with citations, and the trace
    records the same chunk set."""
    token, _, body = _register(client)
    user_id = body["user_id"]
    course_id = _verified_course(client, token)
    _seed_chunks(course_id, user_id)
    monkeypatch.setattr(
        provider,
        "_call_provider",
        lambda task, model, prompt: ("linearity preserves structure [1].", 40, 12),
    )
    response = client.post(
        f"/courses/{course_id}/ask",
        json={"question": "what is linearity"},
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "[1]" in payload["text"]
    assert len(payload["chunk_ids"]) == 1
    assert payload["trace_id"]

    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT retrieved_chunk_ids FROM retrieval_traces"
            " WHERE trace_id = %s",
            (payload["trace_id"],),
        )
        row = cur.fetchone()
        assert row is not None, "trace must exist"
        trace_chunk_ids = row[0]["chunk_ids"]
        assert trace_chunk_ids == payload["chunk_ids"], (
            "the trace and the answer must cite the same evidence"
        )


def test_ask_unauthenticated_rejected(client: TestClient) -> None:
    token, _, _ = _register(client)
    course_id = _verified_course(client, token)
    response = client.post(
        f"/courses/{course_id}/ask", json={"question": "linearity"}
    )
    assert response.status_code == 401


def test_ask_learner_enrollment_granted(client: TestClient, monkeypatch) -> None:
    """An enrolled (non-owner) learner can ask: the caller check is
    ownership OR active enrollment."""
    owner_token, _, owner_body = _register(client)
    learner_token, _, learner_body = _register(client)
    # Public course so the learner can self-enroll
    created = client.post(
        "/courses",
        json={"name": "Public Tutor Course", "visibility": "public"},
        headers=_headers(owner_token),
    )
    assert created.status_code == 201, created.text
    course_id = created.json()["course_id"]
    enrolled = client.post(
        f"/courses/{course_id}/enroll", headers=_headers(learner_token)
    )
    assert enrolled.status_code == 201, enrolled.text
    _seed_chunks(course_id, owner_body["user_id"])
    monkeypatch.setattr(
        provider,
        "_call_provider",
        lambda task, model, prompt: ("linearity preserves structure [1].", 40, 12),
    )
    response = client.post(
        f"/courses/{course_id}/ask",
        json={"question": "what is linearity"},
        headers=_headers(learner_token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["chunk_ids"]

def test_trace_citations_happy_path(client: TestClient, monkeypatch) -> None:
    """The citations endpoint resolves an answer's chunk_ids into
    readable evidence: chunk text + locator label + filename (golden
    rule 1 — the UI can show what the tutor read and where it came
    from)."""
    token, _, body = _register(client)
    user_id = body["user_id"]
    course_id = _verified_course(client, token)
    _seed_chunks(course_id, user_id)
    monkeypatch.setattr(
        provider,
        "_call_provider",
        lambda task, model, prompt: ("linearity preserves structure [1].", 40, 12),
    )
    asked = client.post(
        f"/courses/{course_id}/ask",
        json={"question": "what is linearity"},
        headers=_headers(token),
    )
    assert asked.status_code == 200, asked.text
    trace_id = asked.json()["trace_id"]
    response = client.get(
        f"/courses/{course_id}/traces/{trace_id}/citations",
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    citations = response.json()
    assert len(citations) == 1
    citation = citations[0]
    assert citation["filename"] == "notes.txt"
    assert citation["label"] == "page 1"
    assert citation["locator_type"] == "page"
    assert "linearity" in citation["text"].lower()
    assert citation["chunk_index"] == 0


def test_trace_citations_rejects_foreign_trace(client: TestClient, monkeypatch) -> None:
    """A trace id from another course must not read as this course's
    citations — the WHERE pins trace to course; guessing ids 404s."""
    token, _, body = _register(client)
    user_id = body["user_id"]
    course_id = _verified_course(client, token)
    _seed_chunks(course_id, user_id)
    monkeypatch.setattr(
        provider,
        "_call_provider",
        lambda task, model, prompt: ("linearity preserves structure [1].", 40, 12),
    )
    asked = client.post(
        f"/courses/{course_id}/ask",
        json={"question": "what is linearity"},
        headers=_headers(token),
    )
    trace_id = asked.json()["trace_id"]
    other = _verified_course(client, token)
    response = client.get(
        f"/courses/{other}/traces/{trace_id}/citations",
        headers=_headers(token),
    )
    assert response.status_code == 404


def test_trace_citations_requires_enrollment(client: TestClient, monkeypatch) -> None:
    """A stranger (not owner, not enrolled) gets 404 — existence not
    disclosed."""
    owner_token, _, owner_body = _register(client)
    owner_course = _verified_course(client, owner_token)
    _seed_chunks(owner_course, owner_body["user_id"])
    monkeypatch.setattr(
        provider,
        "_call_provider",
        lambda task, model, prompt: ("linearity preserves structure [1].", 40, 12),
    )
    asked = client.post(
        f"/courses/{owner_course}/ask",
        json={"question": "what is linearity"},
        headers=_headers(owner_token),
    )
    assert asked.status_code == 200, asked.text
    trace_id = asked.json()["trace_id"]
    stranger_token, _, _ = _register(client)
    response = client.get(
        f"/courses/{owner_course}/traces/{trace_id}/citations",
        headers=_headers(stranger_token),
    )
    assert response.status_code == 404
