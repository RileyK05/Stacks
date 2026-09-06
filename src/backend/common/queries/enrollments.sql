-- name: get_enrollment
SELECT enrollment_id, course_id, user_id, role, status, enrollment_source,
       invited_by_user_id, created_at, revoked_at, responded_at
FROM course_enrollments
WHERE course_id = %(course_id)s AND user_id = %(user_id)s;

-- name: upsert_active_enrollment
INSERT INTO course_enrollments
    (course_id, user_id, status, enrollment_source, invited_by_user_id, responded_at)
VALUES
    (%(course_id)s, %(user_id)s, 'active', %(enrollment_source)s, NULL, now())
ON CONFLICT (course_id, user_id) DO UPDATE
SET status = 'active',
    enrollment_source = EXCLUDED.enrollment_source,
    invited_by_user_id = NULL,
    revoked_at = NULL,
    responded_at = now()
WHERE course_enrollments.status <> 'active'
RETURNING enrollment_id, course_id, user_id, role, status, enrollment_source,
          invited_by_user_id, created_at, revoked_at, responded_at;

-- name: upsert_invitation
INSERT INTO course_enrollments
    (course_id, user_id, status, enrollment_source, invited_by_user_id)
VALUES
    (%(course_id)s, %(user_id)s, 'invited', 'invitation', %(invited_by_user_id)s)
ON CONFLICT (course_id, user_id) DO UPDATE
SET status = 'invited',
    enrollment_source = 'invitation',
    invited_by_user_id = EXCLUDED.invited_by_user_id,
    revoked_at = NULL,
    responded_at = NULL
WHERE course_enrollments.status <> 'active'
RETURNING enrollment_id, course_id, user_id, role, status, enrollment_source,
          invited_by_user_id, created_at, revoked_at, responded_at;

-- name: accept_invitation
UPDATE course_enrollments
SET status = 'active', responded_at = now()
WHERE course_id = %(course_id)s
  AND user_id = %(user_id)s
  AND status = 'invited'
  AND enrollment_source = 'invitation'
RETURNING enrollment_id, course_id, user_id, role, status, enrollment_source,
          invited_by_user_id, created_at, revoked_at, responded_at;

-- name: decline_invitation
UPDATE course_enrollments
SET status = 'declined', responded_at = now()
WHERE course_id = %(course_id)s
  AND user_id = %(user_id)s
  AND status = 'invited'
  AND enrollment_source = 'invitation'
RETURNING enrollment_id, course_id, user_id, role, status, enrollment_source,
          invited_by_user_id, created_at, revoked_at, responded_at;

-- name: revoke_enrollment
UPDATE course_enrollments
SET status = 'revoked', revoked_at = now(), responded_at = COALESCE(responded_at, now())
WHERE course_id = %(course_id)s
  AND user_id = %(user_id)s
  AND status IN ('active', 'invited')
RETURNING enrollment_id, course_id, user_id, role, status, enrollment_source,
          invited_by_user_id, created_at, revoked_at, responded_at;

-- name: withdraw_enrollment
UPDATE course_enrollments
SET status = (CASE WHEN status = 'invited' THEN 'declined' ELSE 'revoked' END)::enrollment_status,
    revoked_at = CASE WHEN status = 'invited' THEN revoked_at ELSE now() END,
    responded_at = COALESCE(responded_at, now())
WHERE course_id = %(course_id)s
  AND user_id = %(user_id)s
  AND status IN ('active', 'invited')
RETURNING enrollment_id, course_id, user_id, role, status, enrollment_source,
          invited_by_user_id, created_at, revoked_at, responded_at;

-- name: list_members
SELECT enrollment_id, course_id, user_id, role, status, enrollment_source,
       invited_by_user_id, created_at, revoked_at, responded_at
FROM course_enrollments
WHERE course_id = %(course_id)s AND status IN ('active', 'invited')
ORDER BY created_at;
