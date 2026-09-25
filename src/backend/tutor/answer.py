"""Tutor answer flow (decision 008 retrieval + Fork B/C leans).

Single-turn grounded Q&A (Fork D scope): retrieve against the course,
refuse when nothing relevant was found, otherwise assemble a prompt with
the cited chunks and generate through the provider seam. The citation
contract is the harness: the answer's evidence is exactly the chunk set
the retrieval trace recorded — auditors see what the model saw.

Strict refusal is the recorded lean (notes.md Fork B): an empty retrieval
returns a refusal, NOT an ungrounded answer. The provider-unavailable
case surfaces honestly too — no provider means no answers, and the
endpoint says so (503) rather than pretending.
"""

from __future__ import annotations

import dataclasses
from typing import Any
from uuid import UUID

from src.backend.common import provider
from src.backend.common.db import Connection
from src.backend.common.prompt_registry import strip_fence_echo
from src.backend.retrieval import funnel, rerank, trace
from src.backend.retrieval.config import RetrievalPolicy
from src.backend.tutor.compose import build_prompt as build_prompt
from src.backend.tutor.compose import compose_answer
from src.backend.tutor.workspace import (
    WorkspaceItem,
    extract_workspace_items,
)


class NothingRelevantFoundError(RuntimeError):
    """Retrieval produced no candidates for this question in this course.
    The tutor refuses rather than answering ungrounded (Fork B lean)."""


class Answer:
    """The grounded answer bundle: the raw generated text, the chat body
    with workspace blocks lifted out, the workspace items that passed the
    citation gate (and why any were withheld), per-chunk citations, and
    the trace the answer must be auditable against."""

    def __init__(
        self,
        text: str,
        chunk_ids: tuple[UUID, ...],
        trace_id: UUID,
        layer_contribution: dict[str, int],
        *,
        model: str = "",
        fell_back_to_local: bool = False,
    ) -> None:
        self.text = strip_fence_echo(text)
        self.chunk_ids = chunk_ids
        self.trace_id = trace_id
        self.layer_contribution = layer_contribution
        self.model = model
        self.fell_back_to_local = fell_back_to_local
        extracted = extract_workspace_items(self.text, len(chunk_ids))
        self.body = extracted.body
        self.workspace_items: tuple[WorkspaceItem, ...] = extracted.items
        self.withheld = extracted.withheld


def answer_question(
    conn: Connection,
    course_id: UUID,
    question: str,
    policy: RetrievalPolicy,
    *,
    query_embedding: list[float] | None = None,
    embedding_model: str | None = None,
    bigger: bool = False,
) -> Answer:
    """One grounded answer: retrieve, frame + generate (compose.py), then
    record the trace.

    The trace is written only after generation succeeds, so an answer
    that never happened leaves no evidence-shaped noise — and no write
    transaction is held open during the (possibly minutes-long, on a
    laptop) model call. The caller commits."""
    result = funnel.retrieve(
        conn,
        course_id,
        question,
        policy,
        query_embedding=query_embedding,
        embedding_model=embedding_model,
    )
    if not result.candidates:
        raise NothingRelevantFoundError(
            "nothing in the course materials matches this question"
        )
    calls: list[provider.GenerationResult] = []

    def generate(
        task: str, prompt: str, *, response_schema: dict[str, Any] | None = None
    ) -> str:
        generation = provider.generate(
            task,
            prompt,
            course_id=course_id,
            response_schema=response_schema,
            bigger=bigger,
        )
        calls.append(generation)
        return generation.text

    composed = compose_answer(
        question,
        result.candidates,
        generate,
        on_schema_rejected=lambda err: isinstance(
            err, provider.ProviderRequestRejectedError
        ),
        select=rerank.select_for_generation,
    )
    used = dataclasses.replace(result, candidates=composed.candidates)
    stored = trace.record_trace(
        conn,
        course_id,
        question,
        used,
        embedding_model=embedding_model,
        toc_entry_ids=result.matched_toc_entry_ids,
    )
    last = calls[-1]
    return Answer(
        text=composed.text,
        chunk_ids=tuple(c.chunk_id for c in composed.candidates),
        trace_id=stored.trace_id,
        layer_contribution=result.layer_contribution,
        model=last.model,
        fell_back_to_local=any(call.fell_back_to_local for call in calls),
    )
