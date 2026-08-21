-- name: create
INSERT INTO users (name, email, password_hash)
VALUES (%(name)s, %(email)s, %(password_hash)s)
RETURNING user_id, name, email, created_at;

-- name: get_by_email
SELECT user_id, name, email, password_hash, delete_requested_at, created_at
FROM users
WHERE email = %(email)s;

-- name: get_by_id
SELECT user_id, name, email, password_hash, delete_requested_at, created_at
FROM users
WHERE user_id = %(user_id)s;
