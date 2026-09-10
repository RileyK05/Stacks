"""Course enrollment API: self-enroll, invite, revoke, leave, member list.

Enrollment semantics follow decision 003: self-service on public courses only,
owner-issued invitations on any course, revoked learners re-enrollable through
the DB-validated path. Members list exposes ids and status only — never
learner emails (2026-09-05 ruling) and never course-memory content
(decision 007).
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation
from pydantic import BaseModel, ConfigDict, field_validator
from src.backend.api.deps import current_user
from src.backend.common import codes, courses_repo, enrollments_repo, users_repo
from src.backend.common.schemas.base import (
    CourseVisibility,
    EnrollmentSource,
    EnrollmentStatus,
)
from src.backend.common.schemas.identity import Course, CourseEnrollment, UserAccount

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/courses", tags=["enrollment"])


class EnrollmentView(BaseModel):
    enrollment_id: UUID
    course_id: UUID
    user_id: UUID
    status: EnrollmentStatus
    enrollment_source: EnrollmentSource


class InviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID


class JoinCourseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    join_code: str

    @field_validator("join_code")
    @classmethod
    def _code_format(cls, value: str) -> str:
        try:
            return codes.require_valid(value)
        except ValueError as err:
            raise ValueError(
                "join code must be 16 characters from the code alphabet "
                "(display form: XXXX-XXXX-XXXX-XXXX)"
            ) from err


class MemberView(BaseModel):
    user_id: UUID
    status: EnrollmentStatus


def _course_or_404(course_id: UUID) -> Course:
    course = courses_repo.get_course(course_id)
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")
    return course


def _require_owner(course: Course, user: UserAccount) -> None:
    if course.owner_user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")


def _view(enrollment: CourseEnrollment) -> EnrollmentView:
    return EnrollmentView(
        enrollment_id=enrollment.enrollment_id,
        course_id=enrollment.course_id,
        user_id=enrollment.user_id,
        status=enrollment.status,
        enrollment_source=enrollment.enrollment_source,
    )


def _is_active(enrollment: CourseEnrollment | None) -> bool:
    return enrollment is not None and enrollment.status == EnrollmentStatus.ACTIVE


def _enrollment_conflict(err: Exception) -> HTTPException:
    """CheckViolation from the enrollment policy trigger means the course
    disappeared or changed shape concurrently (archived, privatized) — the
    enrollment no longer applies, not that it was duplicated. Logged so a
    genuine constraint bug cannot hide as routine 404s."""
    logger.warning(
        "enrollment write rejected by policy trigger: %s", err
    )
    return HTTPException(
        status.HTTP_404_NOT_FOUND, "course not available for enrollment"
    )


@router.post(
    "/{course_id}/enroll",
    response_model=EnrollmentView,
    status_code=status.HTTP_201_CREATED,
)
def self_enroll(
    course_id: UUID,
    user: Annotated[UserAccount, Depends(current_user)],
) -> EnrollmentView:
    """Learner self-enrolls in a public course. Owners cannot enroll in their
    own course; a previously revoked learner is re-enrolled via the validated
    DB path."""
    course = _course_or_404(course_id)
    if course.owner_user_id == user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")
    if course.visibility == CourseVisibility.PRIVATE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")
    if course.visibility == CourseVisibility.INVITE_ONLY:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "course is not self-enrollable; "
            "invite-only courses require a join code",
        )
    if _is_active(enrollments_repo.get_enrollment(course_id, user.user_id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "already enrolled")
    try:
        enrollment = enrollments_repo.enroll(course_id, user.user_id)
    except (UniqueViolation, ValueError) as err:
        raise HTTPException(status.HTTP_409_CONFLICT, "already enrolled") from err
    except CheckViolation as err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found") from err
    return _view(enrollment)


@router.post(
    "/join", response_model=EnrollmentView, status_code=status.HTTP_201_CREATED
)
def join_course(
    payload: JoinCourseRequest,
    user: Annotated[UserAccount, Depends(current_user)],
) -> EnrollmentView:
    course = courses_repo.get_by_join_code(payload.join_code)
    if course is None or course.visibility == CourseVisibility.PRIVATE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "join code not found")
    if course.owner_user_id == user.user_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "owner cannot be enrolled")
    try:
        return _view(enrollments_repo.join_with_code(course.course_id, user.user_id))
    except ValueError as err:
        raise HTTPException(status.HTTP_409_CONFLICT, "already enrolled") from err
    except CheckViolation as err:
        raise _enrollment_conflict(err) from err


@router.post(
    "/{course_id}/invitations",
    response_model=EnrollmentView,
    status_code=status.HTTP_201_CREATED,
)
def invite(
    course_id: UUID,
    payload: InviteRequest,
    user: Annotated[UserAccount, Depends(current_user)],
) -> EnrollmentView:
    """Owner invites an existing account. No email infrastructure: the invite
    references an existing account by id."""
    course = _course_or_404(course_id)
    _require_owner(course, user)
    # The invited party must never be the course owner. Stated against
    # course.owner_user_id directly (not the caller) so the invariant holds
    # even if "who can invite" ever expands beyond the owner.
    if payload.user_id == course.owner_user_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "owner cannot be enrolled")
    if users_repo.get_by_id(payload.user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    if _is_active(enrollments_repo.get_enrollment(course_id, payload.user_id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "already enrolled")
    try:
        enrollment = enrollments_repo.invite(course_id, payload.user_id, user.user_id)
    except (UniqueViolation, ValueError) as err:
        raise HTTPException(status.HTTP_409_CONFLICT, "already enrolled") from err
    except CheckViolation as err:
        raise _enrollment_conflict(err) from err
    except ForeignKeyViolation as err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found") from err
    return _view(enrollment)


@router.post("/{course_id}/invitations/accept", response_model=EnrollmentView)
def accept_invitation(
    course_id: UUID,
    user: Annotated[UserAccount, Depends(current_user)],
) -> EnrollmentView:
    _course_or_404(course_id)
    try:
        enrollment = enrollments_repo.accept_invitation(course_id, user.user_id)
    except CheckViolation as err:
        raise _enrollment_conflict(err) from err
    if enrollment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "invitation not found")
    return _view(enrollment)


@router.post("/{course_id}/invitations/decline", response_model=EnrollmentView)
def decline_invitation(
    course_id: UUID,
    user: Annotated[UserAccount, Depends(current_user)],
) -> EnrollmentView:
    _course_or_404(course_id)
    try:
        enrollment = enrollments_repo.decline_invitation(course_id, user.user_id)
    except CheckViolation as err:
        raise _enrollment_conflict(err) from err
    if enrollment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "invitation not found")
    return _view(enrollment)


@router.delete(
    "/{course_id}/enrollments/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
def revoke_enrollment(
    course_id: UUID,
    user_id: UUID,
    user: Annotated[UserAccount, Depends(current_user)],
) -> None:
    """Owner revokes a learner. Future source use and generation end; the
    learner's private artifacts remain theirs."""
    course = _course_or_404(course_id)
    _require_owner(course, user)
    if not enrollments_repo.revoke(course_id, user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "enrollment not found")


@router.delete("/{course_id}/enrollment", status_code=status.HTTP_204_NO_CONTENT)
def leave_course(
    course_id: UUID,
    user: Annotated[UserAccount, Depends(current_user)],
) -> None:
    """A learner withdraws from a course: an active enrollment becomes
    revoked, a pending invitation becomes declined. Either way the row is
    retained so history is preserved."""
    _course_or_404(course_id)
    try:
        if not enrollments_repo.withdraw(course_id, user.user_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not enrolled")
    except CheckViolation as err:
        raise _enrollment_conflict(err) from err


@router.get("/{course_id}/members", response_model=list[MemberView])
def list_members(
    course_id: UUID,
    user: Annotated[UserAccount, Depends(current_user)],
) -> list[MemberView]:
    """Owner-only. Learner membership is private per decision 003. Ids only —
    the owner can identify members out-of-band; emails are never exposed."""
    course = _course_or_404(course_id)
    _require_owner(course, user)
    return [
        MemberView(
            user_id=enrollment.user_id,
            status=enrollment.status,
        )
        for enrollment in enrollments_repo.members(course_id)
    ]
