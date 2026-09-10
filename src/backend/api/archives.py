from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from src.backend.api.deps import current_user
from src.backend.common import budget, course_archives_repo, courses_lifecycle
from src.backend.common import tiers as tier_config
from src.backend.common.schemas.identity import (
    ArchivedCourse,
    CourseMemory,
    UserAccount,
)

router = APIRouter(tags=["archives"])


class ArchiveCopyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)


class ArchiveCopyView(BaseModel):
    course_id: UUID
    name: str


@router.get("/course-archives", response_model=list[ArchivedCourse])
def list_course_archives(
    user: Annotated[UserAccount, Depends(current_user)],
) -> list[ArchivedCourse]:
    return course_archives_repo.list_archives(user.user_id)


@router.get("/course-memories", response_model=list[CourseMemory])
def list_course_memories(
    user: Annotated[UserAccount, Depends(current_user)],
) -> list[CourseMemory]:
    """The caller's own course-memory nodes (decision 007): one per course
    they were the main user of. Read-only; the write seam is internal."""
    return course_archives_repo.list_memories(user.user_id)


@router.post(
    "/course-archives/{course_id}/copy",
    response_model=ArchiveCopyView,
    status_code=status.HTTP_201_CREATED,
)
def copy_course_archive(
    course_id: UUID,
    payload: ArchiveCopyRequest,
    user: Annotated[UserAccount, Depends(current_user)],
) -> ArchiveCopyView:
    budget.verify_tier(user.user_id, user.tier)
    policy = tier_config.load_tier_policies().policy_for(user.tier)
    try:
        course = courses_lifecycle.copy_archived_course(
            course_id,
            user.user_id,
            user.tier,
            policy,
            name=payload.name,
        )
    except courses_lifecycle.ArchiveAccessError as err:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "course archive not found"
        ) from err
    except courses_lifecycle.UncopyableCourseError as err:
        raise HTTPException(status.HTTP_409_CONFLICT, str(err)) from err
    except (budget.CourseLimitExceededError, budget.StorageLimitExceededError) as err:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(err)) from err
    return ArchiveCopyView(course_id=course.course_id, name=course.name)
