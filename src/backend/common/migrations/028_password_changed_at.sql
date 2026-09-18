-- 028_password_changed_at.sql
-- A password reset must invalidate sessions minted before it. Without a
-- record of WHEN the password last changed there is nothing to check a
-- token's `iat` against, so an attacker who triggered the reset concern
-- (compromised password) keeps access for the remaining JWT lifetime.
-- The column is NULL for accounts that have never set a password (legacy
-- rows created before passwords existed); every password write from now
-- on bumps it, and current_user rejects tokens minted before it.

ALTER TABLE users
    ADD COLUMN password_changed_at TIMESTAMPTZ;

-- Backfill: existing password rows count as "changed now" so no live
-- session is broken by this migration.
UPDATE users SET password_changed_at = now() WHERE password_hash IS NOT NULL;