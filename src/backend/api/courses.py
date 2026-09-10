from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, ConfigDict, Field
from src.backend.api.deps import current_user, require_verified_email
from src.backend.common import (
    budget,
    codes,
    courses_lifecycle,
    courses_repo,
    enrollments_repo,
)
from src.backend.common import (
    tiers as tier_config,
)
from src.backend.common.schemas.base import CourseVisibility
from src.backend.common.schemas.identity import Course, UserAccount
from src.backend.common.tiers import TierPolicy

router = APIRouter(prefix="/courses", tags=["courses"])


class CourseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    visibility: CourseVisibility = CourseVisibility.PRIVATE


class CourseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    visibility: CourseVisibility | None = None


class CourseView(BaseModel):
    course_id: UUID
    join_code: str | None
    name: str
    visibility: CourseVisibility
    role: str
    source_count: int
    stored_bytes: int


def _policy_for(user: UserAccount) -> TierPolicy:
    budget.verify_tier(user.user_id, user.tier)
    return tier_config.load_tier_policies().policy_for(user.tier)


def _view(course: Course, role: str, stats: dict[UUID, tuple[int, int]]) -> CourseView:
    source_count, stored_bytes = stats.get(course.course_id, (0, 0))
    shareable = course.visibility == CourseVisibility.PUBLIC or (
        role == "owner" and course.visibility == CourseVisibility.INVITE_ONLY
    )
    return CourseView(
        course_id=course.course_id,
        join_code=codes.display_code(course.join_code) if shareable else None,
        name=course.name,
        visibility=course.visibility,
        role=role,
        source_count=source_count,
        stored_bytes=stored_bytes,
    )


@router.post("", response_model=CourseView, status_code=status.HTTP_201_CREATED)
def create_course(
    payload: CourseCreate,
    user: Annotated[UserAccount, Depends(current_user)],
) -> CourseView:
    require_verified_email(user)
    policy = _policy_for(user)
    try:
        course = courses_repo.create_course(
            user.user_id,
            payload.name,
            payload.visibility,
            max_owned_courses=policy.max_owned_courses,
        )
    except courses_repo.CourseLimitReachedError as err:
        detail = budget.CourseLimitExceededError(user.tier, err.owned, err.limit)
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(detail)) from err
    except UniqueViolation as err:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "could not allocate a unique course join code; retry",
        ) from err
    return _view(course, "owner", {course.course_id: (0, 0)})


@router.get("", response_model=list[CourseView])
def list_courses(
    user: Annotated[UserAccount, Depends(current_user)],
) -> list[CourseView]:
    owned = courses_repo.list_owned(user.user_id)
    enrolled = courses_repo.list_enrolled(user.user_id)
    stats = courses_repo.source_stats(
        [c.course_id for c in owned] + [c.course_id for c in enrolled]
    )
    return [_view(c, "owner", stats) for c in owned] + [
        _view(c, "learner", stats) for c in enrolled
    ]


@router.get("/public", response_model=list[CourseView])
def list_public_courses() -> list[CourseView]:
    courses = courses_repo.list_public()
    stats = courses_repo.source_stats([course.course_id for course in courses])
    return [_view(course, "visitor", stats) for course in courses]


@router.get("/{course_id}", response_model=CourseView)
def get_course(
    course_id: UUID,
    user: Annotated[UserAccount, Depends(current_user)],
) -> CourseView:
    course = courses_repo.get_course(course_id)
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")
    if course.owner_user_id == user.user_id:
        role = "owner"
    elif enrollments_repo.is_active(course_id, user.user_id):
        role = "learner"
    else:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")
    return _view(course, role, courses_repo.source_stats([course_id]))


@router.patch("/{course_id}", response_model=CourseView)
def update_course(
    course_id: UUID,
    payload: CourseUpdate,
    user: Annotated[UserAccount, Depends(current_user)],
) -> CourseView:
    course = courses_repo.get_course(course_id)
    if course is None or course.owner_user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")
    if (
        course.visibility == CourseVisibility.PUBLIC
        and payload.visibility is not None
        and payload.visibility != CourseVisibility.PUBLIC
    ):
        policy = _policy_for(user)
        try:
            successor = courses_lifecycle.restrict_public_course(
                course_id,
                user.user_id,
                user.tier,
                policy,
                payload.visibility,
                name=payload.name,
            )
        except budget.StorageLimitExceededError as err:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(err)) from err
        except courses_lifecycle.UncopyableCourseError as err:
            raise HTTPException(status.HTTP_409_CONFLICT, str(err)) from err
        except courses_lifecycle.UnknownCourseError as err:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "course not found"
            ) from err
        except (
            courses_lifecycle.CourseTransitionError,
            courses_repo.RestrictedTransitionError,
        ) as err:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "course changed concurrently"
            ) from err
        return _view(
            successor,
            "owner",
            courses_repo.source_stats([successor.course_id]),
        )
    try:
        updated = courses_repo.update_course(
            course_id,
            name=payload.name,
            visibility=payload.visibility,
        )
    except courses_repo.RestrictedTransitionError as err:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "course changed concurrently"
        ) from err
    except UniqueViolation as err:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "course update conflicted",
        ) from err
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")
    return _view(updated, "owner", courses_repo.source_stats([course_id]))


@router.post("/{course_id}/join-code/rotate", response_model=CourseView)
def rotate_join_code(
    course_id: UUID,
    user: Annotated[UserAccount, Depends(current_user)],
) -> CourseView:
    course = courses_repo.get_course(course_id)
    if course is None or course.owner_user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")
    if course.visibility == CourseVisibility.PRIVATE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "private courses do not expose a join code",
        )
    try:
        updated = courses_repo.rotate_join_code(course_id)
    except UniqueViolation as err:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "could not allocate a unique course join code; retry",
        ) from err
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")
    return _view(updated, "owner", courses_repo.source_stats([course_id]))


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(
    course_id: UUID,
    user: Annotated[UserAccount, Depends(current_user)],
) -> None:
    course = courses_repo.get_course(course_id)
    if course is None or course.owner_user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")
    try:
        courses_lifecycle.delete_course(course_id)
    except courses_lifecycle.UnknownCourseError as err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found") from err
