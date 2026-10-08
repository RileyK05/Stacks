"""Choose and order the chunks a model will read (plan §5.3, §6.4).

Fusion finds candidates; this decides what goes in the prompt: every
candidate is scored against the question by a cross-encoder, the best
come first, and only `generation_k` are kept. Fails open: if the reranker
cannot load, the fused order is kept (trimmed) and the answer still
happens.
"""

from __future__ import annotations

import logging
import math
from dataclasses import replace

from src.backend.common import provider
from src.backend.rag.config import load_policy as load_passage_policy
from src.backend.rag.segment import windows
from src.backend.retrieval.config import RerankPolicy, load_rerank_policy
from src.backend.retrieval.funnel import Candidate

logger = logging.getLogger(__name__)


def select_for_generation(
    question: str,
    candidates: tuple[Candidate, ...],
    policy: RerankPolicy | None = None,
) -> tuple[Candidate, ...]:
    policy = policy or load_rerank_policy()
    candidates = bound_passages(candidates)
    anchors = tuple(c for c in candidates if not c.context_for)
    context = tuple(c for c in candidates if c.context_for)
    if not policy.enabled or len(anchors) <= 1:
        return _with_context(anchors[: policy.generation_k], context)
    try:
        scores = provider.rerank_scores(
            policy.model, question, [candidate.text for candidate in anchors]
        )
        if len(scores) != len(anchors) or not all(
            math.isfinite(float(score)) for score in scores
        ):
            raise ValueError("reranker returned invalid scores")
    except Exception:
        logger.exception(
            "reranker unavailable or returned invalid scores; keeping fused order"
        )
        return _with_context(anchors[: policy.generation_k], context)
    ranked = sorted(
        zip(scores, range(len(anchors)), anchors, strict=True),
        key=lambda item: (-item[0], item[1]),
    )
    chosen = tuple(candidate for _score, _i, candidate in ranked[: policy.generation_k])
    return _with_context(chosen, context)


def _with_context(
    anchors: tuple[Candidate, ...], context: tuple[Candidate, ...]
) -> tuple[Candidate, ...]:
    ordered: list[Candidate] = []
    seen = set()
    remaining = load_passage_policy().generation_material_tokens
    for anchor in anchors:
        cost = _count(anchor.text)
        if cost > remaining:
            continue
        remaining -= cost
        group = [anchor]
        seen.add(anchor.chunk_id)
        related = sorted(
            (c for c in context if anchor.chunk_id in c.context_for),
            key=lambda c: (abs(c.chunk_index - anchor.chunk_index), c.chunk_index),
        )
        for candidate in related:
            if candidate.chunk_id not in seen:
                cost = _count(candidate.text)
                if cost > remaining:
                    continue
                remaining -= cost
                group.append(candidate)
                seen.add(candidate.chunk_id)
        ordered.extend(sorted(group, key=lambda c: c.chunk_index))
    return tuple(ordered)


def _count(value: str) -> int:
    try:
        return provider.embedding_token_count(value)
    except provider.ProviderUnavailableError:
        return len(value.encode("utf-8")) + 2


def material_budget(candidates: tuple[Candidate, ...]) -> tuple[Candidate, ...]:
    remaining = load_passage_policy().generation_material_tokens
    result = []
    for candidate in candidates:
        cost = _count(candidate.text)
        if cost > remaining:
            continue
        remaining -= cost
        result.append(candidate)
    return tuple(result)


def bound_passages(
    candidates: tuple[Candidate, ...], *, max_tokens: int | None = None
) -> tuple[Candidate, ...]:
    policy = load_passage_policy()
    limit = min(
        max_tokens or policy.retrieved_passage_tokens, policy.retrieved_passage_tokens
    )
    bounded = []

    for candidate in candidates:
        if _count(candidate.text) <= limit:
            bounded.append(candidate)
            continue
        # A whole passage carries its full chunk text and `window_start` is the
        # cursor to window from; a partial already holds only its window.
        base = candidate.window_start if candidate.partial else 0
        start = 0 if candidate.partial else candidate.window_start
        spans = windows(
            candidate.text[start:],
            limit,
            0,
            token_count=_count,
            max_windows=1,
        )
        if not spans:
            bounded.append(candidate)
            continue
        end = start + spans[0][1]
        bounded.append(
            replace(
                candidate,
                text=candidate.text[start:end],
                window_start=base + start,
                window_end=base + end,
                text_length=candidate.text_length or len(candidate.text),
                partial=True,
            )
        )
    return tuple(bounded)
