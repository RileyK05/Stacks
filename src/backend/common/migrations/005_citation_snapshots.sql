-- Imported notebook history keeps a small, source-scoped copy of cited
-- passages. Ingestion is free to rebuild its own chunk IDs without breaking
-- old chat and artifact citations from a .course archive.
CREATE TABLE citation_snapshots (
    chunk_id     UUID PRIMARY KEY,
    course_id    UUID NOT NULL REFERENCES courses (course_id) ON DELETE CASCADE,
    source_id    UUID NOT NULL REFERENCES sources (source_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    text        TEXT NOT NULL,
    locator_type TEXT NOT NULL,
    label       TEXT NOT NULL,
    description TEXT
);
CREATE INDEX idx_citation_snapshots_course ON citation_snapshots (course_id);
