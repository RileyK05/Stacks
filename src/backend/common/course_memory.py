"""Course memory (decision 007): the per-user, per-course focus node.

The course-memory tree: a user-memory root (behavioral, lifelong, the only
layer that may change model behavior) with one course-memory child per
user per course ("what THIS person struggles with in THIS course"). Facts
about understanding only — never behavior instructions, never shared.

This module owns the child node for the MAIN USER of a course (its owner)
and nobody else: `refresh_for_owner` is the only public write seam. The
node belongs to the user, not the course — it survives archival and purge
as the deletion keepsake (golden rule 6).

Current node content is a grounded course-content summary (concepts,
memory objects, sources, evidence snapshot) — the only thing distillable
before attempts/mastery data exists. Target content is FOCUS memory
distilled from the owner's own student data (Milestone 3 wiring); see
decision 007 "Current state vs target".

NOTE: this is NOT course knowledge. Concepts/dependencies/memory objects/
TOC live in `schemas/memory.py`, `src/backend/memory/`, and their tables;
those describe what the course SAYS, shared per course.
"""

from __future__ import annotations

import json
import math
from typing import Any
from uuid import UUID

from psycopg import Cursor
from psycopg.rows import DictRow
from src.backend.common.lifecycle_config import load_lifecycle_policy
from src.backend.common.queries import get
from src.backend.common.schemas.base import UserTier

_ARCHIVE_FILE = "course_archives"

# 4 characters per token is an approximation; the node text is prose, and
# if exact model tokenization ever becomes necessary it must come from a
# versioned tokenizer, not a second hardcoded estimate.
CHARS_PER_TOKEN = 4

_EVIDENCE_HEADER = "Evidence snapshot:"
_SEMANTIC_HEADER = "Concepts and course memory:"
_SOURCES_HEADER = "Sources:"
_TRUNCATED_MARKER = "[truncated at token budget]"


def target_tokens(source_count: int, tier: UserTier) -> int:
    policy = load_lifecycle_policy()
    scaled = round(policy.summary_base_tokens * math.sqrt(max(source_count, 1)))
    return min(policy.memory_limit(tier), scaled)


def _character_budget(token_budget: int) -> int:
    return token_budget * CHARS_PER_TOKEN


def _evidence_line(
    row: dict[str, Any], *, with_excerpt: bool
) -> str:
    locator = f"; {row['label']}" if row["label"] else ""
    fingerprint = f"; sha256={row['file_hash']}" if row["file_hash"] else ""
    excerpt = f"\n  {row['excerpt']}" if with_excerpt and row["excerpt"] else ""
    return f"- {row['filename']}{locator}{fingerprint}{excerpt}"


def _fit_lines(
    lines: list[str], header: str, character_budget: int
) -> tuple[str, int]:
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

    semantic_lines = [
        f"- {row['name']}: {row['definition']}" for row in concepts
    ] + [f"- [{row['kind']}] {row['content']}" for row in memory_objects]
    if semantic_lines and remaining > 0:
        section, spent = _fit_lines(
            semantic_lines, _SEMANTIC_HEADER, remaining
        )
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


def _fetch_material(
    cur: Cursor[Any], course_id: UUID
) -> dict[str, list[DictRow]]:
    sources = cur.execute(
        get(_ARCHIVE_FILE, "memory_sources"), {"course_id": course_id}
    ).fetchall()
    concepts = cur.execute(
        get(_ARCHIVE_FILE, "memory_concepts"), {"course_id": course_id}
    ).fetchall()
    memory_objects = cur.execute(
        get(_ARCHIVE_FILE, "memory_objects"), {"course_id": course_id}
    ).fetchall()
    evidence = cur.execute(
        get(_ARCHIVE_FILE, "memory_evidence"), {"course_id": course_id}
    ).fetchall()
    return {
        "sources": sources,
        "concepts": concepts,
        "memory_objects": memory_objects,
        "evidence": evidence,
    }


def refresh_for_owner(cur: Cursor[Any], course_id: UUID) -> None:
    """Refresh the course-memory node of the course's main user (its
    owner). This is the ONLY public write seam (decision 007): course
    memory is stored for the main user per course and nobody else, so no
    caller can ever write another user's node. Learners get the harness
    plus their own raw private student data — never a course-memory node.
    """
    course = cur.execute(
        "SELECT owner_user_id FROM courses WHERE course_id = %s",
        (course_id,),
    ).fetchone()
    if course is None:
        return
    _write_node(cur, course_id, [course["owner_user_id"]])


def _write_node(
    cur: Cursor[Any], course_id: UUID, user_ids: list[UUID]
) -> None:
    unique_user_ids = set(user_ids)
    if not unique_user_ids:
        return
    course = cur.execute(
        "SELECT course_id, name FROM courses WHERE course_id = %s",
        (course_id,),
    ).fetchone()
    if course is None:
        return
    material = _fetch_material(cur, course_id)
    tiers = {
        row["user_id"]: UserTier(row["tier"])
        for row in cur.execute(
            "SELECT user_id, tier FROM users WHERE user_id = ANY(%s)",
            (list(unique_user_ids),),
        ).fetchall()
    }
    policy = load_lifecycle_policy()
    assembled: dict[UserTier, tuple[str, list[str]]] = {}
    for user_id in unique_user_ids:
        tier = tiers.get(user_id)
        if tier is None:
            continue
        if tier not in assembled:
            token_budget = target_tokens(len(material["sources"]), tier)
            assembled[tier] = (
                _assemble_summary(material, course["name"], token_budget)
            )
        summary, key_concepts = assembled[tier]
        cur.execute(
            get(_ARCHIVE_FILE, "upsert_memory"),
            {
                "user_id": user_id,
                "course_id": course_id,
                "course_ref": str(course_id),
                "name": course["name"],
                "summary": summary,
                "key_concepts": json.dumps(key_concepts),
                "token_budget": target_tokens(
                    len(material["sources"]), tier
                ),
                "summary_version": policy.summary_version,
            },
        )