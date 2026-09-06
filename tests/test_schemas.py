from uuid import uuid4

import pytest
from pydantic import ValidationError
from src.backend.common.schemas import (
    ArchivedCitation,
    AssessmentItem,
    Attempt,
    ChatSummary,
    Chunk,
    Citation,
    CitationSnapshot,
    Claim,
    ConceptMastery,
    Conversation,
    ConversationTurn,
    CourseEnrollment,
    CourseMemory,
    CourseObject,
    Dependency,
    EnrollmentSource,
    EvidenceLevel,
    Locator,
    MasteryState,
    MemoryObject,
    MemoryObjectKind,
    MessageRole,
    ModelDecision,
    PrereqKind,
    Recommendation,
    Response,
    RetrievalTrace,
    Source,
    SourceStatus,
    SourceType,
    StudyPeriod,
    TableOfContents,
    TocEntry,
    User,
    UserAccount,
    UserArtifact,
    UserArtifactOrigin,
)


def test_user_defaults() -> None:
    user = User(name="Ada")
    assert user.user_id is not None
    assert user.created_at is not None


def test_source_rejects_invalid_source_type() -> None:
    with pytest.raises(ValidationError):
        Source(
            object_id=uuid4(),
            uploaded_by_user_id=uuid4(),
            course_id=uuid4(),
            filename="week1.pdf",
            mime_type="application/pdf",
            source_type="not-a-real-type",
        )


def test_source_status_defaults_uploaded() -> None:
    source = Source(
        object_id=uuid4(),
        uploaded_by_user_id=uuid4(),
        course_id=uuid4(),
        filename="week1.pdf",
        mime_type="application/pdf",
        source_type=SourceType.SLIDES,
    )
    assert source.status == SourceStatus.UPLOADED


def test_study_period_is_sliding_window() -> None:
    from datetime import date

    period = StudyPeriod(
        course_id=uuid4(),
        label="Before Exam 2",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 15),
    )
    assert period.label == "Before Exam 2"


def test_dependency_allows_no_prereq() -> None:
    dep = Dependency(dependent_id=uuid4())
    assert dep.prereq_id is None
    assert dep.prereq_kind == PrereqKind.IN_COURSE


def test_dependency_allows_external_prereq() -> None:
    dep = Dependency(
        prereq_id=None,
        dependent_id=uuid4(),
        prereq_kind=PrereqKind.EXTERNAL,
        external_ref="Calc 1: integration",
    )
    assert dep.external_ref == "Calc 1: integration"


def test_dependency_defaults_in_course() -> None:
    dep = Dependency(prereq_id=uuid4(), dependent_id=uuid4())
    assert dep.prereq_kind == PrereqKind.IN_COURSE


def test_locator_holds_arbitrary_format() -> None:
    locator = Locator(
        source_id=uuid4(),
        locator_type="timestamp",
        start="12:30",
        end="14:00",
        label="Timestamp 12:30-14:00",
    )
    assert locator.label.startswith("Timestamp")


def test_locator_type_is_free_string() -> None:
    locator = Locator(
        source_id=uuid4(),
        locator_type="cell_range",  # a format we haven't thought of yet
        start="A1",
        end="D20",
        label="Sheet1 A1:D20",
    )
    assert locator.locator_type == "cell_range"


def test_chunk_has_no_embedding() -> None:
    chunk = Chunk(source_id=uuid4(), locator_id=uuid4(), chunk_index=0, text="x")
    assert not hasattr(chunk, "embedding")


def test_course_object_new_kind() -> None:
    obj = CourseObject(
        course_id=uuid4(),
        created_by_user_id=uuid4(),
        kind="flashcard",
        content_type="application/json",
        content={"front": "What is sufficiency?", "back": "..."},
    )
    assert obj.content["front"] == "What is sufficiency?"


def test_course_object_kind_is_free_string() -> None:
    obj = CourseObject(
        course_id=uuid4(),
        created_by_user_id=uuid4(),
        kind="holodeck",  # a kind we haven't thought of yet
        content_type="application/json",
        content={"scene": "..."},
    )
    assert obj.kind == "holodeck"


def test_course_object_requires_content_or_uri() -> None:
    with pytest.raises(ValidationError):
        CourseObject(
            course_id=uuid4(),
            created_by_user_id=uuid4(),
            kind="flashcard",
            content_type="application/json",
        )


def test_memory_object_evidence_level() -> None:
    obj = MemoryObject(
        concept_id=uuid4(),
        source_id=uuid4(),
        kind=MemoryObjectKind.CONCEPT,
        content="...",
        evidence_level=EvidenceLevel.DIRECT,
    )
    assert obj.evidence_level == EvidenceLevel.DIRECT


def test_toc_and_entry() -> None:
    toc = TableOfContents(course_id=uuid4(), version=1)
    entry = TocEntry(
        toc_id=toc.toc_id,
        source_id=uuid4(),
        title="Sufficiency",
        description="Slide deck on sufficiency",
    )
    assert entry.concepts == []


def test_assessment_item_defaults() -> None:
    item = AssessmentItem(course_id=uuid4(), prompt="Define sufficiency.")
    assert item.difficulty == 1
    assert item.solution is None


def test_attempt_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        Attempt(
            user_id=uuid4(),
            course_id=uuid4(),
            item_id=uuid4(),
            concept_ids=[uuid4()],
            answer="x",
            confidence_before=150,
            evaluation="correct",
        )


