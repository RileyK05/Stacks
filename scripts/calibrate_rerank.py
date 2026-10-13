"""Calibrate the score-mode rerank floor (plan-score-retrieval.md Phase 3).

Read-only on the database. For each case it builds the score-mode pool,
cross-encoder-scores it, writes a CSV of (case, label, source, score, relevant),
then prints recall/precision/empty-correct across a grid of (min_score,
max_drop) and suggests the pair with the best F1 that keeps 100% recall on the
label cases. It never writes config: the human picks the values.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

from src.backend.common import db, provider
from src.backend.common.embeddings_config import load_embedding_policy
from src.backend.retrieval import evals, funnel
from src.backend.retrieval.config import (
    RerankPolicy,
    RetrievalPolicy,
    load_rerank_policy,
    load_retrieval_policy,
)
from src.backend.retrieval.labels import attach_passage_context, candidate_label


@dataclass
class _ScoredCase:
    question: str
    scores: tuple[float, ...]
    relevant: tuple[bool, ...]
    expected_labels: tuple[str, ...]
    expected_source: str
    expect_empty: bool


def _patterns(case: evals.EvalCase) -> list[str]:
    return [
        part.strip().casefold()
        for part in case.expected_source.split("|")
        if part.strip()
    ]


def _scored_cases(
    conn: db.Connection,
    policy: RetrievalPolicy,
    rerank_policy: RerankPolicy,
    embedding_model: str,
    cases_path: Path,
) -> tuple[list[list[object]], list[_ScoredCase]]:
    rows: list[list[object]] = []
    scored: list[_ScoredCase] = []
    for case in evals.load_cases(cases_path):
        course_id = evals._resolve_course(conn, case.course_tag)
        if course_id is None:
            continue
        result = funnel.retrieve(
            conn,
            course_id,
            case.question,
            policy,
            query_embedding=provider.embed_query(case.question),
            embedding_model=embedding_model,
            mode="score",
        )
        enriched = attach_passage_context(conn, result.candidates)
        anchors = tuple(c for c in enriched if not c.context_for)
        if not anchors:
            scored.append(
                _ScoredCase(
                    case.question,
                    (),
                    (),
                    case.expected_labels,
                    case.expected_source,
                    case.expect_empty,
                )
            )
            continue
        scores = provider.rerank_scores(
            rerank_policy.model, case.question, [c.text for c in anchors]
        )
        labels_per = evals._candidate_labels(conn, anchors)
        patterns = _patterns(case)
        flags: list[bool] = []
        for candidate, labels in zip(anchors, labels_per, strict=True):
            relevant = bool(set(case.expected_labels) & labels) or any(
                pattern in (candidate.source_filename or "").casefold()
                for pattern in patterns
            )
            flags.append(relevant)
            rows.append(
                [
                    case.question,
                    candidate_label(candidate),
                    candidate.source_filename,
                    f"{float(scores[len(flags) - 1]):.4f}",
                    relevant,
                ]
            )
        scored.append(
            _ScoredCase(
                case.question,
                tuple(float(score) for score in scores),
                tuple(flags),
                case.expected_labels,
                case.expected_source,
                case.expect_empty,
            )
        )
    return rows, scored


def _evaluate(
    scored: list[_ScoredCase], min_score: float, max_drop: float
) -> tuple[float, float, float, float]:
    label_cases = [case for case in scored if not case.expect_empty]
    empty_cases = [case for case in scored if case.expect_empty]
    true_positive = false_positive = 0
    hits = 0
    for case in label_cases:
        if not case.scores:
            continue
        best = max(case.scores)
        floor = max(min_score, best - max_drop)
        kept = [index for index, score in enumerate(case.scores) if score >= floor]
        true_positive += sum(1 for index in kept if case.relevant[index])
        false_positive += sum(1 for index in kept if not case.relevant[index])
        covered = (
            any(case.relevant[index] for index in kept)
            if case.expected_labels or case.expected_source
            else bool(kept)
        )
        hits += 1 if covered else 0
    recall = hits / len(label_cases) if label_cases else 0.0
    precision = (
        true_positive / (true_positive + false_positive)
        if (true_positive + false_positive)
        else 0.0
    )
    empty_correct = (
        sum(1 for case in empty_cases if not _kept(case, min_score, max_drop))
        / len(empty_cases)
        if empty_cases
        else 0.0
    )
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return recall, precision, f1, empty_correct


def _kept(case: _ScoredCase, min_score: float, max_drop: float) -> list[int]:
    if not case.scores:
        return []
    floor = max(min_score, max(case.scores) - max_drop)
    return [index for index, score in enumerate(case.scores) if score >= floor]


@dataclass
class _Grid:
    min_score: float
    max_drop: float
    recall: float
    precision: float
    f1: float
    empty_correct: float


def _percentile(values: list[float], percent: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round(percent / 100 * (len(ordered) - 1))
    return ordered[min(len(ordered) - 1, max(0, index))]


def _grid(scored: list[_ScoredCase]) -> list[_Grid]:
    all_scores = [score for case in scored for score in case.scores]
    min_scores = [_percentile(all_scores, percent) for percent in range(0, 100, 10)]
    min_scores.append(-1000.0)
    drops = [0.5, 1.0, 2.0, 4.0, 8.0, 1000.0]
    results: list[_Grid] = []
    for min_score in dict.fromkeys(min_scores):
        for max_drop in drops:
            recall, precision, f1, empty_correct = _evaluate(
                scored, min_score, max_drop
            )
            results.append(
                _Grid(min_score, max_drop, recall, precision, f1, empty_correct)
            )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("runs/rerank-calibration.csv")
    )
    args = parser.parse_args()
    if not args.db.is_file():
        parser.error(f"database not found: {args.db}")
    if not args.cases.is_file():
        parser.error(f"cases not found: {args.cases}")

    policy = load_retrieval_policy()
    rerank_policy = load_rerank_policy()
    embedding_model = load_embedding_policy().model
    conn = db.connect(args.db)
    try:
        rows, scored = _scored_cases(
            conn, policy, rerank_policy, embedding_model, args.cases
        )
    finally:
        conn.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["case", "label", "source", "score", "relevant"])
        writer.writerows(rows)
    print(f"CSV: {args.output}")

    grid = _grid(scored)
    print(
        f"{'min_score':>10} {'max_drop':>9} {'recall':>7} {'prec':>6} "
        f"{'f1':>6} {'empty':>6}"
    )
    for row in grid:
        print(
            f"{row.min_score:>10.3f} {row.max_drop:>9.2f} {row.recall:>7.2f} "
            f"{row.precision:>6.2f} {row.f1:>6.2f} {row.empty_correct:>6.2f}"
        )
    full_recall = [row for row in grid if row.recall >= 1.0]
    pick = max(full_recall or grid, key=lambda row: (row.f1, row.empty_correct))
    print(
        f"\nsuggested: min_score={pick.min_score:.3f} max_drop={pick.max_drop:.2f} "
        f"(recall={pick.recall:.2f} precision={pick.precision:.2f} "
        f"empty_correct={pick.empty_correct:.2f})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
