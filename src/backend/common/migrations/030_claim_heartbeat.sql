-- 030_claim_heartbeat.sql
-- Review catch #5 (ratified): dead progress is the worst failure mode —
-- a source that reliably kills its worker used to be re-claimed every
-- STALE_CLAIM_AFTER forever, and a long-but-legitimate run looked
-- identical to a dead one (two pipelines racing delete-then-insert on
-- the same source).
--
-- The fix has three parts:
--   * heartbeat: the run's stage ledger IS the liveness signal. Every
--     stage transition updates heartbeat_at; the stale-claim sweep only
--     reclaims rows whose heartbeat (not claim time) is old. A slow
--     stage longer than the heartbeat budget is impossible at current
--     stage costs (pypdf/chunking are seconds; model stages have HTTP
--     timeouts), so heartbeat staleness means the worker is dead.
--   * claimed_runs cap: enforced since 029 — the claim query refuses
--     over-cap rows, dead-lettering cursed sources by omission.
--   * liveness fence: a re-claimed source's claimed_runs_max is visible
--     in source stats; the deliberate requeue path (API) is the way
--     back after human inspection.

ALTER TABLE pending_ingestion
    ADD COLUMN heartbeat_at TIMESTAMPTZ;