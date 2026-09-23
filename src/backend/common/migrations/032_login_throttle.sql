-- 032_login_throttle.sql
-- Login throttling (carried open security item, notes.md: "login
-- throttling + token revocation before external deployment"). Failed
-- logins are counted against BOTH the targeted account email and the
-- source IP, because they defend different attacks: per-email stops
-- password guessing against one account, per-IP slows credential
-- spraying across many accounts from one host.
--
-- Only a SHA-256 hash of the email (normalized) or IP is stored: the
-- table is security state, not a directory, and a DB leak should not
-- hand over a list of probed addresses or source IPs. Counting is by
-- scope so email and IP keys share one table and one code path.
--
-- The row is bounded by construction (one per distinct key); a stale
-- row is reset in place on the next failure once its window has passed.

CREATE TABLE login_throttle (
    scope            TEXT NOT NULL,
    key_hash         TEXT NOT NULL,
    failure_count    INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    first_failure_at TIMESTAMPTZ,
    last_failure_at  TIMESTAMPTZ,
    locked_until     TIMESTAMPTZ,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (scope, key_hash),
    CONSTRAINT login_throttle_scope_known CHECK (scope IN ('email', 'ip')),
    CONSTRAINT login_throttle_key_hash_hex CHECK (key_hash ~ '^[0-9a-f]{64}$')
);

CREATE INDEX idx_login_throttle_locked
    ON login_throttle(locked_until)
    WHERE locked_until IS NOT NULL;
