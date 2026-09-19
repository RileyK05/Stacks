from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from src.backend.api.deps import current_user, require_verified_email
from src.backend.common import budget, courses_repo, sources_repo, storage
from src.backend.common import tiers as tier_config
from src.backend.common.db import connection
from src.backend.common.schemas.base import SourceStatus, SourceType
from src.backend.common.schemas.identity import UserAccount
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
    """The owner-facing row for the source list (the file browser)."""

    source_id: UUID
    filename: str
    mime_type: str
    source_type: SourceType
    status: SourceStatus
    error_message: str | None
    size_bytes: int | None
    created_at: datetime


@router.post(
    "/{course_id}/sources",
    response_model=SourceUploadView,
    status_code=status.HTTP_201_CREATED,
)
def upload_source(
    course_id: UUID,
    user: Annotated[UserAccount, Depends(current_user)],
    file: Annotated[UploadFile, File()],
    source_type: Annotated[SourceType, Form()],
) -> SourceUploadView:
    require_verified_email(user)
    budget.verify_tier(user.user_id, user.tier)
    declared = file.content_type or "application/octet-stream"
    if declared not in INGESTABLE_MIME_TYPES:
        # Reject BEFORE storage + quota charge: an un-ingestable upload
        # used to consume storage the user can only reclaim by deleting
        # the whole course (the quota ratchet). The sniffing note: this
        # trusts the declared type for dispatch, but the extract stage's
        # decode + dispatch still fail loudly on a mislabeled body.
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"unsupported file type: {declared}",
        )
    policy = tier_config.load_tier_policies().policy_for(user.tier)
    try:
        result = sources_repo.upload_source(
            course_id,
            user.user_id,
            user.tier,
            policy,
            filename=file.filename or "upload",
            mime_type=file.content_type or "application/octet-stream",
            source_type=source_type,
            stream=file.file,
        )
    except sources_repo.UnknownOwnedCourseError as err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found") from err
    except sources_repo.DuplicateSourceError as err:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"source content already uploaded as {err.source_id}",
        ) from err
    except storage.EmptyUploadError as err:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(err)) from err
    except storage.RawUploadLimitExceededError as err:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, str(err)
        ) from err
    except budget.StorageLimitExceededError as err:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(err)) from err
    finally:
        file.file.close()
    # Wake the ingestion worker so upload-to-ingestion latency is
    # seconds, not the poll interval (worker.wakeup is a no-op when no
    # loop is running).
    worker_module.wakeup()
    return SourceUploadView.model_validate(result, from_attributes=True)


@router.get("/{course_id}/sources", response_model=list[SourceView])
def list_sources(
    course_id: UUID,
    user: Annotated[UserAccount, Depends(current_user)],
) -> list[SourceView]:
    """The course's files with their live status (review catch #6: the
    surface was write-only — a user never learned their upload failed).
    Owner-only: failure reasons are owner-facing operational data, and
    the central-area file browser is the owner's view."""
    course = courses_repo.get_course(course_id)
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")
    if course.owner_user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")
    return [
        SourceView(
            source_id=source.source_id,
            filename=source.filename,
            mime_type=source.mime_type,
            source_type=source.source_type,
            status=source.status,
            error_message=source.error_message,
            size_bytes=source.size_bytes,
            created_at=source.created_at,
        )
        for source in sources_repo.list_sources(course_id)
    ]


@router.post("/{course_id}/sources/{source_id}/requeue")
def requeue_source(
    course_id: UUID,
    source_id: UUID,
    user: Annotated[UserAccount, Depends(current_user)],
) -> dict[str, str]:
    """The deliberate retry path for a failed source: failed → uploaded +
    re-enqueued (the worker's wakeup follows). 409 when the source is
    not in a failed state."""
    course = courses_repo.get_course(course_id)
    if course is None or course.owner_user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")
    with connection() as conn:
        requeued = sources_repo.requeue_failed(
            conn, source_id, course_id, user.user_id
        )
        conn.commit()
    if not requeued:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "source is not in a failed state"
        )
    worker_module.wakeup()
    return {"source_id": str(source_id), "status": "uploaded"}
