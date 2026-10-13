"""Retrieval evaluation on a real course database (plan-score-retrieval.md).

Read-only: opens ``--db`` and runs the committed case format through the full
retrieval path (routing, dedupe, the configured limits), so the numbers match
what the tutor actually searches. Course material stays out of the repo.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.backend.common import db, provider
from src.backend.common.embeddings_config import load_embedding_policy
from src.backend.retrieval import evals
from src.backend.retrieval.config import load_retrieval_policy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("data/eval/retrieval/real_cases.json"),
    )
    parser.add_argument("--mode", choices=("top_k", "score"), default="top_k")
    args = parser.parse_args()
    if not args.db.is_file():
        parser.error(f"database not found: {args.db}")
    if not args.cases.is_file():
        parser.error(
            f"cases not found: {args.cases} — copy "
            "data/eval/retrieval/real_cases.example.json and fill in the locator "
            "labels from your own database"
        )

    policy = load_retrieval_policy()
    embedding_model = load_embedding_policy().model
    conn = db.connect(args.db)
    try:
        summary = evals.run_eval(
            conn,
            policy,
            cases_path=args.cases,
            query_embedding_for=lambda _course_id, question: provider.embed_query(
                question
            ),
            embedding_model=embedding_model,
            end_to_end=True,
            mode=args.mode,
        )
    finally:
        conn.close()

    print(summary)
    misses = [
        result.question
        for result in summary.cases
        if result.resolved and not result.hit
    ]
    if misses:
        print("\nMISSES:")
        for question in misses:
            print(f"- {question}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
