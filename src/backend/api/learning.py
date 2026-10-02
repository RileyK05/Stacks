from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from src.backend.api.deps import require_course
from src.backend.common import artifacts_repo, conversations_repo, settings_repo
from src.backend.common.db import connection
from src.backend.common.provider import ProviderUnavailableError
from src.backend.common.queries import get
from src.backend.common.schemas.learning import (
    Capability,
    ContentFeedback,
    ContentFeedbackRequest,
    CoreMemory,
    LearningView,
    PracticeHelp,
    PracticeHelpRequest,
    PracticeQuestion,
    PracticeRun,
    PracticeSubmission,
    SuiteState,
    TeachingMethod,
)
from src.backend.student_model import learning, practice_support

router = APIRouter(tags=["learning"])


class SuiteFromSaved(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: UUID | None = None
    item_index: int = Field(default=0, ge=0)
    artifact_id: UUID | None = None
    artifact_version: int | None = Field(default=None, ge=1)


class AssessmentCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: int | None
    reason: str = Field(min_length=1, max_length=500)


class ForgetTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str = Field(min_length=1, max_length=5000)
    capability: Capability


class CorePreference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preferred_method: TeachingMethod | None


def _state(course_id: UUID, suite_id: UUID) -> SuiteState:
    with connection() as conn:
        try:
            test = learning.suite(conn, course_id, suite_id)
        except LookupError as err:
            raise HTTPException(404, str(err)) from err
        latest = next(
            (
                r
                for r in learning.rows(conn, "runs", course_id=course_id)
                if r["suite_id"] == suite_id
            ),
            None,
        )
        return SuiteState(
            suite=test,
            latest_run=learning.run_view(conn, latest) if latest else None,
            feedback=practice_support.feedback(conn, course_id, suite_id),
        )


@router.get("/courses/{course_id}/learning", response_model=LearningView)
def inspect_learning(course_id: UUID) -> LearningView:
    require_course(course_id)
    with connection() as conn:
        return learning.view(conn, course_id)


@router.post("/courses/{course_id}/practice", response_model=SuiteState)
def practice_from_saved(course_id: UUID, payload: SuiteFromSaved) -> SuiteState:
    require_course(course_id)
    if bool(payload.message_id) == bool(payload.artifact_id):
        raise HTTPException(422, "choose a saved chat quiz or a saved artifact")
    with connection() as conn:
        if payload.message_id:
            message = conversations_repo.message_in_course(
                course_id, payload.message_id
            )
            items = (
                message.payload.get("workspace", [])
                if message and message.role == "assistant"
                else []
            )
            if (
                not isinstance(items, list)
                or payload.item_index >= len(items)
                or items[payload.item_index].get("type") != "quiz"
            ):
                raise HTTPException(404, "saved quiz not found")
            item = items[payload.item_index]
            questions = [
                PracticeQuestion.model_validate(
                    q | {"explanation": q.get("explanation") or ""}
                )
                for q in item["questions"]
            ]
            ids = (
                tuple(UUID(cid) for cid in message.payload.get("chunk_ids", []))
                if message
                else ()
            )
            title = item.get("title") or "Practice test"
            origin = {
                "message_id": str(payload.message_id),
                "item_index": payload.item_index,
            }
            assigned = item.get("practice_id")
            if assigned and learning.rows(
                conn, "suite", course_id=course_id, suite_id=UUID(assigned)
            ):
                return _state(course_id, UUID(assigned))
        else:
            assert payload.artifact_id is not None
            artifact = artifacts_repo.load(conn, course_id, payload.artifact_id)
            if artifact is None or artifact.kind != "quiz":
                raise HTTPException(404, "saved quiz not found")
            if payload.artifact_version != artifact.version:
                raise HTTPException(409, "save or reload the quiz before taking it")
            questions = [
                PracticeQuestion.model_validate(q)
                for q in artifact.content["questions"]
            ]
            ids, title = artifact.sources, artifact.title
            origin = {
                "artifact_id": str(payload.artifact_id),
                "version": artifact.version,
            }
        existing = next(
            (
                r
                for r in learning.rows(conn, "suites", course_id=course_id)
                if r["origin"] == origin
            ),
            None,
        )
        if existing:
            suite_id = existing["suite_id"]
        else:
            try:
                suite_id = learning.create_suite(
                    conn, course_id, title, questions, ids, origin
                )
            except ValueError as err:
                raise HTTPException(422, str(err)) from err
            conn.commit()
    return _state(course_id, suite_id)


@router.get("/courses/{course_id}/practice/{suite_id}", response_model=SuiteState)
def get_practice(course_id: UUID, suite_id: UUID) -> SuiteState:
    require_course(course_id)
    return _state(course_id, suite_id)


@router.post(
    "/courses/{course_id}/practice/{suite_id}/runs", response_model=PracticeRun
)
def submit_practice(
    course_id: UUID, suite_id: UUID, payload: PracticeSubmission
) -> PracticeRun:
    require_course(course_id)
    with connection() as conn:
        try:
            result = learning.submit(conn, course_id, suite_id, payload)
        except LookupError as err:
            raise HTTPException(404, str(err)) from err
        except ValueError as err:
            raise HTTPException(422, str(err)) from err
        conn.commit()
        return result


@router.get("/courses/{course_id}/practice/runs/{run_id}", response_model=SuiteState)
def inspect_run(course_id: UUID, run_id: UUID) -> SuiteState:
    require_course(course_id)
    with connection() as conn:
        records = learning.rows(conn, "run", course_id=course_id, run_id=run_id)
        if not records:
            raise HTTPException(404, "test session not found")
        run = learning.run_view(conn, records[0])
        return SuiteState(
            suite=learning.suite(conn, course_id, run.suite_id),
            latest_run=run,
            feedback=practice_support.feedback(conn, course_id, run.suite_id),
        )


@router.post(
    "/courses/{course_id}/practice/{suite_id}/questions/{index}/help",
    response_model=PracticeHelp,
)
def get_question_help(
    course_id: UUID, suite_id: UUID, index: int, payload: PracticeHelpRequest
) -> PracticeHelp:
    require_course(course_id)
    try:
        return practice_support.help_with(course_id, suite_id, index, payload)
    except LookupError as err:
        raise HTTPException(404, str(err)) from err
    except ProviderUnavailableError as err:
        raise HTTPException(503, str(err)) from err
    except ValueError as err:
        raise HTTPException(422, str(err)) from err


@router.put(
    "/courses/{course_id}/practice/{suite_id}/questions/{index}/feedback",
    response_model=list[ContentFeedback],
)
def rate_question_content(
    course_id: UUID, suite_id: UUID, index: int, payload: ContentFeedbackRequest
) -> list[ContentFeedback]:
    require_course(course_id)
    with connection() as conn:
        try:
            result = practice_support.rate(conn, course_id, suite_id, index, payload)
        except LookupError as err:
            raise HTTPException(404, str(err)) from err
        except ValueError as err:
            raise HTTPException(422, str(err)) from err
        conn.commit()
        return result


@router.delete("/courses/{course_id}/practice/runs/{run_id}", status_code=204)
def delete_run(course_id: UUID, run_id: UUID) -> None:
    require_course(course_id)
    with connection() as conn:
        if not learning.rows(conn, "delete_run", course_id=course_id, run_id=run_id):
            raise HTTPException(404, "test session not found")
        conn.commit()


@router.patch(
    "/courses/{course_id}/practice/{suite_id}/questions/{index}",
    response_model=SuiteState,
)
def correct_key(
    course_id: UUID, suite_id: UUID, index: int, payload: AssessmentCorrection
) -> SuiteState:
    require_course(course_id)
    with connection() as conn:
        try:
            learning.revise(
                conn, course_id, suite_id, index, payload.answer, payload.reason
            )
        except LookupError as err:
            raise HTTPException(404, str(err)) from err
        except ValueError as err:
            raise HTTPException(422, str(err)) from err
        conn.commit()
    return _state(course_id, suite_id)


@router.post("/courses/{course_id}/learning/forget", status_code=204)
def forget_target(course_id: UUID, payload: ForgetTarget) -> None:
    require_course(course_id)
    with connection() as conn:
        for name in ("forget_target", "forget_experiments"):
            conn.execute(
                get("learning", name), {"course_id": course_id, **payload.model_dump()}
            )
        learning.refresh_memory(conn, course_id)
        conn.commit()


@router.get("/learning/core", response_model=CoreMemory)
def inspect_core() -> CoreMemory:
    with connection() as conn:
        return learning.core(conn)


@router.put("/learning/core", response_model=CoreMemory)
def change_preference(payload: CorePreference) -> CoreMemory:
    settings_repo.put_setting("learning.preferred_method", payload.preferred_method)
    return inspect_core()


@router.delete("/learning/core/methods/{method}", status_code=204)
def forget_method(method: TeachingMethod) -> None:
    with connection() as conn:
        conn.execute(get("learning", "forget_method"), {"method": method})
        conn.commit()
