from uuid import uuid4

import pytest
from src.backend.common.schemas import Course, TutorProfile, TutorVerbosity
from src.backend.tutor.profile import (
    load_generic_tutor_profile,
    select_tutor_profile,
)


def test_generic_tutor_profile_is_not_user_owned() -> None:
    profile = load_generic_tutor_profile()
    assert profile.user_id is None
    assert profile.profile_version == "1"


def test_owner_receives_owner_profile() -> None:
    owner_id = uuid4()
    course = Course(owner_user_id=owner_id, code="TEST", name="Test")
    generic = load_generic_tutor_profile()
    owner_profile = TutorProfile(
        user_id=owner_id,
        profile_version="owner-v1",
        verbosity=TutorVerbosity.DETAILED,
    )
    selected = select_tutor_profile(
        course,
        owner_id,
        generic_profile=generic,
        owner_profile=owner_profile,
    )
    assert selected == owner_profile


def test_nonowner_receives_generic_profile_not_owner_profile() -> None:
    owner_id = uuid4()
    course = Course(owner_user_id=owner_id, code="TEST", name="Test")
    generic = load_generic_tutor_profile()
    owner_profile = TutorProfile(
        user_id=owner_id,
        profile_version="owner-v1",
        verbosity=TutorVerbosity.DETAILED,
    )
    selected = select_tutor_profile(
        course,
        uuid4(),
        generic_profile=generic,
        owner_profile=owner_profile,
    )
    assert selected == generic


def test_mismatched_owner_profile_is_rejected() -> None:
    owner_id = uuid4()
    course = Course(owner_user_id=owner_id, code="TEST", name="Test")
    generic = load_generic_tutor_profile()
    wrong_profile = TutorProfile(user_id=uuid4(), profile_version="wrong-v1")
    with pytest.raises(ValueError, match="different user"):
        select_tutor_profile(
            course,
            owner_id,
            generic_profile=generic,
            owner_profile=wrong_profile,
        )
