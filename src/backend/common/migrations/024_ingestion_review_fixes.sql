-- 024_ingestion_review_fixes.sql
-- Review fixes for the M1 ingestion batch:
--   * sources.extracted_text dropped: extracted text was stored as a
--     Postgres row value approaching the 1 GB raw-upload ceiling,
--     duplicating what chunks already store and bypassing the on-disk
--     storage design. Text now lives in the chunks table only.
--   * pending_ingestion.claimed_at: the SKIP LOCKED claim held its lock
--     only until the first mid-run commit, so a second worker could
--     double-claim a mid-ingestion source. A claim is now a persistent
--     state transition (claimed_at set) that claims skip, instead of a
--     lock that evaporates.
--   * failed sources: mark_source_failed no longer filters on
--     status='uploaded', so a failed source can transition back via
--     requeue (failed -> uploaded) and be re-claimed. Failure clears the
--     queue row; requeue re-adds it.

ALTER TABLE sources DROP COLUMN IF EXISTS extracted_text;

ALTER TABLE pending_ingestion
    ADD COLUMN claimed_at TIMESTAMPTZ,
    ADD COLUMN claimed_runs INTEGER NOT NULL DEFAULT 0;

ALTER TABLE pending_ingestion
    ADD CONSTRAINT pending_ingestion_claim_accounted
        CHECK (claimed_runs >= 0);