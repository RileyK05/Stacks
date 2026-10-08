-- name: active_course_exists
SELECT course_id FROM courses
WHERE course_id = :course_id AND deleted_at IS NULL;

-- name: find_by_hash
SELECT source_id
FROM sources
WHERE course_id = :course_id AND file_hash = :file_hash
LIMIT 1;

-- name: insert_source
INSERT INTO sources
    (source_id, course_id, filename, mime_type, source_type, uri, status,
     file_hash, size_bytes, stored_encoding)
VALUES
    (:source_id, :course_id, :filename, :mime_type, :source_type, :uri,
     'uploaded', :file_hash, :size_bytes, :stored_encoding)
RETURNING source_id, course_id, filename, mime_type, source_type, status,
          file_hash, size_bytes, stored_encoding, created_at;

-- name: list_sources
-- The course's files with their live status, including the failure
-- reason, so a failed upload is never silent (review catch #6).
SELECT sources.source_id, sources.course_id, sources.filename, sources.mime_type,
       sources.source_type, sources.status, sources.error_message, sources.size_bytes,
       sources.file_hash, sources.created_at,
       EXISTS (SELECT 1 FROM source_indexes idx WHERE idx.source_id = sources.source_id) AS has_index,
       coverage.pages_total, coverage.pages_empty, coverage.pages_low_quality,
       coverage.pages_ocr, coverage.extraction_version, coverage.segmentation_version,
       (SELECT COUNT(*) FROM chunks WHERE chunks.source_id = sources.source_id) AS chunk_count,
        (
            SELECT stage.stage
            FROM ingestion_runs AS run
            JOIN ingestion_stage_runs AS stage ON stage.run_id = run.run_id
            WHERE run.source_id = sources.source_id
              AND stage.status IN ('running', 'pending')
              AND run.run_id = (
                  SELECT latest.run_id
                  FROM ingestion_runs AS latest
                  WHERE latest.source_id = sources.source_id
                  ORDER BY latest.created_at DESC
                  LIMIT 1
              )
            ORDER BY CASE stage.status WHEN 'running' THEN 0 ELSE 1 END,
                     stage.position
            LIMIT 1
        ) AS ingestion_stage,
        (
            SELECT substr(stage.error_message, 10)
            FROM ingestion_runs AS run
            JOIN ingestion_stage_runs AS stage ON stage.run_id = run.run_id
            WHERE run.source_id = sources.source_id
              AND stage.status = 'succeeded'
              AND stage.error_message LIKE 'warning:%'
              AND run.run_id = (
                  SELECT latest.run_id
                  FROM ingestion_runs AS latest
                  WHERE latest.source_id = sources.source_id
                  ORDER BY latest.created_at DESC
                  LIMIT 1
              )
            ORDER BY stage.position DESC
            LIMIT 1
        ) AS warning
FROM sources
LEFT JOIN source_indexes AS coverage ON coverage.source_id = sources.source_id
WHERE sources.course_id = :course_id
ORDER BY sources.created_at ASC, sources.filename;

-- name: get_source
SELECT sources.source_id, sources.course_id, sources.filename, sources.mime_type,
       sources.source_type, sources.status, sources.error_message, sources.size_bytes,
       sources.file_hash, sources.created_at,
       EXISTS (SELECT 1 FROM source_indexes idx WHERE idx.source_id = sources.source_id) AS has_index,
       coverage.pages_total, coverage.pages_empty, coverage.pages_low_quality,
       coverage.pages_ocr, coverage.extraction_version, coverage.segmentation_version,
       (SELECT COUNT(*) FROM chunks WHERE chunks.source_id = sources.source_id) AS chunk_count,
        (
            SELECT stage.stage
            FROM ingestion_runs AS run
            JOIN ingestion_stage_runs AS stage ON stage.run_id = run.run_id
            WHERE run.source_id = sources.source_id
              AND stage.status IN ('running', 'pending')
              AND run.run_id = (
                  SELECT latest.run_id
                  FROM ingestion_runs AS latest
                  WHERE latest.source_id = sources.source_id
                  ORDER BY latest.created_at DESC
                  LIMIT 1
              )
            ORDER BY CASE stage.status WHEN 'running' THEN 0 ELSE 1 END,
                     stage.position
            LIMIT 1
        ) AS ingestion_stage,
        (
            SELECT substr(stage.error_message, 10)
            FROM ingestion_runs AS run
            JOIN ingestion_stage_runs AS stage ON stage.run_id = run.run_id
            WHERE run.source_id = sources.source_id
              AND stage.status = 'succeeded'
              AND stage.error_message LIKE 'warning:%'
              AND run.run_id = (
                  SELECT latest.run_id
                  FROM ingestion_runs AS latest
                  WHERE latest.source_id = sources.source_id
                  ORDER BY latest.created_at DESC
                  LIMIT 1
              )
            ORDER BY stage.position DESC
            LIMIT 1
        ) AS warning
FROM sources
LEFT JOIN source_indexes AS coverage ON coverage.source_id = sources.source_id
WHERE sources.source_id = :source_id AND sources.course_id = :course_id;

-- name: set_source_type
UPDATE sources
SET source_type = :source_type
WHERE course_id = :course_id AND source_id = :source_id
RETURNING source_id;

-- name: syllabus_ids
SELECT source_id FROM sources
WHERE course_id = :course_id AND source_type = 'syllabus' AND status = 'indexed';

-- name: delete_source
-- Cascades to chunks, embeddings, locators, runs, queue rows.
DELETE FROM sources
WHERE source_id = :source_id AND course_id = :course_id
RETURNING source_id;

-- name: prune_source_from_chats
-- Deletion may empty an explicit selection; never silently widen it to all.
-- Removing a selected source is also a scope revision (B-02): earlier
-- answers may cite it, so mark the change at the chat's current last seq.
UPDATE conversations
SET source_ids = CASE
        WHEN (SELECT COUNT(*) FROM json_each(conversations.source_ids)
              WHERE value != :source_id) = 0
        THEN '[]'
        ELSE (SELECT json_group_array(value)
              FROM (SELECT value FROM json_each(conversations.source_ids)
                    WHERE value != :source_id ORDER BY key))
    END,
    scope_revised_seq = (SELECT COALESCE(MAX(seq), 0) FROM messages
                         WHERE conversation_id = conversations.conversation_id),
    scope_revised_ids = CASE
        WHEN (SELECT COUNT(*) FROM json_each(conversations.source_ids)
              WHERE value != :source_id) = 0
        THEN '[]'
        ELSE (SELECT json_group_array(value)
              FROM (SELECT value FROM json_each(conversations.source_ids)
                    WHERE value != :source_id ORDER BY key))
    END
WHERE course_id = :course_id
  AND source_ids IS NOT NULL
  AND EXISTS (SELECT 1 FROM json_each(conversations.source_ids)
              WHERE value = :source_id);

-- name: archive_sources
-- Everything `.course` export needs to write each source's original bytes
-- and describe it in the manifest. Oldest first, so an import recreates
-- the course in the order it was built.
SELECT source_id, filename, mime_type, source_type, file_hash, stored_encoding
FROM sources
WHERE course_id = :course_id
ORDER BY created_at, filename;

-- name: viewer_source
SELECT mime_type, stored_encoding
FROM sources
WHERE course_id = :course_id AND source_id = :source_id;

-- name: viewer_passage
SELECT chunk.text, locator.locator_type, locator.label, locator.description
FROM chunks AS chunk
JOIN sources AS source ON source.source_id = chunk.source_id
JOIN locators AS locator ON locator.locator_id = chunk.locator_id
WHERE source.course_id = :course_id
  AND source.source_id = :source_id
  AND chunk.chunk_id = :chunk_id
UNION ALL
SELECT text, locator_type, label, description FROM citation_snapshots
WHERE course_id = :course_id AND source_id = :source_id
  AND chunk_id = :chunk_id;

-- name: snapshot_citations_before_reindex
INSERT OR IGNORE INTO citation_snapshots
    (chunk_id, course_id, source_id, chunk_index, text, locator_type,
     label, description)
SELECT chunk.chunk_id, source.course_id, chunk.source_id, chunk.chunk_index,
       chunk.text, locator.locator_type, locator.label, locator.description
FROM chunks AS chunk
JOIN sources AS source ON source.source_id = chunk.source_id
JOIN locators AS locator ON locator.locator_id = chunk.locator_id
WHERE chunk.source_id = :source_id AND source.course_id = :course_id
  AND chunk.chunk_id IN (
      SELECT value FROM retrieval_traces AS trace,
          json_each(json_extract(trace.retrieved_chunk_ids, '$.chunk_ids'))
      WHERE trace.course_id = :course_id
      UNION
      SELECT value FROM artifacts AS artifact, json_each(artifact.sources)
      WHERE artifact.course_id = :course_id
      UNION
      SELECT value FROM artifact_versions AS version
      JOIN artifacts AS artifact ON artifact.artifact_id = version.artifact_id,
          json_each(version.sources)
      WHERE artifact.course_id = :course_id
  );

-- name: mark_for_reindex
UPDATE sources SET status = 'uploaded', error_message = NULL
WHERE course_id = :course_id AND source_id = :source_id AND status = 'indexed';

-- name: enqueue_reindex
INSERT INTO pending_ingestion (source_id, course_id, reason)
VALUES (:source_id, :course_id, 'reindex_updated_extraction');
