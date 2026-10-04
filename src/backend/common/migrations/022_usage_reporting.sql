-- Historical rows cannot establish whether zero meant reported zero or missing
-- usage. Keep their status unknown; only new calls supply explicit provenance.
ALTER TABLE usage_ledger ADD COLUMN usage_reported INTEGER
    CHECK (usage_reported IS NULL OR usage_reported IN (0, 1));
