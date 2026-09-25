"""Saved chats (migration 003; docs/plan-notebook.md §4.2).

A conversation belongs to one course and holds its messages in order.
`model_choice` pins the chat to an endpoint + model (None follows
Settings); `source_ids` narrows retrieval (None means every source).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from src.backend.common.db import Connection, connection
from src.backend.common.queries import get

_FILE = "conversations"
TITLE_MAX_LENGTH = 80


@dataclass(frozen=True)
class Conversation:
    conversation_id: UUID
    course_id: UUID
    title: str
    model_choice: dict[str, Any] | None
    source_ids: tuple[UUID, ...] | None
    created_at: datetime
    updated_at: datetime
    message_count: int
    summary: str = ""
    summary_through: int = 0


@dataclass(frozen=True)
class Message:
    message_id: UUID
    conversation_id: UUID
    seq: int
    role: str
    text: str
    trace_id: UUID | None
    created_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)


def _source_ids(raw: Any) -> tuple[UUID, ...] | None:
    if raw is None:
        return None
    return tuple(UUID(str(value)) for value in raw)


def _to_conversation(row: dict[str, Any]) -> Conversation:
    return Conversation(
        conversation_id=row["conversation_id"],
        course_id=row["course_id"],
        title=row["title"],
        model_choice=row["model_choice"],
        source_ids=_source_ids(row["source_ids"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        message_count=row["message_count"],
        summary=row.get("summary", ""),
        summary_through=row.get("summary_through", 0),
    )


def _to_message(row: dict[str, Any]) -> Message:
    payload = row["payload"] if isinstance(row["payload"], dict) else {}
    return Message(
        message_id=row["message_id"],
        conversation_id=row["conversation_id"],
        seq=row["seq"],
        role=row["role"],
        text=row["text"],
        trace_id=row["trace_id"],
        created_at=row["created_at"],
        payload=payload,
    )


def title_from(question: str) -> str:
    """A chat is titled from its first question: one line, trimmed at a
    word boundary."""
    line = " ".join(question.split())
    if len(line) <= TITLE_MAX_LENGTH:
        return line
    cut = line[: TITLE_MAX_LENGTH - 1].rsplit(" ", 1)[0]
    return f"{cut}…"


def list_conversations(course_id: UUID) -> list[Conversation]:
    with connection() as conn:
        rows = conn.execute(
            get(_FILE, "list_for_course"), {"course_id": course_id}
        ).fetchall()
    return [_to_conversation(row) for row in rows]


def load(
    conn: Connection, course_id: UUID, conversation_id: UUID
) -> Conversation | None:
    row = conn.execute(
        get(_FILE, "get"),
        {"course_id": course_id, "conversation_id": conversation_id},
    ).fetchone()
    return _to_conversation(row) if row else None


def get_conversation(course_id: UUID, conversation_id: UUID) -> Conversation | None:
    with connection() as conn:
        return load(conn, course_id, conversation_id)


def create(course_id: UUID, title: str = "") -> Conversation:
    conversation_id = uuid4()
    with connection() as conn:
        conn.execute(
            get(_FILE, "create"),
            {
                "conversation_id": conversation_id,
                "course_id": course_id,
                "title": title.strip()[:TITLE_MAX_LENGTH],
            },
        )
        conn.commit()
        created = load(conn, course_id, conversation_id)
    assert created is not None
    return created


def update(
    course_id: UUID,
    conversation_id: UUID,
    *,
    title: str,
    model_choice: dict[str, Any] | None,
    source_ids: tuple[UUID, ...] | None,
) -> Conversation | None:
    with connection() as conn:
        conn.execute(
            get(_FILE, "update"),
            {
                "conversation_id": conversation_id,
                "course_id": course_id,
                "title": title.strip()[:TITLE_MAX_LENGTH],
                "model_choice": (
                    json.dumps(model_choice) if model_choice is not None else None
                ),
                "source_ids": (
                    json.dumps([str(value) for value in source_ids])
                    if source_ids is not None
                    else None
                ),
            },
        )
        conn.commit()
        return load(conn, course_id, conversation_id)


def delete(course_id: UUID, conversation_id: UUID) -> bool:
    with connection() as conn:
        cursor = conn.execute(
            get(_FILE, "delete"),
            {"course_id": course_id, "conversation_id": conversation_id},
        )
        conn.commit()
    return cursor.rowcount > 0


def messages(conn: Connection, conversation_id: UUID) -> list[Message]:
    rows = conn.execute(
        get(_FILE, "messages"), {"conversation_id": conversation_id}
    ).fetchall()
    return [_to_message(row) for row in rows]


def add_turn(
    conn: Connection,
    conversation_id: UUID,
    *,
    question: str,
    answer: str,
    trace_id: UUID | None,
    payload: dict[str, Any],
) -> tuple[Message, Message]:
    """Record one question and its answer, and title an untitled chat from
    its first question. Part of the caller's transaction."""
    seq = int(
        conn.execute(
            get(_FILE, "next_seq"), {"conversation_id": conversation_id}
        ).fetchone()["seq"]
    )
    rows: tuple[tuple[UUID, int, str, str, UUID | None, dict[str, Any]], ...] = (
        (uuid4(), seq, "user", question, None, {}),
        (uuid4(), seq + 1, "assistant", answer, trace_id, payload),
    )
    for message_id, message_seq, role, text, trace, data in rows:
        conn.execute(
            get(_FILE, "add_message"),
            {
                "message_id": message_id,
                "conversation_id": conversation_id,
                "seq": message_seq,
                "role": role,
                "text": text,
                "trace_id": trace,
                "payload": json.dumps(data, ensure_ascii=False),
            },
        )
    conn.execute(
        get(_FILE, "set_title_if_empty"),
        {"conversation_id": conversation_id, "title": title_from(question)},
    )
    conn.execute(get(_FILE, "touch"), {"conversation_id": conversation_id})
    stored = [m for m in messages(conn, conversation_id) if m.seq >= seq]
    return stored[0], stored[1]


def set_summary(conversation_id: UUID, summary: str, through: int) -> None:
    """Store a newer rolling summary; an older one never overwrites it."""
    with connection() as conn:
        conn.execute(
            get(_FILE, "set_summary"),
            {
                "conversation_id": conversation_id,
                "summary": summary,
                "summary_through": through,
            },
        )
        conn.commit()


def message_in_course(course_id: UUID, message_id: UUID) -> Message | None:
    with connection() as conn:
        row = conn.execute(
            get(_FILE, "message_in_course"),
            {"course_id": course_id, "message_id": message_id},
        ).fetchone()
    return _to_message(row) if row else None
