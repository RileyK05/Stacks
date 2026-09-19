-- 031_chunk_locator_dedupe.sql
-- Review catch #10 (ratified, must land before embeddings populate):
-- chunks are stored once per overlapping locator — same text, same
-- chunk_index, different chunk_id. Consequences: duplicate retrieval
-- hits cited as different pages, slot consumption and relevance
-- allocation proportional to how finely a source's locators were cut,
-- and (once embeddings land) the same text embedded 3x.
--
-- New shape: chunks.locator_id stays (the PRIMARY locator) and
-- chunk_locators holds the full mapping (many-to-many, ready for a
-- chunk spanning several locators).
--
-- Backfill: dedupe on (source_id, chunk_index), keeping the min
-- locator_id row (deterministic; the pipeline's insert loop was
-- locator-ordered). Every duplicate row's locator is re-pointed at the
-- kept row in chunk_locators, then the duplicates are deleted.

CREATE TABLE chunk_locators (
    chunk_id   UUID NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    locator_id UUID NOT NULL REFERENCES locators(locator_id) ON DELETE CASCADE,
    PRIMARY KEY (chunk_id, locator_id)
);

-- 1. Map every existing row (kept and duplicate alike) into the join
--    table keyed by its (source_id, chunk_index) group. The kept row is
--    the group's min locator_id (UUIDs are not orderable by MIN(), so
--    the group's keeper is found with an ordered subquery — same
--    determinism the insert loop had).
INSERT INTO chunk_locators (chunk_id, locator_id)
SELECT kept.chunk_id, dup.locator_id
FROM chunks AS kept
JOIN chunks AS dup
  ON dup.source_id = kept.source_id
 AND dup.chunk_index = kept.chunk_index
WHERE kept.locator_id = (
    SELECT c2.locator_id FROM chunks c2
    WHERE c2.source_id = kept.source_id
      AND c2.chunk_index = kept.chunk_index
    ORDER BY c2.locator_id ASC
    LIMIT 1
)
ON CONFLICT DO NOTHING;

-- 2. Delete the duplicate rows (keep the min-locator_id row per group).
DELETE FROM chunks
WHERE chunk_id IN (
    SELECT chunk_id
    FROM (
        SELECT chunk_id,
               ROW_NUMBER() OVER (
                   PARTITION BY source_id, chunk_index
                   ORDER BY locator_id ASC
               ) AS position
        FROM chunks
    ) ranked
    WHERE position > 1
);

-- 3. Backstop uniqueness: one row per (source, locator, chunk_index).
--    The 029 constraint already covered (source_id, locator_id,
--    chunk_index); the join table's PK covers the mapping side.
ALTER TABLE chunks
    ADD CONSTRAINT uq_chunks_source_index
    UNIQUE (source_id, chunk_index);