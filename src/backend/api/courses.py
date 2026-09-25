from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from src.backend.common import course_memory_repo, courses_repo
from src.backend.common.schemas.identity import Course, CourseMemory

router = APIRouter(tags=["courses"])


class CourseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)


class CourseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)


class CourseView(BaseModel):
    course_id: UUID
    name: str
    created_at: datetime
    source_count: int
    stored_bytes: int


class TrashedCourseView(CourseView):
    deleted_at: datetime
    purge_after: datetime


def _view(course: Course, stats: dict[UUID, tuple[int, int]]) -> CourseView:
    source_count, stored_bytes = stats.get(course.course_id, (0, 0))
    return CourseView(
        course_id=course.course_id,
        name=course.name,
        created_at=course.created_at,
        source_count=source_count,
        stored_bytes=stored_bytes,
    )


def _trashed_view(
    course: Course, stats: dict[UUID, tuple[int, int]]
) -> TrashedCourseView:
    assert course.deleted_at is not None and course.purge_after is not None
    return TrashedCourseView(
        **_view(course, stats).model_dump(),
        deleted_at=course.deleted_at,
        purge_after=course.purge_after,
    )


@router.post("/courses", response_model=CourseView, status_code=status.HTTP_201_CREATED)
def create_course(payload: CourseCreate) -> CourseView:
    course = courses_repo.create_course(payload.name)
    return _view(course, {})


@router.get("/courses", response_model=list[CourseView])
def list_courses() -> list[CourseView]:
    courses = courses_repo.list_courses()
    stats = courses_repo.source_stats([course.course_id for course in courses])
    return [_view(course, stats) for course in courses]


@router.get("/courses/{course_id}", response_model=CourseView)
def get_course(course_id: UUID) -> CourseView:
    course = courses_repo.get_course(course_id)
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")
    return _view(course, courses_repo.source_stats([course_id]))


@router.patch("/courses/{course_id}", response_model=CourseView)
def rename_course(course_id: UUID, payload: CourseUpdate) -> CourseView:
    course = courses_repo.rename_course(course_id, payload.name)
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")
    return _view(course, courses_repo.source_stats([course_id]))


@router.delete("/courses/{course_id}", response_model=TrashedCourseView)
def delete_course(course_id: UUID) -> TrashedCourseView:
    """Move the course to the trash. It stays restorable until
    `purge_after`, then the maintenance loop purges it."""
    try:
        course = courses_repo.move_to_trash(course_id)
    except courses_repo.UnknownCourseError as err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found") from err
    return _trashed_view(course, courses_repo.source_stats([course_id]))


@router.get("/trash", response_model=list[TrashedCourseView])
def list_trash() -> list[TrashedCourseView]:
    courses = courses_repo.list_trash()
    stats = courses_repo.source_stats([course.course_id for course in courses])
    return [_trashed_view(course, stats) for course in courses]


@router.post("/trash/{course_id}/restore", response_model=CourseView)
def restore_course(course_id: UUID) -> CourseView:
    try:
        course = courses_repo.restore_from_trash(course_id)
    except courses_repo.UnknownCourseError as err:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "course not found in trash"
        ) from err
    return _view(course, courses_repo.source_stats([course_id]))


@router.delete("/trash/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def purge_course(course_id: UUID) -> None:
    """Delete a trashed course permanently, now. Its course-memory
    keepsake survives."""
    if not courses_repo.purge_course(course_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found in trash")


@router.get("/course-memories", response_model=list[CourseMemory])
def list_course_memories() -> list[CourseMemory]:
    """Every course-memory node (decision 007), including the keepsakes
    of purged courses. Read-only; the write seam is internal."""
    return course_memory_repo.list_memories()
