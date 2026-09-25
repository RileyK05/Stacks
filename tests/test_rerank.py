from uuid import uuid4

import pytest
from src.backend.common import provider
from src.backend.retrieval.config import RerankPolicy, load_rerank_policy
from src.backend.retrieval.funnel import Candidate
from src.backend.retrieval.rerank import select_for_generation


def _candidate(text: str, index: int) -> Candidate:
    return Candidate(
        chunk_id=uuid4(),
        source_id=uuid4(),
        locator_id=uuid4(),
        chunk_index=index,
        text=text,
        layers=frozenset({"keyword"}),
        rank=1.0,
    )


TEXTS = (
    "the reading covers pan-ethnicity",
    "office hours are on tuesdays",
    "the final exam is worth forty percent of the final grade",
)


def _policy(**overrides: object) -> RerankPolicy:
    return load_rerank_policy().model_copy(update=overrides)


def test_best_chunk_first_and_prompt_trimmed() -> None:
    candidates = tuple(_candidate(text, i) for i, text in enumerate(TEXTS))
    chosen = select_for_generation(
        "how much is the final exam worth", candidates, _policy(generation_k=2)
    )
    # Best match first; the zero-score tie keeps fused order (TEXTS[0]).
    assert [c.text for c in chosen] == [TEXTS[2], TEXTS[0]]
    assert len(chosen) == 2


def test_disabled_keeps_fused_order_trimmed() -> None:
    candidates = tuple(_candidate(text, i) for i, text in enumerate(TEXTS))
    chosen = select_for_generation(
        "final exam", candidates, _policy(enabled=False, generation_k=2)
    )
    assert [c.text for c in chosen] == list(TEXTS[:2])


def test_reranker_failure_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object) -> list[float]:
        raise provider.ProviderUnavailableError("no model")

    monkeypatch.setattr(provider, "rerank_scores", broken)
    candidates = tuple(_candidate(text, i) for i, text in enumerate(TEXTS))
    chosen = select_for_generation("final exam", candidates, _policy(generation_k=3))
    assert chosen == candidates


def test_ties_keep_fused_order() -> None:
    candidates = tuple(_candidate("same words", i) for i in range(4))
    chosen = select_for_generation("unrelated", candidates, _policy(generation_k=4))
    assert chosen == candidates
