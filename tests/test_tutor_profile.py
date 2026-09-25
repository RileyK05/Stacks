from src.backend.common.schemas import TutorProfile, TutorVerbosity
from src.backend.tutor.profile import (
    load_generic_tutor_profile,
    select_tutor_profile,
)


def test_generic_tutor_profile_loads_versioned_defaults() -> None:
    profile = load_generic_tutor_profile()
    assert profile.profile_version == "1"


def test_saved_profile_wins_over_generic() -> None:
    generic = load_generic_tutor_profile()
    saved = TutorProfile(profile_version="mine-v1", verbosity=TutorVerbosity.DETAILED)
    assert select_tutor_profile(generic_profile=generic, saved_profile=saved) == saved


def test_generic_profile_when_nothing_saved() -> None:
    generic = load_generic_tutor_profile()
    assert select_tutor_profile(generic_profile=generic) == generic
