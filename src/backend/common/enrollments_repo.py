from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from src.backend.common import memory_bank
from src.backend.common.db import connection
from src.backend.common.queries import get
from src.backend.common.schemas.base import EnrollmentSource, EnrollmentStatus
from src.backend.common.schemas.identity import CourseEnrollment

_FILE = "enrollments"


def _to_enrollment(row: dict[str, Any]) -> CourseEnrollment:
    return CourseEnrollment(
        enrollment_id=row["enrollment_id"],
        course_id=row["course_id"],
        user_id=row["user_id"],
        role=row["role"],
        status=row["status"],
        enrollment_source=row["enrollment_source"],
        invited_by_user_id=row["invited_by_user_id"],
        created_at=row["created_at"],
        revoked_at=row["revoked_at"],
        responded_at=row["responded_at"],
    )


def get_enrollment(course_id: UUID, user_id: UUID) -> CourseEnrollment | None:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "get_enrollment"),
            {"course_id": course_id, "user_id": user_id},
        ).fetchone()
    return _to_enrollment(row) if row else None


def is_active(course_id: UUID, user_id: UUID) -> bool:
    enrollment = get_enrollment(course_id, user_id)
    return enrollment is not None and enrollment.status == EnrollmentStatus.ACTIVE


def enroll(course_id: UUID, user_id: UUID) -> CourseEnrollment:
    return _activate(course_id, user_id, EnrollmentSource.SELF_SERVICE)


def join_with_code(course_id: UUID, user_id: UUID) -> CourseEnrollment:
    return _activate(course_id, user_id, EnrollmentSource.JOIN_CODE)


def invite(
    course_id: UUID, user_id: UUID, invited_by_user_id: UUID
) -> CourseEnrollment:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "upsert_invitation"),
            {
                "course_id": course_id,
                "user_id": user_id,
                "invited_by_user_id": invited_by_user_id,
            },
        ).fetchone()
        conn.commit()
    if row is None:
        raise ValueError("already enrolled")
    return _to_enrollment(row)


def _activate(
    course_id: UUID,
    user_id: UUID,
    source: EnrollmentSource,
) -> CourseEnrollment:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "upsert_active_enrollment"),
            {
                "course_id": course_id,
                "user_id": user_id,
                "enrollment_source": source.value,
            },
        ).fetchone()
        if row is not None:
            memory_bank.upsert_for_users(cur, course_id, [user_id])
        conn.commit()
    if row is None:
        raise ValueError("already enrolled")
    return _to_enrollment(row)


def accept_invitation(course_id: UUID, user_id: UUID) -> CourseEnrollment | None:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "accept_invitation"),
            {"course_id": course_id, "user_id": user_id},
        ).fetchone()
        if row is not None:
            memory_bank.upsert_for_users(cur, course_id, [user_id])
        conn.commit()
    return _to_enrollment(row) if row else None


def decline_invitation(course_id: UUID, user_id: UUID) -> CourseEnrollment | None:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "decline_invitation"),
            {"course_id": course_id, "user_id": user_id},
        ).fetchone()
        conn.commit()
    return _to_enrollment(row) if row else None


def revoke(course_id: UUID, user_id: UUID) -> bool:
    """Owner-side rescission: set an active/invited enrollment to revoked.
    Returns whether a row was changed; rows are kept for history."""
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "revoke_enrollment"),
            {"course_id": course_id, "user_id": user_id},
        ).fetchone()
        conn.commit()
    return row is not None


def withdraw(course_id: UUID, user_id: UUID) -> bool:
    """Learner-side exit: active becomes revoked, a pending invitation the
    learner refuses becomes declined rather than owner-revoked."""
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "withdraw_enrollment"),
            {"course_id": course_id, "user_id": user_id},
        ).fetchone()
        conn.commit()
    return row is not None


def members(course_id: UUID) -> list[CourseEnrollment]:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            get(_FILE, "list_members"), {"course_id": course_id}
        ).fetchall()
    return [_to_enrollment(row) for row in rows]
