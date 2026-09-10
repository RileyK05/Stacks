-- name: lock_active_course
SELECT course_id, owner_user_id, code, name, visibility,
       lifecycle_status, archived_at, purge_after
FROM courses
WHERE course_id = %(course_id)s AND lifecycle_status = 'active'
FOR UPDATE;

-- name: archive_participants
SELECT owner_user_id AS user_id FROM courses WHERE course_id = %(course_id)s
UNION
SELECT user_id FROM course_enrollments
WHERE course_id = %(course_id)s AND status = 'active';

-- name: memory_concepts
SELECT name, definition
FROM concepts
WHERE course_id = %(course_id)s
ORDER BY name;

-- name: memory_sources
SELECT filename
FROM sources
WHERE course_id = %(course_id)s
ORDER BY created_at, filename;

-- name: memory_objects
SELECT memory.kind::text AS kind, memory.content
FROM memory_objects AS memory
JOIN concepts AS concept ON concept.concept_id = memory.concept_id
WHERE concept.course_id = %(course_id)s
ORDER BY memory.kind::text, memory.memory_id;

-- name: memory_evidence
WITH representative_chunks AS (
    SELECT source.source_id, source.filename, source.file_hash,
           locator.label, chunk.text,
           ROW_NUMBER() OVER (
               PARTITION BY source.source_id ORDER BY chunk.chunk_index
           ) AS source_rank
    FROM sources AS source
    LEFT JOIN chunks AS chunk ON chunk.source_id = source.source_id
    LEFT JOIN locators AS locator ON locator.locator_id = chunk.locator_id
    WHERE source.course_id = %(course_id)s
)
SELECT filename, file_hash, label, LEFT(text, 240) AS excerpt
FROM representative_chunks
WHERE source_rank = 1
ORDER BY filename
LIMIT 10;

-- name: upsert_memory
INSERT INTO course_memories
    (user_id, course_id, course_ref, name, summary, key_concepts,
     token_budget, summary_version)
VALUES
    (%(user_id)s, %(course_id)s, %(course_ref)s, %(name)s, %(summary)s,
     %(key_concepts)s::jsonb, %(token_budget)s, %(summary_version)s)
ON CONFLICT (user_id, course_id) DO UPDATE
SET name = EXCLUDED.name,
    summary = EXCLUDED.summary,
    key_concepts = EXCLUDED.key_concepts,
    token_budget = EXCLUDED.token_budget,
    summary_version = EXCLUDED.summary_version,
    updated_at = now();

-- name: grant_archive_access
INSERT INTO course_archive_access (course_id, user_id, expires_at)
VALUES (%(course_id)s, %(user_id)s, %(expires_at)s)
ON CONFLICT (course_id, user_id) DO UPDATE
SET expires_at = EXCLUDED.expires_at;

-- name: mark_archived
UPDATE courses
SET lifecycle_status = 'archived',
    archived_at = %(archived_at)s,
    purge_after = %(purge_after)s
WHERE course_id = %(course_id)s AND lifecycle_status = 'active'
RETURNING course_id;

-- name: list_user_archives
SELECT course.course_id, course.name, course.visibility, course.archived_at,
       access.expires_at,
       COUNT(source.source_id) AS source_count,
       COALESCE(SUM(source.size_bytes), 0) AS stored_bytes
FROM course_archive_access AS access
JOIN courses AS course ON course.course_id = access.course_id
LEFT JOIN sources AS source ON source.course_id = course.course_id
WHERE access.user_id = %(user_id)s
  AND access.expires_at > %(now)s
  AND course.lifecycle_status = 'archived'
GROUP BY course.course_id, access.expires_at
ORDER BY course.archived_at DESC;

-- name: get_archive_access
SELECT course.course_id, course.owner_user_id, course.code, course.name,
       course.visibility, course.lifecycle_status, course.archived_at,
       course.purge_after, access.expires_at
FROM course_archive_access AS access
JOIN courses AS course ON course.course_id = access.course_id
WHERE access.course_id = %(course_id)s
  AND access.user_id = %(user_id)s
  AND access.expires_at > %(now)s
  AND course.lifecycle_status = 'archived'
FOR UPDATE;

-- name: insert_course_copy
INSERT INTO courses (owner_user_id, code, name, visibility)
VALUES (%(owner_user_id)s, %(code)s, %(name)s, %(visibility)s)
RETURNING course_id, owner_user_id, code, name, visibility,
          lifecycle_status, archived_at, purge_after;

-- name: copy_study_periods
INSERT INTO study_periods (course_id, label, start_date, end_date)
SELECT %(target_course_id)s, label, start_date, end_date
FROM study_periods
WHERE course_id = %(source_course_id)s;

-- name: source_rows
SELECT source.source_id, source.filename, source.mime_type, source.source_type,
       source.version, source.status, source.file_hash, source.size_bytes,
       source.stored_encoding, object.origin
FROM sources AS source
JOIN course_objects AS object ON object.object_id = source.object_id
WHERE source.course_id = %(course_id)s
ORDER BY source.created_at, source.source_id;

