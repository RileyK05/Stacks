from __future__ import annotations

import pytest
from src.backend.common import body_limits


@pytest.mark.parametrize("declared", [True, False])
def test_oversized_multipart_is_rejected_before_source_storage(
    client, monkeypatch, declared: bool
) -> None:
    monkeypatch.setattr(body_limits, "request_limit", lambda scope: 100)
    payload = (
        b'--boundary\r\nContent-Disposition: form-data; name="file"; '
        b'filename="notes.txt"\r\n\r\n' + b"x" * 1000 + b"\r\n--boundary--\r\n"
    )
    headers = {"Content-Type": "multipart/form-data; boundary=boundary"}
    if declared:
        headers["Content-Length"] = str(len(payload))
    response = client.post(
        "/courses/import",
        headers=headers,
        content=payload if declared else iter([payload]),
    )
    assert response.status_code == 413
    assert "upload limit" in response.json()["detail"]


def test_oversized_chunked_json_returns_413(client, monkeypatch) -> None:
    monkeypatch.setattr(body_limits, "request_limit", lambda scope: 10)
    response = client.post(
        "/courses",
        headers={"Content-Type": "application/json"},
        content=iter([b'{"name":"long name"}']),
    )
    assert response.status_code == 413
