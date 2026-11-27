"""Read-only derivation of COURSE capability evidence and CORE preferences.

This module never records observations or refreshes stored course memory.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, cast, get_args
from uuid import UUID

from src.backend.common import settings_repo
from src.backend.common.db import Connection, utc_now
from src.backend.common.learning_config import load_learning_policy
from src.backend.common.queries import get
from src.backend.common.schemas.learning import (
    Capability,
    CoreMemory,
    LearningExperiment,
    MethodMemory,
    TargetMemory,
    TeachingMethod,
)


def rows(conn: Connection, name: str, **params: Any) -> list[dict[str, Any]]:
    return conn.execute(get("learning", name), params).fetchall()


def _database_state(conn: Connection) -> tuple[int, int]:
    """Changes to the database as this connection sees them: its own writes
    (`total_changes`) and other connections' commits (`data_version`)."""
    version = conn.execute("PRAGMA data_version").fetchone()
    value = next(iter(version.values())) if isinstance(version, dict) else version[0]
    return (conn.total_changes, int(value))


def targets(conn: Connection, course_id: UUID) -> list[TargetMemory]:
    """Capability memory, recomputed only when the database has changed: one
    chat message asked for it up to four times (practice plan, adaptation,
    allocation, course memory), re-reading every observation each time. The
    memo lives on the connection (db.AppConnection), so it dies with it."""
    memo = getattr(conn, "memo", None)
    if memo is None:
        return _targets(conn, course_id)
    key = ("targets", course_id, *_database_state(conn))
    cached = memo.get(key)
    if cached is None:
        for stale in [k for k in memo if k[:2] == ("targets", course_id)]:
            del memo[stale]
        cached = memo[key] = _targets(conn, course_id)
    return list(cached)


def _targets(conn: Connection, course_id: UUID) -> list[TargetMemory]:
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
