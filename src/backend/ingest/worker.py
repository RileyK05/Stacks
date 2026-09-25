"""The ingestion worker: drains pending_ingestion on a loop.

Claims queue rows by persistent state transition (claimed_at — decision
008 review's fix; row locks evaporate at the pipeline's first commit, so
claims must survive it). Each claimed source runs the full pipeline via
`run_ingestion`; on either terminal outcome the queue row is cleared and
history recorded with the ORIGINAL queued_at (the call-order contract:
history must be written before the queue row is deleted).

Stale-claim recovery: rows claimed by a crashed worker become
re-claimable after STALE_CLAIM_AFTER; the claimed_runs counter is the
inspectable signal of how often that has happened (released claims are
logged, so the event is visible without querying).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from src.backend.common.db import Connection, connection
from src.backend.common.queries import get
from src.backend.ingest import runs
from src.backend.ingest.config import load_ingestion_config
from src.backend.ingest.orchestrator import run_ingestion
from src.backend.ingest.pipeline import IngestionPipelineError

logger = logging.getLogger(__name__)

_FILE = "ingestion"

BATCH_SIZE = 5
STALE_CLAIM_AFTER = timedelta(minutes=30)


def process_batch(
    limit: int = BATCH_SIZE,
    *,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[int, int]:
    """One worker pass: claim up to `limit` queued sources per round and
    ingest each. Returns (attempted, succeeded). Failures are already
    recorded by run_ingestion (run ledger + source status + queue
    cleared); this loop counts them and cleans up on unexpected errors.

    `should_stop` is checked between rounds so shutdown does not wait for
    the whole queue to drain. This runs via asyncio.to_thread, and a
    thread cannot be cancelled — without the check, cancelling the task at
    lifespan shutdown returns immediately while the thread keeps draining,
    holding the process open for an unbounded time on a large backlog."""
    attempted = 0
    succeeded = 0
    touched_courses: set[UUID] = set()
    while should_stop is None or not should_stop():
        with connection() as conn:
            _release_stale_claims(conn)
            claimed = runs.claim_pending_sources(conn, limit=limit)
            conn.commit()
        if not claimed:
            break
        for row in claimed:
            if should_stop is not None and should_stop():
                break
            attempted += 1
            source_id = row["source_id"]
            course_id = row["course_id"]
            if _ingest_claimed(source_id, course_id):
                succeeded += 1
                touched_courses.add(course_id)
    # Course-memory refresh is per-BATCH, not per-upload (ratified fix #9):
    # five uploads to one course used to rebuild the same summary five
    # times inside five upload transactions, each holding the owner's
    # quota lock across several queries + summary assembly. One refresh
    # at the end of a successful batch sees all five.
    for course_id in touched_courses:
        _refresh_course_memory(course_id)
    return attempted, succeeded


def _refresh_course_memory(course_id: UUID) -> None:
    """The batch-end memory refresh. Own transaction (the pipeline's
    transactions are closed by now); failures are logged, not fatal — a
    missed refresh is caught by the next terminal path that touches the
    course."""
    from src.backend.common import course_memory

    try:
        with connection() as conn:
            course_memory.refresh(conn, course_id)
            conn.commit()
    except Exception:
        logger.exception(
            "course-memory refresh failed for course %s", course_id
        )


def _ingest_claimed(source_id: UUID, course_id: UUID) -> bool:
    """Run one claimed source. Returns True on success. On pipeline
    failure the ledger already records everything. On unexpected errors
    the claim is cleaned up so the row is not stranded."""
    try:
        with connection() as conn:
            run_ingestion(conn, source_id)
            return True
    except IngestionPipelineError:
        logger.warning(
            "ingestion failed for source %s (recorded in run ledger)",
            source_id,
        )
        return False
    except Exception:
        logger.exception("ingestion worker error for source %s", source_id)
        _cleanup_orphaned_claim(source_id)
        return False


def _release_stale_claims(conn: Connection) -> None:
    """Re-claim rows whose claim is older than the stale threshold (the
    previous worker crashed mid-run). The claimed_runs counter increments
    on the next claim, keeping the event inspectable."""
    threshold = datetime.now(UTC) - STALE_CLAIM_AFTER
    cursor = conn.execute(get(_FILE, "release_stale_claims"), {"threshold": threshold})
    if cursor.rowcount > 0:
        logger.warning(
            "released %s stale ingestion claim(s) older than %s",
            cursor.rowcount,
            STALE_CLAIM_AFTER,
        )


def _cleanup_orphaned_claim(source_id: UUID) -> None:
    """Unexpected failure (not IngestionPipelineError): run_ingestion may
    not have reached its failure audit. Mark the source failed with the
    generic reason and clear the queue row so the row is not stranded."""
    try:
        with connection() as conn:
            runs.mark_source_failed(
                conn, source_id, "worker error: unhandled exception"
            )
            runs.clear_pending_source(conn, source_id)
            conn.commit()
    except Exception:
        logger.exception("could not clean up claim for source %s", source_id)


WAKEUP: asyncio.Event | None = None
_LOOP: asyncio.AbstractEventLoop | None = None


def wakeup() -> None:
    """Called by the upload path after enqueueing so the worker polls
    immediately instead of waiting out the interval (review catch #7).
    Upload handlers run on FastAPI's threadpool, and asyncio.Event is not
    thread-safe, so the set is scheduled onto the worker's loop. A no-op
    when no worker loop is running (tests, the standalone entrypoint)."""
    if WAKEUP is None or _LOOP is None or _LOOP.is_closed():
        return
    _LOOP.call_soon_threadsafe(WAKEUP.set)


async def run_forever(stop: asyncio.Event) -> None:
    global WAKEUP, _LOOP
    interval = load_ingestion_config().poll_interval_seconds
    WAKEUP = asyncio.Event()
    _LOOP = asyncio.get_running_loop()
    while not stop.is_set():
        # Clear BEFORE the pass: an upload that lands mid-pass sets the
        # event again, so the next sleep ends immediately instead of
        # losing the wakeup.
        WAKEUP.clear()
        try:
            await asyncio.to_thread(process_batch, should_stop=stop.is_set)
        except Exception:
            logger.exception("ingestion worker pass failed")
        # Sleep until the poll interval passes, an upload wakes us, or
        # shutdown begins, whichever comes first.
        waiters = {
            asyncio.ensure_future(stop.wait()),
            asyncio.ensure_future(WAKEUP.wait()),
        }
        _done, pending = await asyncio.wait(
            waiters, timeout=interval, return_when=asyncio.FIRST_COMPLETED
        )
        for waiter in pending:
            waiter.cancel()


def main() -> None:
    """Standalone worker process entrypoint (review catch #8): run with
    `.venv/Scripts/python -m src.backend.ingest.worker` to drain the
    queue outside the API process. Polls until Ctrl+C."""
    logging.basicConfig(level=logging.INFO)
    logger.info("ingestion worker starting (standalone)")
    try:
        while True:
            try:
                attempted, succeeded = process_batch()
                if attempted:
                    logger.info(
                        "worker pass: %s attempted, %s succeeded",
                        attempted,
                        succeeded,
                    )
            except Exception:
                logger.exception("ingestion worker pass failed")
    except KeyboardInterrupt:
        logger.info("ingestion worker stopped")


if __name__ == "__main__":
    main()
