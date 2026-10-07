"""Grounded reasoning for the Office add-in (plan-notebook.md, "Bring
Stacks to Office" — second and third spikes).

The task pane is a thin client: it sends the text the student is looking at
(a selection, or a whole slide/sheet/document summary) and an action, and
this module answers from the student's actual course. It reuses the same
seams the built-in tutor does — ``funnel.retrieve`` for course material,
``provider.generate`` for the model call, ``trace.record_trace`` for the
audit record — so an answer in Word is as grounded and as inspectable as an
answer in Stacks.

Two rules carry over from the desktop product:

- **Source grounding is sacred.** Every answer is written from numbered
  course chunks and cites them by number. The citations are returned as
  real ``CitationView`` rows (chunk text + locator) so the pane can show
  them, never as opaque numbers.
- **No graded work.** A request to do the student's graded work is refused
  by the same graded-work classifier the tutor uses (``compose.py``).

The result is a small, typed bundle the bridge serializes to JSON. No
OOXML is ever produced here: the host owns the document and performs every
mutation itself; Stacks only returns text.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from src.backend.common import provider
from src.backend.common.citations import cited_numbers
from src.backend.common.db import Connection, json_ids
from src.backend.common.prompt_registry import (
    grounded_prompt,
    load_prompt,
    strip_fence_echo,
)
from src.backend.common.providers import ProviderChoice
from src.backend.common.queries import get
from src.backend.retrieval import funnel, rerank, trace
from src.backend.retrieval.config import RetrievalPolicy
from src.backend.retrieval.labels import attach_passage_context, candidate_label
from src.backend.student_model import learning
from src.backend.tutor.compose import Intent, classify_intent, numbered_passages

# How much of the host's text is searched with and shown to the model. A
# whole slide is small; a pasted document is bounded so a runaway selection
# cannot blow the context window or the prompt fence.
MAX_CONTEXT_CHARS = 8000


class OfficeAction(StrEnum):
    """What the student asked the pane to do with the looked-at text."""

    EXPLAIN = "explain"
    FIND = "find"
    QUIZ = "quiz"
    SUMMARIZE = "summarize"


class NothingRelevantFoundError(RuntimeError):
    """Retrieval found nothing for this text in this course (Fork B lean:
    refuse rather than answer ungrounded)."""


class NotAllowedError(RuntimeError):
    """The request is graded work (write my essay/answer), which Stacks
    never does for the student."""


class UngroundedAnswerError(ValueError):
    """The model cited a passage number it was not given."""


@dataclass(frozen=True)
class Citation:
    """One cited chunk: what the model read and where it came from."""

    number: int
    chunk_id: str
    source_id: str
    filename: str
    label: str
    text: str


@dataclass(frozen=True)
class OfficeAnswer:
    """The grounded reply the pane renders and may insert into the host.

    ``text`` is Markdown with ``[n]`` citations; ``citations`` resolves each
    n; ``insert_text`` is what to put back into the document when the
    student chooses to (same as ``text`` for now, kept separate so a future
    action can propose a plain-text form distinct from the chat view).
    ``trace_id`` is the stored retrieval trace behind the answer."""

    action: OfficeAction
    text: str
    insert_text: str
    citations: tuple[Citation, ...]
    model: str
    trace_id: str
    message: str = ""


_PROMPTS: dict[OfficeAction, str] = {
    OfficeAction.EXPLAIN: "office_explain",
    OfficeAction.FIND: "office_find",
    OfficeAction.QUIZ: "office_quiz",
    OfficeAction.SUMMARIZE: "office_summarize",
}

# A graded-work request never gets a real answer, whatever the action.
_GRADED = re.compile(
    r"\b(?:write|do|solve|complete|answer)\b[^.]{0,40}"
    r"\b(?:my|the|this)\b[^.]{0,20}"
    r"\b(?:essay|paper|exam|test|assignment|homework|problem set|quiz)\b"
    r"|\bfill in (?:all )?(?:of )?(?:the|my) answers\b"
    r"|\bso (?:i|that i) can (?:submit|hand (?:it )?in|turn (?:it )?in)\b",
    re.IGNORECASE,
)


def _context(text: str) -> str:
    clean = " ".join(text.split())
    if len(clean) <= MAX_CONTEXT_CHARS:
        return clean
    return clean[:MAX_CONTEXT_CHARS].rsplit(" ", 1)[0] + "…"


def _query(action: OfficeAction, context: str, instruction: str) -> str:
    """The string to retrieve with. A free-text instruction (the student's
    question) leads; otherwise the context itself is the query."""
    instruction = instruction.strip()
    if instruction:
        return f"{instruction}\n{context[:600]}"
    return context[:2000] or f"{action.value} this"


def is_graded_request(instruction: str, context: str) -> bool:
    """Whether this looks like a request to do graded work (the tutor's own
    graded classifier plus a direct instruction scan. An explicit request
    controls intent; selected document text is context and may describe an
    assignment the student wants explained. With no instruction, retain the
    conservative context-only refusal."""
    probe = instruction.strip() or context
    return classify_intent(probe) is Intent.GRADED or bool(_GRADED.search(probe))


def _citations(
    conn: Connection,
    candidates: Sequence[funnel.Candidate],
    markers: set[int] | None = None,
) -> tuple[Citation, ...]:
    chunk_ids = [c.chunk_id for c in candidates]
    if not chunk_ids:
        return ()
    rows = conn.execute(
        get("retrieval_traces", "chunks_with_locators_by_ids"),
        {"chunk_ids": json_ids(list(chunk_ids))},
    ).fetchall()
    by_id = {row["chunk_id"]: row for row in rows}
    citations: list[Citation] = []
    for number, candidate in enumerate(candidates, start=1):
        if markers is not None and number not in markers:
            continue
        chunk_id = candidate.chunk_id
        row = by_id.get(chunk_id)
        if row is None:
            continue
        citations.append(
            Citation(
                number=number,
                chunk_id=str(chunk_id),
                source_id=str(row["source_id"]),
                filename=row["filename"],
                label=(candidate_label(candidate, row["label"] or "") or row["label"])
                + (" · partial passage" if candidate.partial else ""),
                text=candidate.text,
            )
        )
    return tuple(citations)


def answer(
    conn: Connection,
    course_id: UUID,
    action: OfficeAction,
    *,
    host: str,
    context: str,
    instruction: str = "",
    policy: RetrievalPolicy,
    query_embedding: list[float] | None = None,
    embedding_model: str | None = None,
    choice: ProviderChoice | None = None,
) -> OfficeAnswer:
    """Ground one Office-pane request in the course and answer it.

    Writes the retrieval trace (the caller commits) so the answer is as
    auditable as one from the built-in tutor. Raises
    ``NothingRelevantFoundError`` when the course has nothing to say, and
    ``NotAllowedError`` for graded work — the pane surfaces both honestly.
    """
    if is_graded_request(instruction, context):
        raise NotAllowedError(
            "Stacks helps you understand your material, but it won't do graded "
            "work you'll submit. Ask it to explain the ideas instead."
        )
    if not context.strip() and not instruction.strip():
        raise NothingRelevantFoundError("there was nothing selected to look at")

    query = _query(action, _context(context), instruction)
    result = funnel.retrieve(
        conn,
        course_id,
        query,
        policy,
        query_embedding=query_embedding,
        embedding_model=embedding_model,
    )
    if not result.candidates:
        raise NothingRelevantFoundError(
            "nothing in this course's materials matches what you selected"
        )
    result = dataclasses.replace(
        result, candidates=attach_passage_context(conn, result.candidates)
    )
    candidates = rerank.select_for_generation(query, result.candidates)
    numbered = numbered_passages(candidates)
    host_label = host.strip() or "the document"
    looked_at = _context(context) or "(nothing selected)"
    request = instruction.strip() or "(none — use the action)"
    material = (
        f"Application: {host_label}\n"
        f"Text the student is looking at:\n{looked_at}\n\n"
        f"Student's request: {request}\n\n"
        f"Course material:\n{numbered}"
    )
    focus, behavior, _ = learning.adaptation(
        conn,
        course_id,
        instruction or context,
        source_ids=list({c.source_id for c in candidates}),
    )
    if focus:
        material += f"\n\nStudent focus observations:\n{focus}"
    prompt = grounded_prompt(
        load_prompt(_PROMPTS[action])
        + load_prompt("learning_adaptation")
        + "\n"
        + behavior,
        material,
    )
    generation = provider.generate(
        "tutor_answer", prompt, course_id=course_id, choice=choice
    )
    text = strip_fence_echo(generation.text)
    markers = cited_numbers(text)
    if any(number < 1 or number > len(candidates) for number in markers):
        raise UngroundedAnswerError("the answer cited source material it was not given")
    used = dataclasses.replace(result, candidates=tuple(candidates))
    stored = trace.record_trace(
        conn,
        course_id,
        query,
        used,
        embedding_model=embedding_model,
        cited=tuple(
            (candidate.chunk_id, number)
            for number, candidate in enumerate(candidates, start=1)
            if number in markers
        ),
    )
    cited = _citations(conn, candidates, markers)
    return OfficeAnswer(
        action=action,
        text=text,
        insert_text=text,
        citations=cited,
        model=generation.model,
        trace_id=str(stored.trace_id),
    )


def citation_payload(citation: Citation) -> dict[str, Any]:
    """A citation as the pane's JSON wants it (mirrors ``tutor.CitationView``)."""
    return {
        "number": citation.number,
        "chunk_id": citation.chunk_id,
        "source_id": citation.source_id,
        "filename": citation.filename,
        "label": citation.label,
        "text": citation.text,
    }
