"""One-shot live answer-eval adapter.

Bills a throwaway eval account (decision 010 catch #10), seeds the
harness course + chunks that cases.json resolves against, runs the real
MiMo provider through run_answer_eval, prints the summary, and deletes
the eval account + course. Not a test — run manually:

    .venv/Scripts/python -m scripts.live_answer_eval
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from uuid import UUID

from psycopg.rows import dict_row
from src.backend.common import courses_repo, users_repo
from src.backend.common.db import connection
from src.backend.evals.answer import run_answer_eval


def _seed() -> tuple[UUID, UUID]:
    user = users_repo.create(
        "Answer Eval Live", f"{uuid.uuid4().hex}@test.invalid", "not-a-hash"
    )
    course = courses_repo.create_course(user.user_id, "harness-course")
    source_id = uuid.uuid4()
    locator_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        object_id = cur.execute(
            "INSERT INTO course_objects (course_id, created_by_user_id,"
            " kind, content_type, content, access_scope)"
            " VALUES (%s, %s, 'source', 'text/plain', '{}', 'enrolled')"
            " RETURNING object_id",
            (course.course_id, user.user_id),
        ).fetchone()
        assert object_id is not None
        object_id = object_id["object_id"]
        cur.execute(
            "INSERT INTO sources (source_id, object_id,"
            " uploaded_by_user_id, course_id, filename, mime_type,"
            " source_type, uri, status, file_hash, size_bytes,"
            " stored_encoding)"
            " VALUES (%s, %s, %s, %s, 'notes.txt', 'text/plain', 'notes',"
            " 'disk://x', 'indexed', %s, 10, 'identity')",
            (
                source_id,
                object_id,
                user.user_id,
                course.course_id,
                f"hash-{uuid.uuid4().hex}",
            ),
        )
        cur.execute(
            "INSERT INTO locators (locator_id, source_id, locator_type,"
            " start, end_value, label, description)"
            " VALUES (%s, %s, 'page', '0', '100', 'page 1',"
            " 'live-eval page 1')",
            (locator_id, source_id),
        )
        cur.execute(
            "INSERT INTO chunks (chunk_id, source_id, locator_id,"
            " chunk_index, text) VALUES (%s, %s, %s, 0, %s)",
            (
                chunk_id,
                source_id,
                locator_id,
                "A linear transformation preserves addition and scalar"
                " multiplication.",
            ),
        )
        cur.execute(
            "INSERT INTO chunk_locators (chunk_id, locator_id)"
            " VALUES (%s, %s)",
            (chunk_id, locator_id),
        )
        conn.commit()
    return user.user_id, course.course_id


def _cleanup(user_id: UUID) -> None:
    with connection() as conn:
        conn.execute(
            "DELETE FROM chunk_locators WHERE chunk_id IN"
            " (SELECT chunk_id FROM chunks WHERE source_id IN"
            "  (SELECT source_id FROM sources WHERE course_id IN"
            "   (SELECT course_id FROM courses WHERE owner_user_id = %s)))",
            (user_id,),
        )
        conn.execute(
            "DELETE FROM chunks WHERE source_id IN"
            " (SELECT source_id FROM sources WHERE course_id IN"
            "  (SELECT course_id FROM courses WHERE owner_user_id = %s))",
            (user_id,),
        )
        conn.execute(
            "DELETE FROM locators WHERE source_id IN"
            " (SELECT source_id FROM sources WHERE course_id IN"
            "  (SELECT course_id FROM courses WHERE owner_user_id = %s))",
            (user_id,),
        )
        conn.execute(
            "DELETE FROM sources WHERE course_id IN"
            " (SELECT course_id FROM courses WHERE owner_user_id = %s)",
            (user_id,),
        )
        conn.execute(
            "DELETE FROM course_objects WHERE course_id IN"
            " (SELECT course_id FROM courses WHERE owner_user_id = %s)",
            (user_id,),
        )
        conn.execute(
            "DELETE FROM courses WHERE owner_user_id = %s", (user_id,)
        )
        conn.execute(
            "DELETE FROM generation_ledger WHERE user_id = %s", (user_id,)
        )
        conn.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        conn.commit()


def main() -> int:
    user_id, _course_id = _seed()
    try:
        with connection() as conn:
            summary = run_answer_eval(
                conn,
                generate=_live_generate,
                log_dir=Path("runs") / "live",
            )
    finally:
        _cleanup(user_id)
    print(summary)
    for result in summary.cases:
        print(
            f"  {result.case_id:<22} {result.kind:<20}"
            f" {'PASS' if result.passed else 'FAIL'} — {result.detail}"
        )
    return 0 if summary.all_passed else 1


def _live_generate(task: str, prompt: str) -> str:
    """The real provider, no budget gate: the eval account is throwaway,
    so the seam's gating adds nothing here — but tokens are still billed
    to it for the run's visibility (decision 010 catch #10)."""
    from src.backend.common import provider

    result = provider._call_provider(task, "mimo-v2.6-flash", prompt)
    text = result[0]
    print(
        f"    [tokens] {result[1]} in / {result[2]} out",
        file=sys.stderr,
    )
    return text


if __name__ == "__main__":
    raise SystemExit(main())