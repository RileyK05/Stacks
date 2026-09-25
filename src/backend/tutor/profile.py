from __future__ import annotations

import tomllib
from pathlib import Path

from src.backend.common.config import PROJECT_ROOT
from src.backend.common.schemas.tutor import TutorProfile

DEFAULT_PROFILE_PATH = PROJECT_ROOT / "configs" / "tutor.toml"


def load_generic_tutor_profile(
    path: Path = DEFAULT_PROFILE_PATH,
) -> TutorProfile:
    with path.open("rb") as profile_file:
        return TutorProfile.model_validate(tomllib.load(profile_file))


def select_tutor_profile(
    *,
    generic_profile: TutorProfile,
    saved_profile: TutorProfile | None = None,
) -> TutorProfile:
    """The student's own saved profile when they have one, else the
    generic default. One local user per database, so there is no other
    user's profile to leak."""
    return saved_profile if saved_profile is not None else generic_profile
