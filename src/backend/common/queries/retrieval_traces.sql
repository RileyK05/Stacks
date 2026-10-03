-- name: insert_trace
INSERT INTO retrieval_traces
    (trace_id, course_id, query, retrieved_chunk_ids, model)
VALUES (:trace_id, :course_id, :query, :chunk_ids, :model)
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
SELECT chunk_id, source_id, locator_id, chunk_index, text, locator_type, label,
       description, filename, char_start, char_end, source_type, container_title
FROM (
    SELECT wanted.key AS position, chunk.chunk_id, source.source_id, locator.locator_id,
           chunk.chunk_index, chunk.text, locator.locator_type,
           locator.label, locator.description, source.filename,
           chunk.char_start, chunk.char_end, source.source_type,
           container.title AS container_title
    FROM json_each(:chunk_ids) AS wanted
    JOIN chunks AS chunk ON chunk.chunk_id = wanted.value
    JOIN locators AS locator ON locator.locator_id = chunk.locator_id
    JOIN sources AS source ON source.source_id = chunk.source_id
    LEFT JOIN passage_containers AS container
        ON container.container_id = chunk.container_id
    UNION ALL
    SELECT wanted.key, snapshot.chunk_id, snapshot.source_id, NULL,
           snapshot.chunk_index, snapshot.text, snapshot.locator_type,
           snapshot.label, snapshot.description, source.filename,
           NULL, NULL, source.source_type, NULL
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

-- name: chunk_locator_spans
-- Every locator overlapping a chunk, in document order, so a window can
-- be labeled with the pages it actually covers rather than the chunk's
-- first page.
SELECT chunk.chunk_id, locator.locator_type, locator.label,
       locator.start, locator.end_value
FROM json_each(:chunk_ids) AS wanted
JOIN chunks AS chunk ON chunk.chunk_id = wanted.value
JOIN chunk_locators AS link ON link.chunk_id = chunk.chunk_id
JOIN locators AS locator ON locator.locator_id = link.locator_id
ORDER BY CAST(wanted.key AS INTEGER), CAST(locator.start AS INTEGER);

-- name: course_by_tag
-- Deterministic eval-course resolution: exact-name match first, then the
-- oldest matching course; never an undefined pick between matches.
SELECT course_id
FROM courses
WHERE deleted_at IS NULL
  AND (name = :tag OR name LIKE '%' || :tag || '%')
ORDER BY (name = :tag) DESC, created_at, course_id
LIMIT 1;
