"""Connect Stacks to Microsoft Office and open documents there (desktop API).

The add-in itself talks to ``/office`` on its own HTTPS origin
(``api/office.py``); these endpoints are the Stacks app's side: set the
add-in up with one click, show whether it works, and launch Word, Excel
or PowerPoint with the Stacks pane ready for a course.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from src.backend.common import courses_repo
from src.backend.office_addin import service
from src.backend.office_addin.windows import OfficeApp

router = APIRouter(prefix="/office", tags=["office"])


class OfficeStatusView(BaseModel):
    supported: bool
    apps: list[OfficeApp]
    connected: bool
    ready: bool
    certificate_trusted: bool
    registered: bool
    running: bool
    url: str
    problems: list[str]


class OpenInOfficeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # A new document in this app, or ...
    app: OfficeApp | None = None
    # ... an existing document (its app follows from the extension).
    path: str | None = Field(default=None, max_length=4096)
    # The course the Stacks pane should open on.
    course_id: UUID | None = None


class OpenInOfficeView(BaseModel):
    app: OfficeApp
    # Office only picks up a newly registered add-in when it starts, so an
    # app that was already open needs a restart the first time.
    first_time: bool


def _view(current: service.OfficeStatus) -> OfficeStatusView:
    return OfficeStatusView(
        supported=current.supported,
        apps=current.apps,
        connected=current.connected,
        ready=current.ready,
        certificate_trusted=current.certificate_trusted,
        registered=current.registered,
        running=current.running,
        url=current.url,
        problems=current.problems,
    )


@router.get("/status", response_model=OfficeStatusView)
def office_status() -> OfficeStatusView:
    return _view(service.status())


@router.post("/connect", response_model=OfficeStatusView)
def connect_office() -> OfficeStatusView:
    try:
        return _view(service.connect())
    except service.OfficeSetupError as err:
        raise HTTPException(status.HTTP_409_CONFLICT, str(err)) from err


@router.post("/disconnect", response_model=OfficeStatusView)
def disconnect_office() -> OfficeStatusView:
    try:
        return _view(service.disconnect())
    except OSError as err:
        raise HTTPException(
            409, f"Could not finish disconnecting Office: {err}"
        ) from err


@router.post("/open", response_model=OpenInOfficeView)
def open_in_office(request: OpenInOfficeRequest) -> OpenInOfficeView:
    """Open Word, Excel or PowerPoint with the Stacks pane available,
    connecting Office first if it is not connected yet."""
    if (
        request.course_id is not None
        and courses_repo.get_course(request.course_id) is None
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")
    try:
        current = service.status()
        first_time = not current.registered
        if not current.ready:
            service.connect()
        app = service.open_document(
            request.app,
            Path(request.path) if request.path else None,
            request.course_id,
        )
    except service.OfficeSetupError as err:
        raise HTTPException(status.HTTP_409_CONFLICT, str(err)) from err
    return OpenInOfficeView(app=app, first_time=first_time)
