-- name: insert_run
INSERT INTO ingestion_runs (source_id, pipeline_version, configuration)
VALUES (%(source_id)s, %(pipeline_version)s, %(configuration)s::jsonb)
RETURNING run_id, source_id, pipeline_version, status, configuration,
          error_message, created_at, started_at, completed_at;

-- name: get_run
SELECT run_id, source_id, pipeline_version, status, configuration,
       error_message, created_at, started_at, completed_at
FROM ingestion_runs
WHERE run_id = %(run_id)s;

-- name: latest_run_for_source
SELECT run_id, source_id, pipeline_version, status, configuration,
       error_message, created_at, started_at, completed_at
FROM ingestion_runs
WHERE source_id = %(source_id)s
ORDER BY created_at DESC
LIMIT 1;

-- name: insert_stage_run
INSERT INTO ingestion_stage_runs
    (run_id, stage, position, depends_on_stage_id, max_attempts,
     handler_version, configuration)
VALUES
    (%(run_id)s, %(stage)s, %(position)s, %(depends_on_stage_id)s,
     %(max_attempts)s, %(handler_version)s, %(configuration)s::jsonb)
RETURNING stage_run_id, run_id, stage, position, depends_on_stage_id, status,
          attempt_count, max_attempts, handler_version, configuration,
          error_message, started_at, completed_at;

-- name: get_stage_run
SELECT stage_run_id, run_id, stage, position, depends_on_stage_id, status,
       attempt_count, max_attempts, handler_version, configuration,
       error_message, started_at, completed_at
FROM ingestion_stage_runs
WHERE run_id = %(run_id)s AND stage = %(stage)s;

-- name: mark_run_started
UPDATE ingestion_runs
SET status = 'running', started_at = COALESCE(started_at, now())
WHERE run_id = %(run_id)s
RETURNING run_id, source_id, pipeline_version, status, configuration,
          error_message, created_at, started_at, completed_at;

-- name: mark_run_terminal
UPDATE ingestion_runs
SET status = %(status)s::ingestion_status,
    error_message = %(error_message)s,
    completed_at = now()
WHERE run_id = %(run_id)s
RETURNING run_id, source_id, pipeline_version, status, configuration,
          error_message, created_at, started_at, completed_at;

-- name: mark_stage_transition
UPDATE ingestion_stage_runs
SET status = %(status)s::ingestion_status,
    attempt_count = %(attempt_count)s,
    error_message = %(error_message)s,
    started_at = COALESCE(started_at, CASE WHEN %(status)s = 'running'
        THEN now() ELSE started_at END),
    completed_at = CASE WHEN %(status)s IN ('succeeded', 'failed')
        THEN now() ELSE completed_at END
WHERE run_id = %(run_id)s AND stage = %(stage)s
RETURNING stage_run_id, run_id, stage, position, depends_on_stage_id, status,
          attempt_count, max_attempts, handler_version, configuration,
          error_message, started_at, completed_at;

-- name: claim_pending_sources
WITH candidate AS (
    SELECT inner_pending.source_id
    FROM pending_ingestion AS inner_pending
    JOIN sources AS source ON source.source_id = inner_pending.source_id
    WHERE inner_pending.claimed_at IS NULL
      AND source.status = 'uploaded'
    ORDER BY inner_pending.created_at
    LIMIT %(limit)s
    FOR UPDATE OF inner_pending SKIP LOCKED
)
UPDATE pending_ingestion AS pending
SET claimed_at = now(), claimed_runs = pending.claimed_runs + 1
FROM candidate
WHERE pending.source_id = candidate.source_id
RETURNING pending.source_id, pending.course_id, pending.reason;

-- name: clear_pending_source
DELETE FROM pending_ingestion
WHERE source_id = %(source_id)s;

-- name: requeue_failed_source
UPDATE sources
SET status = 'uploaded', error_message = NULL
WHERE source_id = %(source_id)s AND status = 'failed'
RETURNING source_id;

-- name: record_ingestion_history
INSERT INTO ingestion_history (source_id, course_id, reason, queued_at)
VALUES (%(source_id)s, %(course_id)s, %(reason)s, %(queued_at)s);

-- name: mark_source_indexed
UPDATE sources
SET status = 'indexed'
WHERE source_id = %(source_id)s AND status = 'uploaded'
RETURNING source_id;

-- name: mark_source_failed
UPDATE sources
SET status = 'failed', error_message = %(error_message)s
WHERE source_id = %(source_id)s
RETURNING source_id;

-- name: source_row
SELECT source_id, course_id, mime_type, stored_encoding
FROM sources
WHERE source_id = %(source_id)s;

-- name: insert_locator
INSERT INTO locators (locator_id, source_id, locator_type, start, end_value, label, description)
VALUES (%(locator_id)s, %(source_id)s, %(locator_type)s, %(start)s, %(end_value)s, %(label)s, %(description)s);

-- name: insert_chunk
INSERT INTO chunks (source_id, locator_id, chunk_index, text)
VALUES (%(source_id)s, %(locator_id)s, %(chunk_index)s, %(text)s);

-- name: delete_chunks
DELETE FROM chunks WHERE source_id = %(source_id)s;

-- name: delete_locators
DELETE FROM locators WHERE source_id = %(source_id)s;
-- name: enqueue_pending
INSERT INTO pending_ingestion (source_id, course_id, reason)
VALUES (%(source_id)s, %(course_id)s, %(reason)s)
ON CONFLICT (source_id) DO NOTHING;

-- name: requeue_row
INSERT INTO pending_ingestion (source_id, course_id, reason)
VALUES (%(source_id)s, %(course_id)s, 'requeue_after_failure')
ON CONFLICT (source_id) DO NOTHING;
