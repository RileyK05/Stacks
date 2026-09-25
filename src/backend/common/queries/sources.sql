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
