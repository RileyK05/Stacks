"""Retrieval evaluation (golden rule 3: evaluation is the center).

An eval case is a question against a real course plus the locator labels
that MUST appear in the retrieved set for the case to count as a hit
(ALL expected labels must match, exactly, per label — no substring games:
"page 1" must not match "page 12").

`run_eval` computes what decision 008's kill-switch requires, with every
number taken at the SAME k (policy.final_k) so the comparison is fair:
- recall@k for EACH seam alone (keyword-only, graph-only,
  embedding-only when a query embedding function is supplied), each seam
  truncated to its own best final_k
- recall@k for the FUSION
- per-case resolution: an eval case whose course_tag resolves to no
  course is UNRESOLVED, never a silent pass.

The decision rule — fusion must beat the best single seam or be
simplified — is computed here as `fusion_beats_best_single`.

Cases live in data/eval/ (committed): JSON shaped as
{"question": str, "course_tag": str, "expected_labels": [str]}. Expected
chunks are matched by exact locator label, so cases survive re-ingestion
(chunk ids change; locator labels don't).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import UUID

from src.backend.common.db import Connection, json_ids
from src.backend.common.queries import get
from src.backend.retrieval import funnel
from src.backend.retrieval.config import RetrievalPolicy, load_rerank_policy
from src.backend.retrieval.funnel import Candidate
from src.backend.retrieval.labels import attach_passage_context

_FILE = "retrieval_traces"

EVAL_DIR = Path(__file__).resolve().parents[3] / "data" / "eval" / "retrieval"

SEAM_NAMES = ("keyword", "embedding", "graph")


@dataclass(frozen=True)
class EvalCase:
    question: str
    course_tag: str
    expected_labels: tuple[str, ...]
    # Source-share expectation: "|"-separated filename substrings. When set,
    # the case reports what fraction of retrieved passages come from those
    # sources (real-material cases scope a question to a week's file).
    expected_source: str = ""
    # The case hits only when source_share >= min_source_share (default 0.0,
    # so it never gates unless asked). Empty labels are allowed when this is
    # positive: the case is scored on source share alone.
    min_source_share: float = 0.0
    # A question the material cannot answer. It hits when retrieval returns
    # nothing at all, and it is the only case kind allowed empty labels.
    expect_empty: bool = False


@dataclass(frozen=True)
class EvalResult:
    question: str
    resolved: bool
    hit: bool
    retrieved_labels: tuple[str, ...]
    layer_contribution: dict[str, int]
    per_seam_hits: dict[str, bool] = field(default_factory=dict)
    # Precision at k: expected labels found / labels retrieved. Recall
    # (`hit`) is all-or-nothing; precision shows how much a seam drags in
    # (B-07) and is 0.0 when nothing relevant was retrieved.
    precision: float = 0.0
    # Reciprocal rank of the first expected label in the fused ranking
    # (1.0 = the top result is relevant); 0.0 when none is present.
    reciprocal_rank: float = 0.0
    # Fraction of retrieved passages from the case's expected_source
    # substrings. 0.0 when the case names no source.
    source_share: float = 0.0
    # This case probes a question the material cannot answer; it is scored
    # by empty_correct, not by fused recall.
    expect_empty: bool = False


@dataclass(frozen=True)
class EvalSummary:
    cases: tuple[EvalResult, ...]
    unresolved_cases: tuple[str, ...]
    seam_recall: dict[str, float]
    fused_recall: float
    best_single_seam: str
    best_single_recall: float
    fusion_beats_best_single: bool
    mean_precision: float = 0.0
    mean_reciprocal_rank: float = 0.0
    # Mean source share over cases that name an expected_source; 0.0 when
    # none do.
    mean_source_share: float = 0.0
    # Fraction of expect_empty cases where retrieval returned nothing.
    empty_correct: float = 0.0

    def __str__(self) -> str:
        lines = [
            f"fused recall@k: {self.fused_recall:.2f}",
            f"fused precision@k: {self.mean_precision:.2f}, "
            f"MRR: {self.mean_reciprocal_rank:.2f}",
            f"mean source share: {self.mean_source_share:.2f}, "
            f"empty correct: {self.empty_correct:.2f}",
            "seam recall@k: "
            + ", ".join(
                f"{seam}={self.seam_recall.get(seam, 0.0):.2f}" for seam in SEAM_NAMES
            ),
            f"best single seam: {self.best_single_seam} "
            f"({self.best_single_recall:.2f})",
            f"fusion beats best single: {self.fusion_beats_best_single}",
        ]
        if self.unresolved_cases:
            lines.append(
                "UNRESOLVED cases (excluded from recall): "
                + ", ".join(self.unresolved_cases)
            )
        return "\n".join(lines)


def load_cases(path: Path = EVAL_DIR / "cases.json") -> list[EvalCase]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases: list[EvalCase] = []
    for case in raw["cases"]:
        labels = tuple(case["expected_labels"])
        expect_empty = bool(case.get("expect_empty", False))
        min_source_share = float(case.get("min_source_share", 0.0))
        if not 0.0 <= min_source_share <= 1.0:
            raise ValueError(
                f"retrieval case {case.get('question')!r} has min_source_share "
                "outside 0..1"
            )
        # A case with no expected labels can never hit by label and would be
        # scored a permanent miss (B-07): reject it at load, unless it is an
        # empty-material probe or a source-share case.
        if not labels and not expect_empty and min_source_share <= 0.0:
            raise ValueError(
                f"retrieval case {case.get('question')!r} has no expected_labels"
            )
        cases.append(
            EvalCase(
                question=case["question"],
                course_tag=case["course_tag"],
                expected_labels=labels,
                expected_source=str(case.get("expected_source", "")),
                min_source_share=min_source_share,
                expect_empty=expect_empty,
            )
        )
    return cases


def _resolve_course(conn: Connection, course_tag: str) -> UUID | None:
    row = conn.execute(
        get("retrieval_traces", "course_by_tag"), {"tag": course_tag}
    ).fetchone()
    return row["course_id"] if row else None


def _labels_for_candidates(
    conn: Connection, candidates: tuple[Candidate, ...]
) -> frozenset[str]:
    return frozenset(
        label for labels in _candidate_labels(conn, candidates) for label in labels
    )


def _candidate_labels(
    conn: Connection, candidates: tuple[Candidate, ...]
) -> tuple[frozenset[str], ...]:
    """Each candidate's locator labels, in candidate order (one query).
    Used for reciprocal rank; a label list per candidate keeps rank tied
    to the candidate position."""
    chunk_ids = [candidate.chunk_id for candidate in candidates]
    if not chunk_ids:
        return ()
    rows = conn.execute(
        get("retrieval", "chunk_id_locator_labels"),
        {"chunk_ids": json_ids(chunk_ids)},
    ).fetchall()
    by_chunk: dict[UUID, list[str]] = {}
    for row in rows:
        by_chunk.setdefault(row["chunk_id"], []).append(row["label"])
    return tuple(
        frozenset(by_chunk.get(candidate.chunk_id, ())) for candidate in candidates
    )


def _top(seam: dict[UUID, Candidate], k: int) -> tuple[Candidate, ...]:
    """The seam's own best k, in seam order.

    Seam dicts are built from rows the SQL already ordered (rank DESC for
    keyword/embedding/graph), so
    insertion order IS the seam's ranking. Truncating here is what makes the
    per-seam and fused numbers comparable: without it each seam is scored at
    its own limit (20) while the fusion is scored at final_k (10), and
    `fusion_beats_best_single` — decision 008's kill switch — measures the k
    gap instead of the fusion."""
    return tuple(seam.values())[:k]


def _hit(expected: tuple[str, ...], retrieved: frozenset[str]) -> bool:
    """All expected labels must appear exactly in the retrieved label set.
    Exact set membership — 'page 1' never matches 'page 12'."""
    if not expected:
        return False
    return all(label in retrieved for label in expected)


def _source_share(candidates: tuple[Candidate, ...], expected_source: str) -> float:
    """Fraction of retrieved passages whose filename contains any of the
    "|"-separated source substrings (case-insensitive). 0.0 when the case
    names no source."""
    needles = [
        part.strip().casefold() for part in expected_source.split("|") if part.strip()
    ]
    if not candidates or not needles:
        return 0.0
    matching = sum(
        1
        for candidate in candidates
        if any(
            needle in (candidate.source_filename or "").casefold() for needle in needles
        )
    )
    return matching / len(candidates)


def _seam_recall(results: list[EvalResult]) -> dict[str, float]:
    resolved = [
        result for result in results if result.resolved and not result.expect_empty
    ]
    if not resolved:
        return dict.fromkeys(SEAM_NAMES, 0.0)
    recall: dict[str, float] = {}
    for seam in SEAM_NAMES:
        hits = sum(1 for result in resolved if result.per_seam_hits.get(seam))
        recall[seam] = hits / len(resolved)
    return recall


def run_eval(
    conn: Connection,
    policy: RetrievalPolicy,
    *,
    cases_path: Path | None = None,
    query_embedding_for: Callable[[UUID, str], list[float] | None] | None = None,
    embedding_model: str = "eval-embed",
    end_to_end: bool = False,
    mode: Literal["top_k", "score"] | None = None,
) -> EvalSummary:
    """Run all cases through every seam alone AND the fusion. A case whose
    course_tag resolves to nothing is UNRESOLVED — excluded from recall and
    reported, never silently passed.

    The per-seam numbers always come from the individual seams. `end_to_end`
    instead takes the fused set from the full `funnel.retrieve` path (routing,
    dedupe, the configured seam limits), and in score mode also applies the
    rerank floor; a floor drop leaves the set empty. `mode` forces the rerank
    mode; None follows config."""
    results: list[EvalResult] = []
    unresolved: list[str] = []
    source_shares: list[float] = []
    empty_checks: list[bool] = []
    cases = load_cases(cases_path or (EVAL_DIR / "cases.json"))
    for case in cases:
        course_id = _resolve_course(conn, case.course_tag)
        if course_id is None:
            unresolved.append(case.question)
            results.append(
                EvalResult(
                    question=case.question,
                    resolved=False,
                    hit=False,
                    retrieved_labels=(),
                    layer_contribution={},
                )
            )
            continue
        embedding = (
            query_embedding_for(course_id, case.question)
            if query_embedding_for is not None
            else None
        )
        keyword = funnel.keyword_seam(
            conn, course_id, case.question, policy.keyword_limit
        )
        embeddings = funnel.embedding_seam(
            conn,
            course_id,
            embedding,
            embedding_model,
            policy.embedding_limit,
        )
        graph = funnel.graph_seam(
            conn,
            course_id,
            {**keyword, **embeddings},
            policy.graph_limit,
            embedding_model,
        )
        if end_to_end:
            fused_candidates = funnel.retrieve(
                conn,
                course_id,
                case.question,
                policy,
                query_embedding=embedding,
                embedding_model=embedding_model,
                mode=mode,
            ).candidates
            if (mode or load_rerank_policy().mode) == "score":
                from src.backend.retrieval import rerank

                rerank_policy = load_rerank_policy().model_copy(
                    update={"mode": "score"}
                )
                try:
                    fused_candidates = rerank.select_for_generation(
                        case.question, fused_candidates, rerank_policy
                    )
                except rerank.NothingAboveFloorError:
                    fused_candidates = ()
        else:
            fused_candidates = funnel.fuse(keyword, embeddings, graph, policy=policy)
        layer_contribution: dict[str, int] = {}
        for candidate in fused_candidates:
            for layer in candidate.layers:
                layer_contribution[layer] = layer_contribution.get(layer, 0) + 1

        if case.expect_empty:
            # The material cannot answer this: a hit is an empty result; a
            # non-empty one is the failure. Each seam must be empty too.
            empty = not fused_candidates
            empty_checks.append(empty)
            per_seam_hits = {
                seam_name: not _top(seam, policy.final_k)
                for seam_name, seam in (
                    ("keyword", keyword),
                    ("graph", graph),
                    ("embedding", embeddings),
                )
            }
            results.append(
                EvalResult(
                    question=case.question,
                    resolved=True,
                    hit=empty,
                    retrieved_labels=(),
                    layer_contribution=layer_contribution,
                    per_seam_hits=per_seam_hits,
                    expect_empty=True,
                )
            )
            continue

        per_seam_hits = {}
        for seam_name, seam in (
            ("keyword", keyword),
            ("graph", graph),
            ("embedding", embeddings),
        ):
            labels = _labels_for_candidates(conn, _top(seam, policy.final_k))
            per_seam_hits[seam_name] = _hit(case.expected_labels, labels)

        fused_labels = _labels_for_candidates(conn, fused_candidates)
        enriched = attach_passage_context(conn, fused_candidates)
        share = _source_share(enriched, case.expected_source)
        if case.expected_source.strip():
            source_shares.append(share)
        expected = set(case.expected_labels)
        precision = (
            len(expected & fused_labels) / len(fused_labels) if fused_labels else 0.0
        )
        # Reciprocal rank of the first relevant candidate in the fused
        # order (a multi-label chunk counts at its position).
        rank_hit = 0.0
        for position, labels in enumerate(
            _candidate_labels(conn, fused_candidates), start=1
        ):
            if labels & expected:
                rank_hit = 1.0 / position
                break
        label_hit = (
            _hit(case.expected_labels, fused_labels) if case.expected_labels else True
        )
        results.append(
            EvalResult(
                question=case.question,
                resolved=True,
                hit=label_hit and share >= case.min_source_share - 1e-9,
                retrieved_labels=tuple(sorted(fused_labels)),
                layer_contribution=layer_contribution,
                per_seam_hits=per_seam_hits,
                precision=precision,
                reciprocal_rank=rank_hit,
                source_share=share,
            )
        )

    resolved_results = [result for result in results if result.resolved]
    label_results = [result for result in resolved_results if not result.expect_empty]
    empty_results = [result for result in resolved_results if result.expect_empty]
    seam_recall = _seam_recall(results)
    fused_recall = (
        sum(1 for result in label_results if result.hit) / len(label_results)
        if label_results
        else 0.0
    )
    best_seam = max(seam_recall, key=lambda seam: seam_recall[seam])
    best_recall = seam_recall[best_seam]
    mean_precision = (
        sum(result.precision for result in label_results) / len(label_results)
        if label_results
        else 0.0
    )
    mean_mrr = (
        sum(result.reciprocal_rank for result in label_results) / len(label_results)
        if label_results
        else 0.0
    )
    mean_source_share = (
        sum(source_shares) / len(source_shares) if source_shares else 0.0
    )
    empty_correct = (
        sum(1 for result in empty_results if result.hit) / len(empty_results)
        if empty_results
        else 0.0
    )
    return EvalSummary(
        cases=tuple(results),
        unresolved_cases=tuple(unresolved),
        seam_recall=seam_recall,
        fused_recall=fused_recall,
        best_single_seam=best_seam,
        best_single_recall=best_recall,
        fusion_beats_best_single=fused_recall > best_recall,
        mean_precision=mean_precision,
        mean_reciprocal_rank=mean_mrr,
        mean_source_share=mean_source_share,
        empty_correct=empty_correct,
    )
