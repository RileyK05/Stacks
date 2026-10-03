"""Persisted course selection shared by Office setup and the bridge."""

from uuid import UUID

from src.backend.common import settings_repo

LAST_COURSE_SETTING = "office.last_course"


def last_course() -> str | None:
    value = settings_repo.get_setting(LAST_COURSE_SETTING)
    return str(value) if value else None


def select_course(course_id: UUID) -> None:
    settings_repo.put_setting(LAST_COURSE_SETTING, str(course_id))
