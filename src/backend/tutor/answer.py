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
import hashlib
import logging
from collections.abc import Collection
from typing import Any
from uuid import UUID, uuid4

from src.backend.common import answer_cache, courses_repo, provider, providers
from src.backend.common.db import Connection, json_ids
from src.backend.common.learning_config import load_learning_policy
from src.backend.common.prompt_registry import (
    load_prompt,
    load_prompt_policy,
    strip_fence_echo,
)
from src.backend.common.queries import get
from src.backend.common.schemas.learning import PracticeQuestion
from src.backend.retrieval import funnel, rerank, trace
from src.backend.retrieval.config import RetrievalPolicy, load_rerank_policy
from src.backend.student_model import learning
from src.backend.tutor.compose import (
    AnswerMode,
    Intent,
    classify_intent,
    compose_answer,
    compose_chat,
)
from src.backend.tutor.compose import build_prompt as build_prompt
from src.backend.tutor.workspace import (
    QuizQuestion,
    WorkspaceItem,
    WorkspaceQuiz,
    extract_workspace_items,
)

logger = logging.getLogger(__name__)


def embed_search(text: str) -> list[float] | None:
    """The embedding of what to search for, or None when the embedding model
    cannot load: the course is then searched by keywords alone, so a missing
    model degrades the search instead of stopping every answer."""
    try:
        return provider.embed_query(text)
    except provider.ProviderUnavailableError:
        logger.warning(
            "embedding unavailable; searching by keywords only", exc_info=True
        )
        return None


class NothingRelevantFoundError(RuntimeError):
    """Retrieval produced no candidates for this question in this course.
    The tutor refuses rather than answering ungrounded (Fork B lean)."""


