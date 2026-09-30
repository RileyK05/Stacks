from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, cast, get_args
from uuid import UUID, uuid4

from src.backend.common import settings_repo
from src.backend.common.db import Connection, json_ids, utc_now
from src.backend.common.learning_config import load_learning_policy
from src.backend.common.queries import get
from src.backend.common.schemas.learning import (
    Capability,
    CoreMemory,
    LearningExperiment,
    LearningView,
    MethodMemory,
    PracticeQuestion,
    PracticeRun,
    PracticeSubmission,
    PracticeSuite,
    TargetMemory,
    TeachingMethod,
)


def rows(conn: Connection, name: str, **params: Any) -> list[dict[str, Any]]:
    return conn.execute(get("learning", name), params).fetchall()


def evidence_for(conn: Connection, chunk_ids: tuple[UUID, ...]) -> list[dict[str, Any]]:
    return conn.execute(
        get("retrieval_traces", "chunks_with_locators_by_ids"),
        {"chunk_ids": json_ids(chunk_ids)},
    ).fetchall()


def _json(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


def create_suite(
    conn: Connection,
    course_id: UUID,
    title: str,
    questions: list[PracticeQuestion],
    chunk_ids: tuple[UUID, ...],
    origin: dict[str, Any],
    method: TeachingMethod | None = None,
) -> UUID:
    if not questions:
        raise ValueError("a practice test needs questions")
    evidence = evidence_for(conn, chunk_ids)
    by_id = {str(row["chunk_id"]): row for row in evidence}
    numbered = [
        by_id.get(str(cid), {"chunk_id": str(cid), "removed": True})
        for cid in chunk_ids
    ]
    for question in questions:
        if question.answer >= len(question.options):
            raise ValueError("the answer key is outside the options")
        if any(not 1 <= n <= len(numbered) for n in question.sources):
            raise ValueError("a question cites material outside this test")
    suite_id = uuid4()
    inserted = conn.execute(
        get("learning", "create_suite"),
        {
            "suite_id": suite_id,
            "course_id": course_id,
            "title": title,
            "questions": _json([q.model_dump() for q in questions]),
            "evidence": _json(numbered),
            "origin": _json(origin),
            "method": method,
        },
    )
    if inserted.rowcount == 0:
        prior = next(
            (
                r
                for r in rows(conn, "suites", course_id=course_id)
                if r["origin"] == origin
            ),
            None,
        )
        if prior is None:
            raise ValueError("practice test could not be registered")
        return UUID(str(prior["suite_id"]))
    return suite_id


def suite(conn: Connection, course_id: UUID, suite_id: UUID) -> PracticeSuite:
    found = rows(conn, "suite", course_id=course_id, suite_id=suite_id)
    if not found:
        raise LookupError("practice test not found")
    return PracticeSuite.model_validate(found[0])


def run_view(conn: Connection, record: dict[str, Any]) -> PracticeRun:
    test = suite(conn, record["course_id"], record["suite_id"])
    corrected = {
        r["question_index"]: r["answer"]
        for r in rows(conn, "assessments", suite_id=test.suite_id)
    }
    keys = [corrected.get(i, q.answer) for i, q in enumerate(test.questions)]
    return PracticeRun(
        **record,
        correct_answers=keys,
        results=[
            None if key is None else picked == key
            for picked, key in zip(record["answers"], keys, strict=True)
        ],
    )


def _fingerprint(question: PracticeQuestion) -> str:
    # Option reordering and answer-key correction do not make a fresh problem.
    text = _json(
        [
            " ".join(question.prompt.casefold().split()),
            sorted(" ".join(o.casefold().split()) for o in question.options),
        ]
    )
    return hashlib.sha256(text.encode()).hexdigest()


def refresh_memory(conn: Connection, course_id: UUID) -> None:
    from src.backend.common import course_memory

    course_memory.refresh(conn, course_id)


def submit(
    conn: Connection,
    course_id: UUID,
    suite_id: UUID,
    payload: PracticeSubmission,
) -> PracticeRun:
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    test = suite(conn, course_id, suite_id)
    requested_help = payload.helped or [False] * len(test.questions)
    existing = rows(conn, "run", course_id=course_id, run_id=payload.run_id)
    if existing:
        if (
            existing[0]["suite_id"] != suite_id
            or existing[0]["answers"] != payload.answers
            or existing[0]["requested_help"] != requested_help
        ):
            raise ValueError("this submission ID already belongs to another attempt")
        return run_view(conn, existing[0])
    if len(payload.answers) != len(test.questions):
        raise ValueError("submit the complete test")
    if payload.helped and len(payload.helped) != len(payload.answers):
        raise ValueError("help flags must match the questions")
    if any(
        pick < 0 or pick >= len(q.options)
        for pick, q in zip(payload.answers, test.questions, strict=True)
    ):
        raise ValueError("a selected option does not exist")
    policy = load_learning_policy()
    if conn.execute(
        get("practice_support", "pending"),
        {
            "course_id": course_id,
            "suite_id": suite_id,
            "run_ref": payload.run_id,
            "expired": utc_now() - timedelta(seconds=policy.support.claim_seconds),
        },
    ).fetchone():
        raise ValueError("wait for the hint to finish before submitting")
    inserted = conn.execute(
        get("learning", "create_run"),
        {
            "run_id": payload.run_id,
            "suite_id": suite_id,
            "course_id": course_id,
            "answers": _json(payload.answers),
            "helped": _json(requested_help),
            "requested_help": _json(requested_help),
            "policy_version": policy.version,
        },
    )
    if inserted.rowcount == 0:
        existing = rows(conn, "run", course_id=course_id, run_id=payload.run_id)
        if not existing:
            raise ValueError("this submission ID belongs to another course")
        return submit(conn, course_id, suite_id, payload)
    prior = rows(conn, "observations", course_id=course_id)
    seen = {r["fingerprint"] for r in prior}
    assisted = {
        _fingerprint(
            PracticeQuestion.model_validate(r["questions"][r["question_index"]])
        )
        for r in conn.execute(
            get("practice_support", "course_help"), {"course_id": course_id}
        )
    }
    actual_help = [
        helped or _fingerprint(q) in seen or _fingerprint(q) in assisted
        for q, helped in zip(test.questions, requested_help, strict=True)
    ]
    conn.execute(
        get("learning", "update_run_help"),
        {
            "course_id": course_id,
            "run_id": payload.run_id,
            "helped": _json(actual_help),
        },
    )
    corrected = {
        r["question_index"]: r["answer"]
        for r in rows(conn, "assessments", suite_id=suite_id)
    }
    for index, (question, picked, helped) in enumerate(
        zip(test.questions, payload.answers, actual_help, strict=True)
    ):
        fingerprint = _fingerprint(question)
        key = corrected.get(index, question.answer)
        correct = None if key is None else picked == key
        fresh = fingerprint not in seen
        seen.add(fingerprint)
        observation_id = uuid4()
        evidence = {
            "question": question.prompt,
            "selected": question.options[picked],
            "selected_index": picked,
            "key": None if key is None else question.options[key],
            "run_id": str(payload.run_id),
            "suite_id": str(suite_id),
            "sources": [test.evidence[n - 1] for n in question.sources],
            "helped": helped,
            "teaching_context": test.origin.get("teaching_context"),
            "fresh": fresh,
        }
        conn.execute(
            get("learning", "create_observation"),
            {
                "observation_id": observation_id,
                "course_id": course_id,
                "run_ref": payload.run_id,
                "suite_ref": suite_id,
                "question_index": index,
                "fingerprint": fingerprint,
                "topic": question.topic.strip() or question.prompt,
                "capability": question.capability,
                "correct": correct,
                "helped": helped,
                "fresh": fresh,
                "method": test.method,
                "evidence": _json(evidence),
            },
        )
        if test.method:
            conn.execute(
                get("learning", "core_observation"),
                {
                    "observation_id": observation_id,
                    "course_ref": str(course_id),
                    "method": test.method,
                    "correct": correct,
                    "helped": helped,
                    "fresh": fresh,
                    "evidence": _json(evidence),
                },
            )
    _check_experiments(
        conn, course_id, test, payload.answers, corrected, requested_help, prior
    )
    refresh_memory(conn, course_id)
    return run_view(
        conn, rows(conn, "run", course_id=course_id, run_id=payload.run_id)[0]
    )


def targets(conn: Connection, course_id: UUID) -> list[TargetMemory]:
    policy = load_learning_policy().scoring
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for observation in rows(conn, "observations", course_id=course_id):
        grouped[(observation["topic"].casefold(), observation["capability"])].append(
            observation
        )
    result: list[TargetMemory] = []
    for (_topic, capability), history in grouped.items():
        valid = [r for r in history if r["fresh"] and r["correct"] is not None]
        independent = sum(not r["helped"] for r in valid)
        weights = [policy.assisted_weight if r["helped"] else 1.0 for r in valid]
        total = sum(weights)
        score = (
            round(
                100
                * sum(
                    weight * r["correct"]
                    for weight, r in zip(weights, valid, strict=True)
                )
                / total
            )
            if total
            else None
        )
        cap = (
            policy.assisted_only_cap
            if independent == 0
            else 100
            if independent >= policy.proficient_items
            else policy.five_item_cap
            if independent >= 5
            else policy.three_item_cap
            if independent >= 3
            else policy.two_item_cap
            if independent >= 2
            else policy.initial_cap
        )
        result.append(
            TargetMemory(
                topic=history[0]["topic"],
                capability=cast(Capability, capability),
                proficiency=min(score, cap) if score is not None else None,
                independent_items=independent,
                observations=len(history),
                last_checked=valid[-1]["created_at"] if valid else None,
                evidence=[
                    r["evidence"]
                    | {"correct": r["correct"], "checked_at": str(r["created_at"])}
                    for r in history[-5:]
                ],
            )
        )
    known_topics = {
        r["topic"].casefold(): r["topic"]
        for r in rows(conn, "observations", course_id=course_id)
    }
    for record in rows(conn, "suites", course_id=course_id):
        for question in record["questions"]:
            topic = question.get("topic") or question["prompt"]
            known_topics.setdefault(topic.casefold(), topic)
    measured = {(t.topic.casefold(), t.capability) for t in result}
    for key, topic in known_topics.items():
        for capability in get_args(Capability):
            if (key, capability) not in measured:
                result.append(
                    TargetMemory(
                        topic=topic,
                        capability=capability,
                        proficiency=None,
                        independent_items=0,
                        observations=0,
                        last_checked=None,
                        evidence=[],
                    )
                )
    return sorted(
        result,
        key=lambda item: (
            item.proficiency is None,
            item.proficiency or 0,
            item.topic,
            item.capability,
        ),
    )


def core(conn: Connection) -> CoreMemory:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows(conn, "core_observations"):
        grouped[row["method"]].append(row)
    methods = [
        MethodMemory(
            method=cast(TeachingMethod, method),
            successes=sum(
                r["correct"] == 1 for r in history if r["fresh"] and not r["helped"]
            ),
            checks=sum(
                r["correct"] is not None
                for r in history
                if r["fresh"] and not r["helped"]
            ),
            courses=len({r["course_ref"] for r in history}),
            evidence=[r["evidence"] for r in history[-5:]],
        )
        for method, history in grouped.items()
    ]
    return CoreMemory(
        preferred_method=settings_repo.get_setting("learning.preferred_method"),
        methods=methods,
    )


def experiments(conn: Connection, course_id: UUID) -> list[LearningExperiment]:
    result = [
        LearningExperiment.model_validate(r)
        for r in rows(conn, "experiments", course_id=course_id)
    ]
    now = utc_now()
    return [
        e.model_copy(update={"status": "retired"})
        if e.status in ("proposed", "cooldown") and e.expires_at <= now
        else e
        for e in result
    ]


def view(conn: Connection, course_id: UUID) -> LearningView:
    return LearningView(
        targets=targets(conn, course_id),
        experiments=experiments(conn, course_id),
        runs=[run_view(conn, r) for r in rows(conn, "runs", course_id=course_id)],
        core=core(conn),
    )


def revise(
    conn: Connection,
    course_id: UUID,
    suite_id: UUID,
    index: int,
    answer: int | None,
    reason: str,
) -> None:
    test = suite(conn, course_id, suite_id)
    if not 0 <= index < len(test.questions):
        raise LookupError("question not found")
    question = test.questions[index]
    if answer is not None and not 0 <= answer < len(question.options):
        raise ValueError("the corrected key must be one of the options")
    conn.execute(
        get("learning", "correct_assessment"),
        {
            "suite_id": suite_id,
            "question_index": index,
            "answer": answer,
            "reason": reason,
        },
    )
    for observation in rows(conn, "observations", course_id=course_id):
        if (
            observation["suite_ref"] != suite_id
            or observation["question_index"] != index
        ):
            continue
        evidence = observation["evidence"]
        evidence["key"] = question.options[answer] if answer is not None else None
        evidence["assessment_correction"] = reason
        correct = evidence["selected_index"] == answer if answer is not None else None
        conn.execute(
            get("learning", "revise_observation"),
            {
                "observation_id": observation["observation_id"],
                "correct": correct,
                "evidence": _json(evidence),
            },
        )
        if observation["method"] and any(
            r["observation_id"] == observation["observation_id"]
            for r in rows(conn, "core_observations")
        ):
            conn.execute(
                get("learning", "core_observation"),
                {
                    **observation,
                    "course_ref": str(course_id),
                    "correct": correct,
                    "evidence": _json(evidence),
                },
            )
    for experiment in experiments(conn, course_id):
        checks = experiment.evidence.get("test_checks", [])
        if any(
            check.get("suite_id") == str(suite_id)
            and index in check.get("questions", [])
            for check in checks
        ):
            conn.execute(
                get("learning", "update_experiment"),
                {
                    "course_id": course_id,
                    "experiment_id": experiment.experiment_id,
                    "status": "proposed"
                    if experiment.expires_at > utc_now()
                    else "retired",
                    "checks": 0,
                    "next_check_at": utc_now(),
                },
            )
    refresh_memory(conn, course_id)


def _check_experiments(
    conn: Connection,
    course_id: UUID,
    test: PracticeSuite,
    answers: list[int],
    corrected: dict[int, int | None],
    helped: list[bool],
    prior: list[dict[str, Any]],
) -> None:
    now = utc_now()
    policy = load_learning_policy().practice
    seen = {r["fingerprint"] for r in prior}
    for experiment in experiments(conn, course_id):
        if experiment.status not in ("proposed", "cooldown"):
            continue
        matches = [
            i
            for i, q in enumerate(test.questions)
            if q.topic.casefold() == experiment.topic.casefold()
            and q.capability == experiment.capability
            and _fingerprint(q) not in seen
            and not helped[i]
            and corrected.get(i, q.answer) is not None
        ]
        if experiment.expires_at <= now:
            status, checks = "retired", experiment.checks
        elif not matches or experiment.next_check_at > now:
            continue
        else:
            passed = all(
                answers[i] == corrected.get(i, test.questions[i].answer)
                for i in matches
            )
            checks = experiment.checks + 1
            experiment.evidence.setdefault("test_checks", []).append(
                {"suite_id": str(test.suite_id), "questions": matches, "passed": passed}
            )
            status = (
                "resolved"
                if passed
                else "retired"
                if checks >= policy.experiment_max_checks
                else "cooldown"
            )
        conn.execute(
            get("learning", "update_experiment"),
            {
                "course_id": course_id,
                "experiment_id": experiment.experiment_id,
                "status": status,
                "checks": checks,
                "next_check_at": now + timedelta(days=policy.cooldown_days),
            },
        )
        conn.execute(
            get("learning", "experiment_evidence"),
            {
                "course_id": course_id,
                "experiment_id": experiment.experiment_id,
                "evidence": _json(experiment.evidence),
            },
        )


def adaptation(
    conn: Connection,
    course_id: UUID,
    question: str,
    *,
    source_ids: list[UUID] | None = None,
    now: datetime | None = None,
) -> tuple[str, str, TeachingMethod | None]:
    now = now or utc_now()
    policy = load_learning_policy()
    root = core(conn)
    method = root.preferred_method or ("step_by_step" if not root.methods else None)
    if method is None and root.methods:
        # Explore less-tested methods occasionally; successes remain observations,
        # not a claim that the method caused the outcome.
        total = sum(m.checks for m in root.methods)
        if total % policy.practice.method_exploration_interval == 0:
            method = cast(
                TeachingMethod,
                min(
                    policy.methods,
                    key=lambda key: next(
                        (m.checks for m in root.methods if m.method == key), 0
                    ),
                ),
            )
        else:
            method = max(
                root.methods, key=lambda m: (m.successes / max(m.checks, 1), -m.checks)
            ).method
    focus, maintenance = practice_plan(
        conn, course_id, question, source_ids=source_ids, now=now
    )
    blocks = []
    if focus:
        blocks.append(
            "Course focus observations (not factual source material):\n"
            + "\n".join(text for _, _, text in focus)
        )
    if maintenance:
        blocks.append(
            "Occasional maintenance checks:\n"
            + "\n".join(text for _, _, text in maintenance)
        )
    context = "\n\n".join(blocks)[: policy.practice.context_chars]
    behavior = policy.methods[method] if method is not None else ""
    return context, behavior, method


def practice_plan(
    conn: Connection,
    course_id: UUID,
    question: str,
    *,
    source_ids: list[UUID] | None = None,
    now: datetime | None = None,
) -> tuple[list[tuple[str, Capability, str]], list[tuple[str, Capability, str]]]:
    from src.backend.tutor.compose import asks_for_overview, retrieval_topic

    now = now or utc_now()
    policy = load_learning_policy().practice
    allowed = {str(cid) for cid in source_ids} if source_ids is not None else None
    generic = not retrieval_topic(question).strip() or asks_for_overview(question)

    def eligible(topic: str, evidence: list[dict[str, Any]]) -> bool:
        related = generic or topic.casefold() in question.casefold()
        scoped = allowed is None or any(
            str(s.get("source_id")) in allowed
            for e in evidence
            for s in e.get("sources", [])
        )
        return related and scoped

    focus: list[tuple[str, Capability, str]] = []
    maintenance: list[tuple[str, Capability, str]] = []
    for target in targets(conn, course_id):
        if target.last_checked is None or not eligible(target.topic, target.evidence):
            continue
        age = now - target.last_checked
        if (
            target.proficiency is not None
            and target.proficiency < policy.weak_below
            and age >= timedelta(days=policy.cooldown_days)
        ):
            focus.append(
                (
                    target.topic.casefold(),
                    target.capability,
                    f"{target.topic}: {target.capability}; estimated "
                    f"{target.proficiency}/100, "
                    f"{target.independent_items} independent items",
                )
            )
        elif (
            target.proficiency is not None
            and target.proficiency >= policy.strong_at
            and age >= timedelta(days=policy.maintenance_days)
        ):
            maintenance.append(
                (
                    target.topic.casefold(),
                    target.capability,
                    f"{target.topic}: {target.capability}",
                )
            )
    for experiment in experiments(conn, course_id):
        if (
            experiment.status in ("proposed", "cooldown")
            and experiment.next_check_at <= now < experiment.expires_at
            and eligible(experiment.topic, [experiment.evidence])
        ):
            focus.append(
                (
                    experiment.topic.casefold(),
                    experiment.capability,
                    f"Unconfirmed: {experiment.topic} / {experiment.capability}: "
                    f"{experiment.proposed_check}",
                )
            )
    return focus[: policy.focus_slots], maintenance[: policy.maintenance_slots]


def allocate_questions(
    conn: Connection,
    course_id: UUID,
    request: str,
    questions: list[PracticeQuestion],
    *,
    source_ids: list[UUID],
) -> list[PracticeQuestion]:
    policy = load_learning_policy().practice
    focus, maintenance = practice_plan(conn, course_id, request, source_ids=source_ids)
    due_focus = {(topic, capability) for topic, capability, _ in focus}
    due_maintenance = {(topic, capability) for topic, capability, _ in maintenance}
    known = {(t.topic.casefold(), t.capability): t for t in targets(conn, course_id)}
    seen = {r["fingerprint"] for r in rows(conn, "observations", course_id=course_id)}
    selected: list[PracticeQuestion] = []
    focused = maintained = 0
    for question in questions:
        fingerprint = _fingerprint(question)
        if fingerprint in seen:
            continue
        key = (question.topic.casefold(), question.capability)
        target = known.get(key)
        explicit = bool(
            question.topic and question.topic.casefold() in request.casefold()
        )
        if not explicit and target is not None and target.proficiency is not None:
            if target.proficiency < policy.weak_below:
                if key not in due_focus or focused >= policy.focus_slots:
                    continue
                focused += 1
            elif target.proficiency >= policy.strong_at:
                if key not in due_maintenance or maintained >= policy.maintenance_slots:
                    continue
                maintained += 1
        elif not explicit and key in due_focus:
            if focused >= policy.focus_slots:
                continue
            focused += 1
        selected.append(question)
        seen.add(fingerprint)
    return selected
