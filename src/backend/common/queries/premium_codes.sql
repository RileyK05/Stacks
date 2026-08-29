-- name: insert_code
INSERT INTO premium_codes (code_hash, issued_for_user_id, grants_premium, note)
VALUES (%(code_hash)s, %(issued_for_user_id)s, %(grants_premium)s, %(note)s)
RETURNING code_id, code_hash, issued_for_user_id, grants_premium, claimed_by_user_id, claimed_at, revoked_at, note, created_at;

-- name: get_by_hash
SELECT code_id, code_hash, issued_for_user_id, grants_premium, claimed_by_user_id, claimed_at, revoked_at, note, created_at
FROM premium_codes
WHERE code_hash = %(code_hash)s;

-- name: mark_claimed
UPDATE premium_codes
SET claimed_by_user_id = %(claimed_by_user_id)s,
    claimed_at = now()
WHERE code_hash = %(code_hash)s
  AND claimed_at IS NULL
  AND revoked_at IS NULL
RETURNING code_id, code_hash, issued_for_user_id, grants_premium, claimed_by_user_id, claimed_at, revoked_at, note, created_at;

-- name: set_revoked
UPDATE premium_codes
SET revoked_at = now()
WHERE code_id = %(code_id)s
  AND revoked_at IS NULL
RETURNING code_id, code_hash, issued_for_user_id, grants_premium, claimed_by_user_id, claimed_at, revoked_at, note, created_at;