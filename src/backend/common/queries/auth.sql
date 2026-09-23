-- name: locked_keys
-- Which of the supplied (scope, key_hash) pairs is currently locked, and
-- when the latest lock lifts. One round trip for both keys.
SELECT scope,
       key_hash,
       locked_until
FROM login_throttle
WHERE (scope, key_hash) IN (
    SELECT * FROM unnest(%(scopes)s::text[], %(key_hashes)s::text[])
)
  AND locked_until IS NOT NULL
  AND locked_until > %(now)s;

-- name: ensure_throttle_row
-- Make the row exist so the next SELECT ... FOR UPDATE has something to
-- lock (two concurrent first failures cannot both insert).
INSERT INTO login_throttle (scope, key_hash, failure_count, first_failure_at,
                            last_failure_at, updated_at)
VALUES (%(scope)s, %(key_hash)s, 0, %(now)s, %(now)s, %(now)s)
ON CONFLICT (scope, key_hash) DO NOTHING;

-- name: lock_throttle_row
SELECT failure_count, first_failure_at, locked_until
FROM login_throttle
WHERE scope = %(scope)s AND key_hash = %(key_hash)s
FOR UPDATE;

-- name: update_throttle_after_failure
UPDATE login_throttle
SET failure_count = %(failure_count)s,
    first_failure_at = %(first_failure_at)s,
    last_failure_at = %(now)s,
    locked_until = %(locked_until)s,
    updated_at = %(now)s
WHERE scope = %(scope)s AND key_hash = %(key_hash)s;

-- name: clear_throttle_key
DELETE FROM login_throttle
WHERE scope = %(scope)s AND key_hash = %(key_hash)s;
