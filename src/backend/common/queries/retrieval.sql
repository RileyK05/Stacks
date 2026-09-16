-- Decision 008: hybrid retrieval. Each named block is one seam; the
-- retrieval module merges their outputs into one cited candidate set.

-- name: keyword_candidates
-- The keyword seam: tsvector match with ranking. OR semantics — any term
-- overlap counts (AND semantics would miss chunks holding only part of
-- the query). Filter by course so retrieval never crosses courses.
SELECT chunk.chunk_id,
       chunk.source_id,
       chunk.locator_id,
       chunk.chunk_index,
       chunk.text,
       ts_rank(
           chunk.search_vector,
           to_tsquery('english', %(or_query)s)
       ) AS rank
FROM chunks AS chunk
JOIN sources AS source ON source.source_id = chunk.source_id
WHERE source.course_id = %(course_id)s
  AND chunk.search_vector @@ to_tsquery('english', %(or_query)s)
ORDER BY rank DESC, chunk.chunk_index
LIMIT %(limit)s;

-- name: toc_candidates
-- TOC seam (static matching): entries whose title/description full-text
-- match the query terms, plus the chunks under those entries' locators.
-- Uses tsvector (stemmed, stopword-filtered) for the same consistency the
-- keyword seam has; plain LIKE wildcards from user input never reach SQL.
-- locator_id IS NULL entries are excluded explicitly: they have no chunks
-- to fetch (schema allows NULL).
WITH current_toc AS (
    SELECT toc_id
    FROM tables_of_contents AS toc
    WHERE toc.course_id = %(course_id)s
    ORDER BY version DESC
    LIMIT 1
)
SELECT chunk.chunk_id,
       chunk.source_id,
       chunk.locator_id,
       chunk.chunk_index,
       chunk.text,
       entry.entry_id,
       entry.title
FROM toc_entries AS entry
JOIN current_toc ON current_toc.toc_id = entry.toc_id
JOIN locators AS locator ON locator.locator_id = entry.locator_id
JOIN chunks AS chunk ON chunk.source_id = entry.source_id
     AND chunk.locator_id = entry.locator_id
WHERE to_tsvector('english', entry.title || ' ' || entry.description)
      @@ to_tsquery('english', %(or_query)s)
ORDER BY entry.position, chunk.chunk_index
LIMIT %(limit)s;

-- name: dependency_expansion
-- Graph-walk seam: given matched concept ids, return chunks attached to
-- prerequisite or dependent concepts (1-hop walk). UNION (not OR-join) so
-- each branch can use its index; deterministic ORDER BY because candidate
-- order feeds reproducible retrieval runs.
-- KNOWN PRECISION GAP: memory_objects links concepts to sources, not
-- locators, so this returns every chunk of the source a concept's evidence
-- lives in. Until a locator link exists (schema gap, migration needed),
-- this seam is coarse by design; the limit bounds the flood. Dormant when
-- no edges exist — the caller passes only matched concept ids and edge
-- trust is enforced upstream.
(
    SELECT chunk.chunk_id,
           chunk.source_id,
           chunk.locator_id,
           chunk.chunk_index,
           chunk.text,
           dep.dependent_id AS via_concept_id
    FROM concepts AS matched
    JOIN dependencies AS dep ON dep.prereq_id = matched.concept_id
    JOIN memory_objects AS mo ON mo.concept_id = dep.dependent_id
    JOIN chunks AS chunk ON chunk.source_id = mo.source_id
    WHERE matched.concept_id = ANY(%(concept_ids)s::uuid[])
      AND matched.course_id = %(course_id)s
)
UNION
(
    SELECT chunk.chunk_id,
           chunk.source_id,
           chunk.locator_id,
           chunk.chunk_index,
           chunk.text,
           dep.prereq_id AS via_concept_id
    FROM concepts AS matched
    JOIN dependencies AS dep ON dep.dependent_id = matched.concept_id
    JOIN memory_objects AS mo ON mo.concept_id = dep.prereq_id
    JOIN chunks AS chunk ON chunk.source_id = mo.source_id
    WHERE matched.concept_id = ANY(%(concept_ids)s::uuid[])
      AND matched.course_id = %(course_id)s
)
ORDER BY chunk_index, chunk_id
LIMIT %(limit)s;

-- name: embedding_candidates
-- Embedding seam: dot-product similarity over chunk embeddings (float8[]
-- now; the pgvector swap uses <=> cosine distance with the same shape).
-- The unnest zip computes dot products natively in SQL. Dimension guard:
-- unequal array lengths truncate silently in Postgres (a model swap would
-- rank garbage with no error), so cardinality() equality is enforced here.
SELECT scored.chunk_id,
       scored.source_id,
       scored.locator_id,
       scored.chunk_index,
       scored.text,
       scored.dot
FROM (
    SELECT chunk.chunk_id,
           chunk.source_id,
           chunk.locator_id,
           chunk.chunk_index,
           chunk.text,
           SUM(emb_value * q_value) AS dot
    FROM chunk_embeddings AS emb
    JOIN chunks AS chunk ON chunk.chunk_id = emb.chunk_id
    JOIN sources AS source ON source.source_id = chunk.source_id
    CROSS JOIN LATERAL unnest(emb.embedding, %(query_embedding)s::float8[])
        AS t(emb_value, q_value)
    WHERE source.course_id = %(course_id)s
      AND emb.model = %(model)s
      AND cardinality(emb.embedding) = cardinality(%(query_embedding)s::float8[])
    GROUP BY chunk.chunk_id, chunk.source_id, chunk.locator_id,
             chunk.chunk_index, chunk.text
) AS scored
ORDER BY scored.dot DESC
LIMIT %(limit)s;

-- name: chunks_by_ids
-- Fusion output hydration: fetch full chunk rows for a merged candidate
-- id set, preserving caller ordering is the caller's job (returns in id
-- order).
SELECT chunk.chunk_id,
       chunk.source_id,
       chunk.locator_id,
       chunk.chunk_index,
       chunk.text
FROM chunks AS chunk
WHERE chunk.chunk_id = ANY(%(chunk_ids)s::uuid[]);

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
WHERE locator.locator_id = ANY(%(locator_ids)s::uuid[]);

-- name: concept_synonym_matches
-- Static concept matching for the dependency seam: concepts whose name or
-- synonyms appear in the query as whole words (word-boundary regex, case-
-- insensitive). Single-character names are rejected in SQL too (defense in
-- depth: 'f' or 'R' would match nearly every question).
SELECT concept.concept_id, concept.name
FROM concepts AS concept
WHERE concept.course_id = %(course_id)s
  AND (
    (char_length(concept.name) >= 2
     AND %(query_lower)s ~ ('(^|[^a-z0-9])' || lower(concept.name) || '([^a-z0-9]|$)'))
    OR EXISTS (
        SELECT 1
        FROM jsonb_array_elements_text(concept.synonyms) AS syn
        WHERE char_length(syn) >= 2
          AND %(query_lower)s ~ ('(^|[^a-z0-9])' || lower(syn) || '([^a-z0-9]|$)')
    )
  )
LIMIT %(limit)s;