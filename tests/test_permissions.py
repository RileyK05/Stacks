from datetime import UTC, datetime
from uuid import uuid4

from src.backend.common.permissions import (
    can_generate_materials,
    can_manage_object,
    can_manage_sources,
    can_manage_user_artifact,
    can_self_enroll,
    can_use_sources,
    can_view_course,
    can_view_object,
    can_view_user_artifact,
)
from src.backend.common.schemas import (
    Course,
    CourseEnrollment,
    CourseObject,
    CourseVisibility,
    EnrollmentSource,
    EnrollmentStatus,
    ObjectAccessScope,
    UserArtifact,
)


def _course(owner_id=None, *, public: bool = False, visibility=None) -> Course:
    return Course(
        owner_user_id=owner_id or uuid4(),
        join_code="RANDOM123456",
        name="Statistical Inference",
        visibility=(
            visibility
            if visibility is not None
            else (
                CourseVisibility.PUBLIC if public else CourseVisibility.PRIVATE
            )
        ),
    )


def _enrollment(
    course: Course, user_id, *, active: bool = True
) -> CourseEnrollment:
    return CourseEnrollment(
        course_id=course.course_id,
        user_id=user_id,
        enrollment_source=EnrollmentSource.INVITATION,
        invited_by_user_id=course.owner_user_id,
        status=EnrollmentStatus.ACTIVE if active else EnrollmentStatus.REVOKED,
        revoked_at=None if active else datetime.now(UTC),
    )


def _course_object(
    course: Course, *, kind="flashcard", scope=ObjectAccessScope.PRIVATE
) -> CourseObject:
    return CourseObject(
        course_id=course.course_id,
        created_by_user_id=course.owner_user_id,
        kind=kind,
        content_type="application/json",
        content={"value": "x"},
        access_scope=scope,
    )


def _user_artifact(course: Course, user_id) -> UserArtifact:
    return UserArtifact(
        user_id=user_id,
        source_course_id=course.course_id,
        source_course_label=course.name,
        kind="study_guide",
        content_type="application/json",
        content={"value": "private"},
    )


def test_anonymous_visitor_can_view_published_public_material() -> None:
    course = _course(public=True)
    published = _course_object(course, scope=ObjectAccessScope.PUBLISHED)
    assert can_view_course(course, None)
    assert can_view_object(course, published, None)
    assert not can_use_sources(course, None)
    assert not can_generate_materials(course, None)


def test_authenticated_public_visitor_must_enroll_before_generation() -> None:
    course = _course(public=True)
    user_id = uuid4()
    assert can_view_course(course, user_id)
    assert can_self_enroll(course, user_id)
    assert not can_use_sources(course, user_id)
    assert not can_generate_materials(course, user_id)


def test_enrolled_learner_can_use_sources_but_not_manage_course() -> None:
    course = _course()
    learner_id = uuid4()
    enrollment = _enrollment(course, learner_id)
    source = _course_object(
        course, kind="source", scope=ObjectAccessScope.ENROLLED
    )
    assert can_view_course(course, learner_id, enrollment)
    assert can_use_sources(course, learner_id, enrollment)
    assert can_view_object(course, source, learner_id, enrollment)
    assert can_generate_materials(course, learner_id, enrollment)
    assert not can_manage_sources(course, learner_id)
    assert not can_manage_object(course, source, learner_id)


def test_owner_can_manage_canonical_course_objects() -> None:
    course = _course()
    source = _course_object(
        course, kind="source", scope=ObjectAccessScope.ENROLLED
    )
    assert can_manage_sources(course, course.owner_user_id)
    assert can_manage_object(course, source, course.owner_user_id)


def test_personal_artifact_is_visible_only_to_learner() -> None:
    course = _course()
    learner_id = uuid4()
    artifact = _user_artifact(course, learner_id)
    assert can_view_user_artifact(artifact, learner_id)
    assert can_manage_user_artifact(artifact, learner_id)
    assert not can_view_user_artifact(artifact, course.owner_user_id)
    assert not can_manage_user_artifact(artifact, course.owner_user_id)


def test_revoked_enrollment_loses_course_use_but_not_personal_artifact() -> None:
    course = _course()
    learner_id = uuid4()
    enrollment = _enrollment(course, learner_id, active=False)
    artifact = _user_artifact(course, learner_id)
    assert not can_view_course(course, learner_id, enrollment)
    assert not can_use_sources(course, learner_id, enrollment)
    assert not can_generate_materials(course, learner_id, enrollment)
    assert can_view_user_artifact(artifact, learner_id)


def test_enrollment_from_another_course_grants_nothing() -> None:
    course = _course()
    other_course = _course()
    learner_id = uuid4()
    wrong_enrollment = _enrollment(other_course, learner_id)
    assert not can_view_course(course, learner_id, wrong_enrollment)
    assert not can_use_sources(course, learner_id, wrong_enrollment)


def test_self_enrollment_is_only_for_public_unenrolled_nonowners() -> None:
    owner_id = uuid4()
    private_course = _course(owner_id)
    public_course = _course(owner_id, public=True)
    learner_id = uuid4()
    enrollment = _enrollment(public_course, learner_id)
    assert not can_self_enroll(private_course, learner_id)
    assert not can_self_enroll(public_course, owner_id)
    assert not can_self_enroll(public_course, learner_id, enrollment)


def test_self_enrollment_allows_revoked_learner_to_reenroll() -> None:
    owner_id = uuid4()
    public_course = _course(owner_id, public=True)
    learner_id = uuid4()
    revoked = _enrollment(public_course, learner_id, active=False)
    assert can_self_enroll(public_course, learner_id, revoked)
    active = _enrollment(public_course, learner_id)
    assert not can_self_enroll(public_course, learner_id, active)
    assert not can_self_enroll(public_course, None)


def test_join_code_works_on_public_and_invite_only_not_private() -> None:
    from src.backend.common.permissions import can_join_with_code

    owner_id = uuid4()
    learner_id = uuid4()
    private_course = _course(owner_id)
    invite_only = _course(
        owner_id, visibility=CourseVisibility.INVITE_ONLY
    )
    public_course = _course(owner_id, public=True)
    assert can_join_with_code(public_course, learner_id)
    assert can_join_with_code(invite_only, learner_id)
    assert not can_join_with_code(private_course, learner_id)
    assert not can_join_with_code(invite_only, owner_id)
    active = _enrollment(invite_only, learner_id)
    assert not can_join_with_code(invite_only, learner_id, active)
