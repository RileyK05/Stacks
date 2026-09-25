"""Phase 0 model bake-off (docs/plan-local-first.md §12).

Runs the answer eval (decision 010) against one or more models behind any
OpenAI-compatible endpoint — a local llama-server, Ollama, LM Studio, or
a cloud API — and records, per model: pass rate by case kind, latency per
case, and real token counts. Everything runs in a throwaway database, so
your own courses are never touched and nothing is written to the usage
ledger.

    # local llama-server serving one model:
    .venv/Scripts/python -m scripts.eval_models \\
        --base-url http://127.0.0.1:8081/v1 --model minicpm5-2b

    # several models on one endpoint (e.g. LM Studio), thinking capped off:
    .venv/Scripts/python -m scripts.eval_models \\
        --base-url http://127.0.0.1:1234/v1 \\
        --model minicpm5-2b --model qwen3.5-2b --model k2-horizon-3.7b

    # a cloud endpoint; the key is read from an environment variable:
    .venv/Scripts/python -m scripts.eval_models \\
        --base-url https://openrouter.ai/api/v1 \\
        --model inclusionai/ling-3.0-tiny:free --api-key-env OPENROUTER_API_KEY

The report is printed and written to runs/bakeoff/<timestamp>.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class ModelReport:
    model: str
    passed: int = 0
    failed: int = 0
    unresolved: int = 0
    by_kind: dict[str, dict[str, int]] = field(default_factory=dict)
    seconds_per_case: list[float] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def mean_seconds(self) -> float:
        times = self.seconds_per_case
        return sum(times) / len(times) if times else 0.0


def _seed_harness_course() -> None:
    """The course + chunk that data/eval/answer/cases.json resolves."""
    from tests.factories import add_chunk, make_course

    course = make_course("harness-course")
    add_chunk(
        course.course_id,
        "A linear transformation preserves addition and scalar multiplication.",
        label="page 1",
    )


def _run_model(args: argparse.Namespace, model: str, run_dir: Path) -> ModelReport:
    from src.backend.common import provider
    from src.backend.common.db import connection
    from src.backend.common.providers import ResolvedProvider
    from src.backend.evals.answer import run_answer_eval

    endpoint = ResolvedProvider(
        name="bakeoff",
        base_url=args.base_url,
        model=model,
        api_key=os.environ.get(args.api_key_env) if args.api_key_env else None,
        is_local=args.local,
    )
    report = ModelReport(model=model)

    def generate(task: str, prompt: str) -> str:
        started = time.perf_counter()
        try:
            text, input_tokens, output_tokens = provider._call_provider(
                task, endpoint, prompt
            )
        except provider.ProviderUnavailableError as err:
            report.errors.append(str(err))
            text, input_tokens, output_tokens = "", 0, 0
        report.seconds_per_case.append(time.perf_counter() - started)
        report.input_tokens += input_tokens
        report.output_tokens += output_tokens
        return text

    with connection() as conn:
        summary = run_answer_eval(
            conn, generate=generate, log_dir=run_dir / model.replace("/", "_")
        )
    for result in summary.cases:
        kind = report.by_kind.setdefault(result.kind, {"passed": 0, "total": 0})
        kind["total"] += 1
        if not result.resolved:
            report.unresolved += 1
        elif result.passed:
            report.passed += 1
            kind["passed"] += 1
        else:
            report.failed += 1
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--api-key-env", default=None)
    parser.add_argument(
        "--cloud",
        dest="local",
        action="store_false",
        help="endpoint is a cloud API (omit llama.cpp-only request fields)",
    )
    args = parser.parse_args(argv)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path("runs") / "bakeoff" / stamp
    run_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as scratch:
        # A throwaway app-data dir: the bake-off never touches real data.
        os.environ["APP_DATA_DIR"] = scratch
        os.environ["DATABASE_PATH"] = str(Path(scratch) / "bakeoff.db")
        os.environ["STORAGE_ROOT"] = str(Path(scratch) / "raw")
        from src.backend.common.migrate import migrate

        migrate()
        _seed_harness_course()
        reports = [_run_model(args, model, run_dir) for model in args.model]

    for report in reports:
        total = report.passed + report.failed
        print(
            f"{report.model}: {report.passed}/{total} passed"
            f" ({report.unresolved} unresolved), "
            f"{report.mean_seconds:.1f}s/case, "
            f"{report.input_tokens} in / {report.output_tokens} out tokens"
        )
        for kind, counts in sorted(report.by_kind.items()):
            print(f"    {kind:<20} {counts['passed']}/{counts['total']}")
        if report.errors:
            print(f"    {len(report.errors)} call error(s); first: {report.errors[0]}")
    output = run_dir / "report.json"
    output.write_text(
        json.dumps(
            [asdict(r) | {"mean_seconds": r.mean_seconds} for r in reports], indent=2
        ),
        encoding="utf-8",
    )
    print(f"report: {output}")
    return 0 if all(not r.errors for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
