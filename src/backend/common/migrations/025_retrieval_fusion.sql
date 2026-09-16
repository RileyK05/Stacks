-- 025_retrieval_fusion.sql
-- Decision 008 (hybrid retrieval): schema support for the fusion funnel.
--   * chunk_embeddings: the pgvector-ready embedding column. Stored as a
--     float8[] for now (vector type requires the pgvector extension, which
--     the dev environment may not have); the swap to pgvector's `vector`
--     type is a later migration that copies column data. A chunk with no
--     embedding is expressed by the absence of a row in this table.
--   * chunk_fts: a tsvector + GIN index for keyword retrieval. Generated
--     column keeps it in lockstep with chunk text.
--   * concept_synonyms normalization stays in the concepts table (already
--     JSONB).

CREATE TABLE chunk_embeddings (
    chunk_id     UUID PRIMARY KEY REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    model        TEXT NOT NULL,
    embedding    float8[] NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE chunks
    ADD COLUMN search_vector tsvector
    GENERATED ALWAYS AS (to_tsvector('english', text)) STORED;

CREATE INDEX idx_chunks_search ON chunks USING GIN (search_vector);
