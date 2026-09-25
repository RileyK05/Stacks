"""Tutor API: grounded answers for a course.

POST /courses/{course_id}/ask — single-turn grounded Q&A (Fork D scope).
Strict refusal on empty retrieval (Fork B lean). Provider-unavailable
surfaces as an honest 503 and a reached cloud budget as a 402 — the
endpoint never pretends to answer.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from src.backend.common import courses_repo, provider, usage_repo
from src.backend.common.db import connection, json_ids
from src.backend.common.embeddings_config import load_embedding_policy
from src.backend.common.queries import get
from src.backend.retrieval.config import load_retrieval_policy
from src.backend.tutor import answer as tutor_answer
from src.backend.tutor.workspace import WorkspaceItem

router = APIRouter(prefix="/courses", tags=["tutor"])


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    # "Ask a bigger model": answer with the user's Settings → bigger-model
    # choice instead of their everyday one. Only ever set by the user.
    bigger_model: bool = False


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
        trace_id=str(result.trace_id),
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
    chunk_index: int
    text: str
    locator_type: str
    label: str
    description: str | None
    filename: str


def _require_course(course_id: UUID) -> None:
    if courses_repo.get_course(course_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")


@router.post("/{course_id}/ask", response_model=AnswerView)
def ask(course_id: UUID, payload: AskRequest) -> AnswerView:
    _require_course(course_id)
    try:
        # Embed before opening the connection: the model call is the slow
        # part and needs no database.
        query_embedding = provider.embed_query(payload.question)
        with connection() as conn:
            result = tutor_answer.answer_question(
                conn,
                course_id,
                payload.question,
                load_retrieval_policy(),
                query_embedding=query_embedding,
                embedding_model=load_embedding_policy().model,
                bigger=payload.bigger_model,
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
    _require_course(course_id)
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
    return [
        CitationView(
            chunk_id=str(row["chunk_id"]),
            chunk_index=row["chunk_index"],
            text=row["text"],
            locator_type=row["locator_type"],
            label=row["label"],
            description=row["description"],
            filename=row["filename"],
        )
        for row in rows
    ]
