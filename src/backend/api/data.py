"""Your data: `.course` export/import and the data folder (plan §12).

Export writes to the user's Downloads folder rather than streaming a
download: the desktop webview cannot attach the per-launch token to a
plain link, and a file on disk plus "Show in folder" works the same in
every shell.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from src.backend.api.courses import CourseView
from src.backend.common import course_archive, courses_repo, storage
from src.backend.common.config import get_settings
from src.backend.common.lifecycle_config import load_lifecycle_policy
from src.backend.ingest import worker as worker_module

router = APIRouter(tags=["data"])


class ExportView(BaseModel):
    path: str
    filename: str
    source_count: int
    size_bytes: int


class ImportView(BaseModel):
    course: CourseView
    imported: int
    duplicates_skipped: int


class DataFolderView(BaseModel):
    data_dir: str
    export_dir: str
    database_bytes: int
    uploads_bytes: int
    models_bytes: int
    runtime_bytes: int


class RevealRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str


def _tree_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                continue
    return total


@router.post("/courses/{course_id}/export", response_model=ExportView)
def export_course(course_id: UUID) -> ExportView:
    try:
        result = course_archive.export_course(
            course_id, Path(get_settings().export_dir)
        )
    except LookupError as err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found") from err
    return ExportView(
        path=str(result.path),
        filename=result.path.name,
        source_count=result.source_count,
        size_bytes=result.size_bytes,
    )


@router.post(
    "/courses/import",
    response_model=ImportView,
    status_code=status.HTTP_201_CREATED,
)
def import_course(file: Annotated[UploadFile, File()]) -> ImportView:
    try:
        temp_path, _, _ = storage.stream_to_temp(
            file.file, max_bytes=load_lifecycle_policy().max_import_bytes
        )
    except storage.RawUploadLimitExceededError as err:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(err)) from err
    except storage.EmptyUploadError as err:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "the file is empty") from err
    finally:
        file.file.close()
    try:
        result = course_archive.import_course(temp_path)
    except course_archive.InvalidArchiveError as err:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(err)) from err
    finally:
        storage.discard_temp(temp_path)
    worker_module.wakeup()
    stats = courses_repo.source_stats([result.course.course_id])
    source_count, stored_bytes = stats.get(result.course.course_id, (0, 0))
    return ImportView(
        course=CourseView(
            course_id=result.course.course_id,
            name=result.course.name,
            created_at=result.course.created_at,
            source_count=source_count,
            stored_bytes=stored_bytes,
        ),
        imported=result.imported,
        duplicates_skipped=result.duplicates_skipped,
    )


@router.get("/settings/data", response_model=DataFolderView)
def data_folder() -> DataFolderView:
    settings = get_settings()
    data_dir = Path(settings.data_dir)
    database = Path(settings.database_path)
    database_bytes = sum(
        path.stat().st_size
        for path in (database, database.with_name(database.name + "-wal"))
        if path.exists()
    )
    return DataFolderView(
        data_dir=str(data_dir),
        export_dir=settings.export_dir,
        database_bytes=database_bytes,
        uploads_bytes=_tree_bytes(Path(settings.storage_root)),
        models_bytes=_tree_bytes(data_dir / "models"),
        runtime_bytes=_tree_bytes(data_dir / "runtime"),
    )


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


@router.post("/settings/reveal", status_code=status.HTTP_204_NO_CONTENT)
def reveal(payload: RevealRequest) -> None:
    """Show a file or folder in the OS file manager. Limited to the data
    folder and the export folder — this is not a general file opener."""
    settings = get_settings()
    target = Path(payload.path)
    roots = [Path(settings.data_dir), Path(settings.export_dir)]
    if not target.exists() or not any(_is_within(target, root) for root in roots):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "nothing to show there")
    _open_in_file_manager(target.resolve())


def _open_in_file_manager(target: Path) -> None:  # pragma: no cover - opens a window
    if sys.platform == "win32":
        if target.is_file():
            subprocess.Popen(["explorer", f"/select,{target}"])
        else:
            os.startfile(target)  # noqa: S606
    elif sys.platform == "darwin":
        flags = ["-R"] if target.is_file() else []
        subprocess.Popen(["open", *flags, str(target)])
    else:
        subprocess.Popen(
            ["xdg-open", str(target if target.is_dir() else target.parent)]
        )
