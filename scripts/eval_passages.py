"""Compare structure and encoder boundaries against original evidence spans.

Uses installed encoders only, with an equal retrieved-token budget. These small
synthetic cases check retrieval coverage; they do not score generated answers.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from src.backend.common import provider
from src.backend.common.embeddings_config import load_embedding_policy
from src.backend.common.encoders import EMBEDDING_SPECS, encoder_dir
from src.backend.rag.config import load_policy
from src.backend.rag.segment import segment, windows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases", type=Path, default=Path("data/eval/retrieval/passage_cases.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("runs/rag-rebuild/passage-evaluation.json")
    )
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    try:
        _validate_cases(cases)
    except ValueError as err:
        parser.error(str(err))
    embedding = load_embedding_policy()
    spec = EMBEDDING_SPECS[embedding.model]
    if not all((encoder_dir(spec) / file.path).is_file() for file in spec.files):
        parser.error("the configured encoder must already be installed")
    budget = cases["budget_tokens"]
    policy = load_policy()
    reports = []
    for document in cases["documents"]:
        text = document["text"]
        queries = [provider.embed_query(case["query"]) for case in document["checks"]]
        for semantic in (False, True):
            started = time.perf_counter()
            segmented = segment(
                text,
                policy.model_copy(update={"semantic_enabled": semantic}),
                encode=provider.embed_chunks,
                token_count=provider.embedding_token_count,
            )
            segmentation_seconds = time.perf_counter() - started
            spans = [
                (p.start + a, p.start + b)
                for p in segmented.passages
                for a, b in windows(
                    text[p.start : p.end],
                    budget,
                    0,
                    token_count=provider.embedding_token_count,
                )
            ]
            if not spans:
                raise ValueError(
                    f"{document['id']}: segmentation produced no searchable spans"
                )
            vectors = np.asarray(provider.embed_chunks([text[a:b] for a, b in spans]))
            for case, query in zip(document["checks"], queries, strict=True):
                start = case.get("evidence_start", text.index(case["evidence"]))
                end = start + len(case["evidence"])
                a, b = spans[int(np.argmax(vectors @ np.asarray(query)))]
                overlap = max(0, min(end, b) - max(start, a))
                reports.append(
                    {
                        "document": document["id"],
                        "query": case["query"],
                        "semantic": semantic,
                        "semantic_used": segmented.semantic_used,
                        "warning": segmented.warning,
                        "passages": len(segmented.passages),
                        "evidence_coverage": overlap / (end - start),
                        "relevant_fraction": overlap / (b - a),
                        "tokens": provider.embedding_token_count(text[a:b]),
                        "span": [a, b],
                        "segmentation_seconds": segmentation_seconds,
                    }
                )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"policy": policy.version, "cases": reports}, indent=2),
        encoding="utf-8",
    )
    for semantic in (False, True):
        results = [r for r in reports if r["semantic"] == semantic]
        print(
            json.dumps(
                {
                    "semantic": semantic,
                    "cases": len(results),
                    "complete_coverage": sum(
                        r["evidence_coverage"] == 1 for r in results
                    ),
                    "mean_relevant_fraction": sum(
                        r["relevant_fraction"] for r in results
                    )
                    / len(results),
                }
            )
        )
    print(f"Report: {args.output}")
    return 0


def _validate_cases(cases: dict) -> None:
    documents = cases.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError("passage evaluation needs at least one document")
    for document in documents:
        identity = document.get("id", "unnamed document")
        text = document.get("text")
        checks = document.get("checks")
        if (
            not isinstance(text, str)
            or not text
            or not isinstance(checks, list)
            or not checks
        ):
            raise ValueError(f"{identity}: supply nonempty text and evidence checks")
        for case in checks:
            evidence = case.get("evidence")
            if not isinstance(evidence, str) or not evidence or evidence not in text:
                raise ValueError(
                    f"{identity}: evidence is empty or absent from the document"
                )
            start = case.get("evidence_start")
            if start is None and text.count(evidence) > 1:
                raise ValueError(
                    f"{identity}: repeated evidence requires evidence_start"
                )
            if start is not None and (
                not isinstance(start, int)
                or start < 0
                or text[start : start + len(evidence)] != evidence
            ):
                raise ValueError(
                    f"{identity}: evidence_start does not identify the evidence"
                )


if __name__ == "__main__":
    raise SystemExit(main())
