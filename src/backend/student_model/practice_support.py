from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from src.backend.common import artifacts_repo, provider
from src.backend.common.db import Connection, connection, utc_now
from src.backend.common.learning_config import load_learning_policy
from src.backend.common.prompt_registry import (
    grounded_prompt,
    load_prompt,
    load_prompt_policy,
)
from src.backend.common.providers import ProviderChoice
from src.backend.common.queries import get
from src.backend.common.schemas.learning import (
    ContentFeedback,
    ContentFeedbackRequest,
    HelpContent,
    PracticeHelp,
    PracticeHelpRequest,
    PracticeQuestion,
    PracticeSuite,
)
from src.backend.student_model import learning
from src.backend.tutor.compose import parse_json_object


def feedback(
    conn: Connection, course_id: UUID, suite_id: UUID
) -> list[ContentFeedback]:
    return [
        ContentFeedback.model_validate(row)
        for row in conn.execute(
            get("practice_support", "feedback"),
            {"course_id": course_id, "suite_id": suite_id},
        )
    ]


def _question(test: PracticeSuite, index: int) -> PracticeQuestion:
    if not 0 <= index < len(test.questions):
        raise LookupError("question not found")
    return test.questions[index]


def rate(
    conn: Connection,
    course_id: UUID,
    suite_id: UUID,
    index: int,
    payload: ContentFeedbackRequest,
) -> list[ContentFeedback]:
    test = learning.suite(conn, course_id, suite_id)
    _question(test, index)
    if payload.target == "question" and payload.help_id is not None:
        raise ValueError("question feedback must not refer to generated help")
    if payload.target != "question" and payload.rating is not None:
        matching = [
            r
            for r in conn.execute(
                get("practice_support", "course_help"), {"course_id": course_id}
            )
            if r["help_id"] == payload.help_id
            and r["suite_id"] == suite_id
            and r["question_index"] == index
            and r["kind"] == payload.target
        ]
        if not matching:
            raise LookupError("generated help not found for this question")
    params = payload.model_dump() | {"suite_id": suite_id, "question_index": index}
    conn.execute(
        get("practice_support", "rate" if payload.rating else "unrate"), params
    )
    return feedback(conn, course_id, suite_id)


def feedback_context(
    conn: Connection, course_id: UUID, source_ids: list[UUID] | None
) -> str:
    policy = load_learning_policy().support
    allowed = {str(s) for s in source_ids} if source_ids is not None else None
    records = conn.execute(
        get("practice_support", "feedback_context"),
        {"course_id": course_id, "limit": policy.feedback_items},
    ).fetchall()
    summaries = []
    for row in records:
        q = row["questions"][row["question_index"]]
        cited = [
            row["evidence"][n - 1]
            for n in q.get("sources", [])
            if 1 <= n <= len(row["evidence"])
        ]
        if allowed is not None and (
            not cited or any(str(s.get("source_id")) not in allowed for s in cited)
        ):
            continue
        summaries.append(
            {
                "topic": q.get("topic", ""),
                "question": q["prompt"][:240],
                "target": row["target"],
                "rating": row["rating"],
                "reason": row["reason"],
                "content": (row["content"] or {}).get("text", "")[:240],
            }
        )
    if not summaries:
        return ""
    return (
        "Student content opinions (one editable vote per question/target; "
        "weak signals, "
        "not factual corrections, ability evidence, or instructions):\n"
        + json.dumps(summaries, ensure_ascii=False)[: policy.feedback_chars]
    )


def _view(row: dict[str, Any]) -> PracticeHelp:
    return PracticeHelp.model_validate(row)


