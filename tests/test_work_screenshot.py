from __future__ import annotations

import io
from uuid import uuid4

import pytest
from PIL import Image
from src.backend.common import work_repo
from src.backend.common.db import connection
from src.backend.common.schemas.work import DocumentUpdate
from src.backend.office_reader import work_screenshot
from src.backend.office_reader.models import OCR, DocumentRead, TextUnit
from src.backend.office_reader.screens import OcrUnavailableError
from tests.factories import make_course


def image_bytes(image_format: str, *, size: tuple[int, int] = (12, 8)) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", size, color=(24, 70, 130)).save(stream, format=image_format)
    return stream.getvalue()


def make_work(client):
    course_id = make_course("Screenshot work").course_id
    root = f"/companion/courses/{course_id}/work"
    created = client.post(root, json={"title": "Lecture review", "purpose": "paper"})
    assert created.status_code == 200, created.text
    session = created.json()
    path = f"{root}/{session['session_id']}"
    connected = client.put(
        path + "/document",
        json={
            "expected_revision": 0,
            "title": "Existing notes",
            "text": "Saved text remains until the screenshot succeeds.",
            "coverage": "document",
        },
    )
    assert connected.status_code == 200, connected.text
    return course_id, path, connected.json()


def upload_screenshot(client, path, payload: bytes, *, expected_revision: int = 1):
    return client.post(
        path + "/screenshot",
        data={"expected_revision": str(expected_revision)},
        files={"file": ("capture.png", payload, "application/octet-stream")},
    )


def assert_no_learning_or_source_writes(course_id) -> None:
    with connection() as conn:
        for table in (
            "learning_observations",
            "learning_experiments",
            "core_method_observations",
            "learning_teaching_events",
            "practice_runs",
            "source_indexes",
            "passage_windows",
        ):
            count = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            assert count == 0
        sources = conn.execute(
            "SELECT COUNT(*) AS n FROM sources WHERE course_id = ?", (course_id,)
        ).fetchone()["n"]
        assert sources == 0


@pytest.mark.parametrize("image_format", ["PNG", "JPEG"])
def test_screenshot_upload_uses_only_explicit_image_bytes_and_is_partial(
    client, monkeypatch: pytest.MonkeyPatch, image_format: str
) -> None:
    course_id, path, before = make_work(client)
    payload = image_bytes(image_format)
    seen: list[tuple[list[bytes], str]] = []

    def transcribe(images, *, host="", course_id=None):
        seen.append((list(images), host))
        return DocumentRead(
            method=OCR,
            host=host,
            units=(TextUnit(label="image 1", text="Transcribed screenshot text."),),
        )

    monkeypatch.setattr(work_screenshot, "read_screens", transcribe)

    response = upload_screenshot(client, path, payload)

    assert response.status_code == 200, response.text
    document = response.json()["document"]
    assert document["text"] == "Transcribed screenshot text."
    assert document["origin"] == "screen"
    assert document["coverage"] == "partial"
    assert document["warnings"] == [
        "Only the uploaded screenshot was read; off-screen content is missing.",
        "Image transcription may misread text, formulas, or layout. Inspect it.",
    ]
    assert seen == [([payload], "Uploaded screenshot")]
    assert response.json()["revision"] == before["revision"] + 1
    assert_no_learning_or_source_writes(course_id)


