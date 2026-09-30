"""The Office add-in bridge: health, token, selection round trip, the
course-grounded assist path, and the redundant reader.

This is the plan-notebook.md "Bring Stacks to Office" backend contract:
the task pane sends a selection (or a read of the document) and the bridge
returns text, an answer with citations, or a merged read. It never
serializes an Office file.
"""

from __future__ import annotations

import base64
import io
import zipfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def office_client() -> TestClient:
    from src.backend.main import create_office

    return TestClient(create_office())


def test_health_reports_the_app_and_no_token_in_dev(office_client: TestClient) -> None:
    response = office_client.get("/health")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["app"]
    assert body["token_required"] is False


def test_selection_round_trip_echoes(office_client: TestClient) -> None:
    response = office_client.post(
        "/process-selection",
        json={"host": "powerpoint", "text": "Hello slides"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["text"] == "STACKS TEST: Hello slides"
    assert body["engine"] == "echo"


def test_empty_selection_returns_no_change(office_client: TestClient) -> None:
    response = office_client.post(
        "/process-selection",
        json={"host": "powerpoint", "text": ""},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["text"] is None
    assert body["message"]


def test_unknown_fields_are_rejected(office_client: TestClient) -> None:
    response = office_client.post(
        "/process-selection",
        json={"host": "powerpoint", "text": "x", "path": "C:/secret.docx"},
    )
    assert response.status_code == 422


def test_oversized_selection_is_rejected(office_client: TestClient) -> None:
    response = office_client.post(
        "/process-selection",
        json={"host": "powerpoint", "text": "x" * 100_001},
    )
    assert response.status_code == 422


def test_bridge_requires_its_own_token_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_OFFICE_TOKEN", "office-secret")
    from src.backend.main import create_office

    client = TestClient(create_office())
    assert client.get("/health").json()["token_required"] is True
    assert client.post(
        "/process-selection", json={"host": "powerpoint", "text": "x"}
    ).status_code == 401
    ok = client.post(
        "/process-selection",
        json={"host": "powerpoint", "text": "x"},
        headers={"X-Office-Token": "office-secret"},
    )
    assert ok.status_code == 200


def test_courses_mark_the_one_office_was_opened_from(
    office_client: TestClient,
) -> None:
    from src.backend.common import courses_repo, settings_repo
    from src.backend.office_addin.service import LAST_COURSE_SETTING

    first = courses_repo.create_course("Econ 301")
    second = courses_repo.create_course("Stats 200")
    settings_repo.put_setting(LAST_COURSE_SETTING, str(second.course_id))
    courses = {c["name"]: c for c in office_client.get("/courses").json()}
    assert courses["Stats 200"]["suggested"] is True
    assert courses["Econ 301"]["suggested"] is False
    assert first.course_id != second.course_id


@pytest.mark.parametrize("received", ["wrong-secret", "caf\u00e9-secret"])
def test_bridge_rejects_invalid_tokens_without_crashing(monkeypatch, received) -> None:
    from fastapi import HTTPException
    from src.backend.api.office import require_office_token

    monkeypatch.setenv("APP_OFFICE_TOKEN", "office-secret")
    with pytest.raises(HTTPException) as caught:
        require_office_token(received)
    assert caught.value.status_code == 401


def test_bridge_accepts_a_matching_unicode_token(monkeypatch) -> None:
    from src.backend.api.office import require_office_token

    monkeypatch.setenv("APP_OFFICE_TOKEN", "caf\u00e9-secret")
    require_office_token("caf\u00e9-secret")


# --- the merged reader --------------------------------------------------


def _docx(*paragraphs: str) -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>',
        )
    return buffer.getvalue()


def test_read_merges_a_scrape_with_a_package(office_client: TestClient) -> None:
    package = base64.b64encode(
        _docx("Linear maps preserve addition", "and scaling")
    ).decode()
    response = office_client.post(
        "/read",
        json={
            "host": "word",
            "kind": "word",
            "scrape": [
                {"label": "paragraph 1", "text": "Linear maps preserve addition"},
            ],
            "package_b64": package,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert sorted(body["methods"]) == ["package", "scrape"]
    assert "and scaling" in body["text"]
    by_method = {item["method"]: item for item in body["agreement"]}
    assert by_method["package"]["matched"] == 1
    assert by_method["package"]["unique"] == 1


def test_read_needs_at_least_one_method(office_client: TestClient) -> None:
    response = office_client.post("/read", json={"host": "word"})
    assert response.status_code == 422


def test_read_needs_a_kind_for_a_package(office_client: TestClient) -> None:
    package = base64.b64encode(_docx("x")).decode()
    response = office_client.post(
        "/read", json={"host": "word", "package_b64": package}
    )
    assert response.status_code == 422


def test_read_rejects_bad_base64(office_client: TestClient) -> None:
    response = office_client.post(
        "/read",
        json={"host": "word", "kind": "word", "package_b64": "not base64!!"},
    )
    assert response.status_code == 422


def test_read_reports_an_unreadable_package_as_a_warning(
    office_client: TestClient,
) -> None:
    package = base64.b64encode(b"not a zip").decode()
    response = office_client.post(
        "/read",
        json={
            "host": "word",
            "kind": "word",
            "scrape": [{"label": "selection", "text": "kept text"}],
            "package_b64": package,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["text"] == "kept text"
    assert any("package" in warning for warning in body["warnings"])


# --- the grounded assistant --------------------------------------------


def test_courses_lists_what_stacks_knows(
    office_client: TestClient, client: TestClient
) -> None:
    client.post("/courses", json={"name": "Linear algebra"})
    response = office_client.get("/courses")
    assert response.status_code == 200, response.text
    assert [course["name"] for course in response.json()] == ["Linear algebra"]


def test_assist_answers_with_citations(
    office_client: TestClient,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import UUID

    from tests.conftest import configure_test_provider
    from tests.factories import add_chunk

    course_id = client.post("/courses", json={"name": "Linear algebra"}).json()[
        "course_id"
    ]
    add_chunk(UUID(course_id), "Linearity means preserving addition and scaling.")
    configure_test_provider(monkeypatch, "A linear map preserves addition [1].")
    response = office_client.post(
        "/assist",
        json={
            "course_id": course_id,
            "action": "explain",
            "host": "powerpoint",
            "context": "Linearity means the map preserves addition and scaling.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"] == "explain"
    assert body["text"] == "A linear map preserves addition [1]."
    assert body["citations"][0]["number"] == 1
    assert (
        body["citations"][0]["text"]
        == "Linearity means preserving addition and scaling."
    )


def test_assist_refuses_graded_work(
    office_client: TestClient,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.conftest import configure_test_provider

    course_id = client.post("/courses", json={"name": "Linear algebra"}).json()[
        "course_id"
    ]
    configure_test_provider(monkeypatch, "no")
    response = office_client.post(
        "/assist",
        json={
            "course_id": course_id,
            "action": "explain",
            "host": "word",
            "context": "Write my essay about linear maps so I can submit it.",
        },
    )
    assert response.status_code == 422


def test_assist_unknown_course_is_404(office_client: TestClient) -> None:
    response = office_client.post(
        "/assist",
        json={
            "course_id": "00000000-0000-0000-0000-000000000000",
            "action": "explain",
            "host": "word",
            "context": "anything",
        },
    )
    assert response.status_code == 404


def test_assist_needs_its_own_token_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_OFFICE_TOKEN", "office-secret")
    from src.backend.main import create_office

    client = TestClient(create_office())
    assert client.get("/courses").status_code == 401
    assert (
        client.post(
            "/read", json={"host": "word", "scrape": [{"label": "x", "text": "y"}]}
        ).status_code
        == 401
    )
