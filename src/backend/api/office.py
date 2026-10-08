"""The Office add-in bridge (plan-notebook.md, "Bring Stacks to Office").

This is the local seam between a Microsoft Office task pane and the Stacks
backend. It is deliberately separate from the desktop API:

- It is served at ``/office`` on the add-in's own HTTPS origin
  (``office_addin/``), same-origin with the pane, because the task pane is a
  web page loaded by Microsoft Office and cannot hold the desktop shell's
  per-launch app token.
- Its own token (``APP_OFFICE_TOKEN``) guards it when configured; empty by
  default.
- It never serializes an Office file. Office owns the document and performs
  every mutation through its own API; this bridge carries text and actions
  in, and prose + citations back.

It exposes three things:

- ``GET /health`` — liveness + whether a token is required.
- ``GET /courses`` — the courses Stacks knows about, so the pane can pick
  the one the student is working in (``suggested``: the course Office was
  last opened from in Stacks).
- ``POST /process-selection`` — the first-spike echo (kept for
  compatibility; the round-trip contract the add-in was built around).
- ``POST /assist`` — real, course-grounded reasoning behind a pane action
  (explain / find / quiz / summarize): it retrieves from the course,
  answers through the provider seam, and returns citations the pane shows.
- ``POST /read`` — the redundant reader: merge the host's own scrape with
  an uploaded package breakdown and/or screenshot OCR, and report how much
  the methods agreed.
"""

from __future__ import annotations

import base64
import binascii
import hmac
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from pypdf.errors import PyPdfError
from src.backend.common import (
    courses_repo,
    provider,
    sources_repo,
    usage_repo,
    work_repo,
)
from src.backend.common.config import get_settings
from src.backend.common.db import connection
from src.backend.common.embeddings_config import load_embedding_policy
from src.backend.common.schemas.office_live import (
    LiveConnection,
    LivePolicyView,
    LivePoll,
    LivePollResult,
    LiveRegistration,
    RefreshCompletion,
    RefreshStatus,
)
from src.backend.common.schemas.work import (
    CritiqueResult,
    DocumentUpdate,
    EssayGenre,
    WorkAsk,
    WorkCitation,
    WorkCreate,
    WorkPackage,
    WorkPublish,
    WorkSession,
)
from src.backend.office_addin import live, preferences
from src.backend.office_reader.work_files import read_work_file
from src.backend.retrieval.config import load_retrieval_policy
from src.backend.tutor import answer as tutor_answer
from src.backend.tutor import office as office_tutor
from src.backend.tutor import work as work_tutor
from src.backend.tutor.office import NotAllowedError

router = APIRouter(tags=["office"])

OFFICE_TOKEN_HEADER = "X-Office-Token"


def require_office_token(
    x_office_token: Annotated[str | None, Header(alias=OFFICE_TOKEN_HEADER)] = None,
) -> None:
    """The Office bridge's own auth (mirrors ``api/deps.require_app_token``).

    Disabled when no token is configured (development, tests). When set, the
    add-in must echo it; this keeps another local program or web page from
    driving the bridge once tokens are in play."""
    expected = get_settings().office_bridge_token
    if not expected:
        return
    if x_office_token is None or not hmac.compare_digest(
        x_office_token.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "missing or invalid office token"
        )


class OfficeHealth(BaseModel):
    app: str
    version: str
    token_required: bool


class CourseSummary(BaseModel):
    course_id: str
    name: str
    source_count: int
    suggested: bool = False


class SelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The kind of document the selection came from. The first spike is
    # PowerPoint; the field keeps the contract open for Word/Excel.
    host: str = Field(min_length=1, max_length=40)
    # The selected text (may be empty). Bounded so a runaway selection cannot
    # be used to exhaust memory.
    text: str = Field(default="", max_length=100_000)
    # Optional course context the student is working in.
    course_id: str | None = Field(default=None, max_length=80)


class SelectionResult(BaseModel):
    # The text the host should put back, if any. None means "no change".
    text: str | None = None
    # A short human explanation shown in the pane.
    message: str = ""
    # Which backend produced this (echo now; the model later).
    engine: str = "echo"


class AssistRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: UUID
    action: Literal["explain", "find", "quiz", "summarize"]
    host: str = Field(min_length=1, max_length=40)
    # The text the student is looking at (a selection, a slide, a sheet
    # summary). Bounded for the same reason as the selection.
    context: str = Field(default="", max_length=100_000)
    # An optional free-text question that overrides or refines the action.
    instruction: str = Field(default="", max_length=2000)


