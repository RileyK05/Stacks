ALTER TABLE passage_containers ADD COLUMN origin TEXT NOT NULL DEFAULT 'source'
    CHECK (origin IN ('source', 'inference'));
