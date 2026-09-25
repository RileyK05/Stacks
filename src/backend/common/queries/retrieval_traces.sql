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
-- show the excerpt. Rows come back in the order of :chunk_ids — the order
-- the model numbered the material — so citation n is the n-th row.
SELECT chunk_id, source_id, chunk_index, text, locator_type, label,
       description, filename
FROM (
    SELECT wanted.key AS position, chunk.chunk_id, source.source_id,
           chunk.chunk_index, chunk.text, locator.locator_type,
           locator.label, locator.description, source.filename
    FROM json_each(:chunk_ids) AS wanted
    JOIN chunks AS chunk ON chunk.chunk_id = wanted.value
    JOIN locators AS locator ON locator.locator_id = chunk.locator_id
    JOIN sources AS source ON source.source_id = chunk.source_id
    UNION ALL
    SELECT wanted.key, snapshot.chunk_id, snapshot.source_id,
           snapshot.chunk_index, snapshot.text, snapshot.locator_type,
           snapshot.label, snapshot.description, source.filename
    FROM json_each(:chunk_ids) AS wanted
    JOIN citation_snapshots AS snapshot ON snapshot.chunk_id = wanted.value
    JOIN sources AS source ON source.source_id = snapshot.source_id
    WHERE NOT EXISTS (
        SELECT 1 FROM chunks AS live WHERE live.chunk_id = snapshot.chunk_id
    )
)
-- json_each keys are TEXT; without the cast "10" sorts before "2" and the
-- citation order contract above breaks as soon as final_k reaches 11.
ORDER BY CAST(position AS INTEGER);

-- name: course_by_tag
-- Deterministic eval-course resolution: exact-name match first, then the
-- oldest matching course; never an undefined pick between matches.
SELECT course_id
FROM courses
WHERE deleted_at IS NULL
  AND (name = :tag OR name LIKE '%' || :tag || '%')
ORDER BY (name = :tag) DESC, created_at, course_id
LIMIT 1;
