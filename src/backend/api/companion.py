"""Authenticated desktop API for the optional Stacks companion."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from src.backend.api import office
from src.backend.api.deps import require_course
from src.backend.common import provider, usage_repo, work_repo
from src.backend.common.companion_config import load_companion_policy
from src.backend.common.db import connection
from src.backend.common.queries import get
from src.backend.common.schemas.work import (
    DocumentInput,
    DocumentUpdate,
    WorkAsk,
    WorkCreate,
    WorkReply,
    WorkSession,
    WorkSummary,
)
from src.backend.office_reader import capture as capture_reader
from src.backend.office_reader.screens import OcrUnavailableError
from src.backend.office_reader.work_files import read_work_file
from src.backend.tutor import work as work_tutor
from src.backend.tutor.office import NotAllowedError
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/companion", tags=["companion"])


@router.post("/assist", response_model=office.AssistResult)
def assist(request: office.AssistRequest) -> office.AssistResult:
    """Run the same grounded document action used by the Office pane.

    The companion is part of the authenticated desktop app, while the Office
    pane reaches the equivalent operation through its separate HTTPS bridge.
    Keeping one request and response contract makes answers and citations
    consistent between both surfaces.
    """
    return office.assist(request)


@router.get("/windows", response_model=list[capture_reader.CaptureWindow])
def windows() -> list[capture_reader.CaptureWindow]:
    try:
        return capture_reader.list_windows()
    except capture_reader.CaptureUnavailableError as err:
        raise HTTPException(503, str(err)) from err


@router.post("/capture", response_model=DocumentInput)
def capture_window(request: capture_reader.CaptureWindow) -> DocumentInput:
    try:
        return capture_reader.capture(request)
    except (capture_reader.CaptureUnavailableError, OcrUnavailableError) as err:
        raise HTTPException(503, str(err)) from err
    except usage_repo.BudgetExceededError as err:
        raise HTTPException(402, str(err)) from err


@router.get("/courses/{course_id}/work", response_model=list[WorkSummary])
def list_work(course_id: UUID) -> list[WorkSummary]:
    require_course(course_id)
    with connection() as conn:
        return work_repo.list_sessions(conn, course_id)


@router.post("/courses/{course_id}/work", response_model=WorkSession)
def create_work(course_id: UUID, request: WorkCreate) -> WorkSession:
    require_course(course_id)
    with connection() as conn:
        work = work_repo.create(conn, course_id, request)
        conn.commit()
        return work


@router.get("/courses/{course_id}/work/{session_id}", response_model=WorkSession)
def get_work(course_id: UUID, session_id: UUID) -> WorkSession:
    require_course(course_id)
    try:
        with connection() as conn:
            return work_repo.session(conn, course_id, session_id)
    except work_repo.WorkNotFoundError as err:
        raise HTTPException(404, str(err)) from err


@router.put(
    "/courses/{course_id}/work/{session_id}/document", response_model=WorkSession
)
def connect_document(
    course_id: UUID, session_id: UUID, request: DocumentUpdate
) -> WorkSession:
    require_course(course_id)
    try:
        with connection() as conn:
            work = work_repo.update_document(conn, course_id, session_id, request)
            conn.commit()
            return work
    except work_repo.WorkNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    except work_repo.WorkConflictError as err:
        raise HTTPException(409, str(err)) from err
    except ValueError as err:
        raise HTTPException(422, str(err)) from err


@router.post("/courses/{course_id}/work/{session_id}/file", response_model=WorkSession)
async def connect_file(
    course_id: UUID,
    session_id: UUID,
    expected_revision: Annotated[int, Form(ge=0)],
    file: Annotated[UploadFile, File()],
) -> WorkSession:
    require_course(course_id)
    data = await file.read(load_companion_policy().max_upload_bytes + 1)
    try:
        document = await run_in_threadpool(
            read_work_file, file.filename or "Document", data
        )
    except Exception as err:
        raise HTTPException(
            422,
            "The file could not be read. "
            + (
                str(err)
                if isinstance(err, ValueError)
                else "Connect a text version instead."
            ),
        ) from err
    finally:
        await file.close()
    return connect_document(
        course_id,
        session_id,
        DocumentUpdate(**document.model_dump(), expected_revision=expected_revision),
    )


@router.post("/courses/{course_id}/work/{session_id}/ask", response_model=WorkReply)
def ask_work(course_id: UUID, session_id: UUID, request: WorkAsk) -> WorkReply:
    require_course(course_id)
    try:
        return work_tutor.answer(course_id, session_id, request)
    except work_repo.WorkNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    except work_repo.WorkConflictError as err:
        raise HTTPException(409, str(err)) from err
    except (ValueError, NotAllowedError) as err:
        raise HTTPException(422, str(err)) from err
    except provider.ProviderUnavailableError as err:
        raise HTTPException(503, str(err)) from err
    except usage_repo.BudgetExceededError as err:
        raise HTTPException(402, str(err)) from err


@router.delete("/courses/{course_id}/work/{session_id}")
def delete_work(course_id: UUID, session_id: UUID) -> dict[str, bool]:
    get_work(course_id, session_id)
    with connection() as conn:
        conn.execute(
            get("work", "delete"), {"session_id": session_id, "course_id": course_id}
        )
        conn.commit()
    return {"deleted": True}
