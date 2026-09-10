-- name: create
INSERT INTO users (name, email, password_hash)
VALUES (%(name)s, %(email)s, %(password_hash)s)
RETURNING user_id, name, email, tier, email_verified_at, created_at;

-- name: get_by_email
SELECT user_id, name, email, tier, email_verified_at, password_hash,
       delete_requested_at, created_at
FROM users
WHERE lower(email) = %(email)s;

-- name: get_by_id
SELECT user_id, name, email, tier, email_verified_at, password_hash,
       delete_requested_at, created_at
FROM users
WHERE user_id = %(user_id)s;

-- name: update_password
UPDATE users
SET password_hash = %(password_hash)s
WHERE user_id = %(user_id)s
RETURNING user_id, name, email, tier, email_verified_at, password_hash,
          delete_requested_at, created_at;