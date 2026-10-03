-- Decision 008: hybrid retrieval. Each named block is one seam; the
-- retrieval module merges their outputs into one cited candidate set.

-- name: keyword_candidates
-- The keyword seam: porter-stemmed FTS5 match ranked by bm25. `:match`
-- is built in Python from sanitized, stopword-filtered tokens joined with
-- OR (any term overlap counts; AND would miss chunks holding only part of
-- the query). bm25() is lower-is-better, so rank is its negation to keep
-- every seam "higher is better". Filtered by course so retrieval never
-- crosses courses.
SELECT chunk.chunk_id,
       chunk.source_id,
       chunk.locator_id,
       chunk.chunk_index,
       chunk.text,
       -bm25(chunks_fts) AS rank
FROM chunks_fts
JOIN chunks AS chunk ON chunk.chunk_rowid = chunks_fts.rowid
JOIN sources AS source ON source.source_id = chunk.source_id
WHERE chunks_fts MATCH :match
  AND source.course_id = :course_id
  AND (source.status = 'indexed' OR EXISTS (SELECT 1 FROM source_indexes WHERE source_id = source.source_id))
  AND EXISTS (SELECT 1 FROM courses WHERE course_id = source.course_id AND deleted_at IS NULL)
  AND (:source_ids IS NULL OR source.source_id IN (SELECT value FROM json_each(:source_ids)))
ORDER BY rank DESC, chunk.chunk_index
LIMIT :limit;

-- name: embedding_rows
SELECT chunk.chunk_id, chunk.source_id, chunk.locator_id, chunk.chunk_index,
       window.dimension, window.embedding,
       window.char_start AS window_start, window.char_end AS window_end
FROM passage_windows AS window
JOIN chunks AS chunk ON chunk.chunk_id = window.chunk_id
JOIN sources AS source ON source.source_id = chunk.source_id
JOIN courses AS course ON course.course_id = source.course_id
WHERE source.course_id = :course_id AND course.deleted_at IS NULL
  AND window.model = :model
  AND (source.status = 'indexed' OR EXISTS (
      SELECT 1 FROM source_indexes WHERE source_id = source.source_id))
  AND (:source_ids IS NULL OR source.source_id IN (SELECT value FROM json_each(:source_ids)))
UNION ALL
SELECT chunk.chunk_id, chunk.source_id, chunk.locator_id, chunk.chunk_index,
       emb.dimension, emb.embedding, 0, length(chunk.text)
FROM chunk_embeddings AS emb
JOIN chunks AS chunk ON chunk.chunk_id = emb.chunk_id
JOIN sources AS source ON source.source_id = chunk.source_id
JOIN courses AS course ON course.course_id = source.course_id
WHERE source.course_id = :course_id AND course.deleted_at IS NULL
  AND emb.model = :model
  AND NOT EXISTS (SELECT 1 FROM passage_windows WHERE chunk_id = chunk.chunk_id)
  AND (source.status = 'indexed' OR EXISTS (SELECT 1 FROM source_indexes WHERE source_id = source.source_id))
  AND (:source_ids IS NULL OR source.source_id IN (SELECT value FROM json_each(:source_ids)));

-- name: similar_candidates
SELECT chunk.chunk_id, chunk.source_id, chunk.locator_id, chunk.chunk_index,
       chunk.text, max(edge.weight) AS rank
FROM graph_edges AS edge
JOIN chunks AS chunk ON chunk.chunk_id = CASE
    WHEN edge.chunk_a IN (SELECT value FROM json_each(:chunk_ids)) THEN edge.chunk_b
    ELSE edge.chunk_a END
JOIN sources AS source ON source.source_id = chunk.source_id
JOIN courses AS course ON course.course_id = source.course_id
WHERE edge.course_id = :course_id AND edge.model = :model
  AND (edge.chunk_a IN (SELECT value FROM json_each(:chunk_ids))
       OR edge.chunk_b IN (SELECT value FROM json_each(:chunk_ids)))
  AND chunk.chunk_id NOT IN (SELECT value FROM json_each(:chunk_ids))
  AND source.course_id = :course_id AND course.deleted_at IS NULL
  AND (source.status = 'indexed' OR EXISTS (SELECT 1 FROM source_indexes WHERE source_id = source.source_id))
  AND (:source_ids IS NULL OR source.source_id IN (SELECT value FROM json_each(:source_ids)))
GROUP BY chunk.chunk_id
ORDER BY rank DESC, chunk.source_id, chunk.chunk_index
LIMIT :limit;

-- name: chunk_locator_labels
SELECT DISTINCT locator.label
FROM chunk_locators AS span
JOIN locators AS locator ON locator.locator_id = span.locator_id
WHERE span.chunk_id IN (SELECT value FROM json_each(:chunk_ids));
