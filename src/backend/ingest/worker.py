"""The ingestion worker: drains pending_ingestion on a loop.

Claims queue rows by persistent state transition (claimed_at — decision
008 review's fix; row locks evaporate at the pipeline's first commit, so
claims must survive it). Each claimed source runs the full pipeline via
`run_ingestion`; on either terminal outcome the queue row is cleared and
history recorded with the ORIGINAL queued_at (the call-order contract:
history must be written before the queue row is deleted).

Stale-claim recovery: rows claimed by a crashed worker become
re-claimable after STALE_CLAIM_AFTER; the claimed_runs counter is the
inspectable signal of how often that has happened.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from src.backend.common import users_repo
from src.backend.common.db import connection
from src.backend.common.lifecycle_config import load_lifecycle_policy
from src.backend.common.queries import get
from src.backend.ingest import runs
from src.backend.ingest.orchestrator import run_ingestion
from src.backend.ingest.pipeline import IngestionPipelineError

logger = logging.getLogger(__name__)

_FILE = "ingestion"

BATCH_SIZE = 5
STALE_CLAIM_AFTER = timedelta(minutes=30)


def process_batch(limit: int = BATCH_SIZE) -> tuple[int, int]:
    """One worker pass: claim up to `limit` queued sources per round and
    ingest each. Returns (attempted, succeeded). Failures are already
    recorded by run_ingestion (run ledger + source status + queue
    cleared); this loop counts them and cleans up on unexpected errors."""
    attempted = 0
    succeeded = 0
    while True:
        with connection() as conn:
            _release_stale_claims(conn)
            claimed = runs.claim_pending_sources(conn, limit=limit)
            conn.commit()
        if not claimed:
            break
        for row in claimed:
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


async def run_forever(stop: asyncio.Event) -> None:
    interval = load_lifecycle_policy().maintenance_interval_seconds
    while not stop.is_set():
        try:
            await asyncio.to_thread(process_batch)
        except Exception:
            logger.exception("ingestion worker pass failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            continue