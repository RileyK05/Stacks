from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from src.backend.common.db import connection
from src.backend.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(autouse=True)
def _clean_test_users() -> Iterator[None]:
    yield
    with connection() as conn:
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
            DELETE FROM course_objects
            WHERE course_id IN (
                SELECT course_id FROM courses
                WHERE owner_user_id IN (
                    SELECT user_id FROM users WHERE email LIKE '%@test.invalid'
                )
            )
            """
        )
        # sources rows cascade from course_objects via sources_object_fk
        conn.execute(
            "DELETE FROM courses WHERE owner_user_id IN "
            "(SELECT user_id FROM users WHERE email LIKE '%@test.invalid')"
        )
        conn.execute("DELETE FROM users WHERE email LIKE '%@test.invalid'")
        conn.commit()
