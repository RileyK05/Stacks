-- name: lock_owned_active_course
SELECT course_id, owner_user_id
FROM courses
WHERE course_id = %(course_id)s
  AND owner_user_id = %(owner_user_id)s
  AND lifecycle_status = 'active'
FOR UPDATE;

-- name: find_by_hash
SELECT source_id
FROM sources
WHERE course_id = %(course_id)s AND file_hash = %(file_hash)s
LIMIT 1;

-- name: course_storage
SELECT COALESCE(SUM(size_bytes), 0) AS stored
FROM sources
WHERE course_id = %(course_id)s;

-- name: owner_storage
SELECT COALESCE(SUM(source.size_bytes), 0) AS stored
FROM sources AS source
JOIN courses AS course ON course.course_id = source.course_id
WHERE course.owner_user_id = %(owner_user_id)s;

-- name: insert_source_object
INSERT INTO course_objects
    (object_id, course_id, created_by_user_id, kind, content_type, content,
     origin, status, access_scope)
VALUES
    (%(object_id)s, %(course_id)s, %(owner_user_id)s, 'source', %(mime_type)s,
     %(content)s::jsonb, 'upload', 'uploaded', 'enrolled');

-- name: insert_source
INSERT INTO sources
    (source_id, object_id, uploaded_by_user_id, course_id, filename, mime_type,
     source_type, uri, status, file_hash, size_bytes, stored_encoding)
VALUES
    (%(source_id)s, %(object_id)s, %(owner_user_id)s, %(course_id)s,
     %(filename)s, %(mime_type)s, %(source_type)s, %(uri)s, 'uploaded',
     %(file_hash)s, %(size_bytes)s, %(stored_encoding)s)
RETURNING source_id, course_id, filename, mime_type, source_type, status,
          file_hash, size_bytes, stored_encoding, created_at;

-- name: lock_user_for_quota
-- SELECT ... FOR UPDATE: makes the owner-quota check race-free (two
-- concurrent uploads serialize here). In sources.sql per the
-- queries-in-named-blocks rule — every statement in upload_source uses
-- one; this was the last inline holdout.
SELECT user_id
FROM users
WHERE user_id = %(user_id)s
FOR UPDATE;

-- name: list_sources
-- The course's source surface (review catch #6: the API was write-only —
-- a user never learned their upload failed). Owner-only read: statuses
-- include the failure reason, which is owner-facing operational data.
SELECT source.source_id,
       source.object_id,
       source.uploaded_by_user_id,
       source.filename,
       source.mime_type,
       source.source_type,
       source.status,
       source.error_message,
       source.size_bytes,
       source.created_at
FROM sources AS source
JOIN courses AS course ON course.course_id = source.course_id
WHERE source.course_id = %(course_id)s
ORDER BY source.created_at DESC, source.source_id;

-- name: verify_owner_source
-- Ownership gate for source-level actions (requeue): the caller must be
-- the course's owner. Returns the course_id on success.
SELECT source.course_id
FROM sources AS source
JOIN courses AS course ON course.course_id = source.course_id
WHERE source.source_id = %(source_id)s
  AND course.owner_user_id = %(owner_user_id)s;