-- name: insert_copied_source_object
INSERT INTO course_objects
    (object_id, course_id, created_by_user_id, kind, content_type, content,
     origin, status, access_scope)
VALUES
    (%(object_id)s, %(course_id)s, %(owner_user_id)s, 'source', %(content_type)s,
     %(content)s::jsonb, %(origin)s, 'uploaded', 'enrolled');

-- name: insert_copied_source
INSERT INTO sources
    (source_id, object_id, uploaded_by_user_id, course_id, filename, mime_type,
     source_type, version, uri, status, file_hash, size_bytes, stored_encoding)
VALUES
    (%(source_id)s, %(object_id)s, %(owner_user_id)s, %(course_id)s,
     %(filename)s, %(mime_type)s, %(source_type)s, %(version)s, %(uri)s,
     'uploaded', %(file_hash)s, %(size_bytes)s, %(stored_encoding)s);

-- name: enqueue_pending_ingestion
INSERT INTO pending_ingestion (source_id, course_id, reason)
VALUES (%(source_id)s, %(course_id)s, %(reason)s)
ON CONFLICT (source_id) DO NOTHING;

-- name: non_source_object_rows
SELECT kind, content_type, content, origin, status, access_scope
FROM course_objects
WHERE course_id = %(course_id)s AND kind <> 'source' AND content IS NOT NULL
ORDER BY created_at, object_id;

-- name: uncopyable_object_count
SELECT COUNT(*) AS uncopyable
FROM course_objects
WHERE course_id = %(course_id)s
  AND kind <> 'source'
  AND content IS NULL
  AND content_uri IS NOT NULL;

-- name: insert_copied_object
INSERT INTO course_objects
    (course_id, created_by_user_id, kind, content_type, content, origin,
     status, access_scope)
VALUES
    (%(course_id)s, %(owner_user_id)s, %(kind)s, %(content_type)s,
     %(content)s::jsonb, %(origin)s, %(status)s, %(access_scope)s);

-- name: due_archives
SELECT course_id
FROM courses
WHERE lifecycle_status = 'archived' AND purge_after <= %(now)s
ORDER BY purge_after
LIMIT %(limit)s;

-- name: claim_due_archive
SELECT course_id
FROM courses
WHERE course_id = %(course_id)s
  AND lifecycle_status = 'archived'
  AND purge_after <= %(now)s
FOR UPDATE SKIP LOCKED;

-- name: enqueue_cleanup
INSERT INTO storage_cleanup_jobs (course_id)
VALUES (%(course_id)s)
ON CONFLICT (course_id) WHERE status IN ('pending', 'running', 'failed')
DO NOTHING;

-- name: claim_cleanup
WITH ready AS (
    SELECT job_id
    FROM storage_cleanup_jobs
    WHERE next_attempt_at <= %(now)s
      AND status IN ('pending', 'failed')
    ORDER BY next_attempt_at, created_at
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
UPDATE storage_cleanup_jobs AS job
SET status = 'running',
    attempt_count = attempt_count + 1,
    next_attempt_at = %(lease_until)s,
    error_message = NULL
FROM ready
WHERE job.job_id = ready.job_id
RETURNING job.job_id, job.course_id, job.status, job.attempt_count,
          job.error_message, job.next_attempt_at, job.created_at, job.completed_at;

-- name: reclaim_expired_cleanup
WITH expired AS (
    SELECT job_id
    FROM storage_cleanup_jobs
    WHERE status = 'running'
      AND next_attempt_at < %(now)s
    ORDER BY next_attempt_at
    LIMIT %(limit)s
    FOR UPDATE SKIP LOCKED
)
UPDATE storage_cleanup_jobs AS job
SET status = CASE
        WHEN job.attempt_count >= %(max_attempts)s THEN 'dead'
        ELSE 'failed'
    END,
    error_message = COALESCE(
        job.error_message,
        'lease expired while claimed; worker presumed dead'
    )
FROM expired
WHERE job.job_id = expired.job_id
RETURNING job.job_id, job.course_id, job.status, job.attempt_count,
          job.error_message, job.next_attempt_at, job.created_at, job.completed_at;

-- name: cleanup_succeeded
UPDATE storage_cleanup_jobs
SET status = 'succeeded', completed_at = now(), error_message = NULL
WHERE job_id = %(job_id)s;

-- name: cleanup_failed
UPDATE storage_cleanup_jobs AS job
SET status = CASE
        WHEN job.attempt_count >= %(max_attempts)s THEN 'dead'
        ELSE 'failed'
    END,
    error_message = %(error_message)s,
    next_attempt_at = %(next_attempt_at)s
WHERE job.job_id = %(job_id)s
RETURNING job.job_id, job.course_id, job.status, job.attempt_count,
          job.error_message, job.next_attempt_at, job.created_at, job.completed_at;

-- name: list_memories
SELECT memory_id, user_id, course_id, course_ref, name, summary,
       key_concepts, token_budget, summary_version, created_at, updated_at
FROM course_memories
WHERE user_id = %(user_id)s
ORDER BY updated_at DESC;
