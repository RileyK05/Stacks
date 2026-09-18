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

from psycopg import Connection
from psycopg.rows import dict_row
from src.backend.common import users_repo
from src.backend.common.db import connection
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
    return attempted, succeeded


def _ingest_claimed(source_id: UUID, course_id: UUID) -> bool:
    """Run one claimed source. Returns True on success. On pipeline
    failure the ledger already records everything. On unexpected errors
    the claim is cleaned up so the row is not stranded."""
    try:
        with connection() as conn:
            owner = _course_owner(conn, course_id)
            if owner is None:
                raise ValueError(
                    f"course {course_id} no longer exists; dropping claim"
                )
            account = users_repo.get_by_id(owner)
            if account is None:
                raise ValueError(
                    f"owner {owner} no longer exists; dropping claim"
                )
            tier = account.tier
        with connection() as conn:
            run_ingestion(conn, source_id, owner, tier)
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


def _course_owner(conn: Connection, course_id: UUID) -> UUID | None:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "course_owner"), {"course_id": course_id}
        ).fetchone()
    return row["owner_user_id"] if row else None


def _release_stale_claims(conn: Connection) -> None:
    """Re-claim rows whose claim is older than the stale threshold (the
    previous worker crashed mid-run). The claimed_runs counter increments
    on the next claim, keeping the event inspectable."""
    threshold = datetime.now(UTC) - STALE_CLAIM_AFTER
    with conn.cursor() as cur:
        cur.execute(
            get(_FILE, "release_stale_claims"), {"threshold": threshold}
        )
        if cur.rowcount > 0:
            logger.warning(
                "released %s stale ingestion claim(s) older than %s",
                cur.rowcount,
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


def wakeup() -> None:
    """Called by the upload path after enqueueing so the worker polls
    immediately instead of waiting out the interval (review catch #7:
    upload-to-ingestion latency was up to an hour on a knob named for
    something else). Safe to call from sync context via loop.call_soon_
    threadsafe by async callers; a no-op when no loop is running
    (tests, worker entrypoint)."""
    if WAKEUP is not None:
        WAKEUP.set()


async def run_forever(stop: asyncio.Event) -> None:
    global WAKEUP
    interval = load_ingestion_config().poll_interval_seconds
    WAKEUP = asyncio.Event()
    while not stop.is_set():
        try:
            await asyncio.to_thread(process_batch, should_stop=stop.is_set)
        except Exception:
            logger.exception("ingestion worker pass failed")
        WAKEUP.clear()
        try:
            await asyncio.wait_for(
                asyncio.gather(stop.wait(), WAKEUP.wait(),
                               return_exceptions=True),
                timeout=interval,
            )
        except TimeoutError:
            continue

def main() -> None:
    """Standalone worker process entrypoint (review catch #8): run with
    `.venv/Scripts/python -m src.backend.ingest.worker` to drain the
    queue outside the API process — extraction CPU and deploy restarts
    then never touch API replicas. Polls until Ctrl+C."""
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
