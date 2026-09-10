from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from src.backend.api.deps import current_user, require_verified_email
from src.backend.common import budget, sources_repo, storage
from src.backend.common import tiers as tier_config
from src.backend.common.schemas.base import SourceStatus, SourceType
from src.backend.common.schemas.identity import UserAccount

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
    return SourceUploadView.model_validate(result, from_attributes=True)
