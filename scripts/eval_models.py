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

    # the app's own bundled runtime (llama-server, reasoning disabled
    # server-side), one catalog model after another:
    .venv/Scripts/python -m scripts.eval_models \
        --runtime-model minicpm5-2b --runtime-model qwen3.5-2b

    # a cloud endpoint; the key is read from an environment variable:
    .venv/Scripts/python -m scripts.eval_models \\
        --base-url https://openrouter.ai/api/v1 \\
        --model inclusionai/ling-3.0-tiny:free --api-key-env OPENROUTER_API_KEY

    # your own material: ingest real files into a named course (through the
    # real pipeline, in the throwaway database) and run a local cases file
    # whose course_tag matches:
    .venv/Scripts/python -m scripts.eval_models --runtime-model minicpm5-2b \
        --course "pols 347=data/raw/syllabus.pdf,data/raw/reading.pdf" \
        --cases runs/local_eval/pols347_cases.json

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


def _seed_course(spec: str) -> None:
    """`name=path1,path2`: ingest real files into a course of that name."""
    import mimetypes

    from src.backend.common import sources_repo
    from src.backend.common.schemas.base import SourceType
    from src.backend.ingest import worker
    from tests.factories import make_course

    name, _, paths = spec.partition("=")
    course = make_course(name.strip())
    for raw_path in paths.split(","):
        path = Path(raw_path.strip())
        mime = mimetypes.guess_type(path.name)[0] or "text/plain"
        with path.open("rb") as stream:
            sources_repo.upload_source(
                course.course_id,
                filename=path.name,
                mime_type=mime,
                source_type=SourceType.NOTES,
                stream=stream,
            )
    attempted, succeeded = worker.process_batch(limit=50)
    print(f"course {name!r}: ingested {succeeded}/{attempted} file(s)")


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

    def generate(task: str, prompt: str, *, response_schema=None) -> str:
        started = time.perf_counter()
        try:
            text, input_tokens, output_tokens = provider._call_provider(
                task, endpoint, prompt, response_schema=response_schema
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
            conn,
            generate=generate,
            cases_path=Path(args.cases) if args.cases else None,
            log_dir=run_dir / model.replace("/", "_"),
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
    parser.add_argument("--base-url")
    parser.add_argument("--model", action="append", default=[])
    parser.add_argument(
        "--runtime-model",
        action="append",
        default=[],
        help="catalog model id to run on the bundled llama-server",
    )
    parser.add_argument("--api-key-env", default=None)
    parser.add_argument(
        "--cloud",
        dest="local",
        action="store_false",
        help="endpoint is a cloud API (omit llama.cpp-only request fields)",
    )
    parser.add_argument("--course", action="append", default=[])
    parser.add_argument("--cases", default=None)
    args = parser.parse_args(argv)
    if bool(args.model) == bool(args.runtime_model):
        parser.error("give --base-url with --model, or --runtime-model")
    if args.model and not args.base_url:
        parser.error("--model needs --base-url")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path("runs") / "bakeoff" / stamp
    run_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as scratch:
        # A throwaway database and upload dir: the bake-off never touches
        # real courses. The runtime and model files stay in the normal
        # app-data dir, so they are downloaded once and reused.
        os.environ["DATABASE_PATH"] = str(Path(scratch) / "bakeoff.db")
        os.environ["STORAGE_ROOT"] = str(Path(scratch) / "raw")
        from src.backend.common.migrate import migrate

        migrate()
        _seed_harness_course()
        for spec in args.course:
            _seed_course(spec)
        reports = [_run_model(args, model, run_dir) for model in args.model]
        if args.runtime_model:
            from src.backend.runtime.server import get_server

            server = get_server()
            args.base_url = f"http://127.0.0.1:{server.port}/v1"
            args.local = True
            for model_id in args.runtime_model:
                started = time.perf_counter()
                server.start(model_id)
                print(f"{model_id}: loaded in {time.perf_counter() - started:.1f}s")
                reports.append(_run_model(args, model_id, run_dir))
            server.stop()

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