class CitationBody(BaseModel):
    number: int
    chunk_id: str
    source_id: str
    filename: str
    label: str
    text: str


class OfficeCritiqueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: UUID
    session_id: UUID
    host: Literal["word"]
    request_id: UUID
    expected_revision: int = Field(ge=1)
    critic_score: int = Field(ge=10, le=100)
    essay_genre: EssayGenre
    instruction: str = Field(default="", max_length=2000)
    selection: str = Field(default="", max_length=4000)
    focus: Literal["draft", "unread"] = "draft"


class OfficeCritiqueResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["critique"] = "critique"
    text: str
    insert_text: str = ""
    citations: list[WorkCitation]
    critique: CritiqueResult
    model: str
    trace_id: str
    message: str = ""


class AssistResult(BaseModel):
    action: str
    text: str
    # What the pane may put back into the document when the student asks.
    insert_text: str
    citations: list[CitationBody]
    model: str
    trace_id: str
    message: str = ""


class ReadRequest(BaseModel):
    """The redundant reader: any subset of methods the host can supply.

    ``scrape`` is the host's own read of the live object; ``package_b64``
    is the real file's bytes; ``images_b64`` are PNG renders. Supplying
    more than one lets the bridge cross-check them and report agreement."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(min_length=1, max_length=40)
    kind: Literal["word", "excel", "powerpoint"] | None = None
    course_id: UUID | None = None
    # Scrape: JSON-ish list of {label, text} the host read directly.
    scrape: list[
        dict[
            Annotated[str, Field(max_length=80)],
            Annotated[str, Field(max_length=100_000)],
        ]
    ] = Field(default_factory=list, max_length=5000)
    # The downloaded package, base64-encoded (no data: prefix).
    package_b64: str | None = Field(default=None, max_length=55_924_056)
    # PNG page/slide renders, base64-encoded.
    images_b64: list[Annotated[str, Field(max_length=27_962_028)]] = Field(
        default_factory=list, max_length=40
    )


class ReadAgreement(BaseModel):
    method: str
    matched: int
    unique: int
    total: int


class ReadResult(BaseModel):
    host: str
    text: str
    methods: list[str]
    agreement: list[ReadAgreement]
    warnings: list[str]
    units: list[dict[str, str]]


@router.get("/health", response_model=OfficeHealth)
def office_health() -> OfficeHealth:
    from src.backend.version import APP_NAME, __version__

    return OfficeHealth(
        app=APP_NAME,
        version=__version__,
        token_required=bool(get_settings().office_bridge_token),
    )


@router.get(
    "/courses",
    response_model=list[CourseSummary],
    dependencies=[Depends(require_office_token)],
)
def list_courses() -> list[CourseSummary]:
    """The courses Stacks knows about, so the pane can let the student pick
    the one the document belongs to."""
    suggested = preferences.last_course()
    return [
        CourseSummary(
            course_id=str(course.course_id),
            name=course.name,
            source_count=len(sources_repo.list_sources(course.course_id)),
            suggested=str(course.course_id) == suggested,
        )
        for course in courses_repo.list_courses()
    ]


@router.post(
    "/process-selection",
    response_model=SelectionResult,
    dependencies=[Depends(require_office_token)],
)
def process_selection(request: SelectionRequest) -> SelectionResult:
    """The first-spike round trip: transform the host's selection.

    Kept as the ``STACKS TEST: <text>`` echo so the original round-trip
    contract still holds; real reasoning lives at ``/assist``.
    """
    if not request.text:
        return SelectionResult(
            text=None,
            message="Nothing selected. Select a text box, then try again.",
            engine="echo",
        )
    return SelectionResult(
        text=f"STACKS TEST: {request.text}",
        message=f"Echoed {len(request.text)} characters ({request.host}).",
        engine="echo",
    )


@router.post(
    "/assist",
    response_model=AssistResult,
    dependencies=[Depends(require_office_token)],
)
def assist(request: AssistRequest) -> AssistResult:
    """Course-grounded reasoning behind a pane action (second/third spike).

    Retrieves from the chosen course, answers with the model through the
    provider seam, and returns citations the pane renders. Refuses graded
    work and empty retrieval honestly (422/404), and surfaces an unavailable
    provider as 503."""
    if courses_repo.get_course(request.course_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")
    action = office_tutor.OfficeAction(request.action)
    try:
        query_embedding = tutor_answer.embed_search(
            f"{request.instruction}\n{request.context[:600]}".strip()
        )
        with connection() as conn:
            result = office_tutor.answer(
                conn,
                request.course_id,
                action,
                host=request.host,
                context=request.context,
                instruction=request.instruction,
                policy=load_retrieval_policy(),
                query_embedding=query_embedding,
                embedding_model=load_embedding_policy().model,
            )
            conn.commit()
    except office_tutor.NotAllowedError as err:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(err)) from err
    except office_tutor.UngroundedAnswerError as err:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(err)) from err
    except office_tutor.NothingRelevantFoundError as err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(err)) from err
    except provider.ProviderUnavailableError as err:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(err)) from err
    except usage_repo.BudgetExceededError as err:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, str(err)) from err
    return AssistResult(
        action=result.action.value,
        text=result.text,
        insert_text=result.insert_text,
        citations=[
            CitationBody(**office_tutor.citation_payload(citation))
            for citation in result.citations
        ],
        model=result.model,
        trace_id=result.trace_id,
        message=result.message,
    )


def _decode(value: str, *, what: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as err:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"{what} is not valid base64"
        ) from err


@router.post(
    "/read",
    response_model=ReadResult,
    dependencies=[Depends(require_office_token)],
)
def read_document(request: ReadRequest) -> ReadResult:
    """Merge the reading methods the host supplied.

    At least one method is required. The OOXML breakdown and screenshot OCR
    are optional and their failures are reported as warnings (so one bad
    method never sinks the others); a scrape alone is always enough to
    return text."""
    from src.backend.office_reader import (
        OcrUnavailableError,
        UnreadablePackageError,
        merge_reads,
        read_package,
        read_screens,
    )
    from src.backend.office_reader.models import SCRAPE, DocumentRead, TextUnit

    reads: list[DocumentRead] = []
    if request.scrape:
        units = tuple(
            TextUnit(label=item.get("label", "selection"), text=item.get("text", ""))
            for item in request.scrape
        )
        reads.append(DocumentRead(method=SCRAPE, host=request.host, units=units))
    if request.package_b64:
        if request.kind is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "kind is required to read a package",
            )
        data = _decode(request.package_b64, what="package_b64")
        try:
            reads.append(read_package(data, kind=request.kind, host=request.host))
        except UnreadablePackageError as err:
            reads.append(
                DocumentRead(
                    method="package",
                    host=request.host,
                    warnings=(str(err),),
                )
            )
    if request.images_b64:
        images = [_decode(image, what="images_b64") for image in request.images_b64]
        try:
            reads.append(read_screens(images, host=request.host))
        except (OcrUnavailableError, usage_repo.BudgetExceededError) as err:
            reads.append(
                DocumentRead(method="ocr", host=request.host, warnings=(str(err),))
            )
    if not reads:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "nothing to read: supply a scrape, a package, or images",
        )
    merged = merge_reads(reads)
    return ReadResult(
        host=merged.host,
        text=merged.text,
        methods=[read.method for read in merged.reads],
        agreement=[
            ReadAgreement(
                method=item.method,
                matched=item.matched,
                unique=item.unique,
                total=item.total,
            )
            for item in merged.agreement
        ],
        warnings=list(merged.warnings),
        units=[{"label": unit.label, "text": unit.text} for unit in merged.units],
    )


@router.post(
    "/work-document",
    response_model=WorkSession,
    dependencies=[Depends(require_office_token)],
)
def publish_work(request: WorkPublish) -> WorkSession:
    if courses_repo.get_course(request.course_id) is None:
        raise HTTPException(404, "course not found")
    try:
        with connection() as conn:
            session_id = request.session_id
            if session_id is None:
                work = work_repo.create(
                    conn,
                    request.course_id,
                    WorkCreate(title=request.document.title, purpose=request.purpose),
                )
                session_id = work.session_id
            document = request.document.model_copy(update={"origin": "office"})
            work = work_repo.update_document(
                conn,
                request.course_id,
                session_id,
                DocumentUpdate(
                    **document.model_dump(), expected_revision=request.expected_revision
                ),
                skip_unchanged=True,
            )
            conn.commit()
            return work
    except work_repo.WorkNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    except work_repo.WorkConflictError as err:
        raise HTTPException(409, str(err)) from err
    except ValueError as err:
        raise HTTPException(422, str(err)) from err


@router.post(
    "/critique",
    response_model=OfficeCritiqueResult,
    dependencies=[Depends(require_office_token)],
)
def critique_essay(request: OfficeCritiqueRequest) -> OfficeCritiqueResult:
    """Comment on a connected Word draft. The pane must not insert the result."""
    if courses_repo.get_course(request.course_id) is None:
        raise HTTPException(404, "course not found")
    try:
        reply = work_tutor.answer(
            request.course_id,
            request.session_id,
            WorkAsk(
                request_id=request.request_id,
                expected_revision=request.expected_revision,
                action="critique",
                instruction=request.instruction,
                selection=request.selection,
                critic_score=request.critic_score,
                essay_genre=request.essay_genre,
                focus=request.focus,
            ),
        )
    except work_repo.WorkNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    except work_repo.WorkConflictError as err:
        raise HTTPException(409, str(err)) from err
    except NotAllowedError as err:
        raise HTTPException(422, str(err)) from err
    except ValueError as err:
        raise HTTPException(422, str(err)) from err
    except provider.ProviderUnavailableError as err:
        raise HTTPException(503, str(err)) from err
    except usage_repo.BudgetExceededError as err:
        raise HTTPException(402, str(err)) from err
    if reply.critique is None:
        raise HTTPException(422, "The critique did not include a review.")
    return OfficeCritiqueResult(
        text=reply.text,
        insert_text="",
        citations=reply.citations,
        critique=reply.critique,
        model=reply.model,
        trace_id=reply.trace_id or "",
    )


@router.get(
    "/work/{session_id}",
    response_model=WorkSession,
    dependencies=[Depends(require_office_token)],
)
def get_work(session_id: UUID, course_id: UUID) -> WorkSession:
    if courses_repo.get_course(course_id) is None:
        raise HTTPException(404, "course not found")
    try:
        with connection() as conn:
            return work_repo.session(conn, course_id, session_id)
    except work_repo.WorkNotFoundError as err:
        raise HTTPException(404, str(err)) from err


@router.post(
    "/work-package",
    response_model=WorkSession,
    dependencies=[Depends(require_office_token)],
)
def publish_package(request: WorkPackage) -> WorkSession:
    data = _decode(request.package_b64, what="package_b64")
    try:
        document = read_work_file(request.filename, data)
    except (ValueError, OSError, PyPdfError) as err:
        raise HTTPException(
            422,
            "The Office document could not be read. Connect a text version instead.",
        ) from err
    document.external_id = request.external_id
    return publish_work(
        WorkPublish(
            course_id=request.course_id,
            session_id=request.session_id,
            expected_revision=request.expected_revision,
            purpose=request.purpose,
            document=document,
        )
    )


@router.get(
    "/live-policy",
    response_model=LivePolicyView,
    dependencies=[Depends(require_office_token)],
)
def live_policy() -> LivePolicyView:
    return live.policy_view()


@router.post(
    "/live", response_model=LiveConnection, dependencies=[Depends(require_office_token)]
)
def register_live(request: LiveRegistration) -> LiveConnection:
    if courses_repo.get_course(request.course_id) is None:
        raise HTTPException(404, "course not found")
    try:
        return live.BROKER.register(request)
    except work_repo.WorkNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    except live.LiveUnavailableError as err:
        raise HTTPException(409, str(err)) from err


@router.post(
    "/live/{connection_id}/poll",
    response_model=LivePollResult,
    dependencies=[Depends(require_office_token)],
)
def poll_live(connection_id: UUID, request: LivePoll) -> LivePollResult:
    try:
        return live.BROKER.poll(connection_id, request.external_id)
    except live.LiveUnavailableError as err:
        raise HTTPException(409, str(err)) from err


@router.post(
    "/live/{connection_id}/complete",
    response_model=RefreshStatus,
    dependencies=[Depends(require_office_token)],
)
def complete_live(connection_id: UUID, request: RefreshCompletion) -> RefreshStatus:
    try:
        return live.BROKER.complete(connection_id, request)
    except live.LiveUnavailableError as err:
        raise HTTPException(409, str(err)) from err


@router.delete(
    "/live/{connection_id}",
    status_code=204,
    dependencies=[Depends(require_office_token)],
)
def disconnect_live(connection_id: UUID) -> None:
    live.BROKER.disconnect(connection_id)
