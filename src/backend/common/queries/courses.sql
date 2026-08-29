-- name: count_owned_courses
SELECT COUNT(*) AS owned
FROM courses
WHERE owner_user_id = %(owner_user_id)s;

-- name: course_storage_bytes
SELECT COALESCE(SUM(size_bytes), 0) AS stored
FROM sources
WHERE course_id = %(course_id)s;

-- name: total_storage_bytes
SELECT COALESCE(SUM(size_bytes), 0) AS stored
FROM sources
WHERE course_id IN (SELECT course_id FROM courses WHERE owner_user_id = %(owner_user_id)s);

-- name: insert_course
INSERT INTO courses (owner_user_id, code, name, visibility)
VALUES (%(owner_user_id)s, %(code)s, %(name)s, %(visibility)s)
RETURNING course_id, owner_user_id, code, name, visibility;