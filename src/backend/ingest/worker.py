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
import threading
import time
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
    while should_stop is None or not should_stop():
        with connection() as conn:
            _release_stale_claims(conn)
            _fail_exhausted_claims(conn)
            claimed = runs.claim_pending_sources(conn, limit=min(limit, 1))
            conn.commit()
        if not claimed:
            break
        for row in claimed:
            if should_stop is not None and should_stop():
                break
            attempted += 1
            source_id = row["source_id"]
            if _ingest_claimed(source_id):
                succeeded += 1
    return attempted, succeeded


def _recover_at_startup() -> None:
    with connection() as conn:
        recover_interrupted_runs(conn)
        conn.commit()


def _ingest_claimed(source_id: UUID) -> bool:
    """Run one claimed source. Returns True on success. On pipeline
    failure the ledger already records everything. On unexpected errors
    the claim is cleaned up so the row is not stranded."""
    heartbeat_stop = threading.Event()

    def heartbeat() -> None:
        while not heartbeat_stop.wait(STALE_CLAIM_AFTER.total_seconds() / 3):
            try:
                with connection() as conn:
                    conn.execute(
                        get(_FILE, "heartbeat_claim"), {"source_id": source_id}
                    )
                    conn.commit()
            except Exception:
                logger.exception("could not heartbeat ingestion %s", source_id)

    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()
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
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join()


def recover_interrupted_runs(conn: Connection) -> int:
    """App-startup recovery: release every claim and close every run the
    previous process left open. This process is the only worker, so a claim
    that exists at startup is by definition dead — leaving it to the
    heartbeat fence would strand a file the user saw "processing" when they
    closed the app for STALE_CLAIM_AFTER, with nothing running. Returns
    the number of claims released. Caller commits."""
    conn.execute(get(_FILE, "fail_interrupted_stage_runs"))
    conn.execute(get(_FILE, "fail_interrupted_runs"))
    released = conn.execute(get(_FILE, "release_all_claims")).rowcount
    if released > 0:
        logger.warning(
            "re-queued %s ingestion(s) interrupted by the last exit", released
        )
    return released


def _fail_exhausted_claims(conn: Connection) -> None:
    """A source claimed and lost `claimed_runs_max` times (the process died
    each time — a file that crashes the parser) is never claimable again.
    Mark it failed so the file browser offers Retry instead of a spinner
    that never ends. Caller commits."""
    for row in conn.execute(get(_FILE, "exhausted_claims")).fetchall():
        message = (
            "indexing was interrupted repeatedly (the app closed or crashed "
            "while reading this file); use Retry to try again"
        )
        runs.mark_source_failed(conn, row["source_id"], message)
        runs.record_history(
            conn, row["source_id"], row["course_id"], "failed", row["queued_at"]
        )
        runs.clear_pending_source(conn, row["source_id"])


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
            queued_at = runs.queued_at_for(conn, source_id)
            runs.mark_source_failed(
                conn, source_id, "worker error: unhandled exception"
            )
            row = conn.execute(
                get(_FILE, "source_row"), {"source_id": source_id}
            ).fetchone()
            run = runs.latest_run_for_source(conn, source_id)
            if run is not None and run.status.value in {"pending", "running"}:
                runs.mark_run_failed_direct(
                    conn, run.run_id, "worker error: unhandled exception"
                )
            if row is not None and queued_at is not None:
                runs.record_history(
                    conn, source_id, row["course_id"], "failed", queued_at
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
    event, loop = WAKEUP, _LOOP
    if event is None or loop is None or loop.is_closed():
        return
    try:
        loop.call_soon_threadsafe(event.set)
    except RuntimeError:
        if not loop.is_closed():
            raise


async def run_forever(stop: asyncio.Event) -> None:
    global WAKEUP, _LOOP
    interval = load_ingestion_config().poll_interval_seconds
    WAKEUP = asyncio.Event()
    _LOOP = asyncio.get_running_loop()
    try:
        await asyncio.to_thread(_recover_at_startup)
    except Exception:
        logger.exception("could not recover interrupted ingestion")
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
            time.sleep(load_ingestion_config().poll_interval_seconds)
    except KeyboardInterrupt:
        logger.info("ingestion worker stopped")


if __name__ == "__main__":
    main()
