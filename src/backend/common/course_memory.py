"""Course memory (decision 007): the per-course focus node.

The course-memory tree: a user-memory root (behavioral, lifelong, the only
layer that may change model behavior) with one course-memory child per
course ("what this student struggles with in THIS course"). Facts about
understanding only — never behavior instructions. One local user per
database, so the node belongs to the course's only user. It survives the
course's trash purge as the deletion keepsake (golden rule 6).

`refresh` is the only write seam. Practice observations and tentative chat
experiments produce the student's focus record, retaining source snapshots.
Courses without student observations retain the material-summary fallback.

NOTE: this is NOT course knowledge. Concepts/dependencies/memory objects/
TOC live in `schemas/memory.py`, `src/backend/memory/`, and their tables;
those describe what the course SAYS.
"""

from __future__ import annotations

import json
import math
from typing import Any
from uuid import UUID, uuid4

from src.backend.common.db import Connection
from src.backend.common.learning_config import load_learning_policy
from src.backend.common.lifecycle_config import load_lifecycle_policy
from src.backend.common.queries import get

_FILE = "course_memory"
DictRow = dict[str, Any]

# 4 characters per token is an approximation; the node text is prose, and
# if exact model tokenization ever becomes necessary it must come from a
# versioned tokenizer, not a second hardcoded estimate.
CHARS_PER_TOKEN = 4

_EVIDENCE_HEADER = "Evidence snapshot:"
_SEMANTIC_HEADER = "Concepts and course memory:"
_SOURCES_HEADER = "Sources:"


def target_tokens(source_count: int) -> int:
    policy = load_lifecycle_policy()
    scaled = round(policy.summary_base_tokens * math.sqrt(max(source_count, 1)))
    return min(policy.memory_max_tokens, scaled)


def _character_budget(token_budget: int) -> int:
    return token_budget * CHARS_PER_TOKEN


def _evidence_line(row: dict[str, Any], *, with_excerpt: bool) -> str:
    locator = f"; {row['label']}" if row["label"] else ""
    fingerprint = f"; sha256={row['file_hash']}" if row["file_hash"] else ""
    excerpt = f"\n  {row['excerpt']}" if with_excerpt and row["excerpt"] else ""
    return f"- {row['filename']}{locator}{fingerprint}{excerpt}"


def _fit_lines(lines: list[str], header: str, character_budget: int) -> tuple[str, int]:
    """Fit whole lines under `character_budget`. Lines are atomic so a hash
    or locator is never cut mid-way. Returns (section, characters used).
    At least the header is always emitted."""
    if character_budget < len(header):
        return header[: max(character_budget, 0)], min(
            len(header), max(character_budget, 0)
        )
    budget = character_budget - len(header)
    body: list[str] = []
    used = 0
    for line in lines:
        cost = len(line) + (1 if body else 0)
        if used + cost > budget:
            break
        body.append(line)
        used += cost
    if not body and lines:
        body = [lines[0][:budget]]
        used = len(body[0])
        return "\n".join([header] + body), len(header) + used
    text = "\n".join([header] + body) if body else header
    return text, len(text)


