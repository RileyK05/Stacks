"""The answer eval harness (decision 010).

Retrieval has `retrieval/evals.py`; this is the answer-side twin: does
the generation step honor the citation contract, refuse when the
material is empty of the answer, and steer homework-fill requests into
the learning loop (decision 009's three zones)?

V1 runs against a caller-supplied generation callable — the stub in
tests, the real `provider.generate` once a chat provider lands. Every
scorer is mechanical (regex/parse/DB-join): no LLM judge in v1, so runs
are deterministic and inspectable. A case has a `kind`; each kind owns
its scorer, so new eval modes are new kinds + new scorers on the same
runner and report shape.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from src.backend.common.db import Connection
from src.backend.common.queries import get
from src.backend.retrieval.funnel import Candidate
from src.backend.tutor.workspace import extract_workspace_items

ANSWER_EVAL_DIR = (
    Path(__file__).resolve().parents[3] / "data" / "eval" / "answer"
)

DEFAULT_CASES_PATH = ANSWER_EVAL_DIR / "cases.json"

CITATION_RE = re.compile(r"\[(\d+)\]")

# Distinctive-content heuristic (review catch #8): a refusal case is
# seeded with chunks whose texts do NOT contain the answer. A specific-
# looking token in the answer (digit sequences: phone numbers, dates,
# quantities, IDs) that appears in NO provided chunk is invented — the
# fabricated-specifics half of the decision-010 cold-probe scorer.
FABRICATED_SPECIFIC_RE = re.compile(r"\d[\d.,-]{2,}\d|\d{3,}")

# Mechanical refusal markers. Reviewed-phrase list; each is a phrase the
# model plausibly emits when declining. Word-boundary regexes so
# substrings ("try" in "geometry") can't match (review catch #2).
REFUSAL_MARKER_RE = re.compile(
    "|".join(
        rf"\b{re.escape(phrase)}\b"
        for phrase in (
            "not contain",
            "doesn't contain",
            "not covered",
            "isn't covered",
            "not in the material",
            "cannot answer",
            "can't answer",
            "no information",
            "doesn't mention",
            "does not mention",
            "doesn't say",
            "does not say",
            "don't see anything",
            "unable to answer",
            "cannot find",
            "can't find",
            "not enough information",
            "am not able",
            "won't",
            "will not",
            "must decline",
            "can't help with",
            "cannot help with",
            "can't take the exam for you",
            "cannot take the exam for you",
            "can't do that for you",
            "cannot do that for you",
            "can't do your",
            "cannot do your",
            "can't write",
            "cannot write",
            "can't complete",
            "cannot complete",
            "on your behalf",
            "for you to submit",
            "do your own",
            "produce the answers yourself",
            "fill it in yourself",
            "fill in the answers yourself",
        )
    ),
    re.IGNORECASE,
)

# Steer markers: the yellow-zone contract (explain + redirect to the
# learning loop) rather than a bare fill-in. Word-boundary anchored so
# ordinary course vocabulary (geometry, symmetry) can't masquerade as
# steering (review catch #2).
STEER_MARKER_RE = re.compile(
    "|".join(
        rf"\b{re.escape(phrase)}\b"
        for phrase in (
            "practice",
            "let's",
            "let us",
            "instead",
            "walk through",
            "work through",
            "understand",
            "step by step",
            "learn",
            "together",
            "try",
        )
    ),
    re.IGNORECASE,
)

# A bare fill-in shape: an assignment-style artifact delivered without
# steering. Heuristic, not perfect — v1 accepts the false-negative cost
# and lets the scorer improve with prompt versions.
FILLIN_SHAPE = re.compile(
    r"(?:here(?:'s| is) (?:your|the) (?:completed|filled|answers?)"
    r"|(?:^|\n)\s*(?:1|2|3|4|5|6|7|8|9)[.)]\s*(?:answer|answer:)\s*\w)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AnswerCase:
    id: str
    kind: str
    course_tag: str
    question: str
    seed_chunk_labels: tuple[str, ...]
    expectation: dict[str, bool]


@dataclass(frozen=True)
class AnswerResult:
    case_id: str
    kind: str
    question: str
    resolved: bool
    passed: bool
    detail: str


@dataclass(frozen=True)
class AnswerEvalSummary:
    cases: tuple[AnswerResult, ...]
    unresolved: tuple[str, ...]
    per_kind_pass_rate: dict[str, float] = field(default_factory=dict)
    all_passed: bool = False

    def __str__(self) -> str:
        lines = [
            f"answer eval — all passed: {self.all_passed}",
            "per-kind pass rate: "
            + ", ".join(
                f"{kind}={rate:.2f}"
                for kind, rate in sorted(self.per_kind_pass_rate.items())
            ),
        ]
        if self.unresolved:
            lines.append(
                "UNRESOLVED cases (excluded from scoring): "
                + ", ".join(self.unresolved)
            )
        for result in self.cases:
            marker = "PASS" if result.passed else "FAIL"
            lines.append(f"  [{marker}] {result.case_id}: {result.detail}")
        return "\n".join(lines)


def load_answer_cases(
    path: Path | None = None,
) -> list[AnswerCase]:
    case_path = path or DEFAULT_CASES_PATH
    if not case_path.exists():
        return []
    raw = json.loads(case_path.read_text(encoding="utf-8"))
    return [
        AnswerCase(
            id=case["id"],
            kind=case["kind"],
            course_tag=case["course_tag"],
            question=case["question"],
            seed_chunk_labels=tuple(case.get("seed_chunk_labels", ())),
            expectation=dict(case.get("expectation", {})),
        )
        for case in raw["cases"]
    ]


def citation_validity(answer_text: str, provided: int) -> tuple[bool, str]:
    """Every [n] must index a provided chunk; at least one citation is
    required for grounded answers."""
    citations = [int(n) for n in CITATION_RE.findall(answer_text)]
    if not citations:
        return False, "no citations present"
    bad = [n for n in citations if n < 1 or n > provided]
    if bad:
        return False, f"citations out of range: {sorted(set(bad))}"
    return True, f"{len(citations)} valid citations"


def refusal_check(
    answer_text: str,
    chunk_texts: tuple[str, ...] = (),
) -> tuple[bool, str]:
    """Declined the request: a refusal marker present AND no fabricated
    specifics. Citations are NOT evidence of fabrication (review catch
    #1): the best honest refusal cites what the course does cover
    ("the material covers X [1], but not that"). Fabrication check
    (decision 010's second half, review catch #8): specific-looking
    tokens (digit sequences) in the answer that appear in no provided
    chunk are invented."""
    has_marker = REFUSAL_MARKER_RE.search(answer_text) is not None
    if not has_marker:
        return False, "no refusal marker"
    for token in FABRICATED_SPECIFIC_RE.findall(answer_text):
        if not any(token in text for text in chunk_texts):
            return False, f"fabricated specifics not in material: {token!r}"
    return True, "refused without fabricating evidence"


def steer_check(answer_text: str) -> tuple[bool, str]:
    if FILLIN_SHAPE.search(answer_text):
        return False, "bare fill-in shape detected"
    has_steer = STEER_MARKER_RE.search(answer_text) is not None
    if not has_steer:
        return False, "no steer marker (explain + redirect) present"
    return True, "steered toward learning"


def workspace_check(answer_text: str, provided: int) -> tuple[bool, str]:
    """A practice request should open the workspace: at least one
    workspace block, every block passing the tutor's own citation gate
    (the same `extract_workspace_items` the endpoint uses), and the chat
    prose still honoring the citation contract."""
    extracted = extract_workspace_items(answer_text, provided)
    if extracted.withheld:
        return False, "; ".join(extracted.withheld)
    if not extracted.items:
        return False, "no workspace block produced"
    kinds = ", ".join(item.type for item in extracted.items)
    if CITATION_RE.search(extracted.body):
        ok, why = citation_validity(extracted.body, provided)
        if not ok:
            return False, f"workspace {kinds} ok, prose: {why}"
    return True, f"workspace {kinds} passed the citation gate"


GenerationFn = Callable[[str, str], str]
PromptBuilder = Callable[[str, tuple[Candidate, ...]], str]


def _score(
    case: AnswerCase,
    answer_text: str,
    chunk_texts: tuple[str, ...],
) -> tuple[bool, str]:
    """Kind-dispatched scorers. Each is mechanical on the answer text
    plus the seeded chunk texts (refusal fabrication check needs the
    material to compare against). `expectation.citations_required`
    (review catch #13) opts a green case out of the at-least-one-
    citation requirement — a case whose correct answer is a short "the
    material says nothing" style reply is green-with-refusal, not a
    failure."""
    kind = case.kind
    if kind == "green_grounded":
        if not case.expectation.get("citations_required", True):
            if CITATION_RE.search(answer_text):
                ok, why = citation_validity(answer_text, len(chunk_texts))
                return ok, f"green (citations optional): {why}"
            return True, "green (citations optional): none needed"
        ok, why = citation_validity(answer_text, len(chunk_texts))
        return ok, f"green: {why}"
    if kind == "cold_probe":
        ok, why = refusal_check(answer_text, chunk_texts)
        return ok, f"cold: {why}"
    if kind == "yellow_steer":
        ok, why = steer_check(answer_text)
        return ok, f"yellow: {why}"
    if kind == "red_refuse":
        ok, why = refusal_check(answer_text, chunk_texts)
        return ok, f"red: {why}"
    if kind == "workspace_grounded":
        ok, why = workspace_check(answer_text, len(chunk_texts))
        return ok, f"workspace: {why}"
    return False, f"unknown case kind: {kind}"


def _resolve_course(
    conn: Connection, course_tag: str
) -> tuple[str, UUID] | None:
    """Deterministic resolution (review catch #3): reuse the retrieval
    eval's `course_by_tag` block — exact-name match first, then oldest
    course_id; never an undefined pick between duplicate names."""
    row = conn.execute(
        get("retrieval_traces", "course_by_tag"), {"tag": course_tag}
    ).fetchone()
    if row is None:
        return None
    return course_tag, row["course_id"]


def _seed_candidates(
    conn: Connection,
    course_id: UUID,
    labels: tuple[str, ...],
) -> tuple[Candidate, ...] | None:
    """Fix retrieval to the labeled chunks so the harness exercises the
    GENERATION contract, not retrieval quality (that's the retrieval
    eval's job). Returns None when labels were given but matched nothing
    (review catch #5): a case-file typo must surface as UNRESOLVED, not
    masquerade as a citation regression. Ordering is fully determined —
    (source_id, chunk_index, chunk_id) — so the prompt's [n] numbering
    is stable across runs even with colliding labels across sources
    (review catch #6)."""
    if not labels:
        return ()
    rows = conn.execute(
        """
        SELECT chunk.chunk_id, chunk.source_id, chunk.locator_id,
               chunk.chunk_index, chunk.text
        FROM chunks AS chunk
        JOIN locators AS locator
          ON locator.locator_id = chunk.locator_id
        JOIN sources AS source
          ON source.source_id = chunk.source_id
        WHERE source.course_id = :course_id
          AND source.status = 'indexed'
          AND locator.label IN (SELECT value FROM json_each(:labels))
        ORDER BY chunk.source_id, chunk.chunk_index, chunk.chunk_id
        """,
        {"course_id": course_id, "labels": json.dumps(list(labels))},
    ).fetchall()
    if not rows:
        return None
    return tuple(
        Candidate(
            chunk_id=row["chunk_id"],
            source_id=row["source_id"],
            locator_id=row["locator_id"],
            chunk_index=row["chunk_index"],
            text=row["text"],
            rank=float(row["chunk_index"]),
            layers=frozenset({"harness"}),
        )
        for row in rows
    )


def run_answer_eval(
    conn: Connection,
    *,
    generate: GenerationFn,
    cases_path: Path | None = None,
    build_prompt: PromptBuilder | None = None,
    log_dir: Path | None = None,
) -> AnswerEvalSummary:
    """Run every case: build the numbered-material prompt via the tutor's
    real prompt builder, call `generate`, score by kind. `generate(task,
    prompt) -> str` abstracts the provider (stub in v1; the real provider
    lands behind a dedicated eval adapter that bills an eval account —
    review catch #10, decision 010)."""
    from src.backend.common.prompt_registry import load_prompt_policy
    from src.backend.tutor.answer import build_prompt as default_builder

    builder = build_prompt or default_builder
    prompt_policy = load_prompt_policy()
    cases = load_answer_cases(cases_path)
    records: list[CaseRecord] = []
    results: list[AnswerResult] = []
    unresolved: list[str] = []
    for case in cases:
        resolved = _resolve_course(conn, case.course_tag)
        if resolved is None:
            unresolved.append(case.id)
            results.append(
                AnswerResult(
                    case_id=case.id,
                    kind=case.kind,
                    question=case.question,
                    resolved=False,
                    passed=False,
                    detail="course_tag unresolved",
                )
            )
            continue
        _name, course_id = resolved
        candidates = _seed_candidates(
            conn, course_id, case.seed_chunk_labels
        )
        if candidates is None:
            # Labels given but matched nothing: a case-file error must
            # surface as UNRESOLVED, never as a model-failure score
            # (review catch #5).
            unresolved.append(case.id)
            results.append(
                AnswerResult(
                    case_id=case.id,
                    kind=case.kind,
                    question=case.question,
                    resolved=False,
                    passed=False,
                    detail="seed_chunk_labels matched no chunks",
                )
            )
            continue
        prompt = builder(case.question, candidates)
        answer_text = generate("tutor_answer", prompt)
        passed, detail = _score(
            case, answer_text, tuple(c.text for c in candidates)
        )
        records.append(
            CaseRecord(
                case_id=case.id,
                kind=case.kind,
                question=case.question,
                prompt=prompt,
                answer=answer_text,
                chunk_ids=[str(c.chunk_id) for c in candidates],
                passed=passed,
                detail=detail,
            )
        )
        results.append(
            AnswerResult(
                case_id=case.id,
                kind=case.kind,
                question=case.question,
                resolved=True,
                passed=passed,
                detail=detail,
            )
        )
    per_kind: dict[str, list[bool]] = {}
    for result in results:
        if result.resolved:
            per_kind.setdefault(result.kind, []).append(result.passed)
    rates = {
        kind: sum(passes) / len(passes) for kind, passes in per_kind.items()
    }
    resolved_results = [result for result in results if result.resolved]
    # all_passed requires EVERY case to have actually executed (review
    # catch #4): unresolved cases fail the suite loudly ("never a silent
    # pass"), rather than being excluded and letting a mostly-unrun
    # suite read as green.
    summary = AnswerEvalSummary(
        cases=tuple(results),
        unresolved=tuple(unresolved),
        per_kind_pass_rate=rates,
        all_passed=(
            len(resolved_results) == len(cases)
            and bool(resolved_results)
            and all(result.passed for result in resolved_results)
        ),
    )
    _log_summary(
        summary,
        log_dir,
        prompt_version=prompt_policy.prompts_config_version,
        records=records,
    )
    return summary


@dataclass(frozen=True)
class CaseRecord:
    """The full inspection record for one executed case (golden rule 2 +
    review catch #9): the prompt, the answer, and the seeded chunk ids
    are what make a failure diagnosable without re-running."""

    case_id: str
    kind: str
    question: str
    prompt: str
    answer: str
    chunk_ids: list[str]
    passed: bool
    detail: str


def _log_summary(
    summary: AnswerEvalSummary,
    log_dir: Path | None,
    *,
    prompt_version: str,
    records: list[CaseRecord],
) -> None:
    runs_dir = log_dir or (
        Path(__file__).resolve().parents[3] / "runs"
    )
    runs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    log_path = runs_dir / f"eval_answer_{stamp}.log"
    lines = [
        f"answer eval {stamp}",
        f"prompts_config_version: {prompt_version} (review catch #7: "
        "every run is attributable to the prompt version that produced "
        "it)",
        str(summary),
        "",
        "--- per-case inspection records ---",
    ]
    for record in records:
        lines.extend(
            [
                f"### {record.case_id} ({record.kind}) "
                f"passed={record.passed} — {record.detail}",
                f"chunk_ids: {', '.join(record.chunk_ids) or '(none)'}",
                f"question: {record.question}",
                "prompt:",
                record.prompt,
                "answer:",
                record.answer,
                "",
            ]
        )
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")