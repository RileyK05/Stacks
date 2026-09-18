"""Tutor API: grounded answers for a course.

POST /courses/{course_id}/ask — single-turn grounded Q&A (Fork D scope).
Enrollment-gated (owner or active learner; the retrieval-caller check the
review flagged lands here). Strict refusal on empty retrieval (Fork B
lean). Provider-unavailable and budget-exhausted surface as honest 503s —
the endpoint never pretends to answer.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from src.backend.api.deps import current_user, require_verified_email
from src.backend.common import (
    budget,
    courses_repo,
    enrollments_repo,
    provider,
)
from src.backend.common.db import connection
from src.backend.common.schemas.identity import UserAccount
from src.backend.retrieval.config import load_retrieval_policy
from src.backend.tutor import answer as tutor_answer

router = APIRouter(prefix="/courses", tags=["tutor"])


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)


class AnswerView(BaseModel):
    text: str
    chunk_ids: list[str]
    trace_id: str


@router.post("/{course_id}/ask", response_model=AnswerView)
def ask(
    course_id: UUID,
    payload: AskRequest,
    user: Annotated[UserAccount, Depends(current_user)],
) -> AnswerView:
    require_verified_email(user)
    course = courses_repo.get_course(course_id)
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")
    is_learner = (
        course.owner_user_id != user.user_id
        and enrollments_repo.is_active(course_id, user.user_id)
    )
    if course.owner_user_id != user.user_id and not is_learner:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")
    budget.verify_tier(user.user_id, user.tier)
    try:
        with connection() as conn:
            result = tutor_answer.answer_question(
                conn,
                user.user_id,
                user.tier,
                course_id,
                payload.question,
                load_retrieval_policy(),
            )
            conn.commit()
    except tutor_answer.NothingRelevantFoundError as err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(err)) from err
    except provider.ProviderUnavailableError as err:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "model provider not configured; answers are unavailable",
        ) from err
    except budget.BudgetExceededError as err:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"weekly {user.tier.value} budget exhausted; resets weekly",
        ) from err
    return AnswerView(
        text=result.text,
        chunk_ids=[str(cid) for cid in result.chunk_ids],
        trace_id=str(result.trace_id),
    )