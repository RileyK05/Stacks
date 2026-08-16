from uuid import uuid4

import pytest
from pydantic import ValidationError
from src.backend.common.schemas import (
    Attempt,
    Chunk,
    Concept,
    CourseObject,
    Dependency,
    EvidenceLevel,
    MemoryObject,
    MemoryObjectKind,
    Page,
    Source,
    SourceStatus,
    SourceType,
    User,
    Week,
)


def test_user_defaults() -> None:
    user = User(name="Ada")
    assert user.user_id is not None
    assert user.created_at is not None


def test_source_requires_valid_source_type() -> None:
    source = Source(
        user_id=uuid4(),
        course_id=uuid4(),
        filename="week1.pdf",
        mime_type="application/pdf",
        source_type=SourceType.SLIDES,
    )
    assert source.status == SourceStatus.UPLOADED


def test_source_rejects_invalid_source_type() -> None:
    with pytest.raises(ValidationError):
        Source(
            user_id=uuid4(),
            course_id=uuid4(),
            filename="week1.pdf",
            mime_type="application/pdf",
            source_type="not-a-real-type",
        )


def test_attempt_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        Attempt(
            user_id=uuid4(),
            course_id=uuid4(),
            concept_id=uuid4(),
            question_version="v1",
            answer="x",
            confidence_before=150,
            evaluation="correct",
        )


def test_course_object_holds_arbitrary_content() -> None:
    obj = CourseObject(
        course_id=uuid4(),
        user_id=uuid4(),
        kind="flashcard",
        content_type="application/json",
        content={"front": "What is sufficiency?", "back": "..."},
    )
    assert obj.content["front"] == "What is sufficiency?"


def test_memory_object_evidence_level() -> None:
    obj = MemoryObject(
        concept_id=uuid4(),
        source_id=uuid4(),
        kind=MemoryObjectKind.CONCEPT,
        content="A random variable is ...",
        evidence_level=EvidenceLevel.DIRECT,
    )
    assert obj.evidence_level == EvidenceLevel.DIRECT


def test_dependency_links_concepts() -> None:
    dep = Dependency(prereq_id=uuid4(), dependent_id=uuid4())
    assert dep.prereq_id != dep.dependent_id


def test_chunk_embedding_optional() -> None:
    chunk = Chunk(
        source_id=uuid4(),
        page_id=uuid4(),
        chunk_index=0,
        text="some text",
    )
    assert chunk.embedding is None


def test_week_and_concept_and_page_construct() -> None:
    course_id = uuid4()
    week = Week(course_id=course_id, week_num=3, topic="Estimation")
    concept = Concept(course_id=course_id, name="sufficiency", definition="...")
    page = Page(source_id=uuid4(), page_num=1, text="...")
    assert week.week_num == 3
    assert concept.name == "sufficiency"
    assert page.page_num == 1
