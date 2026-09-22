-- name: insert_trace
INSERT INTO retrieval_traces
    (user_id, course_id, conversation_id, query, retrieved_chunk_ids,
     retrieved_toc_entry_ids, model)
VALUES (%(user_id)s, %(course_id)s, %(conversation_id)s, %(query)s,
        %(chunk_ids)s::jsonb, %(toc_entry_ids)s::jsonb, %(model)s)
RETURNING trace_id, user_id, course_id, query, created_at;

-- name: trace_for_course
-- The trace row an ask produced. Caller enforces the viewer's access to
-- the course; the WHERE pins the trace to that course so a trace from
-- another course can never be read by guessing the id.
SELECT trace_id, user_id, course_id, query, retrieved_chunk_ids, created_at
FROM retrieval_traces
WHERE trace_id = %(trace_id)s AND course_id = %(course_id)s;

-- name: chunks_with_locators_by_ids
-- The citation view: what the tutor read and where it came from
-- (golden rule 1). One row per chunk; the chunk's PRIMARY locator plus
-- its source's filename — enough to say "page 3 of lecture2.pdf" and
-- show the excerpt, without exposing the raw file.
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
WHERE chunk.chunk_id = ANY(%(chunk_ids)s::uuid[])
ORDER BY chunk.source_id, chunk.chunk_index;

-- name: course_by_tag
-- Deterministic eval-course resolution: exact-name match first, then
-- oldest matching course; never an undefined pick between matches.
-- Wildcards are concatenated in SQL so the tag parameter stays a plain
-- string.
SELECT course_id
FROM courses
WHERE name = %(tag)s
   OR name ILIKE '%%' || %(tag)s || '%%'
ORDER BY (name = %(tag)s) DESC, course_id
LIMIT 1;
