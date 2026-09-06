from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from src.backend.common import courses_lifecycle
from src.backend.common.db import connection
from src.backend.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


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
        conn.execute("DELETE FROM storage_cleanup_jobs")
        conn.execute("DELETE FROM users WHERE email LIKE '%@test.invalid'")
        conn.commit()
