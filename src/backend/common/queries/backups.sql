-- name: backup_source_rows
SELECT course_id, source_id, uri, file_hash, size_bytes, stored_encoding
FROM sources
ORDER BY course_id, source_id;

-- name: sanitize_artifact_origins
-- Provenance may contain a hidden prompt or chat excerpt. Keep only stable
-- academic provenance fields when a backup tier excludes conversations.
UPDATE artifacts SET origin = json_object(
    'by', json_extract(origin, '$.by'),
    'kind', json_extract(origin, '$.kind'),
    'title', json_extract(origin, '$.title'),
    'model', json_extract(origin, '$.model'),
    'source_ids', json_extract(origin, '$.source_ids')
)
WHERE origin IS NOT NULL;

-- name: sanitize_practice_origins
UPDATE practice_suites SET origin = json_object(
    'source', 'saved_chat_material',
    'item_index', json_extract(origin, '$.item_index'),
    'suite_ref', suite_id
)
WHERE json_type(origin, '$.message_id') IS NOT NULL;

-- name: sanitize_source_uris
UPDATE sources SET uri = :uri_prefix || lower(course_id) || '/' ||
    lower(source_id) || '.bin';

-- name: reset_settings
DELETE FROM app_settings
WHERE key NOT IN ('learning.preferred_method', 'backups.preferences');

-- name: delete_messages
DELETE FROM messages;

-- name: delete_conversations
DELETE FROM conversations;

-- name: delete_answer_cache
DELETE FROM answer_cache;

-- name: delete_work_turns
DELETE FROM work_turns;

-- name: delete_usage_ledger
DELETE FROM usage_ledger;

-- name: delete_retrieval_traces
DELETE FROM retrieval_traces;

-- name: delete_chunk_embeddings
DELETE FROM chunk_embeddings;

-- name: delete_practice_assessments
DELETE FROM practice_assessments;

-- name: delete_practice_runs
DELETE FROM practice_runs;

-- name: delete_learning_teaching_events
DELETE FROM learning_teaching_events;

-- name: delete_learning_observations
DELETE FROM learning_observations;

-- name: delete_learning_experiments
DELETE FROM learning_experiments;

-- name: delete_core_method_observations
DELETE FROM core_method_observations;

-- name: delete_course_memories
DELETE FROM course_memories;

-- name: delete_learning_preference
DELETE FROM app_settings WHERE key = 'learning.preferred_method';

-- name: delete_practice_help
DELETE FROM practice_help;

-- name: delete_practice_feedback
DELETE FROM practice_feedback;

-- name: delete_nonacademic_settings
DELETE FROM app_settings
WHERE key NOT IN (:learning_preference, :backup_preferences);

-- name: restore_indexed_sources
SELECT source.source_id, source.course_id
FROM sources AS source
JOIN courses AS course ON course.course_id = source.course_id
WHERE source.status = 'indexed' AND course.deleted_at IS NULL
ORDER BY source.course_id, source.source_id;

-- name: mark_restored_source_for_reindex
UPDATE sources
SET status = 'uploaded', error_message = NULL
WHERE source_id = :source_id AND course_id = :course_id AND status = 'indexed';

-- name: queue_restored_source
INSERT INTO pending_ingestion (source_id, course_id, reason)
VALUES (:source_id, :course_id, 'backup_restore_rebuild_vectors')
ON CONFLICT (source_id) DO UPDATE SET
    reason = excluded.reason,
    claimed_at = NULL,
    claimed_runs = 0,
    heartbeat_at = NULL;

-- name: reset_restored_claims
UPDATE pending_ingestion
SET claimed_at = NULL, claimed_runs = 0, heartbeat_at = NULL;

-- name: schema_table_names
SELECT name FROM sqlite_master WHERE type IN ('table', 'view');

-- name: schema_versions
SELECT version FROM schema_migrations;
