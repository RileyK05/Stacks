-- name: insert_trace
INSERT INTO retrieval_traces
    (user_id, course_id, conversation_id, query, retrieved_chunk_ids,
     retrieved_toc_entry_ids, model)
VALUES (%(user_id)s, %(course_id)s, %(conversation_id)s, %(query)s,
        %(chunk_ids)s::jsonb, %(toc_entry_ids)s::jsonb, %(model)s)
RETURNING trace_id, user_id, course_id, query, created_at;

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
