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
  AND source.status = 'indexed'
ORDER BY rank DESC, chunk.chunk_index
LIMIT :limit;

-- name: toc_candidates
-- TOC seam (static matching): entries of the course's current TOC whose
-- title/description match the query (same stemming as the keyword seam),
-- plus the chunks under those entries' locators. Entries with a NULL
-- locator drop out via the chunks join, which also bounds the seam to
-- entries that actually have text behind them.
WITH current_toc AS (
    SELECT toc_id
    FROM tables_of_contents
    WHERE course_id = :course_id
    ORDER BY version DESC
    LIMIT 1
),
matched_entries AS (
    SELECT entry.entry_id, entry.title, entry.source_id, entry.locator_id,
           entry.position
    FROM toc_entries_fts
    JOIN toc_entries AS entry ON entry.entry_rowid = toc_entries_fts.rowid
    WHERE toc_entries_fts MATCH :match
      AND entry.toc_id IN (SELECT toc_id FROM current_toc)
)
SELECT chunk.chunk_id,
       chunk.source_id,
       chunk.locator_id,
       chunk.chunk_index,
       chunk.text,
       matched_entries.entry_id,
       matched_entries.title
FROM matched_entries
JOIN chunks AS chunk ON chunk.source_id = matched_entries.source_id
     AND chunk.locator_id = matched_entries.locator_id
JOIN sources AS source ON source.source_id = chunk.source_id
WHERE source.course_id = :course_id
  AND source.status = 'indexed'
ORDER BY matched_entries.position, chunk.chunk_index
LIMIT :limit;

-- name: dependency_expansion
-- Graph-walk seam: given matched concept ids, return chunks attached to
-- prerequisite or dependent concepts (1-hop walk). UNION (not an OR
-- join) so each branch uses its index and a chunk reachable both ways
-- burns one LIMIT slot, not two. Deterministic ORDER BY because candidate
-- order feeds reproducible retrieval runs.
-- KNOWN PRECISION GAP: memory_objects link concepts to sources, not
-- locators, so this returns every chunk of the source a concept's
-- evidence lives in; the limit bounds the flood. Dormant without edges.
SELECT chunk.chunk_id,
       chunk.source_id,
       chunk.locator_id,
       chunk.chunk_index,
       chunk.text
FROM concepts AS matched
JOIN dependencies AS dep ON dep.prereq_id = matched.concept_id
JOIN memory_objects AS mo ON mo.concept_id = dep.dependent_id
JOIN chunks AS chunk ON chunk.source_id = mo.source_id
JOIN sources AS src ON src.source_id = chunk.source_id
WHERE matched.concept_id IN (SELECT value FROM json_each(:concept_ids))
  AND matched.course_id = :course_id
  AND src.status = 'indexed'
UNION
SELECT chunk.chunk_id,
       chunk.source_id,
       chunk.locator_id,
       chunk.chunk_index,
       chunk.text
FROM concepts AS matched
JOIN dependencies AS dep ON dep.dependent_id = matched.concept_id
JOIN memory_objects AS mo ON mo.concept_id = dep.prereq_id
JOIN chunks AS chunk ON chunk.source_id = mo.source_id
JOIN sources AS src ON src.source_id = chunk.source_id
WHERE matched.concept_id IN (SELECT value FROM json_each(:concept_ids))
  AND matched.course_id = :course_id
  AND src.status = 'indexed'
ORDER BY chunk_index, chunk_id
LIMIT :limit;

-- name: embedding_rows
-- Embedding seam input: every indexed chunk's vector under the current
-- model for this course. Scoring (dot product) happens in numpy — a
-- course's vectors fit in memory comfortably, and brute force over a few
-- thousand chunks takes milliseconds.
SELECT chunk.chunk_id,
       chunk.source_id,
       chunk.locator_id,
       chunk.chunk_index,
       chunk.text,
       emb.dimension,
       emb.embedding
FROM chunk_embeddings AS emb
JOIN chunks AS chunk ON chunk.chunk_id = emb.chunk_id
JOIN sources AS source ON source.source_id = chunk.source_id
WHERE source.course_id = :course_id
  AND source.status = 'indexed'
  AND emb.model = :model;

-- name: locator_labels
SELECT locator.locator_id,
       locator.locator_type,
       locator.label,
       locator.start AS char_start,
       locator.end_value AS char_end,
       locator.description,
       source.filename
FROM locators AS locator
JOIN sources AS source ON source.source_id = locator.source_id
WHERE locator.locator_id IN (SELECT value FROM json_each(:locator_ids));

-- name: course_concepts
-- The dependency seam's matcher input. Matching itself happens in Python
-- (whole-word, case-insensitive, regex-escaped model-extracted names).
SELECT concept_id, name, synonyms
FROM concepts
WHERE course_id = :course_id
ORDER BY name, concept_id;
