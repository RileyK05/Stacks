from uuid import UUID, uuid4

from src.backend.common.db import Connection
from src.backend.common.queries import get
from src.backend.common.schemas.work import (
    DocumentUpdate,
    WorkAsk,
    WorkCreate,
    WorkDocument,
    WorkReply,
    WorkSession,
    WorkSummary,
    WorkTurn,
)


class WorkNotFoundError(LookupError):
    pass


class WorkConflictError(ValueError):
    pass


def session(conn: Connection, course_id: UUID, session_id: UUID) -> WorkSession:
    row = conn.execute(
        get("work", "session"), {"course_id": course_id, "session_id": session_id}
    ).fetchone()
    if not row:
        raise WorkNotFoundError("Work session not found in this course.")
    doc = conn.execute(
        get("work", "document"), {"session_id": session_id, "revision": row["revision"]}
    ).fetchone()
    turns = conn.execute(get("work", "turns"), {"session_id": session_id}).fetchall()
    return WorkSession(
        **row,
        document=WorkDocument(
            **doc["payload"], revision=doc["revision"], captured_at=doc["captured_at"]
        )
        if doc
        else None,
        turns=[
            WorkTurn.model_validate(
                {k: v for k, v in t.items() if k not in {"session_id", "selection"}}
            )
            for t in turns
        ],
    )


def list_sessions(conn: Connection, course_id: UUID) -> list[WorkSummary]:
    return [
        WorkSummary.model_validate(r)
        for r in conn.execute(get("work", "list"), {"course_id": course_id}).fetchall()
    ]


def create(conn: Connection, course_id: UUID, request: WorkCreate) -> WorkSession:
    session_id = uuid4()
    conn.execute(
        get("work", "create"),
        {"session_id": session_id, "course_id": course_id, **request.model_dump()},
    )
    return session(conn, course_id, session_id)


def update_document(
    conn: Connection,
    course_id: UUID,
    session_id: UUID,
    request: DocumentUpdate,
    *,
    skip_unchanged: bool = False,
) -> WorkSession:
    if skip_unchanged:
        conn.execute(
            get("work", "lock_document"),
            {"course_id": course_id, "session_id": session_id},
        )
    current = session(conn, course_id, session_id)
    if skip_unchanged and current.revision != request.expected_revision:
        raise WorkConflictError(
            "This work session changed elsewhere. Reload before refreshing."
        )
    if not request.text.strip():
        raise ValueError("The document contains no readable text.")
    if (
        skip_unchanged
        and current.document
        and current.document.model_dump(exclude={"revision", "captured_at"})
        == request.model_dump(exclude={"expected_revision"})
    ):
        return current
    changed = conn.execute(
        get("work", "advance"),
        {
            "course_id": course_id,
            "session_id": session_id,
            "expected_revision": request.expected_revision,
        },
    )
    if changed.rowcount != 1:
        raise WorkConflictError(
            "This work session changed elsewhere. Reload before connecting "
            "the document."
        )
    conn.execute(
        get("work", "insert_document"),
        {
            "session_id": session_id,
            "revision": request.expected_revision + 1,
            "payload": request.model_dump_json(exclude={"expected_revision"}),
        },
    )
    return session(conn, course_id, session_id)


def existing_reply(
    conn: Connection, session_id: UUID, request: WorkAsk
) -> WorkReply | None:
    row = conn.execute(
        get("work", "request"), {"request_id": request.request_id}
    ).fetchone()
    if not row:
        return None
    expected = (
        session_id,
        request.action,
        request.instruction,
        request.selection,
        request.expected_revision,
    )
    actual = (
        row["session_id"],
        row["action"],
        row["instruction"],
        row["selection"],
        row["document_revision"],
    )
    if expected != actual:
        raise WorkConflictError(
            "This request ID already belongs to a different question."
        )
    return WorkReply.model_validate(row["reply"])


def save_reply(
    conn: Connection,
    course_id: UUID,
    session_id: UUID,
    request: WorkAsk,
    reply: WorkReply,
) -> WorkReply:
    # Acquire SQLite's writer before the revision check; generation happens outside it.
    conn.execute(get("work", "touch"), {"session_id": session_id})
    current = session(conn, course_id, session_id)
    previous = existing_reply(conn, session_id, request)
    if previous:
        return previous
    if current.revision != request.expected_revision:
        raise WorkConflictError(
            "The document changed while Stacks was answering. Ask again using "
            "the current snapshot."
        )
    conn.execute(
        get("work", "insert_turn"),
        {
            "session_id": session_id,
            **request.model_dump(exclude={"expected_revision"}),
            "document_revision": request.expected_revision,
            "reply": reply.model_dump_json(),
        },
    )
    return reply