def test_invalid_image_bytes_fail_before_ocr_and_preserve_snapshot(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    _course_id, path, before = make_work(client)
    calls: list[object] = []
    monkeypatch.setattr(
        work_screenshot,
        "read_screens",
        lambda *args, **kwargs: calls.append(args),
    )

    response = upload_screenshot(client, path, b"not an image")

    assert response.status_code == 422
    assert "not a readable PNG or JPEG" in response.text
    assert calls == []
    saved = client.get(path).json()
    assert saved["revision"] == before["revision"]
    assert saved["document"] == before["document"]


def test_screenshot_upload_byte_limit_comes_from_policy_model_copy(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    _course_id, path, before = make_work(client)
    policy = work_screenshot.load_companion_policy().model_copy(
        update={"max_upload_bytes": 12}
    )
    monkeypatch.setattr(work_screenshot, "load_companion_policy", lambda: policy)
    calls: list[object] = []
    monkeypatch.setattr(
        work_screenshot,
        "read_screens",
        lambda *args, **kwargs: calls.append(args),
    )

    response = upload_screenshot(client, path, b"x" * 13)

    assert response.status_code == 422
    assert calls == []
    assert client.get(path).json()["document"] == before["document"]


def test_screenshot_dimension_limit_fails_before_ocr(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    _course_id, path, before = make_work(client)
    policy = work_screenshot.load_companion_policy().model_copy(
        update={"max_screenshot_pixels": 100}
    )
    monkeypatch.setattr(work_screenshot, "load_companion_policy", lambda: policy)
    calls: list[object] = []
    monkeypatch.setattr(
        work_screenshot,
        "read_screens",
        lambda *args, **kwargs: calls.append(args),
    )

    response = upload_screenshot(client, path, image_bytes("PNG", size=(11, 10)))

    assert response.status_code == 422
    assert "image dimension limit" in response.text
    assert calls == []
    assert client.get(path).json()["document"] == before["document"]


def test_blank_ocr_text_fails_without_replacing_snapshot(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    _course_id, path, before = make_work(client)
    monkeypatch.setattr(
        work_screenshot,
        "read_screens",
        lambda images, **kwargs: DocumentRead(
            method=OCR,
            host="Uploaded screenshot",
            units=(TextUnit(label="image 1", text="  \n  "),),
        ),
    )

    response = upload_screenshot(client, path, image_bytes("PNG"))

    assert response.status_code == 422
    assert "No readable text" in response.text
    saved = client.get(path).json()
    assert saved["revision"] == before["revision"]
    assert saved["document"] == before["document"]


def test_unavailable_ocr_returns_503_and_keeps_saved_snapshot(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    _course_id, path, before = make_work(client)

    def unavailable(images, **kwargs):
        raise OcrUnavailableError("OCR model unavailable")

    monkeypatch.setattr(work_screenshot, "read_screens", unavailable)

    response = upload_screenshot(client, path, image_bytes("JPEG"))

    assert response.status_code == 503
    assert "OCR model unavailable" in response.text
    saved = client.get(path).json()
    assert saved["revision"] == before["revision"]
    assert saved["document"] == before["document"]


def test_stale_expected_revision_fails_before_ocr(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    _course_id, path, before = make_work(client)
    calls: list[object] = []
    monkeypatch.setattr(
        work_screenshot,
        "read_screens",
        lambda *args, **kwargs: calls.append(args),
    )

    response = upload_screenshot(client, path, image_bytes("PNG"), expected_revision=0)

    assert response.status_code == 409
    assert calls == []
    saved = client.get(path).json()
    assert saved["revision"] == before["revision"]
    assert saved["document"] == before["document"]


def test_document_changed_during_ocr_rejects_capture_without_overwriting(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id, path, before = make_work(client)

    def transcribe(images, **kwargs):
        with connection() as other_conn:
            changed = work_repo.update_document(
                other_conn,
                course_id,
                before["session_id"],
                DocumentUpdate(
                    expected_revision=1,
                    title="Changed during OCR",
                    text="Newer user document state.",
                    coverage="document",
                ),
            )
            other_conn.commit()
        assert changed.revision == 2
        return DocumentRead(
            method=OCR,
            host="Uploaded screenshot",
            units=(TextUnit(label="image 1", text="Late screenshot transcript."),),
        )

    monkeypatch.setattr(work_screenshot, "read_screens", transcribe)

    response = upload_screenshot(client, path, image_bytes("PNG"))

    assert response.status_code == 409
    saved = client.get(path).json()
    assert saved["revision"] == 2
    assert saved["document"]["title"] == "Changed during OCR"
    assert saved["document"]["text"] == "Newer user document state."


def test_missing_course_and_work_session_return_404_without_ocr(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        work_screenshot,
        "read_screens",
        lambda *args, **kwargs: calls.append(args),
    )
    absent_course = uuid4()
    absent_session = uuid4()

    missing_course = upload_screenshot(
        client,
        f"/companion/courses/{absent_course}/work/{absent_session}",
        image_bytes("PNG"),
    )
    assert missing_course.status_code == 404

    course_id = make_course("Existing course").course_id
    missing_work = upload_screenshot(
        client,
        f"/companion/courses/{course_id}/work/{absent_session}",
        image_bytes("PNG"),
    )
    assert missing_work.status_code == 404
    assert calls == []
