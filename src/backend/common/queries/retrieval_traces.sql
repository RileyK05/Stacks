-- name: insert_trace
INSERT INTO retrieval_traces
    (trace_id, course_id, query, retrieved_chunk_ids, retrieved_toc_entry_ids,
     model)
VALUES (:trace_id, :course_id, :query, :chunk_ids, :toc_entry_ids, :model)
RETURNING trace_id, course_id, query, created_at;

-- name: trace_for_course
-- The trace row an ask produced. The WHERE pins the trace to the course
-- so a trace id from another course can never be read by guessing.
SELECT trace_id, course_id, query, retrieved_chunk_ids, created_at
FROM retrieval_traces
WHERE trace_id = :trace_id AND course_id = :course_id;

-- name: chunks_with_locators_by_ids
-- The citation view: what the tutor read and where it came from
-- (golden rule 1). One row per chunk: the chunk's PRIMARY locator plus
-- its source's filename — enough to say "page 3 of lecture2.pdf" and
-- show the excerpt.
SELECT chunk.chunk_id,
       chunk.chunk_index,
       chunk.text,
       locator.locator_type,
       locator.label,
       locator.description,
       source.filename
FROM chunks AS chunk
JOIN locators AS locator ON locator.locator_id = chunk.locator_id
JOIN sources AS source ON source.source_id = chunk.source_id
WHERE chunk.chunk_id IN (SELECT value FROM json_each(:chunk_ids))
ORDER BY chunk.source_id, chunk.chunk_index;

-- name: course_by_tag
-- Deterministic eval-course resolution: exact-name match first, then the
-- oldest matching course; never an undefined pick between matches.
SELECT course_id
FROM courses
WHERE deleted_at IS NULL
  AND (name = :tag OR name LIKE '%' || :tag || '%')
ORDER BY (name = :tag) DESC, created_at, course_id
LIMIT 1;
