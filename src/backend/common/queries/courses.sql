-- Courses on this machine. Active = not in the trash.

-- name: get_active
SELECT course_id, name, created_at, deleted_at, purge_after
FROM courses
WHERE course_id = :course_id AND deleted_at IS NULL;

-- name: get_any
SELECT course_id, name, created_at, deleted_at, purge_after
FROM courses
WHERE course_id = :course_id;

-- name: list_active
SELECT course_id, name, created_at, deleted_at, purge_after
FROM courses
WHERE deleted_at IS NULL
ORDER BY name COLLATE NOCASE, course_id;

-- name: list_trash
SELECT course_id, name, created_at, deleted_at, purge_after
FROM courses
WHERE deleted_at IS NOT NULL
ORDER BY deleted_at DESC, course_id;

-- name: insert_course
INSERT INTO courses (course_id, name)
VALUES (:course_id, :name)
RETURNING course_id, name, created_at, deleted_at, purge_after;

-- name: rename_course
UPDATE courses
SET name = :name
WHERE course_id = :course_id AND deleted_at IS NULL
RETURNING course_id, name, created_at, deleted_at, purge_after;

-- name: move_to_trash
UPDATE courses
SET deleted_at = :deleted_at, purge_after = :purge_after
WHERE course_id = :course_id AND deleted_at IS NULL
RETURNING course_id, name, created_at, deleted_at, purge_after;

-- name: restore_from_trash
UPDATE courses
SET deleted_at = NULL, purge_after = NULL
WHERE course_id = :course_id AND deleted_at IS NOT NULL
RETURNING course_id, name, created_at, deleted_at, purge_after;

-- name: due_for_purge
SELECT course_id
FROM courses
WHERE purge_after IS NOT NULL AND purge_after <= :now
ORDER BY purge_after
LIMIT :limit;

-- name: purge_trashed_course
-- Cascades to every derived row (sources, chunks, embeddings, runs,
-- knowledge, traces). Only a trashed course can be purged: deleting an
-- active course always goes through the trash first.
DELETE FROM courses
WHERE course_id = :course_id AND deleted_at IS NOT NULL
RETURNING course_id;

-- name: course_source_stats
SELECT course_id, COUNT(*) AS source_count,
       COALESCE(SUM(size_bytes), 0) AS stored
FROM sources
WHERE course_id IN (SELECT value FROM json_each(:course_ids))
GROUP BY course_id;

-- name: all_course_ids
SELECT course_id FROM courses;

-- name: all_source_ids
SELECT source_id FROM sources;
