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
SELECT source_id, course_id, filename, mime_type, source_type, status,
       error_message, size_bytes, file_hash, created_at
FROM sources
WHERE course_id = :course_id
ORDER BY created_at DESC, source_id;

-- name: get_source
SELECT source_id, course_id, filename, mime_type, source_type, status,
       error_message, size_bytes, file_hash, created_at
FROM sources
WHERE source_id = :source_id AND course_id = :course_id;

-- name: delete_source
-- Cascades to chunks, embeddings, locators, runs, queue rows.
DELETE FROM sources
WHERE source_id = :source_id AND course_id = :course_id
RETURNING source_id;

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
