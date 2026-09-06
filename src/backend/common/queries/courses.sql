-- name: count_owned_courses
SELECT COUNT(*) AS owned
FROM courses
WHERE owner_user_id = %(owner_user_id)s AND lifecycle_status = 'active';

-- name: get_by_id
SELECT course_id, owner_user_id, code, name, visibility,
       lifecycle_status, archived_at, purge_after
FROM courses
WHERE course_id = %(course_id)s AND lifecycle_status = 'active';

-- name: get_any_by_id
SELECT course_id, owner_user_id, code, name, visibility,
       lifecycle_status, archived_at, purge_after
FROM courses
WHERE course_id = %(course_id)s;

-- name: get_by_join_code
SELECT course_id, owner_user_id, code, name, visibility,
       lifecycle_status, archived_at, purge_after
FROM courses
WHERE code = %(code)s AND lifecycle_status = 'active';

-- name: list_owned
SELECT course_id, owner_user_id, code, name, visibility,
       lifecycle_status, archived_at, purge_after
FROM courses
WHERE owner_user_id = %(owner_user_id)s AND lifecycle_status = 'active'
ORDER BY name;

-- name: list_enrolled
SELECT c.course_id, c.owner_user_id, c.code, c.name, c.visibility,
       c.lifecycle_status, c.archived_at, c.purge_after
FROM courses AS c
JOIN course_enrollments AS e ON e.course_id = c.course_id
WHERE e.user_id = %(user_id)s AND e.status = 'active'
  AND c.lifecycle_status = 'active'
ORDER BY c.name;

-- name: list_public
SELECT course_id, owner_user_id, code, name, visibility,
       lifecycle_status, archived_at, purge_after
FROM courses
WHERE visibility = 'public' AND lifecycle_status = 'active'
ORDER BY name
LIMIT %(limit)s;

-- name: course_source_stats
SELECT course_id, COUNT(*) AS source_count, COALESCE(SUM(size_bytes), 0) AS stored
FROM sources
WHERE course_id = ANY(%(course_ids)s)
GROUP BY course_id;

-- name: update_course
UPDATE courses
SET name = COALESCE(%(name)s, name),
    visibility = COALESCE(%(visibility)s, visibility)
WHERE course_id = %(course_id)s AND lifecycle_status = 'active'
RETURNING course_id, owner_user_id, code, name, visibility,
          lifecycle_status, archived_at, purge_after;

-- name: rotate_join_code
UPDATE courses
SET code = %(code)s
WHERE course_id = %(course_id)s AND lifecycle_status = 'active'
RETURNING course_id, owner_user_id, code, name, visibility,
          lifecycle_status, archived_at, purge_after;

-- name: total_storage_bytes
SELECT COALESCE(SUM(size_bytes), 0) AS stored
FROM sources
WHERE course_id IN (
    SELECT course_id FROM courses WHERE owner_user_id = %(owner_user_id)s
);

-- name: course_storage_bytes
SELECT COALESCE(SUM(size_bytes), 0) AS stored
FROM sources
WHERE course_id = %(course_id)s;

-- name: insert_course
INSERT INTO courses (owner_user_id, code, name, visibility)
VALUES (%(owner_user_id)s, %(code)s, %(name)s, %(visibility)s)
RETURNING course_id, owner_user_id, code, name, visibility,
          lifecycle_status, archived_at, purge_after;

-- name: delete_course_row
DELETE FROM courses WHERE course_id = %(course_id)s;