def _assemble_summary(
    material: dict[str, list[DictRow]],
    name: str,
    token_budget: int,
) -> tuple[str, list[str]]:
    """Assemble the bounded summary. The evidence index is reserved first
    (plan rule: hashes and locators matter more than prose), then semantic
    content fills the remainder. Excerpts are added back only when the
    evidence budget has room."""
    total = _character_budget(token_budget)
    header = f"Course: {name}"
    remaining = total - len(header)

    sources = list(material["sources"])
    concepts = list(material["concepts"])
    memory_objects = list(material["memory_objects"])
    evidence = list(material["evidence"])

    sections: list[str] = [header]
    used = len(header)

    if sources:
        section, spent = _fit_lines(
            [f"- {row['filename']}" for row in sources],
            _SOURCES_HEADER,
            max(remaining // 3, len(_SOURCES_HEADER)),
        )
        sections.append(section)
        used += spent + 1
        remaining -= spent + 1

    if evidence:
        # Reserve at most half the budget; compact lines (no excerpts)
        # always fit before excerpted lines are considered.
        evidence_budget = max(remaining // 2, 1)
        excerpted = [_evidence_line(row, with_excerpt=True) for row in evidence]
        compact = [_evidence_line(row, with_excerpt=False) for row in evidence]
        lines = excerpted if _lines_cost(excerpted) <= evidence_budget else compact
        section, spent = _fit_lines(lines, _EVIDENCE_HEADER, evidence_budget)
        sections.append(section)
        used += spent + 1
        remaining -= spent + 1

    semantic_lines = [f"- {row['name']}: {row['definition']}" for row in concepts] + [
        f"- [{row['kind']}] {row['content']}" for row in memory_objects
    ]
    if semantic_lines and remaining > 0:
        section, spent = _fit_lines(semantic_lines, _SEMANTIC_HEADER, remaining)
        sections.append(section)
        used += spent + 1
        remaining -= spent + 1

    summary = "\n\n".join(sections)

    key_concepts: list[str] = []
    for row in concepts:
        if remaining < len(str(row["name"])):
            break
        key_concepts.append(str(row["name"]))
        remaining -= len(str(row["name"])) + 1
    return summary, key_concepts


def _lines_cost(lines: list[str]) -> int:
    if not lines:
        return 0
    return sum(len(line) for line in lines) + len(lines) - 1


def _fetch_material(conn: Connection, course_id: UUID) -> dict[str, list[DictRow]]:
    params = {"course_id": course_id}
    return {
        "sources": conn.execute(get(_FILE, "memory_sources"), params).fetchall(),
        "concepts": conn.execute(get(_FILE, "memory_concepts"), params).fetchall(),
        "memory_objects": conn.execute(get(_FILE, "memory_objects"), params).fetchall(),
        "evidence": conn.execute(get(_FILE, "memory_evidence"), params).fetchall(),
    }


def refresh(conn: Connection, course_id: UUID) -> None:
    """Rewrite the course's memory node from its current material, inside
    the caller's transaction. The only write seam (decision 007). A course
    that no longer exists leaves its existing node untouched."""
    course = conn.execute(
        get(_FILE, "course_name"), {"course_id": course_id}
    ).fetchone()
    if course is None:
        return
    material = _fetch_material(conn, course_id)
    token_budget = target_tokens(len(material["sources"]))
    summary, key_concepts = _assemble_summary(material, course["name"], token_budget)
    from src.backend.student_model import learning

    focus = learning.targets(conn, course_id)
    docket = learning.experiments(conn, course_id)
    if focus or docket:
        lines = []
        for target in focus:
            if not target.observations:
                continue
            score = (
                "unknown" if target.proficiency is None else f"{target.proficiency}/100"
            )
            observed = target.evidence[-1]
            source: dict[str, Any] = next(iter(observed.get("sources", [])), {})
            checked = (
                target.last_checked.date() if target.last_checked else "unconfirmed"
            )
            lines.append(
                f"- Evidence: {source.get('filename', '(none)')} "
                f"{source.get('label', '')}; source={source.get('source_id')}; "
                f"chunk={source.get('chunk_id')}; {source.get('text', '')[:120]}\n"
                f"  {target.topic} / {target.capability}: {score}; "
                f"{target.independent_items} independent items; "
                f"last checked {checked}; "
                f"selected {observed['selected']}; correct={observed['correct']}; "
                f"fresh={observed['fresh']}; helped={observed['helped']}"
            )
        for experiment in docket:
            if experiment.status in ("proposed", "cooldown"):
                lines.append(
                    f"- Evidence: student message {experiment.message_ref}: "
                    f"{experiment.evidence['student_quote']}\n"
                    f"  Unconfirmed: {experiment.topic} / {experiment.capability}: "
                    f"{experiment.hypothesis}"
                )
        summary, _ = _fit_lines(
            lines,
            f"Course: {course['name']}\n"
            f"Student focus (learning policy {load_learning_policy().version}):",
            _character_budget(token_budget),
        )
        key_concepts = list(dict.fromkeys(t.topic for t in focus))
    conn.execute(
        get(_FILE, "upsert_memory"),
        {
            "memory_id": uuid4(),
            "course_id": course_id,
            "course_ref": str(course_id),
            "name": course["name"],
            "summary": summary,
            "key_concepts": json.dumps(key_concepts),
            "token_budget": token_budget,
            "summary_version": load_lifecycle_policy().summary_version,
        },
    )
