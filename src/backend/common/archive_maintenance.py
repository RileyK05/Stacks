from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import timedelta

from src.backend.common import courses_lifecycle
from src.backend.common.lifecycle_config import load_lifecycle_policy

logger = logging.getLogger(__name__)


def run_once(
    *, should_stop: Callable[[], bool] | None = None
) -> tuple[int, int, int]:
    """One maintenance pass. `should_stop` is checked between phases so
    shutdown is not held open by a long sweep: this runs via
    asyncio.to_thread and a thread cannot be cancelled, so without the
    check, cancelling the task at lifespan shutdown returns immediately
    while the pass keeps running."""

    def stopping() -> bool:
        return should_stop is not None and should_stop()

    reclaimed = courses_lifecycle.reclaim_expired_cleanup_leases()
    if stopping():
        return reclaimed, 0, 0
    purged = len(courses_lifecycle.purge_expired_archives())
    if stopping():
        return reclaimed, purged, 0
    cleaned = courses_lifecycle.process_cleanup_jobs()
    if stopping():
        return reclaimed, purged, cleaned
    courses_lifecycle.sweep_storage_orphans(
        min_age=timedelta(seconds=load_lifecycle_policy().orphan_min_age_seconds)
    )
    return reclaimed, purged, cleaned


async def run_forever(stop: asyncio.Event) -> None:
    interval = load_lifecycle_policy().maintenance_interval_seconds
    while not stop.is_set():
        try:
            await asyncio.to_thread(run_once, should_stop=stop.is_set)
        except Exception:
            logger.exception("archive maintenance pass failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            continue
