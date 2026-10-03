from uuid import uuid4

import pytest
from pydantic import ValidationError
from src.backend.common.schemas.base import SourceStatus, SourceType
from src.backend.common.schemas.identity import Course
from src.backend.common.schemas.source_content import Source


def test_source_rejects_invalid_source_type() -> None:
    with pytest.raises(ValidationError):
        Source(
            course_id=uuid4(),
            filename="week1.pdf",
            mime_type="application/pdf",
            source_type="not-a-real-type",
        )


def test_source_status_defaults_uploaded() -> None:
    source = Source(
        course_id=uuid4(),
        filename="week1.pdf",
        mime_type="application/pdf",
        source_type=SourceType.SLIDES,
    )
    assert source.status == SourceStatus.UPLOADED


def test_course_trash_columns_move_together() -> None:
    course = Course(name="Topology")
    assert not course.in_trash
    with pytest.raises(ValidationError, match="set together"):
        Course(name="Half deleted", deleted_at=course.created_at)
