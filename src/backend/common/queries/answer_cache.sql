-- Answer cache (migration 002).

-- name: course_fingerprint
-- What the course's answers are built from: every indexed source (by id
-- and content hash) and when each was last ingested. Any upload, delete,
-- or re-ingestion changes it.
SELECT COALESCE(group_concat(part, ','), '') AS fingerprint
FROM (
    SELECT source.source_id || ':' || source.file_hash || ':'
           || COALESCE(MAX(run.completed_at), '') AS part
    FROM sources AS source
    LEFT JOIN ingestion_runs AS run
           ON run.source_id = source.source_id AND run.status = 'succeeded'
    WHERE source.course_id = :course_id
      AND source.status = 'indexed'
    GROUP BY source.source_id
    ORDER BY source.source_id
);

-- name: lookup
SELECT trace_id, answer_text, chunk_ids, model
FROM answer_cache
WHERE cache_key = :cache_key;

-- name: store
INSERT INTO answer_cache
    (cache_key, course_id, fingerprint, trace_id, answer_text, chunk_ids, model)
VALUES
    (:cache_key, :course_id, :fingerprint, :trace_id, :answer_text, :chunk_ids,
     :model)
ON CONFLICT (cache_key) DO UPDATE
SET trace_id = excluded.trace_id,
    answer_text = excluded.answer_text,
    chunk_ids = excluded.chunk_ids,
    model = excluded.model,
    created_at = strftime('%Y-%m-%dT%H:%M:%f000Z', 'now');

-- name: drop_stale
DELETE FROM answer_cache
WHERE course_id = :course_id AND fingerprint != :fingerprint;
