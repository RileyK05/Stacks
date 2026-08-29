from __future__ import annotations

import tomllib
from pathlib import Path
from uuid import UUID

from src.backend.common.config import PROJECT_ROOT
from src.backend.common.schemas.identity import Course
from src.backend.common.schemas.tutor import TutorProfile

DEFAULT_PROFILE_PATH = PROJECT_ROOT / "configs" / "tutor.toml"


def load_generic_tutor_profile(
    path: Path = DEFAULT_PROFILE_PATH,
) -> TutorProfile:
    with path.open("rb") as profile_file:
        return TutorProfile.model_validate(tomllib.load(profile_file))


def select_tutor_profile(
    course: Course,
    requester_user_id: UUID,
    *,
    generic_profile: TutorProfile,
    owner_profile: TutorProfile | None = None,
) -> TutorProfile:
    if generic_profile.user_id is not None:
        raise ValueError("generic tutor profile cannot belong to a user")
    if requester_user_id != course.owner_user_id or owner_profile is None:
        return generic_profile
    if owner_profile.user_id != course.owner_user_id:
        raise ValueError("owner tutor profile belongs to a different user")
    return owner_profile
