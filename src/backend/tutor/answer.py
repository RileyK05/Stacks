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
from collections.abc import Collection
from typing import Any
from uuid import UUID

from src.backend.common import answer_cache, provider, providers
from src.backend.common.db import Connection
from src.backend.common.prompt_registry import (
    load_prompt_policy,
    strip_fence_echo,
)
from src.backend.retrieval import funnel, rerank, trace
from src.backend.retrieval.config import RetrievalPolicy
from src.backend.tutor.compose import (
    AnswerMode,
    Intent,
    classify_intent,
    compose_answer,
)
from src.backend.tutor.compose import build_prompt as build_prompt
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
    the cache."""
    answer_mode = AnswerMode(providers.load_models_config().generation.answer_mode)
    cacheable = not conversation and source_ids is None
    cache = (
        _cache_slot(
            conn, course_id, question, policy, answer_mode, bigger=bigger, choice=choice
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
    result = funnel.retrieve(
        conn,
        course_id,
        search_query or question,
        policy,
        query_embedding=query_embedding,
        embedding_model=embedding_model,
        source_ids=source_ids,
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
            choice=choice,
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
        answer_mode=answer_mode,
        conversation=conversation,
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
            trace_id=answer.trace_id,
            text=composed.text,
            chunk_ids=answer.chunk_ids,
            model=answer.model,
        )
    return answer


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
        },
    )
    return _CacheSlot(key=key, fingerprint=fingerprint)
