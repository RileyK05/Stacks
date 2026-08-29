from __future__ import annotations

from uuid import UUID

from src.backend.common.schemas.base import (
    CourseVisibility,
    EnrollmentStatus,
    ObjectAccessScope,
)
from src.backend.common.schemas.identity import (
    Course,
    CourseEnrollment,
    CourseObject,
    UserArtifact,
)


def _is_owner(course: Course, user_id: UUID | None) -> bool:
    return user_id is not None and user_id == course.owner_user_id


def _is_actively_accessible_to_course(
    enrollment: CourseEnrollment | None, user_id: UUID | None, course_id: UUID
) -> bool:
    return (
        user_id is not None
        and enrollment is not None
        and enrollment.user_id == user_id
        and enrollment.course_id == course_id
        and enrollment.status == EnrollmentStatus.ACTIVE
    )


def can_view_course(
    course: Course,
    user_id: UUID | None,
    enrollment: CourseEnrollment | None = None,
) -> bool:
    return (
        course.visibility == CourseVisibility.PUBLIC
        or _is_owner(course, user_id)
        or _is_actively_accessible_to_course(enrollment, user_id, course.course_id)
    )


def can_self_enroll(
    course: Course,
    user_id: UUID | None,
    enrollment: CourseEnrollment | None = None,
) -> bool:
    return (
        user_id is not None
        and not _is_owner(course, user_id)
        and course.visibility == CourseVisibility.PUBLIC
        and enrollment is None
    )


def can_use_sources(
    course: Course,
    user_id: UUID | None,
    enrollment: CourseEnrollment | None = None,
) -> bool:
    return _is_owner(course, user_id) or _is_actively_accessible_to_course(
        enrollment, user_id, course.course_id
    )


def can_manage_sources(course: Course, user_id: UUID | None) -> bool:
    return _is_owner(course, user_id)


def can_generate_materials(
    course: Course,
    user_id: UUID | None,
    enrollment: CourseEnrollment | None = None,
) -> bool:
    return user_id is not None and (
        _is_owner(course, user_id)
        or _is_actively_accessible_to_course(
            enrollment, user_id, course.course_id
        )
    )


def can_view_object(
    course: Course,
    course_object: CourseObject,
    user_id: UUID | None,
    enrollment: CourseEnrollment | None = None,
) -> bool:
    if course_object.course_id != course.course_id:
        return False
    if _is_owner(course, user_id):
        return True
    if course_object.access_scope == ObjectAccessScope.PRIVATE:
        return False
    if course_object.access_scope == ObjectAccessScope.ENROLLED:
        return _is_actively_accessible_to_course(
            enrollment, user_id, course.course_id
        )
    return can_view_course(course, user_id, enrollment)


def can_manage_object(
    course: Course,
    course_object: CourseObject,
    user_id: UUID | None,
) -> bool:
    if course_object.course_id != course.course_id:
        return False
    return _is_owner(course, user_id)


def can_view_user_artifact(artifact: UserArtifact, user_id: UUID | None) -> bool:
    return user_id is not None and artifact.user_id == user_id


def can_manage_user_artifact(artifact: UserArtifact, user_id: UUID | None) -> bool:
    return can_view_user_artifact(artifact, user_id)
