from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from src.backend.common import courses_lifecycle
from src.backend.common.lifecycle_config import load_lifecycle_policy

logger = logging.getLogger(__name__)


def run_once() -> tuple[int, int, int]:
    reclaimed = courses_lifecycle.reclaim_expired_cleanup_leases()
    purged = len(courses_lifecycle.purge_expired_archives())
    cleaned = courses_lifecycle.process_cleanup_jobs()
    courses_lifecycle.sweep_storage_orphans(
        min_age=timedelta(seconds=load_lifecycle_policy().orphan_min_age_seconds)
    )
    return reclaimed, purged, cleaned


async def run_forever(stop: asyncio.Event) -> None:
    interval = load_lifecycle_policy().maintenance_interval_seconds
    while not stop.is_set():
        try:
            await asyncio.to_thread(run_once)
        except Exception:
            logger.exception("archive maintenance pass failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            continue
