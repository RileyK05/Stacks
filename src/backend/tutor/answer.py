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

from psycopg import Connection
from src.backend.common import provider
from src.backend.common.schemas.base import UserTier
from src.backend.retrieval import funnel, trace
from src.backend.retrieval.config import RetrievalPolicy
from src.backend.retrieval.funnel import Candidate


class NothingRelevantFoundError(RuntimeError):
    """Retrieval produced no candidates for this question in this course.
    The tutor refuses rather than answering ungrounded (Fork B lean)."""


class Answer:
    """The grounded answer bundle: text, per-chunk citations, and the
    trace the answer must be auditable against."""

    def __init__(
        self,
        text: str,
        chunk_ids: tuple[UUID, ...],
        trace_id: UUID,
        layer_contribution: dict[str, int],
    ) -> None:
        self.text = text
        self.chunk_ids = chunk_ids
        self.trace_id = trace_id
        self.layer_contribution = layer_contribution


def answer_question(
    conn: Connection,
    user_id: UUID,
    tier: UserTier,
    course_id: UUID,
    question: str,
    policy: RetrievalPolicy,
    *,
    query_embedding: list[float] | None = None,
    embedding_model: str | None = None,
) -> Answer:
    """One grounded answer. Same-transaction contract: retrieval, trace,
    and the billed provider call share `conn` so a failed generation
    rolls the trace back (an answer that never happened leaves no
    evidence-shaped noise)."""
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
    stored = trace.record_trace(
        conn, user_id, course_id, question, result,
        embedding_model=embedding_model,
        toc_entry_ids=result.matched_toc_entry_ids,
    )
    prompt = build_prompt(question, result.candidates)
    generation = provider.generate(
        "tutor_answer",
        prompt,
        user_id,
        tier,
        course_id=course_id,
    )
    return Answer(
        text=generation.text,
        chunk_ids=tuple(c.chunk_id for c in result.candidates),
        trace_id=stored.trace_id,
        layer_contribution=result.layer_contribution,
    )


def build_prompt(question: str, candidates: tuple[Candidate, ...]) -> str:
    """The grounded prompt: question + cited chunks with their locator
    ids. The instruction line carries the citation contract (Fork C
    working direction): every factual claim cites the locator it rests
    on; the model may only use the provided material."""
    blocks = [
        f"[{index + 1}] chunk {candidate.chunk_id}"
        f"\n{candidate.text}"
        for index, candidate in enumerate(candidates)
    ]
    evidence = "\n\n".join(blocks)
    return (
        "You are a course tutor. Answer the student's question using ONLY"
        " the numbered course material below. Cite the material you use as"
        " [n]. If the material does not contain the answer, say so"
        " plainly. Do not use outside knowledge.\n\n"
        f"Question: {question}\n\n"
        f"Course material:\n{evidence}"
    )