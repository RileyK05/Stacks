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
        conn.execute("DELETE FROM users WHERE email LIKE '%@test.invalid'")
        conn.commit()