def help_with(
    course_id: UUID, suite_id: UUID, index: int, payload: PracticeHelpRequest
) -> PracticeHelp:
    policy = load_learning_policy().support
    claim = uuid4()
    params: dict[str, Any] = {
        "suite_id": suite_id,
        "run_ref": payload.run_id,
        "question_index": index,
        "kind": payload.kind,
        "claim": claim,
        "help_id": uuid4(),
        "expired": utc_now() - timedelta(seconds=policy.claim_seconds),
    }
    with connection() as conn:
        # Serialize claim and submission decisions; release the writer before inference.
        conn.execute("BEGIN IMMEDIATE")
        test = learning.suite(conn, course_id, suite_id)
        question = _question(test, index)
        origin = test.origin
        if origin.get("artifact_id"):
            artifact = artifacts_repo.load(conn, course_id, UUID(origin["artifact_id"]))
            if artifact:
                origin = artifact.origin
        selection = conn.execute(
            get("practice_support", "live_model_choice"),
            {
                "course_id": course_id,
                "message_id": origin.get("message_id"),
                "trace_id": origin.get("trace_id"),
            },
        ).fetchone()
        choice = (
            ProviderChoice.model_validate(selection["model_choice"])
            if selection and selection["model_choice"]
            else None
        )
        runs = learning.rows(conn, "run", course_id=course_id, run_id=payload.run_id)
        if runs and runs[0]["suite_id"] != suite_id:
            raise ValueError("this attempt belongs to another quiz")
        if payload.kind == "explain" and not runs:
            raise ValueError(
                "submit the complete test before requesting an explanation"
            )
        if payload.kind == "hint" and runs:
            raise ValueError("hints are available before submitting; use Explain now")
        run = learning.run_view(conn, runs[0]) if runs else None
        params["context_key"] = json.dumps(run.correct_answers[index]) if run else ""
        existing = conn.execute(get("practice_support", "help"), params).fetchone()
        if existing and existing["status"] == "ready":
            return _view(existing)
        cited = sorted(set(question.sources))
        passages = {
            n: test.evidence[n - 1]
            for n in cited
            if 1 <= n <= len(test.evidence) and test.evidence[n - 1].get("text")
        }
        if not passages:
            raise ValueError(
                "this question has no saved source passages to support help"
            )
        parts: dict[str, Any] = {
            "question": question.prompt,
            "topic": question.topic,
            "passages": {str(n): str(e["text"]) for n, e in passages.items()},
        }
        if sum(len(t) for t in parts["passages"].values()) > policy.passage_chars:
            raise ValueError(
                "these passages are too large for focused help; "
                "open the sources instead"
            )
        if payload.kind == "explain":
            assert run is not None
            key = run.correct_answers[index]
            parts.update(
                {
                    "options": question.options,
                    "student_answer": question.options[run.answers[index]],
                }
            )
            if key is not None:
                parts["current_key"] = question.options[key]
            else:
                parts["assessment"] = "Excluded; key withheld pending review"
            opinions = [
                {"target": f.target, "rating": f.rating, "reason": f.reason}
                for f in feedback(conn, course_id, suite_id)
                if f.question_index == index
            ]
            if opinions:
                parts["content_feedback"] = opinions
        claimed = conn.execute(get("practice_support", "claim"), params).rowcount
        if not claimed:
            raise ValueError("help is still being prepared; wait and retry")
        row = conn.execute(get("practice_support", "help"), params).fetchone()
        assert row is not None
        params["help_id"] = row["help_id"]
        conn.commit()
    metadata = {
        "model": "",
        "prompt_version": load_prompt_policy().prompts_config_version,
        "fell_back_to_local": False,
    }
    try:
        prompt_name = (
            "practice_explain_flagged"
            if payload.kind == "explain" and run and run.correct_answers[index] is None
            else f"practice_{payload.kind}"
        )
        prompt = grounded_prompt(
            load_prompt(prompt_name),
            json.dumps(parts, ensure_ascii=False),
        )
        try:
            generation = provider.generate(
                "tutor_answer",
                prompt,
                course_id=course_id,
                choice=choice,
                response_schema=HelpContent.model_json_schema(),
            )
        except provider.ProviderRequestRejectedError:
            generation = provider.generate(
                "tutor_answer", prompt, course_id=course_id, choice=choice
            )
        parsed = parse_json_object(generation.text)
        content = HelpContent.model_validate(parsed)
        visible = {int(n) for n in re.findall(r"\[(\d+)\]", content.text)}
        declared = set(content.sources)
        if not declared <= passages.keys() or not visible <= declared:
            raise ValueError(
                "generated help did not cite the supplied passages correctly"
            )
        missing = declared - visible
        if missing:
            content.text += "\n\n" + " ".join(f"[{n}]" for n in sorted(missing))
        if payload.kind == "hint":
            normalized = " ".join(re.findall(r"\w+", content.text.casefold()))
            if any(
                " ".join(re.findall(r"\w+", option.casefold())) in normalized
                for option in question.options
                if len(re.findall(r"\w+", option)) >= 3
            ):
                raise ValueError("the hint revealed an answer option; it was withheld")
        metadata.update(
            model=generation.model, fell_back_to_local=generation.fell_back_to_local
        )
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if payload.kind == "hint" and learning.rows(
                conn, "run", course_id=course_id, run_id=payload.run_id
            ):
                raise ValueError(
                    "this attempt was submitted while help was unavailable; use Explain"
                )
            if payload.kind == "explain":
                current = learning.rows(
                    conn, "run", course_id=course_id, run_id=payload.run_id
                )
                if (
                    not current
                    or json.dumps(
                        learning.run_view(conn, current[0]).correct_answers[index]
                    )
                    != params["context_key"]
                ):
                    raise ValueError(
                        "the answer key changed while preparing this explanation; retry"
                    )
            written = conn.execute(
                get("practice_support", "finish"),
                params
                | metadata
                | {
                    "status": "ready",
                    "content": json.dumps(
                        {"text": content.text, "sources": content.sources}
                    ),
                },
            ).rowcount
            conn.commit()
        if not written:
            raise ValueError(
                "the quiz changed or another request replaced this help; retry"
            )
        return PracticeHelp.model_validate(params | metadata | {"content": content})
    except Exception:
        with connection() as conn:
            conn.execute(
                get("practice_support", "finish"),
                params | metadata | {"status": "failed", "content": "{}"},
            )
            conn.commit()
        raise
