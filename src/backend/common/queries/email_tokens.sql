-- name: create_token
INSERT INTO email_tokens (user_id, kind, token_hash, expires_at)
VALUES (%(user_id)s, %(kind)s, %(token_hash)s, %(expires_at)s)
RETURNING token_id, user_id, kind, token_hash, expires_at, used_at, created_at;

-- name: open_token_by_user
SELECT token_id, user_id, kind, token_hash, expires_at, used_at, created_at
FROM email_tokens
WHERE user_id = %(user_id)s AND kind = %(kind)s AND used_at IS NULL
ORDER BY created_at DESC
LIMIT 1;

-- name: token_by_hash
SELECT token_id, user_id, kind, token_hash, expires_at, used_at, created_at
FROM email_tokens
WHERE token_hash = %(token_hash)s
ORDER BY created_at DESC
LIMIT 1;

-- name: mark_token_used
UPDATE email_tokens
SET used_at = now()
WHERE token_id = %(token_id)s AND used_at IS NULL
RETURNING token_id, user_id, kind, token_hash, expires_at, used_at, created_at;

-- name: revoke_open_tokens
UPDATE email_tokens
SET used_at = now()
WHERE user_id = %(user_id)s AND kind = %(kind)s AND used_at IS NULL;

-- name: verify_user_email
UPDATE users
SET email_verified_at = now()
WHERE user_id = %(user_id)s AND email_verified_at IS NULL
RETURNING user_id;

-- name: enqueue_email
INSERT INTO email_outbox (user_id, to_email, kind, subject, body)
VALUES (%(user_id)s, %(to_email)s, %(kind)s, %(subject)s, %(body)s)
RETURNING message_id, user_id, to_email, kind, subject, body, created_at;

-- name: latest_outbox_email
SELECT message_id, user_id, to_email, kind, subject, body, created_at
FROM email_outbox
WHERE user_id = %(user_id)s AND kind = %(kind)s
ORDER BY created_at DESC
LIMIT 1;