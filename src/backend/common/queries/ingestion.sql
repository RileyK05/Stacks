-- name: insert_run
INSERT INTO ingestion_runs (run_id, source_id, pipeline_version, configuration)
VALUES (:run_id, :source_id, :pipeline_version, :configuration)
RETURNING run_id, source_id, pipeline_version, status, configuration,
          error_message, created_at, started_at, completed_at;

-- name: get_run
SELECT run_id, source_id, pipeline_version, status, configuration,
       error_message, created_at, started_at, completed_at
FROM ingestion_runs
WHERE run_id = :run_id;

-- name: latest_run_for_source
SELECT run_id, source_id, pipeline_version, status, configuration,
       error_message, created_at, started_at, completed_at
FROM ingestion_runs
WHERE source_id = :source_id
ORDER BY created_at DESC
LIMIT 1;

-- name: insert_stage_run
INSERT INTO ingestion_stage_runs
    (stage_run_id, run_id, stage, position, depends_on_stage_id, max_attempts,
     handler_version, configuration)
VALUES
    (:stage_run_id, :run_id, :stage, :position, :depends_on_stage_id,
     :max_attempts, :handler_version, :configuration)
RETURNING stage_run_id, run_id, stage, position, depends_on_stage_id, status,
          attempt_count, max_attempts, handler_version, configuration,
          error_message, started_at, completed_at;

-- name: get_stage_run
SELECT stage_run_id, run_id, stage, position, depends_on_stage_id, status,
       attempt_count, max_attempts, handler_version, configuration,
       error_message, started_at, completed_at
FROM ingestion_stage_runs
WHERE run_id = :run_id AND stage = :stage;

-- name: mark_run_started
UPDATE ingestion_runs
SET status = 'running', started_at = COALESCE(started_at, now_utc())
WHERE run_id = :run_id
RETURNING run_id;

-- name: mark_run_terminal
UPDATE ingestion_runs
SET status = :status,
    error_message = :error_message,
    completed_at = now_utc()
WHERE run_id = :run_id
RETURNING run_id;

-- name: mark_stage_transition
UPDATE ingestion_stage_runs
SET status = :status,
    attempt_count = :attempt_count,
    error_message = :error_message,
    started_at = COALESCE(started_at, CASE WHEN :status = 'running'
        THEN now_utc() ELSE started_at END),
    completed_at = CASE WHEN :status IN ('succeeded', 'failed')
        THEN now_utc() ELSE completed_at END
WHERE run_id = :run_id AND stage = :stage
RETURNING stage_run_id;

-- name: claim_pending_sources
-- One UPDATE ... RETURNING is atomic under SQLite's single writer, so no
-- row locks are needed: two workers can never claim the same row.
UPDATE pending_ingestion
SET claimed_at = now_utc(), claimed_runs = claimed_runs + 1
WHERE source_id IN (
    SELECT pending.source_id
    FROM pending_ingestion AS pending
    JOIN sources AS source ON source.source_id = pending.source_id
    JOIN courses AS course ON course.course_id = pending.course_id
    WHERE pending.claimed_at IS NULL
      AND pending.claimed_runs < pending.claimed_runs_max
      AND source.status = 'uploaded'
      AND course.deleted_at IS NULL
    ORDER BY pending.created_at
    LIMIT :limit
)
RETURNING source_id, course_id, reason;

-- name: clear_pending_source
DELETE FROM pending_ingestion
WHERE source_id = :source_id;

-- name: requeue_failed_source
UPDATE sources
SET status = 'uploaded', error_message = NULL
WHERE source_id = :source_id AND status = 'failed'
RETURNING source_id;

-- name: record_ingestion_history
INSERT INTO ingestion_history (history_id, source_id, course_id, reason, queued_at)
VALUES (:history_id, :source_id, :course_id, :reason, :queued_at);

-- name: mark_source_indexed
UPDATE sources
SET status = 'indexed'
WHERE source_id = :source_id AND status = 'uploaded'
RETURNING source_id;

-- name: mark_source_failed
UPDATE sources
SET status = 'failed', error_message = :error_message
WHERE source_id = :source_id
RETURNING source_id;

-- name: source_row
SELECT source_id, course_id, filename, mime_type, stored_encoding
FROM sources
WHERE source_id = :source_id;

-- name: insert_locator
INSERT INTO locators (locator_id, source_id, locator_type, start, end_value, label, description)
VALUES (:locator_id, :source_id, :locator_type, :start, :end_value, :label, :description);

-- name: insert_chunk
-- One row per LOGICAL chunk (review catch #10): the primary locator on
-- the row, the full span in chunk_locators.
INSERT INTO chunks (chunk_id, source_id, locator_id, chunk_index, text)
VALUES (:chunk_id, :source_id, :locator_id, :chunk_index, :text);

-- name: insert_chunk_locator
INSERT INTO chunk_locators (chunk_id, locator_id)
VALUES (:chunk_id, :locator_id)
ON CONFLICT DO NOTHING;

-- name: delete_chunks
DELETE FROM chunks WHERE source_id = :source_id;

-- name: delete_chunk_embeddings
DELETE FROM chunk_embeddings
WHERE chunk_id IN (
    SELECT chunk_id FROM chunks WHERE source_id = :source_id
);

-- name: chunk_ids_by_source_index
SELECT chunk_id, chunk_index
FROM chunks
WHERE source_id = :source_id;

-- name: replace_chunk_embedding
-- One row per chunk, keyed by model name (decision 008).
INSERT INTO chunk_embeddings (chunk_id, model, dimension, embedding)
VALUES (:chunk_id, :model, :dimension, :embedding)
ON CONFLICT (chunk_id) DO UPDATE
    SET model = excluded.model,
        dimension = excluded.dimension,
        embedding = excluded.embedding,
        created_at = now_utc();

-- name: delete_locators
DELETE FROM locators WHERE source_id = :source_id;

-- name: enqueue_pending
INSERT INTO pending_ingestion (source_id, course_id, reason)
VALUES (:source_id, :course_id, :reason)
ON CONFLICT (source_id) DO NOTHING;

-- name: requeue_row
INSERT INTO pending_ingestion (source_id, course_id, reason)
VALUES (:source_id, :course_id, 'requeue_after_failure')
ON CONFLICT (source_id) DO NOTHING;

-- name: release_stale_claims
-- The heartbeat fence: a claim is stale only when its HEARTBEAT is old,
-- not its claim time. Stage transitions keep heartbeat_at fresh, so a
-- slow-but-alive run is never re-claimed. Rows with no heartbeat yet fall
-- back to claimed_at. On a laptop this is also the resume path after
-- sleep or a crash mid-run.
UPDATE pending_ingestion
SET claimed_at = NULL, heartbeat_at = NULL
WHERE claimed_at IS NOT NULL
  AND COALESCE(heartbeat_at, claimed_at) < :threshold;

-- name: heartbeat_claim
UPDATE pending_ingestion
SET heartbeat_at = now_utc()
WHERE source_id = :source_id;

-- name: queued_at_for
-- The queue row's original enqueue time, read BEFORE the row is deleted
-- so the history row preserves it.
SELECT created_at AS queued_at
FROM pending_ingestion
WHERE source_id = :source_id;

-- name: queue_status
-- What the UI shows while a course is processing.
SELECT pending.source_id, pending.claimed_at, pending.heartbeat_at,
       pending.created_at
FROM pending_ingestion AS pending
WHERE pending.course_id = :course_id
ORDER BY pending.created_at;
