from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from src.backend.common import courses_lifecycle
from src.backend.common.config import get_settings
from src.backend.common.db import connection
from src.backend.main import create_app


def _require_test_database() -> None:
    """Tests delete rows wholesale (all @test.invalid users, their courses,
    and derived rows). Refuse to run against a database whose name does not
    look like a test target, unless PYTEST_ALLOW_ANY_DB is set — so a stray
    .env pointed at a real environment fails fast instead of shredding it.
    Local dev DBs named without 'test' (e.g. course_assistant) opt in via
    the environment variable; that is a deliberate operator action."""
    dsn = get_settings().dsn
    lowered = dsn.lower()
    if "test" not in lowered and not os.environ.get("PYTEST_ALLOW_ANY_DB"):
        raise RuntimeError(
            "refusing to run tests against a database whose name does not "
            "contain 'test'. Set PYTEST_ALLOW_ANY_DB=1 to run against this "
            f"database deliberately ({lowered.split('dbname=')[-1].split()[0]!r})."
        )


_require_test_database()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def verify_email(client: TestClient, token: str) -> None:
    """Mark the account behind a login token as email-verified, the way the
    real flow would (outbox token -> verify endpoint). Used by every API
    test that needs to pass the resource-creation gate."""
    from src.backend.common import email_repo, users_repo
    from src.backend.common.auth import token_user_id

    user_id = token_user_id(token)
    account = users_repo.get_by_id(user_id)
    assert account is not None and account.email is not None
    with connection() as conn:
        plaintext = email_repo.issue_token(
            conn,
            user_id=user_id,
            kind=email_repo.VERIFICATION_KIND,
            to_email=account.email,
            subject="test verification",
            body_template="{token}",
        )
        conn.commit()
    response = client.post(
        f"/auth/verify-email/{plaintext}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text


@pytest.fixture(autouse=True)
def _clean_test_users() -> Iterator[None]:
    yield
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        course_rows = cur.execute(
            """
            SELECT course_id FROM courses
            WHERE owner_user_id IN (
                SELECT user_id FROM users WHERE email LIKE '%@test.invalid'
            )
            """
        ).fetchall()
        for row in course_rows:
            courses_lifecycle._delete_subtree(cur, row["course_id"])
        conn.execute(
            """
            DELETE FROM generation_ledger
            WHERE user_id IN (
                SELECT user_id FROM users WHERE email LIKE '%@test.invalid'
            )
            """
        )
        conn.execute(
            """
            DELETE FROM course_memories
            WHERE user_id IN (
                SELECT user_id FROM users WHERE email LIKE '%@test.invalid'
            )
            """
        )
        conn.execute(
            """
            DELETE FROM citation_snapshots
            WHERE user_id IN (
                SELECT user_id FROM users WHERE email LIKE '%@test.invalid'
            )
            """
        )
        # Cleanup jobs have no user FK; delete test-owned courses' jobs plus
        # jobs whose course row no longer exists (left over from earlier test
        # purges). A real environment's pending purge jobs must never be
        # destroyed by a test run that happens to share the database.
        conn.execute(
            """
            DELETE FROM storage_cleanup_jobs
            WHERE course_id IN (
                SELECT course_id FROM courses
                WHERE owner_user_id IN (
                    SELECT user_id FROM users
                    WHERE email LIKE '%@test.invalid'
                )
            )
               OR NOT EXISTS (
                   SELECT 1 FROM courses
                   WHERE courses.course_id = storage_cleanup_jobs.course_id
               )
            """
        )
        conn.execute("DELETE FROM users WHERE email LIKE '%@test.invalid'")
        conn.commit()
