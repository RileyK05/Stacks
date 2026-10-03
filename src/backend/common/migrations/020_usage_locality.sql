ALTER TABLE usage_ledger ADD COLUMN is_local INTEGER NOT NULL DEFAULT 0 CHECK (is_local IN (0, 1));
UPDATE usage_ledger SET is_local = 1 WHERE provider = 'local';
CREATE INDEX IF NOT EXISTS idx_ingestion_runs_source_created ON ingestion_runs (source_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pending_ingestion_claim_created ON pending_ingestion (claimed_at, created_at);
