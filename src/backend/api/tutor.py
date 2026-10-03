"""Tutor API: grounded answers for a course.

POST /courses/{course_id}/ask — single-turn grounded Q&A (Fork D scope).
Strict refusal on empty retrieval (Fork B lean). Provider-unavailable
surfaces as an honest 503 and a reached cloud budget as a 402 — the
endpoint never pretends to answer.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from src.backend.api.deps import require_course
from src.backend.common import provider, usage_repo
from src.backend.common.db import connection, json_ids
from src.backend.common.embeddings_config import load_embedding_policy
from src.backend.common.queries import get
from src.backend.retrieval.config import load_retrieval_policy
from src.backend.tutor import answer as tutor_answer
from src.backend.tutor import chat
from src.backend.tutor.compose import Intent, classify_intent
from src.backend.tutor.workspace import WorkspaceItem

router = APIRouter(prefix="/courses", tags=["tutor"])


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    # "Ask a bigger model": answer with the user's Settings → bigger-model
    # choice instead of their everyday one. Only ever set by the user.
    bigger_model: bool = False

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("write a question first")
        return value


class AnswerView(BaseModel):
    """`text` is the chat body: the answer with its ```workspace blocks
    lifted out. Blocks that passed the citation gate arrive as
    `workspace`; blocks that failed are named in `withheld` so the reader
    sees that something was generated and why it is not shown."""

    text: str
    chunk_ids: list[str]
    trace_id: str
    workspace: list[WorkspaceItem] = Field(default_factory=list)
    withheld: list[str] = Field(default_factory=list)
    model: str = ""
    # True when a rate-limited cloud provider fell back to the local model.
    fell_back_to_local: bool = False
    # True when this exact question was answered before on unchanged
    # material and the stored answer was returned.
    cached: bool = False
    # Answered by the Settings → "Bigger model" choice, at the user's request.
    bigger: bool = False


def answer_view(result: tutor_answer.Answer, *, bigger: bool = False) -> AnswerView:
    return AnswerView(
        text=result.body,
        chunk_ids=[str(cid) for cid in result.chunk_ids],
        trace_id=str(result.trace_id) if result.trace_id else "",
        workspace=list(result.workspace_items),
        withheld=list(result.withheld),
        model=result.model,
        fell_back_to_local=result.fell_back_to_local,
        cached=result.cached,
        bigger=bigger,
    )


class CitationView(BaseModel):
    """One cited chunk as the reader sees it: what the tutor read and
    where it came from (golden rule 1 — every answer shows its
    sources)."""

    chunk_id: str
    source_id: str
    chunk_index: int
    text: str
    locator_type: str
    label: str
    description: str | None
    filename: str
    partial: bool = False
    char_start: int | None = None
    char_end: int | None = None
    text_length: int | None = None
    generated_materials: list[dict[str, str | int]] = Field(default_factory=list)


class _Coverage(BaseModel):
    chunk_id: str
    partial: bool = False
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    text_length: int | None = Field(default=None, ge=0)
    generated_materials: list[dict[str, str | int]] = Field(default_factory=list)


@router.post("/{course_id}/ask", response_model=AnswerView)
def ask(course_id: UUID, payload: AskRequest) -> AnswerView:
    require_course(course_id)
    search = chat.retrieval_query(payload.question, None)
    overview = chat.wants_overview(payload.question, None)
    searches = not overview and classify_intent(payload.question) is not Intent.CHAT
    try:
        # Embed before opening the connection: the model call is the slow
        # part and needs no database.
        query_embedding = tutor_answer.embed_search(search) if searches else None
        with connection() as conn:
            result = tutor_answer.answer_question(
                conn,
                course_id,
                payload.question,
                load_retrieval_policy(),
                query_embedding=query_embedding,
                embedding_model=load_embedding_policy().model,
                bigger=payload.bigger_model,
                search_query=search,
                overview=overview,
            )
            conn.commit()
    except tutor_answer.NothingRelevantFoundError as err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(err)) from err
    except provider.ProviderUnavailableError as err:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(err)) from err
    except usage_repo.BudgetExceededError as err:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, str(err)) from err
    return answer_view(result, bigger=payload.bigger_model)


@router.get(
    "/{course_id}/traces/{trace_id}/citations",
    response_model=list[CitationView],
)
def trace_citations(course_id: UUID, trace_id: UUID) -> list[CitationView]:
    """The evidence behind one answer: chunk text + locator label +
    filename. The trace must belong to this course (a trace id from
    another course 404s)."""
    require_course(course_id)
    with connection() as conn:
        trace = conn.execute(
            get("retrieval_traces", "trace_for_course"),
            {"trace_id": trace_id, "course_id": course_id},
        ).fetchone()
        if trace is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "trace not found")
        payload = trace["retrieved_chunk_ids"]
        if not isinstance(payload, dict):
            payload = {}
        chunk_ids = [UUID(cid) for cid in payload.get("chunk_ids", [])]
        if not chunk_ids:
            return []
        rows = conn.execute(
            get("retrieval_traces", "chunks_with_locators_by_ids"),
            {"chunk_ids": json_ids(chunk_ids)},
        ).fetchall()
    coverage = {}
    for item in payload.get("per_chunk_layers", []) or []:
        try:
            parsed = _Coverage.model_validate(item)
        except ValidationError:
            continue
        coverage[parsed.chunk_id] = parsed
    result = []
    for row in rows:
        detail = coverage.get(str(row["chunk_id"]), _Coverage(chunk_id=""))
        start, end = detail.char_start, detail.char_end
        partial = (
            detail.partial
            and start is not None
            and end is not None
            and 0 <= start < end <= len(row["text"])
        )
        result.append(
            CitationView(
                chunk_id=str(row["chunk_id"]),
                source_id=str(row["source_id"]),
                chunk_index=row["chunk_index"],
                text=row["text"][start:end] if partial else row["text"],
                locator_type=row["locator_type"],
                label=row["label"],
                description=row["description"],
                filename=row["filename"],
                partial=partial,
                char_start=start if partial else None,
                char_end=end if partial else None,
                text_length=len(row["text"]),
                generated_materials=detail.generated_materials,
            )
        )
    return result
