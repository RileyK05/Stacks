"""The maintenance loop: purge trashed courses past their retention and
sweep orphaned stored files. Runs inside the app process on an interval."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import timedelta

from src.backend.common import courses_repo
from src.backend.common.lifecycle_config import load_lifecycle_policy

logger = logging.getLogger(__name__)


def run_once(*, should_stop: Callable[[], bool] | None = None) -> tuple[int, int]:
    """One maintenance pass: (courses purged, orphan directories swept).
    `should_stop` is checked between phases so shutdown is not held open
    by a long sweep (this runs via asyncio.to_thread; a thread cannot be
    cancelled)."""
    purged = len(courses_repo.purge_due())
    if should_stop is not None and should_stop():
        return purged, 0
    swept = courses_repo.sweep_storage_orphans(
        min_age=timedelta(seconds=load_lifecycle_policy().orphan_min_age_seconds)
    )
    return purged, len(swept)


async def run_forever(stop: asyncio.Event) -> None:
    interval = load_lifecycle_policy().maintenance_interval_seconds
    while not stop.is_set():
        try:
            await asyncio.to_thread(run_once, should_stop=stop.is_set)
        except Exception:
            logger.exception("maintenance pass failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            continue
