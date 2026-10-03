"""Saved generated material is a lookup aid; factual evidence stays original."""

from __future__ import annotations

import json
import re
from collections.abc import Collection
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from src.backend.common.db import Connection, json_ids
from src.backend.common.queries import get


class RetrievalSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_generated: bool = False


def settings(conn: Connection, course_id: UUID) -> RetrievalSettings:
    row = conn.execute(
        get("settings", "get_setting"), {"key": f"rag.generated:{course_id}"}
    ).fetchone()
    return RetrievalSettings.model_validate(row["value"] if row else {})


def save_settings(conn: Connection, course_id: UUID, value: RetrievalSettings) -> None:
    conn.execute(
        get("settings", "put_setting"),
        {
            "key": f"rag.generated:{course_id}",
            "value": value.model_dump_json(),
        },
    )


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_text(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(
            _text(item)
            for key, item in value.items()
            if key not in {"sources", "id", "type", "answer"}
        )
    return ""


def lookup(
    conn: Connection,
    course_id: UUID,
    tokens: list[str],
    limit: int,
    source_ids: Collection[UUID] | None,
) -> list[dict[str, Any]]:
    if limit < 1 or not tokens or not settings(conn, course_id).include_generated:
        return []
    materials = conn.execute(
        get("passages", "saved_generated_materials"), {"course_id": course_id}
    ).fetchall()
    ranked = []
    for material in materials:
        origin = material["origin"]
        if not (
            origin.get("model")
            or material["has_model_history"]
            or origin.get("type") == "legacy_knowledge_annotation"
        ):
            continue
        support_ids = material["sources"]
        if not support_ids:
            continue
        rows = conn.execute(
            get("passages", "eligible_support"),
            {
                "course_id": course_id,
                "chunk_ids": json.dumps(support_ids),
                "source_ids": json_ids(source_ids) if source_ids is not None else None,
            },
        ).fetchall()
        if {str(row["chunk_id"]) for row in rows} != set(support_ids):
            continue
        content = (material["title"] + "\n" + _text(material["content"])).casefold()
        vocabulary = set(re.findall(r"[^\W_]+", content))
        score = sum(token in vocabulary for token in tokens) / len(tokens)
        if not score:
            continue
        for row in rows:
            ranked.append(
                {
                    **row,
                    "rank": score,
                    "generated_title": material["title"],
                    "generated_artifact_id": material["artifact_id"],
                    "generated_version": material["version"],
                }
            )
    ranked.sort(
        key=lambda row: (
            -row["rank"],
            str(row["generated_artifact_id"]),
            str(row["chunk_id"]),
        )
    )
    seen = set()
    result = []
    for row in ranked:
        if row["chunk_id"] not in seen:
            seen.add(row["chunk_id"])
            result.append(row)
        if len(result) >= limit:
            break
    return result
