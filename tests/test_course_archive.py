"""`.course` export/import (common/course_archive.py, api/data.py)."""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from src.backend.common import course_archive, courses_repo
from src.backend.common.db import connection

NOTES = b"# Eigenvalues\n\nAn eigenvalue scales its eigenvector.\n" * 50
SLIDES = b"plain text notes about orthogonality\n" * 20


def _course_with_sources(client: TestClient) -> str:
    course_id: str = client.post(
        "/courses", json={"name": "Linear Algebra: Fall"}
    ).json()["course_id"]
    for filename, body, mime, kind in (
        ("notes.md", NOTES, "text/markdown", "notes"),
        ("week 2.txt", SLIDES, "text/plain", "slides"),
    ):
        response = client.post(
            f"/courses/{course_id}/sources",
            data={"source_type": kind},
            files={"file": (filename, body, mime)},
        )
        assert response.status_code == 201, response.text
    return course_id


def _import(client: TestClient, path: Path):
    with path.open("rb") as handle:
        return client.post(
            "/courses/import",
            files={"file": ("x.course", handle, "application/zip")},
        )


def _count(table: str) -> int:
    with connection() as conn:
        return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


def test_export_then_import_round_trips_the_files(client: TestClient) -> None:
    course_id = _course_with_sources(client)
    exported = client.post(f"/courses/{course_id}/export")
    assert exported.status_code == 200, exported.text
    view = exported.json()
    path = Path(view["path"])
    assert path.name == "Linear Algebra_ Fall.course"
    assert view["source_count"] == 2 and path.exists()

    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format"] == "course-assistant/course"
        names = [s["filename"] for s in manifest["sources"]]
        assert names == ["notes.md", "week 2.txt"]
        assert archive.read(manifest["sources"][0]["path"]) == NOTES

    again = client.post(f"/courses/{course_id}/export").json()
    assert Path(again["path"]).name == "Linear Algebra_ Fall (2).course"

    imported = _import(client, path)
    assert imported.status_code == 201, imported.text
    body = imported.json()
    assert body["imported"] == 2 and body["duplicates_skipped"] == 0
    new_id = body["course"]["course_id"]
    assert new_id != course_id and body["course"]["name"] == "Linear Algebra: Fall"
    sources = client.get(f"/courses/{new_id}/sources").json()
    assert sorted((s["filename"], s["source_type"]) for s in sources) == [
        ("notes.md", "notes"),
        ("week 2.txt", "slides"),
    ]
    with connection() as conn:
        queued = conn.execute(
            "SELECT COUNT(*) AS n FROM pending_ingestion WHERE course_id = ?",
            (new_id,),
        ).fetchone()["n"]
    assert queued == 2, "imported sources are re-derived by ingestion"


def test_export_unknown_course_is_404(client: TestClient) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.post(f"/courses/{missing}/export").status_code == 404


def _archive(tmp_path: Path, manifest: object, files: dict[str, bytes]) -> Path:
    path = tmp_path / "crafted.course"
    with zipfile.ZipFile(path, "w") as archive:
        if manifest is not None:
            archive.writestr("manifest.json", json.dumps(manifest))
        for name, data in files.items():
            archive.writestr(name, data)
    return path


def _manifest(**source_overrides: object) -> dict[str, object]:
    source: dict[str, object] = {
        "path": "sources/0001-notes.md",
        "filename": "notes.md",
        "mime_type": "text/markdown",
        "source_type": "notes",
        "sha256": hashlib.sha256(NOTES).hexdigest(),
    }
    source.update(source_overrides)
    return {
        "format": "course-assistant/course",
        "format_version": 1,
        "name": "Crafted",
        "exported_at": "2026-09-25T00:00:00+00:00",
        "sources": [source],
    }


GOOD_FILES = {"sources/0001-notes.md": NOTES}


@pytest.mark.parametrize(
    ("manifest", "files", "reason"),
    [
        (None, GOOD_FILES, "no manifest"),
        (_manifest(), {}, "missing file"),
        (
            _manifest(path="../evil.md"),
            {"../evil.md": NOTES},
            "unexpected file location",
        ),
        (_manifest(mime_type="application/x-msdownload"), GOOD_FILES, "unsupported"),
        (_manifest(sha256="0" * 64), GOOD_FILES, "checksum"),
        ({**_manifest(), "format_version": 9}, GOOD_FILES, "format version 9"),
    ],
)
def test_import_rejects_bad_archives_and_leaves_nothing(
    client: TestClient,
    tmp_path: Path,
    manifest: object,
    files: dict[str, bytes],
    reason: str,
) -> None:
    response = _import(client, _archive(tmp_path, manifest, files))
    assert response.status_code == 422, response.text
    assert reason in response.json()["detail"]
    assert _count("courses") == 0
    assert _count("sources") == 0
    assert _count("course_memories") == 0, "an aborted import leaves no keepsake"


def test_import_rejects_non_zip(client: TestClient, tmp_path: Path) -> None:
    path = tmp_path / "not.course"
    path.write_bytes(b"hello")
    response = _import(client, path)
    assert response.status_code == 422
    assert "unreadable zip" in response.json()["detail"]


def test_import_enforces_the_size_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = course_archive.load_lifecycle_policy()
    tight = real.model_copy(update={"max_import_bytes": len(NOTES) - 1})
    monkeypatch.setattr(course_archive, "load_lifecycle_policy", lambda: tight)
    path = _archive(tmp_path, _manifest(), GOOD_FILES)
    with pytest.raises(course_archive.InvalidArchiveError, match="import limit"):
        course_archive.import_course(path)
    assert courses_repo.list_courses() == []


def test_duplicate_files_inside_an_archive_are_skipped(tmp_path: Path) -> None:
    manifest = _manifest()
    sources = manifest["sources"]
    assert isinstance(sources, list)
    sources.append(
        {**sources[0], "path": "sources/0002-copy.md", "filename": "copy.md"}
    )
    path = _archive(tmp_path, manifest, {**GOOD_FILES, "sources/0002-copy.md": NOTES})
    result = course_archive.import_course(path)
    assert (result.imported, result.duplicates_skipped) == (1, 1)


def test_data_folder_and_reveal_are_scoped(client: TestClient, tmp_path: Path) -> None:
    view = client.get("/settings/data").json()
    assert view["database_bytes"] > 0
    assert view["export_dir"] == str(tmp_path / "exports")
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("x")
    response = client.post("/settings/reveal", json={"path": str(outside)})
    assert response.status_code == 404
