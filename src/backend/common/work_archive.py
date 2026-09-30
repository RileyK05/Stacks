import json
from uuid import UUID, uuid4

from src.backend.common.db import Connection
from src.backend.common.queries import get
from src.backend.common.schemas.work import ArchivedWork, ArchivedWorkTurn, WorkDocument
from src.backend.common.work_repo import list_sessions


def export_work(conn: Connection, course_id: UUID) -> list[ArchivedWork]:
    result = []
    for summary in list_sessions(conn, course_id):
        params = {"session_id": summary.session_id}
        documents = [
            WorkDocument(
                **r["payload"], revision=r["revision"], captured_at=r["captured_at"]
            )
            for r in conn.execute(get("work", "documents"), params).fetchall()
        ]
        turns = [
            ArchivedWorkTurn.model_validate(
                {k: v for k, v in r.items() if k != "session_id"}
            )
            for r in conn.execute(get("work", "turns"), params).fetchall()
        ]
        result.append(
            ArchivedWork(**summary.model_dump(), documents=documents, turns=turns)
        )
    return result


def import_work(
    conn: Connection,
    course_id: UUID,
    items: list[ArchivedWork],
    chunk_map: dict[UUID, UUID],
    source_map: dict[UUID, UUID],
    trace_map: dict[UUID, UUID],
) -> None:
    for item in items:
        revisions = {d.revision for d in item.documents}
        if (
            len(revisions) != len(item.documents)
            or item.revision != max(revisions, default=0)
            or any(
                t.document_revision not in revisions
                or t.reply.document_revision != t.document_revision
                for t in item.turns
            )
        ):
            raise ValueError("Invalid work-session document revisions.")
        session_id = uuid4()
        conn.execute(
            get("work", "import_session"),
            {
                "session_id": session_id,
                "course_id": course_id,
                "title": item.title,
                "purpose": item.purpose,
                "revision": item.revision,
                "updated_at": item.updated_at,
            },
        )
        for doc in item.documents:
            payload = doc.model_dump(exclude={"revision", "captured_at"})
            payload["external_id"] = ""
            conn.execute(
                get("work", "import_document"),
                {
                    "session_id": session_id,
                    "revision": doc.revision,
                    "payload": json.dumps(payload),
                    "captured_at": doc.captured_at,
                },
            )
        for turn in item.turns:
            reply = turn.reply.model_dump()
            mapped_trace = (
                trace_map.get(UUID(turn.reply.trace_id))
                if turn.reply.trace_id
                else None
            )
            reply["trace_id"] = str(mapped_trace) if mapped_trace else None
            for citation in reply["citations"]:
                cid = UUID(citation["chunk_id"])
                sid = UUID(citation["source_id"]) if citation["source_id"] else None
                citation["chunk_id"] = str(chunk_map.setdefault(cid, uuid4()))
                mapped_source = source_map.get(sid) if sid else None
                citation["source_id"] = str(mapped_source) if mapped_source else None
            conn.execute(
                get("work", "import_turn"),
                {
                    "request_id": uuid4(),
                    "session_id": session_id,
                    "action": turn.action,
                    "instruction": turn.instruction,
                    "selection": turn.selection,
                    "document_revision": turn.document_revision,
                    "reply": json.dumps(reply),
                    "created_at": turn.created_at,
                },
            )
