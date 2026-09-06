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


def _has_active_enrollment(
    enrollment: CourseEnrollment | None, user_id: UUID | None, course_id: UUID
) -> bool:
    """True when this user already holds an active enrollment row for this
    course. No row (fresh learner), revoked, invited, and declined all permit
    enrollment actions."""
    return _is_actively_accessible_to_course(enrollment, user_id, course_id)


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
    """Self-service enrollment is public-only. Blocked only by an *active*
    enrollment: a fresh learner (no row), a revoked, or a declined learner
    may all enroll (revoked re-enrollment is migration 011's validated path)."""
    return (
        user_id is not None
        and not _is_owner(course, user_id)
        and course.visibility == CourseVisibility.PUBLIC
        and not _has_active_enrollment(enrollment, user_id, course.course_id)
    )


def can_join_with_code(
    course: Course,
    user_id: UUID | None,
    enrollment: CourseEnrollment | None = None,
) -> bool:
    """Join codes unlock the two joinable shapes: public and invite_only.
    Private courses are reachable only through an owner invitation. Blocked
    only by an active enrollment."""
    return (
        user_id is not None
        and not _is_owner(course, user_id)
        and course.visibility
        in (CourseVisibility.PUBLIC, CourseVisibility.INVITE_ONLY)
        and not _has_active_enrollment(enrollment, user_id, course.course_id)
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