class Answer:
    """The grounded answer bundle: the raw generated text, the chat body
    with workspace blocks lifted out, the workspace items that passed the
    citation gate (and why any were withheld), per-chunk citations, and
    the trace the answer must be auditable against. Small talk has no
    material behind it, so no chunks and no trace (`trace_id` is None)."""

    def __init__(
        self,
        text: str,
        chunk_ids: tuple[UUID, ...],
        trace_id: UUID | None,
        layer_contribution: dict[str, int],
        *,
        model: str = "",
        fell_back_to_local: bool = False,
        cached: bool = False,
    ) -> None:
        self.text = strip_fence_echo(text)
        self.chunk_ids = chunk_ids
        self.trace_id = trace_id
        self.layer_contribution = layer_contribution
        self.model = model
        self.fell_back_to_local = fell_back_to_local
        self.cached = cached
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
    choice: providers.ProviderChoice | None = None,
    conversation: str = "",
    source_ids: Collection[UUID] | None = None,
    search_query: str | None = None,
    overview: bool = False,
) -> Answer:
    """One grounded answer: retrieve, frame + generate (compose.py), then
    record the trace.

    The trace is written only after generation succeeds, so an answer
    that never happened leaves no evidence-shaped noise — and no write
    transaction is held open during the (possibly minutes-long, on a
    laptop) model call. The caller commits.

    A plain question asked before, on unchanged material, with the same
    model and settings, is answered from the cache (common/answer_cache.py)
    without retrieval or generation.

    In a saved chat, `conversation` is the context block (tutor/chat.py),
    `search_query` what to retrieve with (a follow-up searched together
    with the previous question), `source_ids` the chat's source selection,
    and `choice` its pinned model. An answer that depends on the chat
    (context or a source selection) is neither read from nor written to
    the cache.

    Small talk ("hi", "echo hello") is answered without retrieval. With
    `overview`, the material is a spread of the course instead of the
    passages nearest to the question (funnel.overview)."""
    calls: list[provider.GenerationResult] = []
    focus, behavior, method = learning.adaptation(
        conn,
        course_id,
        question,
        source_ids=list(source_ids) if source_ids is not None else None,
    )
    teaching = "\n\n" + load_prompt("learning_adaptation")
    if behavior:
        teaching += "\nPresentation preference: " + behavior
    if focus:
        conversation = "\n\n".join(part for part in (conversation, focus) if part)

    def generate(
        task: str, prompt: str, *, response_schema: dict[str, Any] | None = None
    ) -> str:
        generation = _generate(
            task,
            prompt,
            course_id=course_id,
            response_schema=response_schema,
            bigger=bigger,
            choice=choice,
        )
        calls.append(generation)
        return generation.text

    if classify_intent(question) is Intent.CHAT:
        course = courses_repo.get_course(course_id)
        text = compose_chat(
            question,
            generate,
            conversation=conversation,
            course_name=course.name if course is not None else "",
            teaching=teaching,
        )
        return Answer(
            text=text,
            chunk_ids=(),
            trace_id=None,
            layer_contribution={},
            model=calls[-1].model,
            fell_back_to_local=any(call.fell_back_to_local for call in calls),
        )
    answer_mode = AnswerMode(providers.load_models_config().generation.answer_mode)
    cacheable = not conversation and source_ids is None
    cache = (
        _cache_slot(
            conn,
            course_id,
            question,
            policy,
            answer_mode,
            bigger=bigger,
            choice=choice,
            learning_fingerprint=hashlib.sha256(
                (teaching + load_learning_policy().version).encode()
            ).hexdigest(),
        )
        if cacheable
        else None
    )
    if cache is not None:
        hit = answer_cache.lookup(conn, cache.key)
        if hit is not None:
            return Answer(
                text=hit.text,
                chunk_ids=hit.chunk_ids,
                trace_id=hit.trace_id,
                layer_contribution={},
                model=hit.model,
                cached=True,
            )
    generation_k = load_rerank_policy().generation_k
    result = None
    if overview:
        result = funnel.overview(
            conn,
            course_id,
            generation_k,
            embedding_model=embedding_model,
            source_ids=source_ids,
        )
        # Nothing embedded to spread over: search by the words as usual.
        overview = bool(result.candidates)
    if not overview:
        result = funnel.retrieve(
            conn,
            course_id,
            search_query or question,
            policy,
            query_embedding=query_embedding,
            embedding_model=embedding_model,
            source_ids=source_ids,
        )
    assert result is not None
    if not result.candidates:
        raise NothingRelevantFoundError(
            "nothing in the course materials matches this question"
        )

    composed = compose_answer(
        question,
        result.candidates,
        generate,
        on_schema_rejected=lambda err: isinstance(
            err, provider.ProviderRequestRejectedError
        ),
        # A spread of the course is already chosen and ordered: re-ranking it
        # against "make me a study guide" would only shuffle it.
        select=(
            (lambda _question, candidates: candidates[:generation_k])
            if overview
            else rerank.select_for_generation
        ),
        answer_mode=answer_mode,
        conversation=conversation,
        teaching=teaching,
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
    answer = Answer(
        text=composed.text,
        chunk_ids=tuple(c.chunk_id for c in composed.candidates),
        trace_id=stored.trace_id,
        layer_contribution=result.layer_contribution,
        model=last.model,
        fell_back_to_local=any(call.fell_back_to_local for call in calls),
    )
    evidence = learning.evidence_for(conn, answer.chunk_ids)
    current_sources = {str(row["source_id"]) for row in evidence}
    previous_teaching = next(
        (
            event
            for event in learning.rows(conn, "teaching_events", course_id=course_id)
            if current_sources.intersection(event["source_ids"])
        ),
        None,
    )
    previous_method = previous_teaching["method"] if previous_teaching else None
    items = []
    for item in answer.workspace_items:
        if isinstance(item, WorkspaceQuiz):
            selected = learning.allocate_questions(
                conn,
                course_id,
                question,
                [
                    PracticeQuestion.model_validate(q.model_dump(exclude_none=True))
                    for q in item.questions
                ],
                source_ids=[UUID(cid) for cid in current_sources],
            )
            if not selected:
                answer.withheld = (
                    *answer.withheld,
                    "No fresh questions fit the current practice plan.",
                )
                answer.body = (
                    "I couldn't create fresh, supported questions for this request. "
                    "Try another topic or a broader source selection."
                )
                continue
            item = item.model_copy(
                update={
                    "questions": [
                        QuizQuestion.model_validate(q.model_dump()) for q in selected
                    ]
                }
            )
            suite_id = learning.create_suite(
                conn,
                course_id,
                item.title or "Practice test",
                selected,
                answer.chunk_ids,
                {
                    "trace_id": str(stored.trace_id),
                    "teaching_context": previous_teaching,
                },
                previous_method,
            )
            item = item.model_copy(update={"practice_id": suite_id})
        items.append(item)
    answer.workspace_items = tuple(items)
    if method and not any(isinstance(item, WorkspaceQuiz) for item in items):
        conn.execute(
            get("learning", "teach"),
            {
                "event_id": uuid4(),
                "course_id": course_id,
                "method": method,
                "source_ids": json_ids(current_sources),
                "trace_ref": stored.trace_id,
                "excerpt": answer.body[:2000],
            },
        )
    if (
        cache is not None
        and not answer.fell_back_to_local
        and not answer.workspace_items
    ):
        answer_cache.store(
            conn,
            key=cache.key,
            course_id=course_id,
            fingerprint=cache.fingerprint,
            trace_id=stored.trace_id,
            text=composed.text,
            chunk_ids=answer.chunk_ids,
            model=answer.model,
        )
    return answer


_CUT_OFF_RETRY = (
    "\n\nYour previous reply was cut off for length. Reply again, much more briefly."
)


def _generate(task: str, prompt: str, **options: Any) -> provider.GenerationResult:
    """One model call, with one automatic second try for the two failures a
    second try often fixes and the student cannot: a reply with no text
    (common with small and free models) and one cut off at the output limit."""
    try:
        return provider.generate(task, prompt, **options)
    except provider.EmptyModelError:
        return provider.generate(task, prompt, **options)
    except provider.ModelOutputTruncatedError:
        return provider.generate(task, prompt + _CUT_OFF_RETRY, **options)


@dataclasses.dataclass(frozen=True)
class _CacheSlot:
    key: str
    fingerprint: str


def _cache_slot(
    conn: Connection,
    course_id: UUID,
    question: str,
    policy: RetrievalPolicy,
    answer_mode: AnswerMode,
    *,
    bigger: bool,
    choice: providers.ProviderChoice | None = None,
    learning_fingerprint: str = "",
) -> _CacheSlot | None:
    """The cache key for this question, or None when it must not be cached
    (a workspace request, or no endpoint configured to key it on)."""
    if classify_intent(question) not in (Intent.ANSWER, Intent.GRADED):
        return None
    if choice is not None and not bigger:
        endpoint = providers.resolve_choice(choice)
    else:
        endpoint = providers.resolve(
            providers.TaskClass.BIGGER if bigger else providers.TaskClass.INTERACTIVE
        )
    if endpoint is None:
        return None
    fingerprint = answer_cache.course_fingerprint(conn, course_id)
    key = answer_cache.cache_key(
        course_id=course_id,
        fingerprint=fingerprint,
        question=question,
        endpoint=endpoint,
        versions={
            "prompts": load_prompt_policy().prompts_config_version,
            "retrieval": policy.retrieval_config_version,
            "models": providers.load_models_config().models_config_version,
            "answer_mode": answer_mode.value,
            "learning": learning_fingerprint,
        },
    )
    return _CacheSlot(key=key, fingerprint=fingerprint)
