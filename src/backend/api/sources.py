from __future__ import annotations

import io
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from src.backend.common import courses_repo, sources_repo, storage
from src.backend.common.db import connection
from src.backend.common.lifecycle_config import load_lifecycle_policy
from src.backend.common.queries import get
from src.backend.common.schemas.base import SourceStatus, SourceType
from src.backend.ingest import worker as worker_module
from src.backend.ingest.extract import INGESTABLE_MIME_TYPES

router = APIRouter(prefix="/courses", tags=["sources"])


class SourceUploadView(BaseModel):
    source_id: UUID
    course_id: UUID
    filename: str
    mime_type: str
    source_type: SourceType
    status: SourceStatus
    file_hash: str
    raw_size_bytes: int
    stored_size_bytes: int
    stored_encoding: str


class SourceView(BaseModel):
    """One row of the course's file browser."""

    source_id: UUID
    filename: str
    mime_type: str
    source_type: SourceType
    status: SourceStatus
    error_message: str | None
    size_bytes: int | None
    created_at: datetime


class PassageView(BaseModel):
    text: str
    locator_type: str
    label: str
    description: str | None


def _require_course(course_id: UUID) -> None:
    if courses_repo.get_course(course_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")


@router.post(
    "/{course_id}/sources",
    response_model=SourceUploadView,
    status_code=status.HTTP_201_CREATED,
)
def upload_source(
    course_id: UUID,
    file: Annotated[UploadFile, File()],
    source_type: Annotated[SourceType, Form()],
) -> SourceUploadView:
    declared = file.content_type or "application/octet-stream"
    if declared not in INGESTABLE_MIME_TYPES:
        # Reject BEFORE storage: an un-ingestable upload would otherwise
        # take disk space the user can only reclaim by deleting it.
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"unsupported file type: {declared}",
        )
    try:
        result = sources_repo.upload_source(
            course_id,
            filename=file.filename or "upload",
            mime_type=declared,
            source_type=source_type,
            stream=file.file,
        )
    except sources_repo.UnknownCourseError as err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found") from err
    except sources_repo.DuplicateSourceError as err:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"source content already uploaded as {err.source_id}",
        ) from err
    except storage.EmptyUploadError as err:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(err)) from err
    except storage.RawUploadLimitExceededError as err:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(err)) from err
    finally:
        file.file.close()
    # Wake the ingestion worker so upload-to-ingestion latency is seconds,
    # not the poll interval.
    worker_module.wakeup()
    return SourceUploadView.model_validate(result, from_attributes=True)


@router.get("/{course_id}/sources", response_model=list[SourceView])
def list_sources(course_id: UUID) -> list[SourceView]:
    """The course's files with their live status, including why a failed
    one failed (review catch #6: a failed upload must never be silent)."""
    _require_course(course_id)
    return [
        SourceView.model_validate(source, from_attributes=True)
        for source in sources_repo.list_sources(course_id)
    ]


@router.get("/{course_id}/sources/{source_id}/content")
def source_content(course_id: UUID, source_id: UUID) -> Response:
    """Original source bytes for the in-app viewer, scoped to this course."""
    _require_course(course_id)
    with connection() as conn:
        row = conn.execute(
            get("sources", "viewer_source"),
            {"course_id": course_id, "source_id": source_id},
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "source not found")
    data = storage.read_stored(
        course_id,
        source_id,
        row["stored_encoding"],
        max_decompressed_bytes=load_lifecycle_policy().max_decompressed_bytes,
    )
    return Response(
        content=data,
        media_type=row["mime_type"],
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/{course_id}/sources/{source_id}/pages/{page_number}")
def source_pdf_page(course_id: UUID, source_id: UUID, page_number: int) -> Response:
    """Render one original PDF page for the cited-passage viewer."""
    import pypdfium2 as pdfium

    _require_course(course_id)
    with connection() as conn:
        row = conn.execute(
            get("sources", "viewer_source"),
            {"course_id": course_id, "source_id": source_id},
        ).fetchone()
    if row is None or row["mime_type"] != "application/pdf":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PDF source not found")
    raw = storage.read_stored(
        course_id,
        source_id,
        row["stored_encoding"],
        max_decompressed_bytes=load_lifecycle_policy().max_decompressed_bytes,
    )
    pdf = pdfium.PdfDocument(io.BytesIO(raw))
    try:
        if page_number < 1 or page_number > len(pdf):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "page not found")
        page = pdf[page_number - 1]
        try:
            width, height = page.get_size()
            scale = min(1.5, 4096 / max(width, 1), 4096 / max(height, 1))
            image = page.render(scale=scale).to_pil()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
        finally:
            page.close()
        return Response(
            content=buffer.getvalue(),
            media_type="image/png",
            headers={
                "X-Page-Count": str(len(pdf)),
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "private, no-store",
            },
        )
    finally:
        pdf.close()


@router.get(
    "/{course_id}/sources/{source_id}/chunks/{chunk_id}",
    response_model=PassageView,
)
def source_passage(course_id: UUID, source_id: UUID, chunk_id: UUID) -> PassageView:
    _require_course(course_id)
    with connection() as conn:
        row = conn.execute(
            get("sources", "viewer_passage"),
            {"course_id": course_id, "source_id": source_id, "chunk_id": chunk_id},
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "passage not found")
    return PassageView.model_validate(row)


@router.post("/{course_id}/sources/{source_id}/requeue")
def requeue_source(course_id: UUID, source_id: UUID) -> dict[str, str]:
    """Retry a failed source: failed → uploaded + re-enqueued. 409 when the
    source is not in a failed state."""
    _require_course(course_id)
    with connection() as conn:
        requeued = sources_repo.requeue_failed(conn, source_id, course_id)
        conn.commit()
    if not requeued:
        raise HTTPException(status.HTTP_409_CONFLICT, "source is not in a failed state")
    worker_module.wakeup()
    return {"source_id": str(source_id), "status": "uploaded"}


@router.post("/{course_id}/sources/{source_id}/reindex")
def reindex_source(course_id: UUID, source_id: UUID) -> dict[str, str]:
    _require_course(course_id)
    if not sources_repo.reindex_source(course_id, source_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "source is not indexed or does not exist"
        )
    worker_module.wakeup()
    return {"source_id": str(source_id), "status": "uploaded"}


@router.delete(
    "/{course_id}/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_source(course_id: UUID, source_id: UUID) -> None:
    """Remove one file and everything derived from it (chunks,
    embeddings, run history). Immediate — sources have no trash; the
    course does."""
    _require_course(course_id)
    if not sources_repo.delete_source(course_id, source_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "source not found")
