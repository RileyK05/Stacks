-- name: get_setting
SELECT key, value, updated_at FROM app_settings WHERE key = :key;

-- name: put_setting
INSERT INTO app_settings (key, value)
VALUES (:key, :value)
ON CONFLICT (key) DO UPDATE
SET value = excluded.value, updated_at = now_utc();

-- name: delete_setting
DELETE FROM app_settings WHERE key = :key;
