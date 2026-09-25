"""Choose and order the chunks a model will read (plan §5.3, §6.4).

Fusion finds candidates; this decides what goes in the prompt: every
candidate is scored against the question by a cross-encoder, the best
come first, and only `generation_k` are kept. Fails open: if the reranker
cannot load, the fused order is kept (trimmed) and the answer still
happens.
"""

from __future__ import annotations

import logging

from src.backend.common import provider
from src.backend.retrieval.config import RerankPolicy, load_rerank_policy
from src.backend.retrieval.funnel import Candidate

logger = logging.getLogger(__name__)


def select_for_generation(
    question: str,
    candidates: tuple[Candidate, ...],
    policy: RerankPolicy | None = None,
) -> tuple[Candidate, ...]:
    policy = policy or load_rerank_policy()
    if not policy.enabled or len(candidates) <= 1:
        return candidates[: policy.generation_k]
    try:
        scores = provider.rerank_scores(
            policy.model, question, [candidate.text for candidate in candidates]
        )
    except Exception:
        logger.exception("reranker unavailable; keeping fused order")
        return candidates[: policy.generation_k]
    ranked = sorted(
        zip(scores, range(len(candidates)), candidates, strict=True),
        key=lambda item: (-item[0], item[1]),
    )
    return tuple(candidate for _score, _i, candidate in ranked[: policy.generation_k])