def test_concept_mastery_defaults_unseen() -> None:
    mastery = ConceptMastery(user_id=uuid4(), concept_id=uuid4())
    assert mastery.state == MasteryState.UNSEEN


def test_recommendation_traces_to_concept() -> None:
    concept_id = uuid4()
    rec = Recommendation(
        user_id=uuid4(),
        course_id=uuid4(),
        concept_id=concept_id,
        reason="Missed the factorization condition",
        source="attempt",
    )
    assert rec.concept_id == concept_id


def test_conversation_and_summary() -> None:
    conv = Conversation(user_id=uuid4(), course_id=uuid4(), title="Sufficiency")
    turn = ConversationTurn(
        conversation_id=conv.conversation_id, role="user", content="hi"
    )
    summary = ChatSummary(
        conversation_id=conv.conversation_id, summary="...", version=1
    )
    assert turn.role == "user"
    assert summary.version == 1


def test_retrieval_trace_records_retrieved() -> None:
    trace = RetrievalTrace(
        user_id=uuid4(),
        course_id=uuid4(),
        query="factorization",
        retrieved_chunk_ids=[uuid4()],
    )
    assert len(trace.retrieved_chunk_ids) == 1


def test_claim_citation_chain() -> None:
    claim = Claim(response_id=uuid4(), claim_type="academic", text="...")
    citation = Citation(claim_id=claim.claim_id, target_type="chunk", target_id=uuid4())
    assert citation.target_type == "chunk"


def test_response_grounds_claims() -> None:
    response = Response(
        conversation_id=uuid4(),
        content="Sufficiency is ...",
        model="deepseek-v4-flash",
    )
    claim = Claim(response_id=response.response_id, claim_type="academic", text="...")
    assert claim.response_id == response.response_id


def test_message_role_is_enum() -> None:
    turn = ConversationTurn(
        conversation_id=uuid4(), role=MessageRole.ASSISTANT, content="hi"
    )
    assert turn.role == MessageRole.ASSISTANT


def test_model_decision_stores_decision() -> None:
    record = ModelDecision(source_id=uuid4(), decision={"store_as": "slides"})
    assert record.decision["store_as"] == "slides"


def test_course_memory_survives_course_deletion() -> None:
    memory = CourseMemory(
        user_id=uuid4(),
        course_id=uuid4(),  # course row may be gone; memory outlives it
        course_ref="former-course-id",
        name="Statistical Inference",
        summary="Covered estimation, sufficiency, factorization.",
        key_concepts=["sufficiency", "estimator"],
        token_budget=1000,
        summary_version="deterministic-v1",
    )
    assert memory.key_concepts == ["sufficiency", "estimator"]


def test_citation_snapshot_preserves_evidence() -> None:
    snapshot = CitationSnapshot(
        user_id=uuid4(),
        course_id=uuid4(),
        source_id=uuid4(),
        source_name="Week 3 slides",
        citations=[
            ArchivedCitation(
                claim_text="Sufficiency is ...",
                target_type="chunk",
                target_id=uuid4(),
                locator_type="slide",
                locator_label="Slide 12",
                excerpt="A statistic is sufficient when ...",
                why_valid="The slide states the course definition.",
            )
        ],
    )
    assert snapshot.source_name == "Week 3 slides"


def test_user_soft_delete_marker() -> None:
    from datetime import UTC, datetime

    user = UserAccount(
        name="Ada",
        email="ada@example.com",
        delete_requested_at=datetime.now(UTC),
    )
    assert user.delete_requested_at is not None


def test_public_user_has_no_credential_fields() -> None:
    user = User(name="Ada", email="ada@example.com")
    assert not hasattr(user, "password_hash")
    assert not hasattr(user, "delete_requested_at")


def test_internal_password_hash_masks_if_accidentally_serialized() -> None:
    account = UserAccount(
        name="Ada", email="ada@example.com", password_hash="sensitive-hash"
    )
    assert "sensitive-hash" not in account.model_dump_json()


def test_course_enrollment_defaults_to_active_learner() -> None:
    enrollment = CourseEnrollment(
        course_id=uuid4(),
        user_id=uuid4(),
        enrollment_source=EnrollmentSource.INVITATION,
        invited_by_user_id=uuid4(),
    )
    assert enrollment.status == "active"
    assert enrollment.role == "learner"


def test_self_service_enrollment_cannot_have_inviter() -> None:
    with pytest.raises(ValidationError):
        CourseEnrollment(
            course_id=uuid4(),
            user_id=uuid4(),
            enrollment_source=EnrollmentSource.SELF_SERVICE,
            invited_by_user_id=uuid4(),
        )


def test_user_artifact_has_separate_private_identity() -> None:
    artifact = UserArtifact(
        user_id=uuid4(),
        source_course_id=uuid4(),
        source_course_label="MATH 361",
        kind="study_guide",
        content_type="application/json",
        content={"body": "private"},
    )
    origin = UserArtifactOrigin(
        artifact_id=artifact.artifact_id,
        tutor_profile_version="generic-v1",
    )
    assert artifact.user_id is not None
    assert origin.artifact_id == artifact.artifact_id


def test_week_removed() -> None:
    from src.backend.common import schemas

    assert not hasattr(schemas, "Week")
    assert hasattr(schemas, "StudyPeriod")
