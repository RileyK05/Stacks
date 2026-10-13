from dataclasses import replace
from uuid import uuid4

import pytest
from src.backend.common import provider
from src.backend.retrieval.config import RerankPolicy, load_rerank_policy
from src.backend.retrieval.funnel import LABEL, Candidate
from src.backend.retrieval.rerank import NothingAboveFloorError, select_for_generation


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


@pytest.mark.parametrize("scores", ([1.0], [1.0, float("nan"), 0.0]))
def test_invalid_reranker_scores_fail_open(
    monkeypatch: pytest.MonkeyPatch, scores: list[float]
) -> None:
    monkeypatch.setattr(provider, "rerank_scores", lambda *_args: scores)
    candidates = tuple(_candidate(text, i) for i, text in enumerate(TEXTS))
    chosen = select_for_generation("final exam", candidates, _policy(generation_k=2))
    assert chosen == candidates[:2]


def test_ties_keep_fused_order() -> None:
    candidates = tuple(_candidate("same words", i) for i in range(4))
    chosen = select_for_generation("unrelated", candidates, _policy(generation_k=4))
    assert chosen == candidates


# --- score mode (plan-score-retrieval.md Phase 3) -------------------------


def _score_policy(**overrides: object) -> RerankPolicy:
    return load_rerank_policy().model_copy(update={"mode": "score", **overrides})


def test_score_mode_keeps_only_candidates_above_the_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provider, "rerank_scores", lambda *_a: [5.0, 1.0, 4.0])
    candidates = tuple(_candidate(text, i) for i, text in enumerate(TEXTS))
    chosen = select_for_generation(
        "final exam", candidates, _score_policy(min_score=3.0, max_drop=1000.0)
    )
    assert [c.text for c in chosen] == [TEXTS[0], TEXTS[2]]


def test_score_mode_max_drop_relative_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provider, "rerank_scores", lambda *_a: [5.0, 1.0, 4.5])
    candidates = tuple(_candidate(text, i) for i, text in enumerate(TEXTS))
    chosen = select_for_generation(
        "final exam", candidates, _score_policy(min_score=-1000.0, max_drop=1.0)
    )
    assert [c.text for c in chosen] == [TEXTS[0], TEXTS[2]]


def test_score_mode_all_below_floor_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider, "rerank_scores", lambda *_a: [-9.0, -9.0, -9.0])
    candidates = tuple(_candidate(text, i) for i, text in enumerate(TEXTS))
    with pytest.raises(NothingAboveFloorError):
        select_for_generation(
            "final exam", candidates, _score_policy(min_score=0.0, max_drop=0.0)
        )


def test_score_mode_pins_survive_the_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    pin = replace(_candidate("TABLE 2.2 pinned passage", 0), layers=frozenset({LABEL}))
    others = tuple(_candidate(text, i + 1) for i, text in enumerate(TEXTS))
    monkeypatch.setattr(provider, "rerank_scores", lambda *_a: [-5.0, -5.0, -5.0])
    chosen = select_for_generation(
        "table 2.2", (pin, *others), _score_policy(min_score=0.0, max_drop=0.0)
    )
    assert [c.chunk_id for c in chosen] == [pin.chunk_id]


def test_score_mode_reranker_failure_falls_back_to_top_k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*_args: object) -> list[float]:
        raise provider.ProviderUnavailableError("no model")

    monkeypatch.setattr(provider, "rerank_scores", broken)
    candidates = tuple(_candidate(text, i) for i, text in enumerate(TEXTS))
    chosen = select_for_generation(
        "final exam", candidates, _score_policy(generation_k=2)
    )
    assert [c.text for c in chosen] == list(TEXTS[:2])


def test_score_mode_records_trace_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider, "rerank_scores", lambda *_a: [5.0, 1.0, 4.0])
    candidates = tuple(_candidate(text, i) for i, text in enumerate(TEXTS))
    meta: dict[str, object] = {}
    select_for_generation(
        "final exam",
        candidates,
        _score_policy(min_score=3.0, max_drop=1000.0),
        meta=meta,
    )
    assert meta["mode"] == "score"
    assert meta["kept"] == 2 and meta["dropped"] == 1
    assert meta["min_score"] == 3.0
