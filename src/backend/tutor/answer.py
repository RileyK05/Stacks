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

from uuid import UUID

from src.backend.common import provider
from src.backend.common.db import Connection
from src.backend.common.prompt_registry import grounded_prompt, load_prompt
from src.backend.retrieval import funnel, trace
from src.backend.retrieval.config import RetrievalPolicy
from src.backend.retrieval.funnel import Candidate
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
        self.text = text
        self.chunk_ids = chunk_ids
        self.trace_id = trace_id
        self.layer_contribution = layer_contribution
        self.model = model
        self.fell_back_to_local = fell_back_to_local
        extracted = extract_workspace_items(text, len(chunk_ids))
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
) -> Answer:
    """One grounded answer: retrieve, generate, then record the trace.

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
    prompt = build_prompt(question, result.candidates)
    generation = provider.generate("tutor_answer", prompt, course_id=course_id)
    stored = trace.record_trace(
        conn,
        course_id,
        question,
        result,
        embedding_model=embedding_model,
        toc_entry_ids=result.matched_toc_entry_ids,
    )
    return Answer(
        text=generation.text,
        chunk_ids=tuple(c.chunk_id for c in result.candidates),
        trace_id=stored.trace_id,
        layer_contribution=result.layer_contribution,
        model=generation.model,
        fell_back_to_local=generation.fell_back_to_local,
    )


def build_prompt(question: str, candidates: tuple[Candidate, ...]) -> str:
    """The grounded prompt: question + cited chunks with their locator
    ids. The instruction line comes from the prompt registry (decision
    010) and carries the citation contract (Fork C working direction) +
    the three-zone steer (decision 009): every factual claim cites the
    locator it rests on; the model may only use the provided material;
    homework-fill requests steer to reasoning + practice. Course chunks
    are untrusted uploaded text, so the material and the question are
    fenced as data (input marking, the prompt-injection gate)."""
    blocks = [
        f"[{index + 1}] chunk {candidate.chunk_id}"
        f"\n{candidate.text}"
        for index, candidate in enumerate(candidates)
    ]
    evidence = "\n\n".join(blocks)
    instruction = load_prompt("tutor_answer")
    material = f"Question: {question}\n\nCourse material:\n{evidence}"
    return grounded_prompt(instruction, material)