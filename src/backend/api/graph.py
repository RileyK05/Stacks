from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from src.backend.api.deps import require_course
from src.backend.graph.view import CourseGraphOut, course_graph

router = APIRouter(tags=["graph"])


@router.get("/courses/{course_id}/graph", response_model=CourseGraphOut)
def get_course_graph(
    course_id: UUID, source_ids: Annotated[list[UUID] | None, Query()] = None
) -> CourseGraphOut:
    """Original source structure and inferred passage similarity."""
    require_course(course_id)
    return course_graph(course_id, source_ids)
