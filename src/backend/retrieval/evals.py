"""Retrieval evaluation (golden rule 3: evaluation is the center).

An eval case is a question against a real course plus the locator labels
that MUST appear in the retrieved set for the case to count as a hit
(ALL expected labels must match, exactly, per label — no substring games:
"page 1" must not match "page 12").

`run_eval` computes what decision 008's kill-switch requires, with every
number taken at the SAME k (policy.final_k) so the comparison is fair:
- recall@k for EACH seam alone (keyword-only, toc-only, dependency-only,
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
from uuid import UUID

from src.backend.common.db import Connection, json_ids
from src.backend.common.queries import get
from src.backend.retrieval import funnel
from src.backend.retrieval.config import RetrievalPolicy
from src.backend.retrieval.funnel import Candidate

_FILE = "retrieval_traces"

EVAL_DIR = (
    Path(__file__).resolve().parents[3] / "data" / "eval" / "retrieval"
)

SEAM_NAMES = ("keyword", "toc", "dependency", "embedding")


@dataclass(frozen=True)
class EvalCase:
    question: str
    course_tag: str
    expected_labels: tuple[str, ...]


@dataclass(frozen=True)
class EvalResult:
    question: str
    resolved: bool
    hit: bool
    retrieved_labels: tuple[str, ...]
    layer_contribution: dict[str, int]
    per_seam_hits: dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class EvalSummary:
    cases: tuple[EvalResult, ...]
    unresolved_cases: tuple[str, ...]
    seam_recall: dict[str, float]
    fused_recall: float
    best_single_seam: str
    best_single_recall: float
    fusion_beats_best_single: bool

    def __str__(self) -> str:
        lines = [
            f"fused recall@k: {self.fused_recall:.2f}",
            "seam recall@k: "
            + ", ".join(
                f"{seam}={self.seam_recall.get(seam, 0.0):.2f}"
                for seam in SEAM_NAMES
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
    return [
        EvalCase(
            question=case["question"],
            course_tag=case["course_tag"],
            expected_labels=tuple(case["expected_labels"]),
        )
        for case in raw["cases"]
    ]


def _resolve_course(conn: Connection, course_tag: str) -> UUID | None:
    row = conn.execute(
        get("retrieval_traces", "course_by_tag"), {"tag": course_tag}
    ).fetchone()
    return row["course_id"] if row else None


def _labels_for_candidates(
    conn: Connection, candidates: tuple[Candidate, ...]
) -> frozenset[str]:
    locator_ids = [candidate.locator_id for candidate in candidates]
    if not locator_ids:
        return frozenset()
    rows = conn.execute(
        get("retrieval", "locator_labels"), {"locator_ids": json_ids(locator_ids)}
    ).fetchall()
    return frozenset(row["label"] for row in rows)


def _top(
    seam: dict[UUID, Candidate], k: int
) -> tuple[Candidate, ...]:
    """The seam's own best k, in seam order.

    Seam dicts are built from rows the SQL already ordered (rank DESC for
    keyword/embedding, position for TOC, deterministic for dependency), so
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


def _seam_recall(results: list[EvalResult]) -> dict[str, float]:
    resolved = [result for result in results if result.resolved]
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
) -> EvalSummary:
    """Run all cases through every seam alone AND the fusion. A case whose
    course_tag resolves to nothing is UNRESOLVED — excluded from recall and
    reported, never silently passed."""
    results: list[EvalResult] = []
    unresolved: list[str] = []
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
        toc, _entries = funnel.toc_seam(
            conn, course_id, case.question, policy.toc_limit
        )
        matched = funnel.concept_matches(
            conn, course_id, case.question, policy.dependency_limit
        )
        matched_ids = [row["concept_id"] for row in matched]
        dependency = funnel.dependency_seam(
            conn, course_id, matched_ids, policy.dependency_limit
        )
        embeddings = funnel.embedding_seam(
            conn,
            course_id,
            embedding,
            embedding_model,
            policy.embedding_limit,
        )
        # Fuse the seams already computed above rather than calling
        # funnel.retrieve(), which would re-run all four seams plus the
        # concept match — double the DB work per case for the same answer.
        fused_candidates = funnel.fuse(
            keyword, toc, dependency, embeddings, policy=policy
        )
        layer_contribution: dict[str, int] = {}
        for candidate in fused_candidates:
            for layer in candidate.layers:
                layer_contribution[layer] = layer_contribution.get(layer, 0) + 1

        per_seam_hits: dict[str, bool] = {}
        for seam_name, seam in (
            ("keyword", keyword),
            ("toc", toc),
            ("dependency", dependency),
            ("embedding", embeddings),
        ):
            labels = _labels_for_candidates(conn, _top(seam, policy.final_k))
            per_seam_hits[seam_name] = _hit(case.expected_labels, labels)

        fused_labels = _labels_for_candidates(conn, fused_candidates)
        results.append(
            EvalResult(
                question=case.question,
                resolved=True,
                hit=_hit(case.expected_labels, fused_labels),
                retrieved_labels=tuple(sorted(fused_labels)),
                layer_contribution=layer_contribution,
                per_seam_hits=per_seam_hits,
            )
        )

    resolved_results = [result for result in results if result.resolved]
    seam_recall = _seam_recall(results)
    fused_recall = (
        sum(1 for result in resolved_results if result.hit) / len(resolved_results)
        if resolved_results
        else 0.0
    )
    best_seam = max(seam_recall, key=lambda seam: seam_recall[seam])
    best_recall = seam_recall[best_seam]
    return EvalSummary(
        cases=tuple(results),
        unresolved_cases=tuple(unresolved),
        seam_recall=seam_recall,
        fused_recall=fused_recall,
        best_single_seam=best_seam,
        best_single_recall=best_recall,
        fusion_beats_best_single=fused_recall > best_recall,
    )