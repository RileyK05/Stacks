from __future__ import annotations

import json
import math
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from psycopg import Cursor
from src.backend.common.lifecycle_config import load_lifecycle_policy
from src.backend.common.queries import get
from src.backend.common.schemas.base import UserTier

_ARCHIVE_FILE = "course_archives"


def target_tokens(source_count: int, tier: UserTier) -> int:
    policy = load_lifecycle_policy()
    scaled = round(policy.summary_base_tokens * math.sqrt(max(source_count, 1)))
    return min(policy.memory_limit(tier), scaled)


def _summary_material(
    cur: Cursor[Any], course_id: UUID, name: str
) -> tuple[str, list[str], int]:
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
    sections = [f"Course: {name}"]
    if concepts:
        sections.append(
            "Concepts:\n"
            + "\n".join(
                f"- {row['name']}: {row['definition']}" for row in concepts
            )
        )
    if memory_objects:
        sections.append(
            "Course memory:\n"
            + "\n".join(
                f"- [{row['kind']}] {row['content']}" for row in memory_objects
            )
        )
    if sources:
        source_lines = "\n".join(f"- {row['filename']}" for row in sources)
        sections.append(f"Sources:\n{source_lines}")
    if evidence:
        evidence_lines = []
        for row in evidence:
            fingerprint = f"; sha256={row['file_hash']}" if row["file_hash"] else ""
            locator = f"; {row['label']}" if row["label"] else ""
            excerpt = f"\n  {row['excerpt']}" if row["excerpt"] else ""
            evidence_lines.append(
                f"- {row['filename']}{locator}{fingerprint}{excerpt}"
            )
        sections.append("Evidence snapshot:\n" + "\n".join(evidence_lines))
    return "\n\n".join(sections), [row["name"] for row in concepts], len(sources)


def _truncate_to_tokens(text: str, token_budget: int) -> str:
    character_budget = token_budget * 4
    if len(text) <= character_budget:
        return text
    marker = "\n\n[Memory truncated at configured token budget]"
    return text[: character_budget - len(marker)].rstrip() + marker


def upsert_for_users(
    cur: Cursor[Any], course_id: UUID, user_ids: Iterable[UUID]
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
    material, key_concepts, source_count = _summary_material(
        cur, course_id, course["name"]
    )
    policy = load_lifecycle_policy()
    for user_id in unique_user_ids:
        tier_row = cur.execute(
            "SELECT tier FROM users WHERE user_id = %s", (user_id,)
        ).fetchone()
        if tier_row is None:
            continue
        token_budget = target_tokens(source_count, UserTier(tier_row["tier"]))
        cur.execute(
            get(_ARCHIVE_FILE, "upsert_memory"),
            {
                "user_id": user_id,
                "course_id": course_id,
                "course_ref": str(course_id),
                "name": course["name"],
                "summary": _truncate_to_tokens(material, token_budget),
                "key_concepts": json.dumps(key_concepts),
                "token_budget": token_budget,
                "summary_version": policy.summary_version,
            },
        )


def upsert_for_current_participants(cur: Cursor[Any], course_id: UUID) -> None:
    participants = cur.execute(
        get(_ARCHIVE_FILE, "archive_participants"), {"course_id": course_id}
    ).fetchall()
    upsert_for_users(cur, course_id, (row["user_id"] for row in participants))
