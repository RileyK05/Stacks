-- 029_ingestion_claim_safety.sql
-- Review catches #5/#13 backstops:
--   * UNIQUE on (source_id, locator_id, chunk_index): the backstop
--     against double-claim racing two pipelines doing delete-then-insert
--     on the same source. Insert order varies with retry timing, so a
--     unique violation here is the loud failure, not silent duplicates.
--   * claimed_runs cap: a re-claim is recovery, not a retry loop. A
--     source that reliably kills its worker would be re-claimed every
--     STALE_CLAIM_AFTER forever; the cap dead-letters it into
--     sources.status='failed' with an inspectable reason, and the
--     deliberate requeue path is the only way back.

ALTER TABLE chunks
    ADD CONSTRAINT uq_chunks_source_locator_index
    UNIQUE (source_id, locator_id, chunk_index);

ALTER TABLE pending_ingestion
    ADD COLUMN claimed_runs_max INT NOT NULL DEFAULT 5;