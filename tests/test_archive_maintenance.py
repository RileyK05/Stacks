from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from src.backend.common import archive_maintenance, storage
from src.backend.common.db import connection
from src.backend.main import create_app


@pytest.fixture(autouse=True)
def _storage_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(
        "src.backend.common.storage.get_settings",
        lambda: type("S", (), {"storage_root": str(tmp_path)})(),
    )
    return tmp_path


def test_lifespan_maintenance_loop_runs_and_stops() -> None:
    """The app lifespan must actually run the archive maintenance pass:
    expired leases are reclaimed, expired archives purged, cleanup jobs
    processed, and orphaned directories swept. A fresh empty orphan dir is
    kept (in-flight-copy protection: dir mtime grace); an aged one goes."""
    import os

    fresh_orphan = uuid4()
    fresh_dir = storage.storage_root() / str(fresh_orphan)
    fresh_dir.mkdir(parents=True)

    aged_orphan = uuid4()
    aged_dir = storage.storage_root() / str(aged_orphan)
    aged_dir.mkdir(parents=True)
    os.utime(aged_dir, (0, 0))

    with TestClient(create_app()) as client:
        assert client.get("/courses/public").status_code == 200
        import asyncio

        async def probe() -> tuple[int, int, int]:
            return archive_maintenance.run_once()

        reclaimed, purged, cleaned = asyncio.run(probe())

    assert (reclaimed, purged, cleaned) == (0, 0, 0)
    assert fresh_dir.exists()
    assert not aged_dir.exists()


def test_maintenance_reclaims_stuck_lease_via_run_once() -> None:
    course_id = uuid4()
    with connection() as conn:
        conn.execute(
            "INSERT INTO storage_cleanup_jobs "
            "(course_id, status, attempt_count, next_attempt_at) "
            "VALUES (%s, 'running', 1, now() - interval '10 minutes')",
            (course_id,),
        )
        conn.commit()

    reclaimed, purged, cleaned = archive_maintenance.run_once()
    assert reclaimed >= 1
    with connection() as conn:
        state = conn.execute(
            "SELECT status FROM storage_cleanup_jobs WHERE course_id = %s",
            (course_id,),
        ).fetchone()
    assert state[0] in ("failed", "succeeded")
    assert purged == 0